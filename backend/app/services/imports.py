"""Import pipeline (Import.md §2): upload → parse → resolve account → dedupe → classify → review → commit."""

import hashlib
import json
import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors import IMPORTERS, detect
from app.connectors.base import ParsedRow, dedupe_key, norm_text
from app.db.models import (
    Account,
    AccountIdentifier,
    AccountReconciliation,
    Category,
    Debt,
    ImportBatch,
    ImportRow,
    Security,
    Txn,
    TxnLeg,
)
from app.services import debts as debt_svc
from app.services import ledger
from app.services.common import DomainError, NotFound, get_or_404, get_setting
from app.services.fx import RateBook

INTEREST_RE = re.compile(r"\b(rente|interest|creditrente)\b", re.I)
TRANSFER_WINDOW = timedelta(days=3)


# ---------------------------------------------------------------- lookups

class Lookup:
    """Identifier → account map plus named system categories/accounts, loaded once per operation."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.by_ident: dict[str, int] = {}
        for ident in session.scalars(select(AccountIdentifier)):
            value = ident.value.replace(" ", "").upper()
            self.by_ident[value] = ident.account_id
            if ident.kind == "iban" and len(value) > 8:
                self.by_ident[str(int(value[8:])) if value[8:].isdigit() else value[8:]] = ident.account_id
        self.accounts = {a.id: a for a in session.scalars(select(Account))}
        self.ignored = {x.replace(" ", "").upper() for x in (get_setting(session, "ignored_own_ibans") or [])}
        self.card_payees = {x.replace(" ", "").upper() for x in (get_setting(session, "card_payee_ibans") or [])}
        self.categories = list(session.scalars(select(Category).where(Category.archived_at.is_(None))))

    def account_for(self, hint: str | None) -> int | None:
        if not hint:
            return None
        h = hint.replace(" ", "").upper()
        if h in self.by_ident:
            return self.by_ident[h]
        if h.isdigit():
            return self.by_ident.get(str(int(h)))
        return None

    def first_account(self, type_: str, currency: str = "EUR") -> Account | None:
        cands = [a for a in self.accounts.values() if a.type == type_ and a.currency == currency and not a.archived_at]
        return sorted(cands, key=lambda a: (a.sort_order, a.id))[0] if cands else None

    def category(self, name: str, kind: str | None = None) -> Category | None:
        name_l = name.lower()
        for c in self.categories:
            if c.name.lower() == name_l and (kind is None or c.kind == kind):
                return c
        return None


# ---------------------------------------------------------------- dedupe

def row_dedupe_key(source: str, account_id: int | None, r: ParsedRow, nth: int) -> str:
    acct = account_id or r.account_hint
    if r.stated_balance is not None:  # XLS and MT940 carry a running balance: identical across formats
        return dedupe_key("bal", acct, r.date, r.amount, r.stated_balance)
    if r.external_id:
        return dedupe_key("ext", acct, r.external_id)
    return dedupe_key(source, acct, r.date, r.amount, norm_text(r.counterparty), norm_text(r.description), nth)


# ---------------------------------------------------------------- classification (Import.md §4)

def _find_inferred_leg(session: Session, account_id: int, amount: int, d: date) -> TxnLeg | None:
    return session.execute(
        select(TxnLeg)
        .join(Txn)
        .where(
            TxnLeg.account_id == account_id,
            TxnLeg.amount == amount,
            TxnLeg.inferred == 1,
            Txn.date >= d - TRANSFER_WINDOW,
            Txn.date <= d + TRANSFER_WINDOW,
        )
        .order_by(Txn.date)
        .limit(1)
    ).scalar_one_or_none()


def _transfer(account_id: int, other_id: int, amount: int, desc: str, rule: str) -> dict[str, Any]:
    return {
        "kind": "transfer",
        "rule": rule,
        "description": desc,
        "legs": [
            {"account_id": account_id, "amount": amount, "inferred": False},
            {"account_id": other_id, "amount": -amount, "inferred": True},
        ],
        "splits": [],
    }


def classify(session: Session, lk: Lookup, row: ImportRow, hints: dict[str, Any]) -> dict[str, Any]:
    """Rule-based proposal. Returns a draft dict; `needs_category` marks rows for the AI/review."""
    acc = lk.accounts.get(row.account_id) if row.account_id else None
    base = {"description": row.description or "", "counterparty": row.counterparty, "notes": None}
    if acc is None:
        return {**base, "kind": "expense" if row.amount < 0 else "income", "legs": [], "splits": [],
                "needs_category": True, "rule": "unknown_account"}
    abn = hints.get("abn") or {}
    cp_iban = (row.counterparty_iban or "").upper()

    # 1. own-account transfer
    other = lk.account_for(cp_iban) if cp_iban else None
    if other and other != acc.id:
        return {**base, **_transfer(acc.id, other, row.amount, base["description"], "own_transfer")}
    # ignored old own account (Import.md §1): wealth in/out of an untracked account, not income
    if cp_iban and cp_iban in lk.ignored:
        return {**base, "kind": "adjustment", "rule": "ignored_account",
                "description": f"Old account {cp_iban}: {base['description']}".strip(),
                "legs": [{"account_id": acc.id, "amount": row.amount, "inferred": False}], "splits": []}
    # 2. credit card repayment (bank side, or the card statement's payment line)
    card = lk.first_account("credit_card", acc.currency)
    if card and cp_iban and cp_iban in lk.card_payees and acc.type != "credit_card":
        return {**base, **_transfer(acc.id, card.id, row.amount, "Credit card repayment", "card_repayment")}
    if acc.type == "credit_card" and hints.get("card_payment"):
        current = lk.first_account("current", acc.currency)
        if current:
            return {**base, **_transfer(acc.id, current.id, row.amount, "Credit card repayment", "card_repayment")}
    # 3. ATM → Cash
    if abn.get("kind") == "atm":
        cash = lk.first_account("cash", acc.currency)
        if cash:
            return {**base, **_transfer(acc.id, cash.id, row.amount, "ATM withdrawal", "atm")}
    # 4. debt payment by lender match
    if row.amount < 0:
        for debt in session.scalars(select(Debt).where(Debt.parent_debt_id.is_(None), Debt.closed_at.is_(None))):
            ident = (debt.lender_identifier or "").strip()
            if not ident:
                continue
            hay = f"{cp_iban} {row.counterparty or ''} {row.description or ''}"
            if ident.upper() == cp_iban or re.search(ident, hay, re.I):
                try:
                    splits = debt_svc.suggest_payment_splits(session, debt.id, row.date, -row.amount)
                except DomainError:
                    splits = []
                return {**base, "kind": "debt_payment", "rule": "debt", "debt_id": debt.id,
                        "legs": [{"account_id": acc.id, "amount": row.amount, "inferred": False}],
                        "splits": splits, "needs_category": not splits}
    # 5. investment patterns (ABN Invest)
    legs = [{"account_id": acc.id, "amount": row.amount, "inferred": False}]
    # interest on savings (before the bank-fee pattern: ABN books it as 'ABN AMRO Bank N.V. RENTE')
    if row.amount > 0 and acc.type == "savings" and INTEREST_RE.search(f"{row.description} {row.counterparty}"):
        return _categorised(base, legs, row.amount, lk.category("Interest", "income"), "interest", None)
    kind = abn.get("kind")
    extra = abn.get("extra") or {}
    if kind in ("invest_buy", "invest_sell") and acc.type == "investment":
        units = Decimal(extra["units"]) * (1 if kind == "invest_buy" else -1)
        return {**base, "kind": "investment", "rule": kind, "legs": legs, "splits": [],
                "trades": [{"account_id": acc.id, "security_code": extra["code"], "security_name": row.counterparty,
                            "currency": extra.get("ccy", "EUR"), "action": "buy" if units > 0 else "sell",
                            "units": str(units), "price": extra["price"], "fees": 0}]}
    if kind == "dividend":
        cat = lk.category("Dividend", "income")
        note = f"{extra.get('shares')} sh × {extra.get('per_share')} {extra.get('ccy')}" + (
            f", tax {extra['tax']}" if extra.get("tax") else "")
        return _categorised(base, legs, row.amount, cat, "dividend", note)
    if kind in ("invest_fee", "fee"):
        return _categorised(base, legs, row.amount, lk.category("Bank", "expense"), kind, None)
    # 6. everything else → AI + review
    return {**base, "kind": "expense" if row.amount < 0 else "income", "rule": None, "legs": legs,
            "splits": [{"amount": row.amount, "category_id": None, "cost_type": None, "project_id": None}],
            "needs_category": True}


def _categorised(base: dict, legs: list, amount: int, cat: Category | None, rule: str, note: str | None) -> dict:
    return {**base, "kind": "income" if amount > 0 else "expense", "rule": rule, "legs": legs, "notes": note,
            "splits": [{"amount": amount, "category_id": cat.id if cat else None, "cost_type": None, "project_id": None}],
            "needs_category": cat is None}


# ---------------------------------------------------------------- batch lifecycle

def create_batch(
    session: Session, filename: str, data: bytes, user_id: int | None,
    source: str | None = None, account_id: int | None = None,
) -> ImportBatch:
    sha = hashlib.sha256(data).hexdigest()
    dup = session.execute(
        select(ImportBatch).where(ImportBatch.file_sha256 == sha, ImportBatch.status != "discarded")
    ).scalar_one_or_none()
    if dup:
        raise DomainError("duplicate_file", f"This file was already imported (batch {dup.id})", status=409, batch_id=dup.id)
    source = source or detect(filename, data[:4096])
    if source not in IMPORTERS:
        raise DomainError("unknown_format", "File format not recognised; choose the source explicitly")
    batch = ImportBatch(source=source, account_id=account_id, file_name=filename, file_sha256=sha,
                        status="parsing", created_by=user_id)
    session.add(batch)
    session.flush()
    try:
        result = IMPORTERS[source].parse(data)
    except Exception as e:  # parsers raise ValueError / format errors
        batch.status, batch.error = "failed", str(e)
        return batch
    lk = Lookup(session)
    committed_keys = set(session.scalars(select(ImportRow.dedupe_key).where(ImportRow.status == "committed")))
    seen: Counter = Counter()
    batch_keys: set[str] = set()
    unknown_accounts: set[str] = set()
    for i, r in enumerate(result.rows, start=1):
        acc_id = lk.account_for(r.account_hint) or account_id
        if acc_id is None and r.account_hint:
            unknown_accounts.add(r.account_hint)
        seen[(acc_id, r.date, r.amount, norm_text(r.description))] += 1
        key = row_dedupe_key(source, acc_id, r, seen[(acc_id, r.date, r.amount, norm_text(r.description))])
        acc = lk.accounts.get(acc_id) if acc_id else None
        if acc and acc.currency != r.currency:
            raise DomainError("currency_mismatch", f"{acc.name} is {acc.currency}, file row is {r.currency}")
        row = ImportRow(
            batch_id=batch.id, row_no=i, raw=json.dumps({**r.raw, "hints": r.hints}, default=str, ensure_ascii=False),
            date=r.date, amount=r.amount, currency=r.currency, account_id=acc_id, counterparty=r.counterparty,
            counterparty_iban=r.counterparty_iban, description=r.description, external_id=r.external_id,
            dedupe_key=key, stated_balance=r.stated_balance,
        )
        if key in committed_keys or key in batch_keys:
            row.status = "duplicate"
        elif acc is not None and r.date < acc.opening_date:
            row.status = "skipped"
            row.proposed = json.dumps({"skip_reason": f"before {acc.name} opening date {acc.opening_date}"})
        batch_keys.add(key)
        session.add(row)
        session.flush()
        if row.status == "new":
            proposal = classify(session, lk, row, r.hints)
            row.proposed = json.dumps(proposal, default=str)
            if not proposal.get("needs_category") and proposal.get("rule"):
                row.status = "accepted"  # rule-classified (transfers, invest...): pre-accepted, still needs commit
    batch.status = "reviewing"
    batch.stats = json.dumps({
        "rows": len(result.rows),
        "checkpoints": [(k, h, d.isoformat(), b) for k, h, d, b in result.checkpoints],
        "meta": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in result.meta.items()},
        "unknown_accounts": sorted(unknown_accounts),
    })
    refresh_stats(session, batch)
    return batch


def refresh_stats(session: Session, batch: ImportBatch) -> dict:
    stats = json.loads(batch.stats or "{}")
    counts = Counter(r.status for r in batch.rows)
    stats["status_counts"] = dict(counts)
    batch.stats = json.dumps(stats)
    return stats


def update_row(session: Session, row_id: int, proposed: dict | None, status: str | None) -> ImportRow:
    row = get_or_404(session, ImportRow, row_id)
    if row.status == "committed":
        raise DomainError("row_committed", "Row is already committed", status=409)
    if proposed is not None:
        current = json.loads(row.proposed or "{}")
        current.update(proposed)
        current["needs_category"] = False
        current["edited"] = True
        row.proposed = json.dumps(current, default=str)
    if status is not None:
        if status not in ("new", "accepted", "skipped", "duplicate", "suggested"):
            raise DomainError("status", f"Cannot set status {status}")
        row.status = status
    return row


def _security(session: Session, code: str, name: str | None, currency: str) -> Security:
    sec = session.execute(select(Security).where(Security.symbol == code)).scalar_one_or_none()
    if sec is None:
        sec = Security(symbol=code, name=name or code, currency=currency)
        session.add(sec)
        session.flush()
    return sec


def _draft(session: Session, row: ImportRow, p: dict) -> ledger.TxnDraft:
    trades = []
    for t in p.get("trades") or []:
        sec_id = t.get("security_id") or _security(session, t["security_code"], t.get("security_name"), t["currency"]).id
        trades.append(ledger.TradeIn(account_id=t["account_id"], security_id=sec_id, action=t["action"],
                                     units=Decimal(t["units"]), price=Decimal(t["price"]), fees=int(t.get("fees") or 0)))
    splits = [
        ledger.SplitIn(**{k: v for k, v in s.items() if k in ledger.SplitIn.model_fields})
        for s in p.get("splits") or []
    ]
    return ledger.TxnDraft(
        date=date.fromisoformat(p["date"]) if p.get("date") else row.date,
        kind=p["kind"],
        description=p.get("description") or "",
        counterparty=p.get("counterparty"),
        notes=p.get("notes"),
        legs=[ledger.LegIn(**leg) for leg in p.get("legs") or []],
        splits=splits,
        trades=trades,
        source="import",
        import_row_id=row.id,
    )


def commit_row(session: Session, row: ImportRow, user_id: int | None, book: RateBook) -> Txn:
    p = json.loads(row.proposed or "{}")
    if p.get("update_txn_id"):  # sheet match mode: enrich an existing bank transaction
        return apply_match(session, row, p, user_id)
    if p.get("needs_category") or any(s.get("category_id") is None and not any(
        s.get(k) for k in ("debt_id", "earmark_id", "asset_id")) for s in p.get("splits") or []):
        raise DomainError("uncategorised", f"Row {row.row_no} has no category yet")
    if p.get("kind") == "transfer" and p.get("legs"):
        own = next(leg for leg in p["legs"] if not leg.get("inferred"))
        leg = _find_inferred_leg(session, own["account_id"], own["amount"], row.date)
        if leg is not None:  # the other statement already created this transfer: confirm our side
            leg.inferred = 0
            txn = leg.txn
            row.txn_id = txn.id
            return txn
    txn = ledger.create_txn(session, _draft(session, row, p), user_id, book)
    row.txn_id = txn.id
    return txn


def apply_match(session: Session, row: ImportRow, p: dict, user_id: int | None) -> Txn:
    txn = get_or_404(session, Txn, p["update_txn_id"])
    draft = ledger.draft_from_txn(txn)
    if p.get("description"):
        draft.description = p["description"] if not draft.description else f"{p['description']} · {draft.description}"
    new_splits = p.get("splits")
    if new_splits and txn.kind in ("expense", "income") and len(txn.legs) == 1:
        draft.kind = p.get("kind", draft.kind)
        draft.splits = [ledger.SplitIn(**{k: v for k, v in s.items() if k in ledger.SplitIn.model_fields})
                        for s in new_splits]
        if sum(s.amount for s in draft.splits) != sum(leg.amount for leg in draft.legs):
            draft.splits = [ledger.SplitIn(amount=draft.legs[0].amount, category_id=new_splits[0].get("category_id"),
                                           cost_type=new_splits[0].get("cost_type"), project_id=new_splits[0].get("project_id"))]
    txn = ledger.update_txn(session, txn.id, draft, user_id)
    row.txn_id = txn.id
    return txn


def commit_batch(session: Session, batch_id: int, user_id: int | None, row_ids: list[int] | None = None) -> dict:
    batch = get_or_404(session, ImportBatch, batch_id)
    if batch.status not in ("reviewing",):
        raise DomainError("batch_status", f"Batch is {batch.status}")
    book = RateBook(session)
    rows = [r for r in batch.rows if r.status == "accepted" and (row_ids is None or r.id in row_ids)]
    rows.sort(key=lambda r: (r.date, r.row_no))
    committed, errors = 0, []
    for row in rows:
        try:
            with session.begin_nested():
                commit_row(session, row, user_id, book)
                row.status = "committed"
                committed += 1
        except DomainError as e:
            errors.append({"row_id": row.id, "row_no": row.row_no, "code": e.code, "message": e.message})
    session.flush()
    _store_checkpoints(session, batch, user_id)
    if all(r.status in ("committed", "skipped", "duplicate") for r in batch.rows):
        batch.status = "committed"
    refresh_stats(session, batch)
    return {"committed": committed, "errors": errors, "status": batch.status}


def _store_checkpoints(session: Session, batch: ImportBatch, user_id: int | None) -> None:
    stats = json.loads(batch.stats or "{}")
    lk = Lookup(session)
    for _kind, hint, d, balance in stats.get("checkpoints") or []:
        acc_id = lk.account_for(hint)
        if acc_id is None:
            continue
        on = date.fromisoformat(d)
        exists = session.execute(
            select(AccountReconciliation).where(
                AccountReconciliation.account_id == acc_id, AccountReconciliation.date == on,
                AccountReconciliation.source == "statement")
        ).scalar_one_or_none()
        computed = ledger.account_balance(session, acc_id, on)
        if exists:
            exists.stated_balance, exists.computed_balance = balance, computed
        else:
            session.add(AccountReconciliation(account_id=acc_id, date=on, stated_balance=balance,
                                              computed_balance=computed, source="statement",
                                              note=f"batch {batch.id}", created_by=user_id))


def discard_batch(session: Session, batch_id: int) -> None:
    batch = get_or_404(session, ImportBatch, batch_id)
    if any(r.status == "committed" for r in batch.rows):
        raise DomainError("batch_committed", "Batch has committed rows; delete those transactions first", status=409)
    batch.status = "discarded"
    for r in batch.rows:
        r.status = "skipped"


def bulk_update(session: Session, batch_id: int, row_ids: list[int] | None, filter_: dict | None,
                status: str | None, patch: dict | None) -> int:
    batch = get_or_404(session, ImportBatch, batch_id)
    rows = [r for r in batch.rows if r.status != "committed"]
    if row_ids is not None:
        rows = [r for r in rows if r.id in set(row_ids)]
    if filter_:
        rows = [r for r in rows if _matches(r, filter_)]
    for r in rows:
        if patch:
            p = json.loads(r.proposed or "{}")
            for s in p.get("splits") or []:
                for k in ("category_id", "cost_type", "project_id"):
                    if k in patch:
                        s[k] = patch[k]
            p["needs_category"] = False
            r.proposed = json.dumps(p, default=str)
        if status:
            r.status = status
    refresh_stats(session, batch)
    return len(rows)


def _matches(r: ImportRow, f: dict) -> bool:
    p = json.loads(r.proposed or "{}")
    if "status" in f and r.status != f["status"]:
        return False
    if "min_confidence" in f:
        if r.suggestion is None or float(r.suggestion.confidence) < float(f["min_confidence"]):
            return False
    if f.get("ai_agrees_with_sheet") and not p.get("ai_agrees_with_sheet"):
        return False
    if "category_id" in f and not any(s.get("category_id") == f["category_id"] for s in p.get("splits") or []):
        return False
    if f.get("rule") and p.get("rule") != f["rule"]:
        return False
    return True


def row_view(row: ImportRow) -> dict:
    p = json.loads(row.proposed or "{}")
    sug = row.suggestion
    return {
        "id": row.id, "row_no": row.row_no, "date": row.date, "amount": row.amount, "currency": row.currency,
        "account_id": row.account_id, "counterparty": row.counterparty, "counterparty_iban": row.counterparty_iban,
        "description": row.description, "status": row.status, "stated_balance": row.stated_balance,
        "proposed": p, "txn_id": row.txn_id, "generated": bool(row.generated),
        "suggestion": None if sug is None else {
            "kind": sug.kind, "category_id": sug.category_id, "cost_type": sug.cost_type, "project_id": sug.project_id,
            "confidence": float(sug.confidence), "rationale": sug.rationale, "model": sug.model,
        },
    }


def get_batch(session: Session, batch_id: int) -> ImportBatch:
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise NotFound("ImportBatch", batch_id)
    return batch

