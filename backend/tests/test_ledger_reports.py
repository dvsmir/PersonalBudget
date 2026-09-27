from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.db.models import Debt, DebtRatePeriod, Earmark
from app.domain import loans
from app.services import debts as debt_svc
from app.services import positions, reports
from app.services.common import DomainError
from app.services.ledger import LegIn, SplitIn, TxnDraft, account_balance, create_txn
from tests.conftest import acc, cat

D = date(2026, 3, 10)


def expense(db, amount, category="Eetwaar", account="ABN", d=D, **kw):
    a = acc(db, account)
    return create_txn(db, TxnDraft(date=d, kind="expense", description="x", legs=[LegIn(account_id=a.id, amount=amount)],
                                   splits=[SplitIn(amount=amount, category_id=cat(db, category).id, **kw)]), None)


def test_expense_and_balance(db):
    expense(db, -1234)
    assert account_balance(db, acc(db, "ABN").id) == -1234


def test_split_sum_must_match(db):
    a = acc(db, "ABN")
    with pytest.raises(DomainError) as e:
        create_txn(db, TxnDraft(date=D, kind="expense", legs=[LegIn(account_id=a.id, amount=-1000)],
                                splits=[SplitIn(amount=-900, category_id=cat(db, "Eetwaar").id)]), None)
    assert e.value.code == "split_sum"


def test_before_opening_rejected(db):
    with pytest.raises(DomainError) as e:
        expense(db, -100, d=date(2019, 1, 1))
    assert e.value.code == "before_opening"


def test_conversion_is_wealth_neutral_and_not_an_expense(db):
    """Spec §3.2: €1,000 → ₽95,000 at market 100 → conversion cost −€50, no income/expense."""
    eur, rub = acc(db, "ABN"), acc(db, "Rubles")
    t = create_txn(db, TxnDraft(date=D, kind="transfer", legs=[LegIn(account_id=eur.id, amount=-100000),
                                                             LegIn(account_id=rub.id, amount=9500000)]), None)
    assert t.fx_diff_ref == -5000
    m = reports.month_summary(db, "2026-03")
    assert m["summary_ref"]["income"] == 0 and m["summary_ref"]["expenses"] == 0
    assert m["summary_ref"]["conversion_cost"] == -5000
    # spend the rubles: counted once, valued at that day's rate (100) = €100
    expense(db, -1000000, account="Rubles")
    assert reports.month_summary(db, "2026-03")["summary_ref"]["expenses"] == -10000


def test_same_currency_transfer_must_cancel(db):
    with pytest.raises(DomainError):
        create_txn(db, TxnDraft(date=D, kind="transfer", legs=[LegIn(account_id=acc(db, "ABN").id, amount=-100),
                                                             LegIn(account_id=acc(db, "Cash").id, amount=90)]), None)


def test_month_summary_by_cost_type_and_subcategory(db):
    apt = cat(db, "Apt")
    vve = next(c for c in apt.children if c.name == "VVE")
    a = acc(db, "ABN")
    create_txn(db, TxnDraft(date=D, kind="expense", legs=[LegIn(account_id=a.id, amount=-50000)],
                            splits=[SplitIn(amount=-50000, category_id=vve.id)]), None)
    expense(db, -3000)  # Eetwaar, variable
    expense(db, -20000, category="Meubilair")  # one_time by default
    expense(db, -1000, cost_type="one_time")  # override on Eetwaar
    m = reports.month_summary(db, "2026-03")
    assert m["by_cost_type"]["fixed"]["EUR"] == -50000
    assert m["by_cost_type"]["variable"]["EUR"] == -3000
    assert m["by_cost_type"]["one_time"]["EUR"] == -21000
    apt_node = next(n for n in m["expense"] if n["name"] == "Apt")
    assert apt_node["subcategories"][0]["name"] == "VVE"


def test_earmark_lowers_available_funds_not_net_worth(db):
    a = acc(db, "ABN")
    create_txn(db, TxnDraft(date=D, kind="income", legs=[LegIn(account_id=a.id, amount=500000)],
                            splits=[SplitIn(amount=500000, category_id=cat(db, "JB Salaris", "income").id)]), None)
    alisa = db.query(Earmark).filter_by(name="Alisa").one()
    create_txn(db, TxnDraft(date=D, kind="earmark", splits=[SplitIn(amount=100000, earmark_id=alisa.id)]), None)
    snap = positions.snapshot(db, D)
    assert snap["funds"] == 500000
    assert snap["available_funds"] == 400000
    assert snap["net_worth"] == snap["funds"] - snap["debts"]  # earmark not subtracted
    assert snap["debts"] == 1_750_000  # seeded Hypotheek part 2


