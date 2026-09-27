"""Historical migration from the Google Sheet (Import.md §5).

- import_sheet: sheet rows → import batch. Accounts via rules (§5.5); match mode against bank-backed ledger
  data on/after the cut-over dates, sheet-only before (§5.3).
- load_anchors: year-end State blocks + total anchors → reconciliation anchors, opening balances,
  asset valuations and debt snapshots (§5.3 B-1).
- generate_balancing: per period between anchors, transfers for non-primary accounts and residual
  adjustments for the primary ones (§5.3 B-3/4). Idempotent: regenerates from scratch.
"""

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.base import dedupe_key
from app.connectors.gsheet import SheetRow, parse_workbook
from app.db.models import (
    Account,
    AccountReconciliation,
    Asset,
    AssetValuation,
    Category,
    Debt,
    DebtBalanceSnapshot,
    ImportBatch,
    ImportRow,
    ImportRule,
    Txn,
    TxnLeg,
)
from app.domain.money import to_minor
from app.services import debts as debt_svc
from app.services import ledger
from app.services.common import DomainError, get_setting
from app.services.fx import RateBook
from app.services.imports import refresh_stats

MATCH_WINDOW = timedelta(days=3)
CARD_WINDOW = timedelta(days=40)  # sheet books card spend on the repayment day

DEFAULT_SHEET_ACCOUNT_MAP = {
    "ABN": "ABN",
    "Cash": "Cash",
    "Invest ABN": "ABN Invest",
    "Sparen ABN": "Sparen ABN",
    "Sparen Bunq": "Sparen Bunq",
    "VTB": "Rubles",
    "Bunq": None,  # old account, ignored
}


@dataclass
class Rule:
    id: int
    priority: int
    match: dict
    action: dict

    def applies(self, r: SheetRow) -> bool:
        m = self.match
        if m.get("date_from") and r.date < date.fromisoformat(m["date_from"]):
            return False
        if m.get("date_to") and r.date > date.fromisoformat(m["date_to"]):
            return False
        if m.get("currency") and m["currency"] != r.currency:
            return False
        if m.get("category") and (r.category or "").lower() != m["category"].lower():
            return False
        if m.get("desc_regex") and not re.search(m["desc_regex"], r.description or "", re.I):
            return False
        if m.get("sign") == "negative" and r.amount >= 0:
            return False
        if m.get("sign") == "positive" and r.amount <= 0:
            return False
        return True


def _rules(session: Session) -> list[Rule]:
    rows = session.scalars(
        select(ImportRule).where(ImportRule.source == "gsheet", ImportRule.is_active == 1).order_by(ImportRule.priority)
    )
    return [Rule(r.id, r.priority, json.loads(r.match), json.loads(r.action)) for r in rows]


class Ctx:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.accounts = {a.name: a for a in session.scalars(select(Account))}
        self.cats = list(session.scalars(select(Category).where(Category.archived_at.is_(None))))
        self.debts = list(session.scalars(select(Debt).where(Debt.archived_at.is_(None))))
        self.rules = _rules(session)
        self.bank_cutover = date.fromisoformat(get_setting(session, "bank_cutover_date"))
        self.card_cutover = date.fromisoformat(get_setting(session, "card_cutover_date"))

    def account(self, name: str | None) -> Account | None:
        return self.accounts.get(name) if name else None

    def category(self, name: str | None, positive: bool) -> Category | None:
        if not name:
            return None
        n = name.lower()
        hits = [c for c in self.cats if c.name.lower() == n and c.parent_id is None]
        if not hits:
            hits = [c for c in self.cats if c.name.lower() == n]
        if len(hits) > 1:
            want = "income" if positive else "expense"
            hits = [c for c in hits if c.kind == want] or hits
        return hits[0] if hits else None

    def debt_for(self, text: str | None) -> Debt | None:
        for d in self.debts:
            if d.parent_debt_id is not None:
                continue
            pattern = d.lender_identifier or re.escape(d.name)
            if re.search(pattern, text or "", re.I) or re.search(re.escape(d.name), text or "", re.I):
                return d
        return None


