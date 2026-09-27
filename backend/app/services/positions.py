"""Point-in-time values of accounts, holdings, assets, debts and earmarks (native and EUR)."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Asset,
    AssetValuation,
    Debt,
    Earmark,
    InvestmentTrade,
    Security,
    SecurityPrice,
    Txn,
    TxnLeg,
    TxnSplit,
)
from app.domain.money import minor_units, round_minor
from app.services import debts as debt_svc
from app.services.fx import RateBook


def account_balances(session: Session, on: date) -> dict[int, int]:
    rows = session.execute(
        select(TxnLeg.account_id, func.sum(TxnLeg.amount))
        .join(Txn)
        .where(Txn.date <= on)
        .group_by(TxnLeg.account_id)
    ).all()
    sums = {acc_id: int(total) for acc_id, total in rows}
    result = {}
    for acc in session.scalars(select(Account)):
        if acc.opening_date <= on:
            result[acc.id] = acc.opening_balance + sums.get(acc.id, 0)
    return result


def holdings(session: Session, on: date) -> list[dict]:
    rows = session.execute(
        select(InvestmentTrade.account_id, InvestmentTrade.security_id, InvestmentTrade.units)
        .join(Txn, Txn.id == InvestmentTrade.txn_id)
        .where(Txn.date <= on)
    ).all()
    units: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    for acc_id, sec_id, u in rows:
        units[(acc_id, sec_id)] += Decimal(u)
    out = []
    for (acc_id, sec_id), u in units.items():
        if u == 0:
            continue
        sec = session.get(Security, sec_id)
        price_row = session.execute(
            select(SecurityPrice.price, SecurityPrice.date)
            .where(SecurityPrice.security_id == sec_id, SecurityPrice.date <= on)
            .order_by(SecurityPrice.date.desc())
            .limit(1)
        ).first()
        if price_row is None:  # fall back to the last trade price
            price_row = session.execute(
                select(InvestmentTrade.price, Txn.date)
                .join(Txn)
                .where(InvestmentTrade.security_id == sec_id, Txn.date <= on)
                .order_by(Txn.date.desc())
                .limit(1)
            ).first()
        price = Decimal(price_row[0]) if price_row else Decimal(0)
        value = round_minor(u * price * (Decimal(10) ** minor_units(sec.currency)))  # type: ignore[union-attr]
        out.append(
            {
                "account_id": acc_id,
                "security_id": sec_id,
                "symbol": sec.symbol,  # type: ignore[union-attr]
                "name": sec.name,  # type: ignore[union-attr]
                "currency": sec.currency,  # type: ignore[union-attr]
                "units": u,
                "price": price,
                "price_date": price_row[1] if price_row else None,
                "value": value,
            }
        )
    return out


def asset_values(session: Session, on: date) -> list[dict]:
    out = []
    for asset in session.scalars(select(Asset).where(Asset.archived_at.is_(None))):
        if asset.acquired_date and asset.acquired_date > on:
            continue
        if asset.disposed_date and asset.disposed_date <= on:
            continue
        row = session.execute(
            select(AssetValuation.value, AssetValuation.date)
            .where(AssetValuation.asset_id == asset.id, AssetValuation.date <= on)
            .order_by(AssetValuation.date.desc())
            .limit(1)
        ).first()
        value = row[0] if row else (asset.acquired_value or 0)
        out.append({"asset": asset, "value": value, "valued_on": row[1] if row else asset.acquired_date})
    return out


def earmark_balances(session: Session, on: date) -> dict[int, int]:
    rows = session.execute(
        select(TxnSplit.earmark_id, func.sum(TxnSplit.amount))
        .join(Txn)
        .where(TxnSplit.earmark_id.is_not(None), Txn.date <= on)
        .group_by(TxnSplit.earmark_id)
    ).all()
    return {eid: int(total) for eid, total in rows}


def snapshot(session: Session, on: date, book: RateBook | None = None) -> dict:
    """Net-worth components in EUR at the end of `on`. See Data.md §15."""
    book = book or RateBook(session)
    balances = account_balances(session, on)
    accounts = {a.id: a for a in session.scalars(select(Account))}
    funds = investments = 0
    for acc_id, bal in balances.items():
        acc = accounts[acc_id]
        if not acc.include_in_net_worth:
            continue
        ref = book.to_ref(bal, acc.currency, on).amount
        if acc.type == "investment":
            investments += ref
        else:
            funds += ref
    for h in holdings(session, on):
        if accounts[h["account_id"]].include_in_net_worth:
            investments += book.to_ref(h["value"], h["currency"], on).amount
    assets = sum(
        book.to_ref(a["value"], a["asset"].currency, on).amount
        for a in asset_values(session, on)
        if a["asset"].include_in_net_worth
    )
    debts_total = 0
    for debt in session.scalars(select(Debt).where(Debt.repayment_type != "group")):
        if debt.closed_at and debt.closed_at <= on:
            continue
        debts_total += book.to_ref(debt_svc.outstanding(session, debt, on), debt.currency, on).amount
    earmarks = 0
    for eid, bal in earmark_balances(session, on).items():
        em = session.get(Earmark, eid)
        earmarks += book.to_ref(bal, em.currency, on).amount  # type: ignore[union-attr]
    return {
        "date": on,
        "funds": funds,
        "available_funds": funds - earmarks,
        "earmarks": earmarks,
        "investments": investments,
        "assets": assets,
        "debts": debts_total,
        "net_worth": funds + investments + assets - debts_total,
    }
