"""Loan maths: schedules and interest/principal suggestions. Pure functions, amounts in minor units."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.money import round_minor


@dataclass(frozen=True)
class ScheduleRow:
    period: int
    date: date
    payment: int
    interest: int
    principal: int
    balance_after: int


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError("unreachable")


def monthly_interest(balance: int, annual_rate: Decimal) -> int:
    return round_minor(Decimal(balance) * annual_rate / 12)


def annuity_payment(balance: int, annual_rate: Decimal, months: int) -> int:
    if months <= 0:
        return balance
    r = annual_rate / 12
    if r == 0:
        return round_minor(Decimal(balance) / months)
    factor = (1 + r) ** months
    return round_minor(Decimal(balance) * r * factor / (factor - 1))


def build_schedule(
    principal: int,
    start: date,
    term_months: int,
    repayment_type: str,
    rate_for: Callable[[date], Decimal],
) -> list[ScheduleRow]:
    """Expected schedule. The annuity payment is recomputed whenever the rate changes."""
    rows: list[ScheduleRow] = []
    balance = principal
    current_rate: Decimal | None = None
    payment = 0
    for n in range(1, term_months + 1):
        pay_date = add_months(start, n)
        rate = rate_for(pay_date)
        remaining = term_months - n + 1
        interest = monthly_interest(balance, rate)
        if repayment_type == "annuity":
            if rate != current_rate:
                payment = annuity_payment(balance, rate, remaining)
                current_rate = rate
            principal_part = min(balance, payment - interest) if n < term_months else balance
        elif repayment_type == "linear":
            principal_part = min(balance, round_minor(Decimal(balance) / remaining))
        elif repayment_type == "interest_only":
            principal_part = balance if n == term_months else 0
        else:  # free: no schedule
            break
        balance -= principal_part
        rows.append(ScheduleRow(n, pay_date, interest + principal_part, interest, principal_part, balance))
        if balance <= 0:
            break
    return rows


def suggest_split(outstanding: int, annual_rate: Decimal, amount: int, repayment_type: str) -> tuple[int, int]:
    """Split a (positive) payment amount into (interest, principal)."""
    if repayment_type == "free" or outstanding <= 0:
        return 0, amount
    interest = min(amount, monthly_interest(outstanding, annual_rate))
    return interest, amount - interest
