import io
import json
from datetime import date, datetime

import openpyxl
import pytest
from sqlalchemy import func, select

from app.db.models import AccountReconciliation, ImportRow, Txn, TxnLeg
from app.services import categoriser, imports, migration
from app.services.common import DomainError
from app.services.ledger import account_balance
from tests.conftest import acc, cat

ABN_MT940 = b""":20:ABN AMRO BANK NV
:25:ABNANL2A/0886956927
:28C:1
:60F:C260301EUR1000,00
:61:2603020302D250,00N654NONREF
:86:/TRTP/SEPA OVERBOEKING/IBAN/NL61ABNA0119875748/BIC/ABNANL2A/NAME/D.V. Smirnov and/or E. Smirnova/EREF/NOTPROVIDED
:61:2603030303D45,20N426NONREF
:86:BEA, Google Pay                  Albert Heijn 1391,PAS492        NR:BS102526, 03.03.26/08:32      AMSTERDAM
:61:2603040304D100,00N426NONREF
:86:GEA, Betaalpas                   ABN AMRO BANK,PAS502            NR:ABC, 04.03.26/10:00      AMSTELVEEN
:61:2603050305D692,85N654NONREF
:86:/TRTP/SEPA OVERBOEKING/IBAN/NL75ABNA0844997056/BIC/ABNANL2A/NAME/ICS/REMI/82497790012/EREF/NOTPROVIDED
:62F:D260305EUR88,05
"""

SPAREN_MT940 = b""":20:ABN AMRO BANK NV
:25:ABNANL2A/0119875748
:28C:1
:60F:C260301EUR5000,00
:61:2603020302C250,00N654NONREF
:86:/TRTP/SEPA OVERBOEKING/IBAN/NL05ABNA0886956927/BIC/ABNANL2A/NAME/D SMIRNOV/EREF/NOTPROVIDED
:61:2603310331C3,10N654NONREF
:86:ABN AMRO Bank N.V.               RENTE
:62F:C260331EUR5253,10
"""


def fake_ai(category_ids):
    def call(model, system, rows):
        assert "category tree" in system or "categories" in system
        items = [categoriser.RowSuggestion(i=r["i"], kind="expense" if r["amount"].startswith("-") else "income",
                                           category_id=category_ids[0], cost_type="variable", project_id=None,
                                           confidence=0.9, rationale="test") for r in rows]
        return categoriser.Suggestions(items=items), {"input_tokens": 10, "output_tokens": 5}
    return call


def test_bank_import_rules_and_commit(db, user):
    abn = acc(db, "ABN")
    abn.opening_balance = 100000  # 1000.00 per :60F:
    batch = imports.create_batch(db, "abn.sta", ABN_MT940, user.id)
    assert batch.status == "reviewing"
    rules = [json.loads(r.proposed)["rule"] for r in batch.rows]
    assert rules == ["own_transfer", None, "atm", "card_repayment"]
    assert [r.status for r in batch.rows] == ["accepted", "new", "accepted", "accepted"]

    # AI suggestion for the grocery row, then accept everything and commit
    res = categoriser.suggest(db, batch, call=fake_ai([cat(db, "Eetwaar").id]))
    assert res["suggested"] == 1
    imports.bulk_update(db, batch.id, None, {"status": "suggested"}, "accepted", None)
    out = imports.commit_batch(db, batch.id, user.id)
    assert out["errors"] == [] and out["committed"] == 4 and out["status"] == "committed"
    assert account_balance(db, abn.id) == -8805
    assert account_balance(db, acc(db, "Cash").id) == 10000
    assert account_balance(db, acc(db, "Credit card").id) == 69285
    # closing balance stored as a statement checkpoint and it matches
    cp = db.execute(select(AccountReconciliation).where(AccountReconciliation.account_id == abn.id)).scalar_one()
    assert cp.stated_balance == cp.computed_balance == -8805


