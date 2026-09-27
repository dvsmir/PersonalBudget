"""Household set-up (structure only, no transactions): currencies, categories (from the sheet's Config/Month
tabs), accounts + identifiers (Import.md §1), debts/assets/earmarks shells, import rules (Import.md §5.5).
Idempotent: existing rows (by name) are left alone."""

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    AccountIdentifier,
    Asset,
    Category,
    Currency,
    Debt,
    Earmark,
    ImportRule,
)
from app.services.common import get_setting, set_setting

HISTORY_START = date(2020, 11, 21)

CURRENCIES = [("EUR", "Euro", "€", 2), ("RUB", "Russian rouble", "₽", 2), ("USD", "US dollar", "$", 2),
              ("GBP", "Pound sterling", "£", 2)]

# name: (default cost type, AI hint, [(subcategory, cost type)])
EXPENSE = {
    "Accomodation": ("one_time", "hotels, holiday rentals", []),
    "Amusement": ("variable", "cinema, museums, games, streaming", [("Youtube", "fixed"), ("Domain", "fixed")]),
    "Apt": ("fixed", "running costs of the home in Amstelveen", [
        ("VVE", "fixed"), ("Verzekering", "fixed"), ("Life insurance", "fixed"), ("Stroom", "fixed"),
        ("Verwarming", "fixed"), ("Woning belasting", "fixed"), ("Verisure", "fixed"), ("Waterschap", "fixed"),
        ("Afval", "fixed"), ("Water", "fixed")]),
    "AptKopen": ("one_time", "buying property", []),
    "Apts Spb": ("variable", "costs of the apartment in St Petersburg", []),
    "Aqarium": ("variable", "aquarium", []),
    "Auto": ("variable", "car running costs", [
        ("AutoTax", "fixed"), ("AutoVerz", "fixed"), ("Fuel", "variable"), ("Parkeren", "variable"),
        ("Onderhoud", "variable")]),
    "AutoKopen": ("one_time", "buying a car", []),
    "Bank": ("fixed", "bank fees, card fees, investment fees", [("Account", "fixed"), ("LiabilityVerz", "fixed")]),
    "Belasting": ("fixed", "taxes (Belastingdienst)", []),
    "Cosmetics": ("variable", "cosmetics, hairdresser", []),
    "Diverse": ("variable", "small miscellaneous purchases", []),
    "Eetwaar": ("variable", "groceries: Albert Heijn, Jumbo, Lidl, markets", []),
    "Fietsen": ("variable", "bicycles", [("ANWB", "fixed")]),
    "Huishouden": ("variable", "household goods, cleaning, small home items", []),
    "Huur": ("fixed", "rent", []),
    "Hypotheek": ("fixed", "mortgage interest (principal is booked on the debt)", []),
    "Juwelier": ("one_time", "jewellery", []),
    "Kind": ("variable", "children: school, clubs, clothes, toys", [
        ("Guitar", "fixed"), ("Naschool", "fixed"), ("School", "fixed"), ("Basket", "fixed"), ("Platforma C", "fixed"),
        ("Music", "fixed"), ("Chess", "fixed"), ("Kinderopvang", "fixed")]),
    "Kleding": ("variable", "clothes and shoes", []),
    "Meubilair": ("one_time", "furniture", []),
    "Renovatie": ("one_time", "renovation materials and work", []),
    "Restaraunt": ("variable", "restaurants, cafés, take-away", []),
    "Travel": ("one_time", "tickets, travel bookings", []),
    "Verbinding": ("fixed", "internet, phone", [("KPN", "fixed"), ("Mobile", "fixed")]),
    "Vervoer": ("variable", "public transport, taxi", []),
    "Vita": ("variable", "Vita", []),
    "Zorg": ("variable", "health: insurance, pharmacy, doctors", [("ZorgVerz", "fixed"), ("EigenRisico", "variable")]),
}
INCOME = {
    "Allowance": "child benefit / allowances (SVB, toeslagen)",
    "Apts Spb": "rent from the St Petersburg apartment",
    "Bonus": "bonuses, gifts",
    "Debt": "money borrowed or returned to us",
    "Dividend": "dividends",
    "Freelance": "freelance work",
    "Interest": "interest on savings (rente)",
    "JB Salaris": "salary",
    "Marina": "Marina",
    "Psychoanalysis": "psychoanalysis practice fees (EUR and RUB)",
    "Return": "refunds and returns",
    "Salaris": "salary (older)",
    "Vita": "Vita",
}

# name, type, currency, institution, opening date, identifiers
ACCOUNTS = [
    ("ABN", "current", "EUR", "ABN AMRO", HISTORY_START, [("iban", "NL05ABNA0886956927"), ("account_no", "886956927")]),
    ("Sparen ABN", "savings", "EUR", "ABN AMRO", HISTORY_START, [("iban", "NL61ABNA0119875748"), ("account_no", "119875748")]),
    ("Sparen Bunq", "savings", "EUR", "bunq", HISTORY_START, [("iban", "NL42BUNQ2094599752")]),
    ("ABN Invest", "investment", "EUR", "ABN AMRO", HISTORY_START, [("account_no", "109047850")]),
    ("Credit card", "credit_card", "EUR", "ICS / ABN AMRO", HISTORY_START, [("card_last4", "4926")]),
    ("Cash", "cash", "EUR", None, HISTORY_START, []),
    ("Rubles", "current", "RUB", None, date(2021, 1, 1), []),
]

ASSETS = [("Fideliolaan 32", "real_estate", "EUR"), ("Ленинский 82-55", "real_estate", "RUB"),
          ("BMW X5", "vehicle", "RUB"), ("Outlander", "vehicle", "EUR")]