def _leg(account: Account, amount: int, inferred: bool = False) -> dict:
    return {"account_id": account.id, "amount": amount, "inferred": inferred}


def _propose(ctx: Ctx, r: SheetRow) -> dict:
    """Sheet row → draft proposal (before match mode)."""
    rule = next((x for x in ctx.rules if x.applies(r)), None)
    action = rule.action if rule else {}
    default = "Rubles" if r.currency == "RUB" else "ABN"
    account = ctx.account(action.get("account") or default)
    if account is None:
        raise DomainError("setup", f"Account '{action.get('account') or default}' missing; run the seed first")
    base = {"description": r.description or "", "counterparty": None, "sheet_category": r.category,
            "rule": f"R{rule.priority}" if rule else None, "sheet": f"{r.sheet}!{r.row_no}"}
    kind = action.get("kind")
    cat_name = (r.category or "").lower()

    if re.search(r"meegebracht", r.description or "", re.I):
        return {**base, "skip": "opening balance (set by load_anchors)"}
    if kind == "adjustment" or re.fullmatch(r"balancing|корректировка", (r.description or "").strip().lower()):
        return {**base, "kind": "adjustment", "legs": [_leg(account, r.amount)], "splits": []}
    if kind == "transfer" or cat_name in ("convert", "invest"):
        if cat_name == "convert":
            return {**base, "kind": "transfer", "convert": True, "legs": [_leg(account, r.amount)], "splits": []}
        counter = ctx.account(action.get("counter_account") or ("ABN Invest" if cat_name == "invest" else None))
        if counter is None:
            return {**base, "kind": "transfer", "legs": [_leg(account, r.amount)], "splits": [], "needs_category": True}
        # 'Invest' in the sheet is money out of ABN into the investment account
        return {**base, "kind": "transfer", "legs": [_leg(account, r.amount), _leg(counter, -r.amount)], "splits": []}
    if cat_name in ("debt return", "hypotheek") and r.amount < 0:
        debt = ctx.debt_for("Hypotheek" if cat_name == "hypotheek" else r.description)
        if debt is not None:
            try:
                splits = debt_svc.suggest_payment_splits(ctx.session, debt.id, r.date, -r.amount)
            except DomainError:
                splits = []
            if splits:
                return {**base, "kind": "debt_payment", "debt_id": debt.id, "legs": [_leg(account, r.amount)], "splits": splits}
        return {**base, "kind": "debt_payment", "legs": [_leg(account, r.amount)], "splits": [], "needs_category": True,
                "note": "pick the debt"}
    cat = ctx.category(action.get("category") or r.category, r.amount > 0)
    return {
        **base,
        "kind": "income" if (cat and cat.kind == "income") or (cat is None and r.amount > 0) else "expense",
        "legs": [_leg(account, r.amount)],
        "splits": [{"amount": r.amount, "category_id": cat.id if cat else None, "cost_type": None, "project_id": None}],
        "sheet_category_id": cat.id if cat else None,
        "needs_category": cat is None,
    }


def _match_candidates(session: Session, account_id: int, amount: int, d: date, card: bool, used: set[int]) -> Txn | None:
    lo, hi = (d - CARD_WINDOW, d + MATCH_WINDOW) if card else (d - MATCH_WINDOW, d + MATCH_WINDOW)
    q = (
        select(Txn)
        .join(TxnLeg, TxnLeg.txn_id == Txn.id)
        .where(TxnLeg.account_id == account_id, TxnLeg.amount == amount, Txn.date >= lo, Txn.date <= hi,
               Txn.source == "import")
    )
    cands = [t for t in session.scalars(q) if t.id not in used]
    if not cands:
        return None
    return min(cands, key=lambda t: abs((t.date - d).days))