def _hypotheek_parts(db):
    group = db.query(Debt).filter_by(name="Hypotheek").one()
    p1, p2 = sorted(group.parts, key=lambda d: d.name)
    p1.principal_original, p1.term_months, p1.start_date = 40_000_000, 360, date(2021, 1, 1)
    p2.principal_original, p2.term_months, p2.start_date = 1_750_000, 360, date(2021, 1, 1)
    p1.rate_periods = [DebtRatePeriod(from_date=date(2021, 1, 1), annual_rate=Decimal("0.03"))]
    p2.rate_periods = [DebtRatePeriod(from_date=date(2021, 1, 1), annual_rate=Decimal("0.05"))]
    db.flush()
    return group, p1, p2


def test_mortgage_two_parts_split_and_outstanding(db):
    group, p1, p2 = _hypotheek_parts(db)
    splits = debt_svc.suggest_payment_splits(db, group.id, D, 175000)
    assert sum(s["amount"] for s in splits) == -175000
    interest = {s["note"]: s["amount"] for s in splits if "category_id" in s}
    assert interest["Interest Hypotheek deel 1"] == -100000  # 400k × 3% / 12
    assert interest["Interest Hypotheek deel 2"] == -7292  # 17.5k × 5% / 12
    a = acc(db, "ABN")
    create_txn(db, TxnDraft(date=D, kind="debt_payment", legs=[LegIn(account_id=a.id, amount=-175000)],
                            splits=[SplitIn(**s) for s in splits]), None)
    principal = -sum(s["amount"] for s in splits if s.get("debt_id"))
    assert debt_svc.outstanding(db, group, D) == 40_000_000 + 1_750_000 - principal
    # only the interest is an expense; principal is wealth-neutral
    m = reports.month_summary(db, "2026-03")
    assert m["summary_ref"]["expenses"] == -107292
    assert m["summary_ref"]["debt_principal_repaid"] == principal


def test_group_debt_cannot_be_booked_directly(db):
    group, *_ = _hypotheek_parts(db)
    with pytest.raises(DomainError) as e:
        create_txn(db, TxnDraft(date=D, kind="debt_payment", legs=[LegIn(account_id=acc(db, "ABN").id, amount=-100)],
                                splits=[SplitIn(amount=-100, debt_id=group.id)]), None)
    assert e.value.code == "debt_group"


def test_net_worth_bridge_explains_delta(db):
    expense(db, -5000)
    a, rub = acc(db, "ABN"), acc(db, "Rubles")
    create_txn(db, TxnDraft(date=D, kind="income", legs=[LegIn(account_id=a.id, amount=300000)],
                            splits=[SplitIn(amount=300000, category_id=cat(db, "JB Salaris", "income").id)]), None)
    create_txn(db, TxnDraft(date=D, kind="transfer", legs=[LegIn(account_id=a.id, amount=-100000),
                                                         LegIn(account_id=rub.id, amount=9000000)]), None)
    b = reports.net_worth_bridge(db, date(2026, 3, 1), date(2026, 3, 31))
    assert sum(b["components"].values()) == b["net_worth_end"] - b["net_worth_start"]
    assert b["components"]["conversion_cost"] == -10000
    assert b["components"]["fx_revaluation_and_rounding"] == 0


def test_year_overview_months(db):
    expense(db, -700)
    y = reports.year_overview(db, 2026)
    march = y["months"][2]
    assert march["expenses"]["EUR"] == -700


@settings(max_examples=50, deadline=None)
@given(principal=st.integers(100_00, 1_000_000_00), rate=st.decimals("0", "0.08", places=4), months=st.integers(12, 360))
def test_annuity_schedule_repays_everything(principal, rate, months):
    rows = loans.build_schedule(principal, date(2020, 1, 1), months, "annuity", lambda d: Decimal(rate))
    assert rows[-1].balance_after == 0
    assert sum(r.principal for r in rows) == principal