# (priority, match, action, note) — Import.md §5.5. Defaults (€ → ABN, ₽ → Rubles) are built in.
RULES = [
    (1, {"desc_regex": r"^cre?d(i)?t\s*-", "currency": "EUR"}, {"account": "Credit card"}, "R1 credit card rows"),
    (3, {"category": "Invest", "currency": "EUR"}, {"account": "ABN", "kind": "transfer", "counter_account": "ABN Invest"}, "R3"),
    (4, {"desc_regex": r"^(balancing|корректировка)$"}, {"kind": "adjustment"}, "R4"),
    (6, {"category": "Bonus", "desc_regex": r"abn\s*rente", "currency": "EUR"},
     {"account": "Sparen ABN", "category": "Interest"}, "R6a"),
    (7, {"category": "Bonus", "desc_regex": r"bunq\s*rente", "currency": "EUR"},
     {"account": "Sparen Bunq", "category": "Interest"}, "R6b"),
    (8, {"category": "Bonus", "desc_regex": r"^rente$", "currency": "EUR"}, {"category": "Interest"}, "R6c bank unknown"),
]


def seed(session: Session) -> dict:
    created: dict[str, int] = {}

    def bump(k: str) -> None:
        created[k] = created.get(k, 0) + 1

    for code, name, symbol, minor in CURRENCIES:
        if session.get(Currency, code) is None:
            session.add(Currency(code=code, name=name, symbol=symbol, minor_units=minor))
            bump("currencies")
    session.flush()

    existing = {(c.parent_id, c.name, c.kind) for c in session.scalars(select(Category))}
    for order, (name, (ct, hint, subs)) in enumerate(EXPENSE.items()):
        parent = session.execute(select(Category).where(Category.name == name, Category.kind == "expense",
                                                        Category.parent_id.is_(None))).scalar_one_or_none()
        if parent is None:
            parent = Category(kind="expense", name=name, default_cost_type=ct, description=hint, sort_order=order)
            session.add(parent)
            session.flush()
            bump("categories")
        for j, (sub, sct) in enumerate(subs):
            if (parent.id, sub, "expense") not in existing:
                session.add(Category(kind="expense", name=sub, parent_id=parent.id, default_cost_type=sct, sort_order=j))
                bump("categories")
    for order, (name, hint) in enumerate(INCOME.items()):
        if (None, name, "income") not in existing:
            session.add(Category(kind="income", name=name, description=hint, sort_order=order))
            bump("categories")
    session.flush()

    for order, (name, type_, ccy, inst, opening, idents) in enumerate(ACCOUNTS):
        acc = session.execute(select(Account).where(Account.name == name)).scalar_one_or_none()
        if acc is None:
            acc = Account(name=name, type=type_, currency=ccy, institution=inst, opening_date=opening,
                          opening_balance=0, sort_order=order)
            session.add(acc)
            session.flush()
            bump("accounts")
        have = {(i.kind, i.value) for i in acc.identifiers}
        for kind, value in idents:
            if (kind, value) not in have:
                session.add(AccountIdentifier(account_id=acc.id, kind=kind, value=value))
    session.flush()

    hyp_cat = session.execute(select(Category).where(Category.name == "Hypotheek", Category.kind == "expense")).scalar_one()
    if session.execute(select(Debt).where(Debt.name == "Hypotheek")).scalar_one_or_none() is None:
        group = Debt(name="Hypotheek", lender="Mortgage lender", currency="EUR", type="mortgage", repayment_type="group",
                     start_date=HISTORY_START, interest_category_id=hyp_cat.id)
        session.add(group)
        session.flush()
        # principal, rates and terms are filled in via the UI (Wealth → Debts)
        session.add(Debt(name="Hypotheek deel 1", currency="EUR", type="mortgage", repayment_type="annuity",
                         principal_original=0, start_date=HISTORY_START, parent_debt_id=group.id,
                         interest_category_id=hyp_cat.id))
        session.add(Debt(name="Hypotheek deel 2", currency="EUR", type="mortgage", repayment_type="annuity",
                         principal_original=1_750_000, start_date=HISTORY_START, parent_debt_id=group.id,
                         interest_category_id=hyp_cat.id))
        bump("debts")
    for name, ccy, pattern in (("AutoKredit", "EUR", r"auto\s*kredit"), ("Родителям", "RUB", r"родител"),
                               ("Vita", "EUR", r"\bvita\b")):
        if session.execute(select(Debt).where(Debt.name == name)).scalar_one_or_none() is None:
            session.add(Debt(name=name, currency=ccy, type="personal" if ccy == "RUB" or name == "Vita" else "loan",
                             repayment_type="free", principal_original=0, start_date=HISTORY_START,
                             lender_identifier=pattern))
            bump("debts")
    for name, type_, ccy in ASSETS:
        if session.execute(select(Asset).where(Asset.name == name)).scalar_one_or_none() is None:
            session.add(Asset(name=name, type=type_, currency=ccy))
            bump("assets")
    for name in ("Alisa", "Max"):
        if session.execute(select(Earmark).where(Earmark.name == name)).scalar_one_or_none() is None:
            session.add(Earmark(name=name, currency="EUR"))
            bump("earmarks")

    if not session.scalars(select(ImportRule).where(ImportRule.source == "gsheet")).first():
        for prio, match, action, note in RULES:
            session.add(ImportRule(source="gsheet", priority=prio, match=json.dumps(match), action=json.dumps(action), note=note))
            bump("import_rules")

    if not get_setting(session, "ignored_own_ibans"):
        set_setting(session, "ignored_own_ibans", ["NL77BUNQ2084045134"])
    if not get_setting(session, "card_payee_ibans"):
        set_setting(session, "card_payee_ibans", ["NL75ABNA0844997056"])
    return created
