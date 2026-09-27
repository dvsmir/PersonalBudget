"""Ledger writes. Validates the invariants of Data.md §7.1, computes EUR values, writes audit entries."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Category,
    Debt,
    Earmark,
    InvestmentTrade,
    Txn,
    TxnLeg,
    TxnSplit,
)
from app.services.common import DomainError, NotFound, audit, get_setting
from app.services.fx import RateBook


class LegIn(BaseModel):
    account_id: int
    amount: int  # minor units, signed from the account's perspective
    inferred: bool = False


class SplitIn(BaseModel):
    amount: int  # minor units, same sign convention as the legs
    category_id: int | None = None
    debt_id: int | None = None
    earmark_id: int | None = None
    asset_id: int | None = None
    cost_type: str | None = None
    project_id: int | None = None
    note: str | None = None


class TradeIn(BaseModel):
    account_id: int
    security_id: int
    action: str
    units: Decimal
    price: Decimal
    fees: int = 0


class TxnDraft(BaseModel):
    date: date
    kind: str
    description: str = ""
    counterparty: str | None = None
    notes: str | None = None
    legs: list[LegIn] = Field(default_factory=list)
    splits: list[SplitIn] = Field(default_factory=list)
    trades: list[TradeIn] = Field(default_factory=list)
    source: str = "manual"
    import_row_id: int | None = None


def _target(s: SplitIn) -> str:
    targets = [n for n in ("category_id", "debt_id", "earmark_id", "asset_id") if getattr(s, n) is not None]
    if len(targets) != 1:
        raise DomainError("split_target", "Each split needs exactly one target (category, debt, earmark or asset)")
    return targets[0]


def validate(session: Session, d: TxnDraft) -> dict[int, Account]:
    """Raise DomainError when the draft breaks a ledger invariant. Returns the accounts by id."""
    accounts: dict[int, Account] = {}
    for leg in d.legs:
        acc = session.get(Account, leg.account_id)
        if acc is None:
            raise NotFound("Account", leg.account_id)
        if leg.amount == 0:
            raise DomainError("leg_zero", "Leg amounts must not be zero")
        if d.date < acc.opening_date:
            raise DomainError(
                "before_opening", f"{acc.name} opens on {acc.opening_date}; transaction dated {d.date}"
            )
        accounts[acc.id] = acc

    lock = get_setting(session, "lock_date")
    if lock and d.date <= date.fromisoformat(lock):
        raise DomainError("period_locked", f"Period up to {lock} is locked")

    targets = [_target(s) for s in d.splits]
    for s in d.splits:
        if s.cost_type not in (None, "fixed", "variable", "one_time"):
            raise DomainError("cost_type", f"Unknown cost type {s.cost_type}")
        if s.category_id is not None and session.get(Category, s.category_id) is None:
            raise NotFound("Category", s.category_id)
        if s.debt_id is not None:
            debt = session.get(Debt, s.debt_id)
            if debt is None:
                raise NotFound("Debt", s.debt_id)
            if debt.repayment_type == "group":
                raise DomainError("debt_group", f"Book on the loan parts of {debt.name}, not on the group")
        if s.earmark_id is not None and session.get(Earmark, s.earmark_id) is None:
            raise NotFound("Earmark", s.earmark_id)

    legs_sum = sum(leg.amount for leg in d.legs)
    money_splits_sum = sum(s.amount for s, t in zip(d.splits, targets, strict=True) if t != "earmark_id")
    currencies = {a.currency for a in accounts.values()}

    def need(cond: bool, code: str, msg: str) -> None:
        if not cond:
            raise DomainError(code, msg)

    k = d.kind
    if k in ("expense", "income"):
        need(len(d.legs) == 1, "legs", f"{k} needs exactly one account leg")
        need(any(t == "category_id" for t in targets), "splits", f"{k} needs at least one category split")
        need(all(t in ("category_id", "earmark_id") for t in targets), "splits", f"{k} splits must be categories")
    elif k == "transfer":
        need(len(d.legs) == 2, "legs", "A transfer needs two legs")
        need(d.legs[0].account_id != d.legs[1].account_id, "legs", "A transfer needs two different accounts")
        need(not d.splits, "splits", "A transfer has no splits")
        if len(currencies) == 1:
            need(legs_sum == 0, "transfer_sum", "Same-currency transfer legs must cancel out")
        else:
            need(d.legs[0].amount * d.legs[1].amount < 0, "transfer_sign", "Conversion legs need opposite signs")
    elif k == "debt_payment":
        need(len(d.legs) == 1 and d.legs[0].amount < 0, "legs", "A debt payment needs one outgoing leg")
        need(any(t == "debt_id" for t in targets), "splits", "A debt payment needs a principal (debt) split")
    elif k == "debt_drawdown":
        need(len(d.legs) <= 1, "legs", "A drawdown has at most one leg")
        need(any(t == "debt_id" for t in targets), "splits", "A drawdown needs a debt split")
    elif k == "investment":
        need(len(d.legs) == 1, "legs", "An investment txn needs one cash leg")
        need(accounts[d.legs[0].account_id].type == "investment", "account", "Use an investment account")
        need(bool(d.trades), "trades", "An investment txn needs at least one trade")
    elif k == "asset_purchase":
        need(len(d.legs) == 1, "legs", "An asset purchase needs one leg")
        need(any(t == "asset_id" for t in targets), "splits", "An asset purchase needs an asset split")
    elif k == "earmark":
        need(not d.legs, "legs", "Earmark movements have no account legs")
        need(bool(d.splits) and all(t == "earmark_id" for t in targets), "splits", "Only earmark splits allowed")
    elif k == "adjustment":
        need(len(d.legs) == 1 and not d.splits, "legs", "An adjustment has one leg and no splits")
    elif k == "mixed":
        need(len(d.legs) == 1, "legs", "A mixed txn has one leg")
    else:
        raise DomainError("kind", f"Unknown transaction kind {k}")

    if k not in ("transfer", "adjustment", "investment", "earmark"):
        need(
            money_splits_sum == legs_sum,
            "split_sum",
            f"Splits ({money_splits_sum}) must add up to the account amount ({legs_sum})",
        )
    if k != "transfer":
        need(len(currencies) <= 1, "currency", "All legs of a transaction must share one currency")
    return accounts


def _currency_of(session: Session, d: TxnDraft, accounts: dict[int, Account]) -> str:
    if accounts:
        return next(iter(accounts.values())).currency
    for s in d.splits:
        if s.earmark_id is not None:
            return session.get(Earmark, s.earmark_id).currency  # type: ignore[union-attr]
    return "EUR"


def _apply(session: Session, txn: Txn, d: TxnDraft, accounts: dict[int, Account], book: RateBook) -> None:
    txn.date, txn.kind, txn.description = d.date, d.kind, d.description
    txn.counterparty, txn.notes = d.counterparty, d.notes
    txn.legs.clear()
    txn.splits.clear()
    txn.trades.clear()
    session.flush()

    currency = _currency_of(session, d, accounts)
    fx_diff = 0
    for leg in d.legs:
        acc = accounts[leg.account_id]
        conv = book.to_ref(leg.amount, acc.currency, d.date)
        txn.legs.append(
            TxnLeg(
                account_id=acc.id,
                amount=leg.amount,
                amount_ref=conv.amount,
                ref_estimated=int(conv.estimated),
                inferred=int(leg.inferred),
            )
        )
        fx_diff += conv.amount
    # conversion cost only exists for cross-currency transfers
    is_conversion = d.kind == "transfer" and len({a.currency for a in accounts.values()}) > 1
    txn.fx_diff_ref = fx_diff if is_conversion else 0

    for s in d.splits:
        conv = book.to_ref(s.amount, currency, d.date)
        txn.splits.append(
            TxnSplit(
                amount=s.amount,
                currency=currency,
                amount_ref=conv.amount,
                ref_estimated=int(conv.estimated),
                category_id=s.category_id,
                debt_id=s.debt_id,
                earmark_id=s.earmark_id,
                asset_id=s.asset_id,
                cost_type=s.cost_type,
                project_id=s.project_id,
                note=s.note,
            )
        )
    for t in d.trades:
        txn.trades.append(InvestmentTrade(**t.model_dump()))


def snapshot(txn: Txn) -> dict:
    return {
        "date": txn.date,
        "kind": txn.kind,
        "description": txn.description,
        "legs": [(leg.account_id, leg.amount, leg.inferred) for leg in txn.legs],
        "splits": [
            (s.amount, s.category_id, s.debt_id, s.earmark_id, s.asset_id, s.cost_type, s.project_id)
            for s in txn.splits
        ],
    }


def create_txn(session: Session, d: TxnDraft, user_id: int | None, book: RateBook | None = None) -> Txn:
    accounts = validate(session, d)
    txn = Txn(source=d.source, import_row_id=d.import_row_id, created_by=user_id, updated_by=user_id)
    session.add(txn)
    _apply(session, txn, d, accounts, book or RateBook(session))
    session.flush()
    audit(session, user_id, "txn", txn.id, "create", after=snapshot(txn))
    return txn


def update_txn(session: Session, txn_id: int, d: TxnDraft, user_id: int | None) -> Txn:
    txn = session.get(Txn, txn_id)
    if txn is None:
        raise NotFound("Txn", txn_id)
    accounts = validate(session, d)
    before = snapshot(txn)
    txn.updated_by = user_id
    _apply(session, txn, d, accounts, RateBook(session))
    session.flush()
    audit(session, user_id, "txn", txn.id, "update", before=before, after=snapshot(txn))
    return txn


def delete_txn(session: Session, txn_id: int, user_id: int | None) -> None:
    txn = session.get(Txn, txn_id)
    if txn is None:
        raise NotFound("Txn", txn_id)
    lock = get_setting(session, "lock_date")
    if lock and txn.date <= date.fromisoformat(lock):
        raise DomainError("period_locked", f"Period up to {lock} is locked")
    audit(session, user_id, "txn", txn.id, "delete", before=snapshot(txn))
    session.delete(txn)


def account_balance(session: Session, account_id: int, on: date | None = None) -> int:
    acc = session.get(Account, account_id)
    if acc is None:
        raise NotFound("Account", account_id)
    q = select(func.coalesce(func.sum(TxnLeg.amount), 0)).join(Txn).where(TxnLeg.account_id == account_id)
    if on is not None:
        q = q.where(Txn.date <= on)
    return acc.opening_balance + int(session.execute(q).scalar_one())


def draft_from_txn(txn: Txn) -> TxnDraft:
    return TxnDraft(
        date=txn.date,
        kind=txn.kind,
        description=txn.description,
        counterparty=txn.counterparty,
        notes=txn.notes,
        source=txn.source,
        import_row_id=txn.import_row_id,
        legs=[LegIn(account_id=leg.account_id, amount=leg.amount, inferred=bool(leg.inferred)) for leg in txn.legs],
        splits=[
            SplitIn(
                amount=s.amount,
                category_id=s.category_id,
                debt_id=s.debt_id,
                earmark_id=s.earmark_id,
                asset_id=s.asset_id,
                cost_type=s.cost_type,
                project_id=s.project_id,
                note=s.note,
            )
            for s in txn.splits
        ],
        trades=[
            TradeIn(
                account_id=t.account_id,
                security_id=t.security_id,
                action=t.action,
                units=t.units,
                price=t.price,
                fees=t.fees,
            )
            for t in txn.trades
        ],
    )