def import_sheet(session: Session, filename: str, data: bytes, user_id: int | None,
                 years: set[int] | None = None) -> ImportBatch:
    sha = hashlib.sha256(data + json.dumps(sorted(years or [])).encode()).hexdigest()
    if session.execute(select(ImportBatch).where(ImportBatch.file_sha256 == sha,
                                                 ImportBatch.status != "discarded")).scalar_one_or_none():
        raise DomainError("duplicate_file", "This workbook/year selection was already imported", status=409)
    wb = parse_workbook(data, years)
    ctx = Ctx(session)
    batch = ImportBatch(source="gsheet", file_name=filename, file_sha256=sha, status="parsing", created_by=user_id)
    session.add(batch)
    session.flush()
    used = set(session.scalars(select(ImportRow.matched_txn_id).where(ImportRow.matched_txn_id.is_not(None))))
    proposals: list[tuple[SheetRow, dict]] = [(r, _propose(ctx, r)) for r in wb.rows]
    _pair_conversions(proposals, ctx)
    modes = set()
    for n, (r, p) in enumerate(proposals, start=1):
        row = ImportRow(batch_id=batch.id, row_no=n, raw=json.dumps({"sheet": r.sheet, "row": r.row_no}),
                        date=r.date, amount=r.amount, currency=r.currency,
                        account_id=p["legs"][0]["account_id"] if p.get("legs") else None,
                        description=r.description, dedupe_key=dedupe_key("gsheet", r.sheet, r.row_no, r.currency))
        if p.get("skip"):
            row.status = "skipped"
        elif p.get("paired_into"):
            row.status = "skipped"
        else:
            acc = session.get(Account, row.account_id) if row.account_id else None
            card = acc is not None and acc.type == "credit_card"
            bank_backed = acc is not None and acc.type in ("current", "savings", "credit_card", "investment")
            cutover = ctx.card_cutover if card else ctx.bank_cutover
            if bank_backed and r.date >= cutover:
                modes.add("match")
                p["mode"] = "match"
                txn = _match_candidates(session, acc.id, r.amount, r.date, card, used)  # type: ignore[union-attr]
                if txn is not None:
                    used.add(txn.id)
                    row.matched_txn_id = txn.id
                    if p.get("kind") in ("transfer", "adjustment") or txn.kind not in ("expense", "income"):
                        row.status = "duplicate"  # already in the ledger from the bank side
                        p["note"] = f"already booked as txn {txn.id}"
                    else:
                        p = {**p, "update_txn_id": txn.id}
                        row.status = "suggested" if not p.get("needs_category") else "new"
                else:
                    p["unmatched_in_bank_period"] = True
                    row.status = "new"
            else:
                modes.add("sheet_only")
                p["mode"] = "sheet_only"
                row.status = "new" if p.get("needs_category") else "suggested"
        p["needs_category"] = bool(p.get("needs_category"))
        row.proposed = json.dumps(p, default=str)
        session.add(row)
    batch.mode = "match" if modes == {"match"} else "sheet_only" if modes == {"sheet_only"} else None
    batch.status = "reviewing"
    batch.stats = json.dumps({"rows": len(wb.rows), "sheets": wb.sheets_parsed, "warnings": wb.warnings[:50],
                              "modes": sorted(modes)})
    session.flush()
    refresh_stats(session, batch)
    return batch


def _pair_conversions(proposals: list[tuple[SheetRow, dict]], ctx: Ctx) -> None:
    """R2: a € Convert row and a ₽ Convert row on the same day with opposite signs become one transfer."""
    by_day: dict[date, list[int]] = defaultdict(list)
    for i, (_, p) in enumerate(proposals):
        if p.get("convert"):
            by_day[proposals[i][0].date].append(i)
    for idxs in by_day.values():
        eur = [i for i in idxs if proposals[i][0].currency == "EUR"]
        rub = [i for i in idxs if proposals[i][0].currency == "RUB"]
        for e in eur:
            partner = next((x for x in rub if (proposals[x][0].amount > 0) != (proposals[e][0].amount > 0)), None)
            if partner is None:
                continue
            rub.remove(partner)
            pe, pr = proposals[e][1], proposals[partner][1]
            pe["legs"] = pe["legs"] + pr["legs"]
            pe["description"] = pe.get("description") or "Currency conversion"
            pe.pop("convert", None)
            pr["paired_into"] = f"{proposals[e][0].sheet}!{proposals[e][0].row_no}"
    for _, p in proposals:
        if p.pop("convert", None):
            p["needs_category"] = True
            p["note"] = "unpaired conversion: add the other currency leg"


