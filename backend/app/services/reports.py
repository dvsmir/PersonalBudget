"""Dashboards and reports. All figures are computed here; clients only format them."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.db.models import (
    Account,
    BudgetLine,
    Category,
    Debt,
    Project,
    Txn,
    TxnLeg,
    TxnSplit,
)
from app.services import debts as debt_svc
from app.services import positions
from app.services.fx import RateBook


@dataclass
class IELine:
    date: date
    category_id: int  # top-level
    subcategory_id: int | None
    ie_kind: str
    cost_type: str
    amount: int
    currency: str
    amount_ref: int
    project_id: int | None
    txn_kind: str
    txn_id: int


def month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    start = date(y, m, 1)
    end = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
    return start, end


def ie_lines(session: Session, start: date, end: date, category_ids: list[int] | None = None) -> list[IELine]:
    """Every income/expense split in [start, end] with resolved hierarchy and cost type (Data.md v_ie_line)."""
    parent = aliased(Category)
    q = (
        select(
            Txn.date,
            Category.id,
            Category.parent_id,
            Category.kind,
            TxnSplit.cost_type,
            Category.default_cost_type,
            parent.default_cost_type,
            TxnSplit.amount,
            TxnSplit.currency,
            TxnSplit.amount_ref,
            TxnSplit.project_id,
            Txn.kind,
            Txn.id,
        )
        .join(Txn, Txn.id == TxnSplit.txn_id)
        .join(Category, Category.id == TxnSplit.category_id)
        .outerjoin(parent, parent.id == Category.parent_id)
        .where(Txn.date >= start, Txn.date <= end)
    )
    out = []
    for d, cid, pid, kind, ct, ct_sub, ct_parent, amount, ccy, ref, proj, tkind, tid in session.execute(q):
        top = pid if pid is not None else cid
        if category_ids and top not in category_ids and cid not in category_ids:
            continue
        out.append(
            IELine(
                d, top, cid if pid is not None else None, kind,
                ct or ct_sub or ct_parent or "variable", amount, ccy, ref, proj, tkind, tid,
            )
        )
    return out


def _cat_names(session: Session) -> dict[int, Category]:
    return {c.id: c for c in session.scalars(select(Category))}


def _funds_flow(session: Session, start: date, end: date) -> dict[str, int]:
    """Movements in EUR that are neither income nor expense: principal repaid, net savings into investments."""
    principal = session.execute(
        select(func.coalesce(func.sum(TxnSplit.amount_ref), 0))
        .join(Txn)
        .where(TxnSplit.debt_id.is_not(None), TxnSplit.amount < 0, Txn.date >= start, Txn.date <= end)
    ).scalar_one()
    inv_accounts = select(Account.id).where(Account.type == "investment")
    to_investments = session.execute(
        select(func.coalesce(func.sum(TxnLeg.amount_ref), 0))
        .join(Txn)
        .where(
            Txn.kind == "transfer",
            TxnLeg.account_id.in_(inv_accounts),
            Txn.date >= start,
            Txn.date <= end,
        )
    ).scalar_one()
    adjustments = session.execute(
        select(func.coalesce(func.sum(TxnLeg.amount_ref), 0))
        .join(Txn)
        .where(Txn.kind == "adjustment", Txn.date >= start, Txn.date <= end)
    ).scalar_one()
    conversion = session.execute(
        select(func.coalesce(func.sum(Txn.fx_diff_ref), 0)).where(Txn.date >= start, Txn.date <= end)
    ).scalar_one()
    return {
        "debt_principal_repaid": -int(principal),
        "to_investments": int(to_investments),
        "adjustments": int(adjustments),
        "conversion_cost": int(conversion),
    }


def _group(lines: list[IELine], cats: dict[int, Category], native: bool) -> dict:
    """Totals by ie_kind -> category -> subcategory, per currency (native) or in EUR."""
    tree: dict[str, dict[int, dict]] = {"income": {}, "expense": {}}
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, dict[str, int]] = {"income": defaultdict(int), "expense": defaultdict(int)}
    for ln in lines:
        ccy = ln.currency if native else "EUR"
        val = ln.amount if native else ln.amount_ref
        node = tree[ln.ie_kind].setdefault(
            ln.category_id, {"category_id": ln.category_id, "name": cats[ln.category_id].name,
                             "totals": defaultdict(int), "sub": {}}
        )
        node["totals"][ccy] += val
        sub_id = ln.subcategory_id
        if sub_id:
            sub = node["sub"].setdefault(
                sub_id, {"category_id": sub_id, "name": cats[sub_id].name, "totals": defaultdict(int)}
            )
            sub["totals"][ccy] += val
        totals[ln.ie_kind][ccy] += val
        if ln.ie_kind == "expense":
            by_type[ln.cost_type][ccy] += val

    def finish(nodes: dict[int, dict]) -> list[dict]:
        result = []
        for n in nodes.values():
            item = {"category_id": n["category_id"], "name": n["name"], "totals": dict(n["totals"])}
            if "sub" in n:
                item["subcategories"] = sorted(
                    ({**s, "totals": dict(s["totals"])} for s in n["sub"].values()), key=lambda s: s["name"]
                )
            result.append(item)
        return sorted(result, key=lambda x: x["name"].lower())

    return {
        "income": finish(tree["income"]),
        "expense": finish(tree["expense"]),
        "by_cost_type": {k: dict(v) for k, v in by_type.items()},
        "totals": {k: dict(v) for k, v in totals.items()},
    }


def month_summary(session: Session, month: str, native: bool = False) -> dict:
    start, end = month_bounds(month)
    lines = ie_lines(session, start, end)
    grouped = _group(lines, _cat_names(session), native)
    inc = sum(ln.amount_ref for ln in lines if ln.ie_kind == "income")
    exp = sum(ln.amount_ref for ln in lines if ln.ie_kind == "expense")
    flows = _funds_flow(session, start, end)
    # comparisons in EUR
    prev_start, prev_end = month_bounds((start - timedelta(days=1)).strftime("%Y-%m"))
    prev = ie_lines(session, prev_start, prev_end)
    y_start = date(start.year - 1, start.month, 1)
    last12 = ie_lines(session, y_start, start - timedelta(days=1))
    return {
        "month": month,
        "currency_mode": "native" if native else "reference",
        **grouped,
        "summary_ref": {
            "income": inc,
            "expenses": exp,
            "balance": inc + exp,
            "cash_flow": inc + exp - flows["debt_principal_repaid"] - flows["to_investments"],
            **flows,
        },
        "compare_ref": {
            "prev_income": sum(x.amount_ref for x in prev if x.ie_kind == "income"),
            "prev_expenses": sum(x.amount_ref for x in prev if x.ie_kind == "expense"),
            "avg12_income": sum(x.amount_ref for x in last12 if x.ie_kind == "income") // 12,
            "avg12_expenses": sum(x.amount_ref for x in last12 if x.ie_kind == "expense") // 12,
        },
    }


def year_overview(session: Session, year: int, native: bool = False) -> dict:
    start, end = date(year, 1, 1), date(year, 12, 31)
    lines = ie_lines(session, start, end)
    cats = _cat_names(session)
    book = RateBook(session)
    months = []
    for m in range(1, 13):
        ms, me = month_bounds(f"{year}-{m:02d}")
        ml = [ln for ln in lines if ms <= ln.date <= me]
        inc: dict[str, int] = defaultdict(int)
        exp: dict[str, int] = defaultdict(int)
        for ln in ml:
            ccy, val = (ln.currency, ln.amount) if native else ("EUR", ln.amount_ref)
            (inc if ln.ie_kind == "income" else exp)[ccy] += val
        snap = positions.snapshot(session, min(me, date.today()), book) if ms <= date.today() else None
        months.append(
            {
                "month": f"{year}-{m:02d}",
                "income": dict(inc),
                "expenses": dict(exp),
                "balance": {c: inc.get(c, 0) + exp.get(c, 0) for c in set(inc) | set(exp)},
                "funds_end_ref": snap["funds"] if snap else None,
            }
        )
    elapsed = 12 if year < date.today().year else max(1, date.today().month)
    grouped = _group(lines, cats, native)
    for kind in ("income", "expense"):
        for node in grouped[kind]:
            node["avg_per_month"] = {c: v // elapsed for c, v in node["totals"].items()}
    heat: dict[int, list[int]] = defaultdict(lambda: [0] * 12)
    for ln in lines:
        if ln.ie_kind == "expense":
            heat[ln.category_id][ln.date.month - 1] += ln.amount_ref
    return {
        "year": year,
        "currency_mode": "native" if native else "reference",
        "months": months,
        **grouped,
        "heatmap_ref": [{"category_id": k, "name": cats[k].name, "months": v} for k, v in heat.items()],
    }


def month_ends(start: date, end: date) -> list[date]:
    out = []
    y, m = start.year, start.month
    while True:
        _, me = month_bounds(f"{y}-{m:02d}")
        out.append(min(me, end))
        if me >= end:
            break
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def net_worth_series(session: Session, start: date, end: date) -> list[dict]:
    book = RateBook(session)
    return [positions.snapshot(session, d, book) for d in month_ends(start, end)]


def net_worth_bridge(session: Session, start: date, end: date) -> dict:
    """Explain ΔNW over [start, end] (Spec.md §3.2)."""
    book = RateBook(session)
    before = positions.snapshot(session, start - timedelta(days=1), book)
    after = positions.snapshot(session, end, book)
    lines = ie_lines(session, start, end)
    income = sum(x.amount_ref for x in lines if x.ie_kind == "income")
    expenses = sum(x.amount_ref for x in lines if x.ie_kind == "expense")
    flows = _funds_flow(session, start, end)

    def period_sum(col, *conds):  # type: ignore[no-untyped-def]
        return int(
            session.execute(
                select(func.coalesce(func.sum(col), 0)).join(Txn).where(Txn.date >= start, Txn.date <= end, *conds)
            ).scalar_one()
        )

    capitalised = -period_sum(TxnSplit.amount_ref, TxnSplit.asset_id.is_not(None))
    asset_reval = after["assets"] - before["assets"] - capitalised
    # investment gain = change in holdings value not explained by trade cash
    trade_cash = period_sum(TxnLeg.amount_ref, Txn.kind == "investment")
    hold_before = before["investments"] - _inv_cash(session, start - timedelta(days=1), book)
    hold_after = after["investments"] - _inv_cash(session, end, book)
    investment_gain = hold_after - hold_before + trade_cash
    debt_flows = period_sum(TxnSplit.amount_ref, TxnSplit.debt_id.is_not(None))
    debt_corrections = -((after["debts"] - before["debts"]) - debt_flows)
    delta = after["net_worth"] - before["net_worth"]
    known = income + expenses + flows["adjustments"] + flows["conversion_cost"] + asset_reval + investment_gain + debt_corrections
    return {
        "start": start,
        "end": end,
        "net_worth_start": before["net_worth"],
        "net_worth_end": after["net_worth"],
        "components": {
            "income": income,
            "expenses": expenses,
            "adjustments": flows["adjustments"],
            "conversion_cost": flows["conversion_cost"],
            "asset_revaluation": asset_reval,
            "investment_gain": investment_gain,
            "debt_corrections": debt_corrections,
            "fx_revaluation_and_rounding": delta - known,
        },
    }


def _inv_cash(session: Session, on: date, book: RateBook) -> int:
    total = 0
    for acc_id, bal in positions.account_balances(session, on).items():
        acc = session.get(Account, acc_id)
        if acc and acc.type == "investment" and acc.include_in_net_worth:
            total += book.to_ref(bal, acc.currency, on).amount
    return total


def balances(session: Session, on: date) -> dict:
    book = RateBook(session)
    bals = positions.account_balances(session, on)
    snap = positions.snapshot(session, on, book)
    items = []
    per_ccy: dict[str, int] = defaultdict(int)
    for acc in session.scalars(select(Account).where(Account.archived_at.is_(None)).order_by(Account.sort_order, Account.name)):
        bal = bals.get(acc.id, 0)
        items.append(
            {
                "account_id": acc.id,
                "name": acc.name,
                "type": acc.type,
                "currency": acc.currency,
                "balance": bal,
                "balance_ref": book.to_ref(bal, acc.currency, on).amount,
            }
        )
        per_ccy[acc.currency] += bal
    return {"date": on, "accounts": items, "per_currency": dict(per_ccy), "snapshot": snap}


def budget_status(session: Session, month: str) -> dict:
    start, end = month_bounds(month)
    plan: dict[tuple[int, str], int] = defaultdict(int)
    cats = _cat_names(session)
    for line in session.scalars(select(BudgetLine).where(BudgetLine.month == month)):
        c = cats[line.category_id]
        plan[(c.parent_id or c.id, line.currency)] += line.amount
    actual: dict[tuple[int, str], int] = defaultdict(int)
    for ln in ie_lines(session, start, end):
        sign = -1 if ln.ie_kind == "expense" else 1
        actual[(ln.category_id, ln.currency)] += sign * ln.amount
    rows = []
    for key in sorted(set(plan) | set(actual), key=lambda k: (cats[k[0]].kind, cats[k[0]].name.lower())):
        cid, ccy = key
        p, a = plan.get(key, 0), actual.get(key, 0)
        rows.append(
            {
                "category_id": cid,
                "name": cats[cid].name,
                "kind": cats[cid].kind,
                "currency": ccy,
                "planned": p,
                "actual": a,
                "remaining": p - a,
                "pct_used": round(a / p * 100, 1) if p else None,
                "planned_line": key in plan,
            }
        )
    return {"month": month, "rows": rows}


def category_trend(session: Session, category_id: int, start: date, end: date) -> list[dict]:
    lines = ie_lines(session, start, end, [category_id])
    by_month: dict[str, int] = defaultdict(int)
    for ln in lines:
        by_month[ln.date.strftime("%Y-%m")] += ln.amount_ref
    return [{"month": d.strftime("%Y-%m"), "amount_ref": by_month.get(d.strftime("%Y-%m"), 0)} for d in month_ends(start, end)]


def project_summary(session: Session, project: Project) -> dict:
    cats = _cat_names(session)
    rows = session.execute(
        select(TxnSplit.category_id, TxnSplit.currency, func.sum(TxnSplit.amount), func.sum(TxnSplit.amount_ref),
               func.min(Txn.date), func.max(Txn.date))
        .join(Txn)
        .where(TxnSplit.project_id == project.id)
        .group_by(TxnSplit.category_id, TxnSplit.currency)
    ).all()
    by_cat = []
    total_ref = 0
    first = last = None
    for cid, ccy, amount, ref, d0, d1 in rows:
        c = cats.get(cid) if cid else None
        by_cat.append({"category_id": cid, "name": c.name if c else "—", "currency": ccy, "amount": int(amount), "amount_ref": int(ref)})
        total_ref += int(ref)
        first = min(first or d0, d0)
        last = max(last or d1, d1)
    return {
        "project_id": project.id,
        "total_ref": total_ref,
        "first_date": first,
        "last_date": last,
        "by_category": sorted(by_cat, key=lambda r: r["amount_ref"]),
        "budget_amount": project.budget_amount,
        "budget_currency": project.budget_currency,
    }


def debt_overview(session: Session, on: date) -> list[dict]:
    year_start = date(on.year, 1, 1)
    out = []
    for debt in session.scalars(select(Debt).where(Debt.parent_debt_id.is_(None), Debt.archived_at.is_(None))):
        original = sum(p.principal_original for p in debt.parts) if debt.repayment_type == "group" else debt.principal_original
        out.append(
            {
                "debt_id": debt.id,
                "name": debt.name,
                "currency": debt.currency,
                "outstanding": debt_svc.outstanding(session, debt, on),
                "original": original,
                "ytd": debt_svc.repayment_summary(session, debt, year_start, on),
                "payoff_date": debt_svc.payoff_date(session, debt, on),
                "parts": [
                    {"debt_id": p.id, "name": p.name, "outstanding": debt_svc.outstanding(session, p, on),
                     "rate": str(debt_svc.rate_on(p, on))}
                    for p in debt.parts
                ],
            }
        )
    return out


def reconciliation_report(session: Session, account_id: int) -> list[dict]:
    """Derived balance vs every checkpoint (statement / anchor / manual) for one account."""
    from app.db.models import AccountReconciliation
    from app.services.ledger import account_balance

    out = []
    for r in session.scalars(
        select(AccountReconciliation).where(AccountReconciliation.account_id == account_id).order_by(AccountReconciliation.date)
    ):
        derived = account_balance(session, account_id, r.date)
        out.append({"date": r.date, "source": r.source, "stated": r.stated_balance, "derived": derived,
                    "difference": derived - r.stated_balance, "note": r.note})
    inferred = session.execute(
        select(func.count()).select_from(TxnLeg).where(TxnLeg.account_id == account_id, TxnLeg.inferred == 1)
    ).scalar_one()
    if inferred:
        out.append({"date": None, "source": "inferred_legs", "stated": None, "derived": None,
                    "difference": None, "note": f"{inferred} inferred legs awaiting a statement row"})
    return out