def test_transfer_seen_from_both_sides_is_booked_once(db, user):
    sparen = acc(db, "Sparen ABN")
    sparen.opening_balance = 500000
    b1 = imports.create_batch(db, "abn.sta", ABN_MT940, user.id)
    imports.bulk_update(db, b1.id, None, {"rule": "own_transfer"}, "accepted", None)
    imports.commit_batch(db, b1.id, user.id)
    inferred = db.execute(select(TxnLeg).where(TxnLeg.account_id == sparen.id)).scalar_one()
    assert inferred.inferred == 1

    b2 = imports.create_batch(db, "sparen.sta", SPAREN_MT940, user.id)
    assert [json.loads(r.proposed)["rule"] for r in b2.rows] == ["own_transfer", "interest"]
    out = imports.commit_batch(db, b2.id, user.id)
    assert out["committed"] == 2
    transfers = db.execute(select(func.count(func.distinct(Txn.id))).join(TxnLeg)
                           .where(Txn.kind == "transfer", TxnLeg.account_id == sparen.id)).scalar_one()
    assert transfers == 1  # confirmed, not duplicated
    db.refresh(inferred)
    assert inferred.inferred == 0
    assert account_balance(db, sparen.id) == 525310


def test_duplicate_file_and_overlapping_rows(db, user):
    b1 = imports.create_batch(db, "abn.sta", ABN_MT940, user.id)
    imports.bulk_update(db, b1.id, None, {"rule": "atm"}, "accepted", None)
    imports.commit_batch(db, b1.id, user.id, [r.id for r in b1.rows if r.status == "accepted"])
    with pytest.raises(DomainError) as e:
        imports.create_batch(db, "abn-again.sta", ABN_MT940, user.id)
    assert e.value.code == "duplicate_file"
    # same statement with a different trailing :20: → rows with a committed dedupe key are duplicates
    b2 = imports.create_batch(db, "abn2.sta", ABN_MT940.replace(b":28C:1", b":28C:2"), user.id)
    statuses = {r.amount: r.status for r in b2.rows}
    assert statuses[-10000] == "duplicate"  # the ATM row committed from the first file
    assert statuses[-4520] == "new"


def test_uncategorised_rows_do_not_commit(db, user):
    b = imports.create_batch(db, "abn.sta", ABN_MT940, user.id)
    grocery = next(r for r in b.rows if r.status == "new")
    grocery.status = "accepted"
    out = imports.commit_batch(db, b.id, user.id, [grocery.id])
    assert out["errors"][0]["code"] == "uncategorised"


# ---------------------------------------------------------------- sheet migration

def workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions 2024"
    ws.append([None, "Kosten"])
    ws.append([None, "Bedrag", None, "Categorie", "Omschrijving"])
    ws.append([None, "€", "₽"])
    rows = [
        (datetime(2024, 3, 1), -50.0, None, "Eetwaar", "AH"),
        (datetime(2024, 3, 2), None, 9500.0, "Convert", None),
        (datetime(2024, 3, 2), -100.0, None, "Convert", None),
        (datetime(2024, 3, 3), -20.0, None, "Kleding", "Credit - shoes"),
        (datetime(2024, 3, 4), 3.5, None, "Bonus", "ABN rente"),
        (datetime(2024, 3, 5), 1000.0, None, "JB Salaris", None),
        (datetime(2024, 3, 6), None, -500.0, "Eetwaar", "Пятёрочка"),
    ]
    for r in rows:
        ws.append(list(r))
    d = wb.create_sheet("Dashboard 2024")
    d.append(["State"])
    d.append([None, "Funds", None, None, None, None, "Debts"])
    d.append([None, "Total", 1500.0])
    d.append([None, "ABN", 700.0, None, None, None, "AutoKredit", 1000.0, None, None, None, None, "Outlander", 30000.0])
    d.append([None, "Sparen ABN", 800.0])
    d.append([None, "Bunq", 0.0])
    d.append([None, "VTB", None, 20000.0])
    d.append(["Year summary"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sheet_import_sheet_only_mode(db, user):
    batch = migration.import_sheet(db, "Budget.xlsx", workbook(), user.id)
    by_desc = {(r.description, r.currency): r for r in batch.rows}
    by_amount = {r.amount: r for r in batch.rows}
    conv_eur = json.loads(by_amount[-10000].proposed)
    assert conv_eur["kind"] == "transfer" and len(conv_eur["legs"]) == 2  # € and ₽ legs paired
    assert by_amount[950000].status == "skipped"
    credit = json.loads(by_desc[("Credit - shoes", "EUR")].proposed)
    assert credit["legs"][0]["account_id"] == acc(db, "Credit card").id
    rente = json.loads(by_desc[("ABN rente", "EUR")].proposed)
    assert rente["legs"][0]["account_id"] == acc(db, "Sparen ABN").id
    assert rente["splits"][0]["category_id"] == cat(db, "Interest", "income").id
    assert all(json.loads(r.proposed)["mode"] == "sheet_only" for r in batch.rows if r.status != "skipped")
    imports.bulk_update(db, batch.id, None, {"status": "suggested"}, "accepted", None)
    out = imports.commit_batch(db, batch.id, user.id)
    assert out["errors"] == []
    assert account_balance(db, acc(db, "Rubles").id) == 950000 - 50000


def test_anchors_and_generated_balancing(db, user):
    data = workbook()
    batch = migration.import_sheet(db, "Budget.xlsx", data, user.id)
    imports.bulk_update(db, batch.id, None, {"status": "suggested"}, "accepted", None)
    imports.commit_batch(db, batch.id, user.id)
    res = migration.load_anchors(db, data, user.id)
    assert res["anchors"] == 3  # ABN, Sparen ABN, Rubles (Bunq ignored)
    assert res["debt_snapshots"] == 1 and res["asset_valuations"] == 1
    report = migration.generate_balancing(db, user.id)
    end = date(2024, 12, 31)
    assert account_balance(db, acc(db, "ABN").id, end) == 70000
    assert account_balance(db, acc(db, "Sparen ABN").id, end) == 80000
    assert account_balance(db, acc(db, "Rubles").id, end) == 2000000
    kinds = {(r["account"], r["kind"]) for r in report}
    assert ("Sparen ABN", "transfer") in kinds and ("ABN", "adjustment") in kinds
    # regenerating is idempotent
    migration.generate_balancing(db, user.id)
    assert account_balance(db, acc(db, "ABN").id, end) == 70000


def test_sheet_match_mode_enriches_bank_rows(db, user):
    abn = acc(db, "ABN")
    abn.opening_balance = 100000
    b = imports.create_batch(db, "abn.sta", ABN_MT940, user.id)
    grocery = next(r for r in b.rows if r.status == "new")
    imports.update_row(db, grocery.id, {"splits": [{"amount": -4520, "category_id": cat(db, "Diverse").id}]}, "accepted")
    imports.commit_batch(db, b.id, user.id, [grocery.id])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions 2026"
    ws.append([])
    ws.append([])
    ws.append([])
    ws.append([datetime(2026, 3, 4), -45.2, None, "Eetwaar", "AH weekly"])
    buf = io.BytesIO()
    wb.save(buf)
    sb = migration.import_sheet(db, "Budget.xlsx", buf.getvalue(), user.id, {2026})
    row = sb.rows[0]
    p = json.loads(row.proposed)
    assert p["mode"] == "match" and p["update_txn_id"] == grocery.txn_id
    row.status = "accepted"
    imports.commit_batch(db, sb.id, user.id)
    txn = db.get(Txn, grocery.txn_id)
    assert txn.splits[0].category_id == cat(db, "Eetwaar").id
    assert txn.description.startswith("AH weekly")
    assert db.execute(select(func.count()).select_from(ImportRow).where(ImportRow.matched_txn_id == txn.id)).scalar_one() == 1