# ---------------------------------------------------------------- anchors (§5.3 B-1)

def load_anchors(session: Session, data: bytes, user_id: int | None) -> dict:
    wb = parse_workbook(data, years={0})  # no transaction sheets needed
    accounts = {a.name: a for a in session.scalars(select(Account))}
    mapping = get_setting(session, "sheet_account_map") or DEFAULT_SHEET_ACCOUNT_MAP
    today = date.today()
    # remove previous sheet anchors so the operation is repeatable
    session.query(AccountReconciliation).filter(AccountReconciliation.source == "anchor").delete()
    created, valuations, snapshots = 0, 0, 0

    def anchor(acc: Account, d: date, value: Decimal, note: str) -> None:
        nonlocal created
        stated = to_minor(value.quantize(Decimal("0.01")), acc.currency)
        session.add(AccountReconciliation(account_id=acc.id, date=d, stated_balance=stated,
                                          computed_balance=ledger.account_balance(session, acc.id, d),
                                          source="anchor", note=note, created_by=user_id))
        created += 1

    abn, rubles = accounts.get(mapping.get("ABN") or "ABN"), accounts.get(mapping.get("VTB") or "Rubles")
    history_start = date.fromisoformat(get_setting(session, "history_start_date"))
    # opening balances (§5.1): ABN = 'Euros meegebracht', Rubles = funds at the start of 2021
    full = parse_workbook(data, years={2020})
    brought = next((r for r in full.rows if re.search("meegebracht", r.description or "", re.I)), None)
    if abn and brought:
        abn.opening_date, abn.opening_balance = history_start, brought.amount
    for d, eur, rub in wb.total_anchors:
        if d == date(2020, 12, 31) and rubles and rub is not None:
            rubles.opening_date = date(2021, 1, 1)
            rubles.opening_balance = to_minor(rub.quantize(Decimal("0.01")), "RUB")
            continue
        if abn and eur is not None and d >= history_start:
            anchor(abn, d, eur, f"sheet total funds {d.year}")
        if rubles and rub is not None and d >= rubles.opening_date:
            anchor(rubles, d, rub, f"sheet total funds {d.year}")
    session.flush()
    assets = {a.name: a for a in session.scalars(select(Asset))}
    debts = {d.name: d for d in session.scalars(select(Debt))}
    for state in wb.states:
        if state.year >= today.year:
            continue  # the current year's block is 'now', not a year end
        d = date(state.year, 12, 31)
        for label, (eur, rub) in state.funds.items():
            name = mapping.get(label, label)
            acc = accounts.get(name) if name else None
            if acc is None:
                continue
            value = rub if acc.currency == "RUB" else eur
            if value is not None and d >= acc.opening_date:
                anchor(acc, d, value, f"Dashboard {state.year}")
        for label, value in state.assets.items():
            asset = assets.get(label)
            if asset is None:
                continue
            existing = session.execute(select(AssetValuation).where(AssetValuation.asset_id == asset.id,
                                                                    AssetValuation.date == d)).scalar_one_or_none()
            minor = to_minor(value.quantize(Decimal("0.01")), asset.currency)
            if existing:
                existing.value, existing.source = minor, "import"
            else:
                session.add(AssetValuation(asset_id=asset.id, date=d, value=minor, source="import"))
            valuations += 1
        for label, value in state.debts.items():
            debt = debts.get(label)
            if debt is None or debt.repayment_type == "group" or value < 0:
                continue
            existing = session.execute(select(DebtBalanceSnapshot).where(DebtBalanceSnapshot.debt_id == debt.id,
                                                                         DebtBalanceSnapshot.date == d)).scalar_one_or_none()
            minor = to_minor(value.quantize(Decimal("0.01")), debt.currency)
            if existing:
                existing.balance = minor
            else:
                session.add(DebtBalanceSnapshot(debt_id=debt.id, date=d, balance=minor, note=f"Dashboard {state.year}"))
            snapshots += 1
    return {"anchors": created, "asset_valuations": valuations, "debt_snapshots": snapshots,
            "abn_opening": abn.opening_balance if abn else None, "rubles_opening": rubles.opening_balance if rubles else None}


