"""Debts: outstanding principal, expected schedules, payment split suggestions, repayment summaries."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Debt, DebtBalanceSnapshot, Txn, TxnSplit
from app.domain import loans
from app.services.common import DomainError, NotFound


def rate_on(debt: Debt, d: date) -> Decimal:
    rate = Decimal(0)
    for p in debt.rate_periods:  # ordered by from_date
        if p.from_date <= d:
            rate = p.annual_rate
        elif rate == 0:
            rate = p.annual_rate  # before the first period: use the first known rate
            break
        else:
            break
    return rate


def outstanding(session: Session, debt: Debt, on: date) -> int:
    """Outstanding principal (positive) at the end of `on`."""
    if debt.repayment_type == "group":
        return sum(outstanding(session, part, on) for part in debt.parts)
    if debt.start_date > on:
        return 0
    snap = session.execute(
        select(DebtBalanceSnapshot)
        .where(DebtBalanceSnapshot.debt_id == debt.id, DebtBalanceSnapshot.date <= on)
        .order_by(DebtBalanceSnapshot.date.desc())
        .limit(1)
    ).scalar_one_or_none()
    base_date, base = (snap.date, snap.balance) if snap else (debt.start_date, debt.principal_original)
    q = (
        select(func.coalesce(func.sum(TxnSplit.amount), 0))
        .join(Txn, Txn.id == TxnSplit.txn_id)
        .where(TxnSplit.debt_id == debt.id, Txn.date <= on)
    )
    # a snapshot is the balance at the end of its day; the original principal is the balance before day-one flows
    q = q.where(Txn.date > base_date) if snap else q.where(Txn.date >= base_date)
    return base + int(session.execute(q).scalar_one())


def schedule(session: Session, debt: Debt) -> list[loans.ScheduleRow]:
    if debt.repayment_type in ("group", "free") or not debt.term_months:
        return []
    return loans.build_schedule(
        debt.principal_original, debt.start_date, debt.term_months, debt.repayment_type, lambda d: rate_on(debt, d)
    )


def _expected_principal(debt: Debt, on: date, balance: int) -> int:
    if debt.repayment_type == "annuity" and debt.term_months:
        elapsed = (on.year - debt.start_date.year) * 12 + on.month - debt.start_date.month
        remaining = max(1, debt.term_months - elapsed + 1)
        rate = rate_on(debt, on)
        return max(0, loans.annuity_payment(balance, rate, remaining) - loans.monthly_interest(balance, rate))
    if debt.repayment_type == "linear" and debt.term_months:
        elapsed = (on.year - debt.start_date.year) * 12 + on.month - debt.start_date.month
        remaining = max(1, debt.term_months - elapsed + 1)
        return balance // remaining
    return 0


def suggest_payment_splits(session: Session, debt_id: int, on: date, amount: int) -> list[dict]:
    """Split an outgoing payment (positive `amount`) into interest (expense) and principal (debt) splits.
    For a loan group, interest and expected principal are computed per part and any remainder goes to
    the largest part. Returned split amounts are negative (money leaving the account)."""
    debt = session.get(Debt, debt_id)
    if debt is None:
        raise NotFound("Debt", debt_id)
    parts = debt.parts if debt.repayment_type == "group" else [debt]
    if not parts:
        raise DomainError("debt_parts", f"{debt.name} has no loan parts")
    plan: list[tuple[Debt, int, int]] = []
    for part in parts:
        balance = outstanding(session, part, on)
        if part.repayment_type == "free":
            plan.append((part, 0, 0))
            continue
        interest = loans.monthly_interest(balance, rate_on(part, on))
        plan.append((part, interest, min(balance, _expected_principal(part, on, balance))))
    total = sum(i + p for _, i, p in plan)
    remainder = amount - total
    largest = max(range(len(plan)), key=lambda i: outstanding(session, plan[i][0], on))
    part, i, p = plan[largest]
    if remainder < 0 and total > 0 and len(plan) == 1:
        # single loan paid less than expected: interest first
        i2 = min(i, amount)
        plan[largest] = (part, i2, amount - i2)
    else:
        plan[largest] = (part, i, p + remainder)
    splits: list[dict] = []
    for part, interest, principal in plan:
        if interest:
            if part.interest_category_id is None and debt.interest_category_id is None:
                raise DomainError("interest_category", f"Set an interest category on {part.name}")
            splits.append(
                {
                    "amount": -interest,
                    "category_id": part.interest_category_id or debt.interest_category_id,
                    "cost_type": "fixed",
                    "note": f"Interest {part.name}",
                }
            )
        if principal:
            splits.append({"amount": -principal, "debt_id": part.id, "note": f"Principal {part.name}"})
    return splits


def repayment_summary(session: Session, debt: Debt, start: date, end: date) -> dict:
    ids = [p.id for p in debt.parts] if debt.repayment_type == "group" else [debt.id]
    principal = session.execute(
        select(func.coalesce(func.sum(TxnSplit.amount), 0))
        .join(Txn)
        .where(TxnSplit.debt_id.in_(ids), Txn.date >= start, Txn.date <= end, TxnSplit.amount < 0)
    ).scalar_one()
    cats = {c for c in [debt.interest_category_id, *[p.interest_category_id for p in debt.parts]] if c}
    interest = 0
    if cats:
        pay_txns = select(TxnSplit.txn_id).where(TxnSplit.debt_id.in_(ids))
        interest = session.execute(
            select(func.coalesce(func.sum(TxnSplit.amount), 0))
            .join(Txn)
            .where(
                TxnSplit.category_id.in_(cats),
                TxnSplit.txn_id.in_(pay_txns),
                Txn.date >= start,
                Txn.date <= end,
            )
        ).scalar_one()
    return {"principal_repaid": -int(principal), "interest_paid": -int(interest)}


def payoff_date(session: Session, debt: Debt, on: date) -> date | None:
    if debt.repayment_type == "group":
        dates = [payoff_date(session, p, on) for p in debt.parts]
        known = [d for d in dates if d]
        return max(known) if known else None
    if debt.repayment_type == "free" or not debt.term_months:
        return None
    return loans.add_months(debt.start_date, debt.term_months)