# ---------------------------------------------------------------- generated balancing (§5.3 B-3/4)

def _virtual_cutover_anchor(session: Session, acc: Account, until: date) -> tuple[date, int] | None:
    """Balance at the day before the bank cut-over, derived back from the first statement checkpoint."""
    cp = session.execute(
        select(AccountReconciliation)
        .where(AccountReconciliation.account_id == acc.id, AccountReconciliation.source == "statement",
               AccountReconciliation.date >= until)
        .order_by(AccountReconciliation.date).limit(1)
    ).scalar_one_or_none()
    if cp is None:
        return None
    day_before = until - timedelta(days=1)
    flows = session.execute(
        select(func.coalesce(func.sum(TxnLeg.amount), 0)).join(Txn)
        .where(TxnLeg.account_id == acc.id, Txn.date > day_before, Txn.date <= cp.date)
    ).scalar_one()
    return day_before, cp.stated_balance - int(flows)


def generate_balancing(session: Session, user_id: int | None) -> list[dict]:
    until = date.fromisoformat(get_setting(session, "bank_cutover_date"))
    for txn in session.scalars(select(Txn).where(Txn.source == "generated", Txn.date < until)):
        session.delete(txn)
    session.flush()
    accounts = list(session.scalars(select(Account).where(Account.archived_at.is_(None))))
    primary = {c: next((a for a in accounts if a.type == "current" and a.currency == c), None) for c in ("EUR", "RUB")}
    book = RateBook(session)
    report = []

    def anchors_for(acc: Account) -> list[tuple[date, int, str]]:
        rows = [(r.date, r.stated_balance, r.note or "") for r in session.scalars(
            select(AccountReconciliation).where(AccountReconciliation.account_id == acc.id,
                                                AccountReconciliation.source == "anchor",
                                                AccountReconciliation.date < until)
            .order_by(AccountReconciliation.date))]
        virtual = _virtual_cutover_anchor(session, acc, until)
        if virtual:
            rows.append((virtual[0], virtual[1], "first bank statement"))
        return rows

    def book_txn(draft: ledger.TxnDraft) -> None:
        draft.source = "generated"
        ledger.create_txn(session, draft, user_id, book)
        session.flush()

    # non-primary accounts first: their movements are transfers with the primary account of the same currency
    ordered = [a for a in accounts if a not in primary.values()] + [a for a in primary.values() if a]
    for acc in ordered:
        main = primary.get(acc.currency)
        for d, stated, note in anchors_for(acc):
            if d < acc.opening_date:
                continue
            diff = stated - ledger.account_balance(session, acc.id, d)
            if diff == 0:
                continue
            label = "Cash movements" if acc.type == "cash" else "Savings movements" if acc.type == "savings" else "Movements"
            if acc is not main and main is not None and d >= main.opening_date:
                book_txn(ledger.TxnDraft(date=d, kind="transfer", description=f"{label} {d.year} ({acc.name})",
                                         notes=f"generated from anchor: {note}",
                                         legs=[ledger.LegIn(account_id=acc.id, amount=diff),
                                               ledger.LegIn(account_id=main.id, amount=-diff)]))
                report.append({"account": acc.name, "date": d, "kind": "transfer", "amount": diff})
            else:
                book_txn(ledger.TxnDraft(date=d, kind="adjustment", description=f"Unrecorded movements {d.year}",
                                         notes=f"generated from anchor: {note}",
                                         legs=[ledger.LegIn(account_id=acc.id, amount=diff)]))
                report.append({"account": acc.name, "date": d, "kind": "adjustment", "amount": diff})
    return report
