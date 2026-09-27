"""Parser tests. Synthetic fixtures always run; the real samples in Spec/samples (git-ignored) run when present."""

from datetime import date
from pathlib import Path

import pytest

from app.connectors import abn_desc, detect
from app.connectors.bunq_csv import BunqCsvImporter
from app.connectors.mt940 import Mt940Importer
from app.domain.money import parse_localized

SAMPLES = Path(__file__).resolve().parents[2] / "Spec" / "samples"
needs_samples = pytest.mark.skipif(not SAMPLES.exists(), reason="Spec/samples not present")

MT940 = b""":20:ABN AMRO BANK NV
:25:ABNANL2A/0886956927
:28C:26
:60F:C260826EUR69,66
:61:2608260826D6,69N426NONREF
:86:/TRTP/iDEAL/Wero/IBAN/NL58CITI2032329913/BIC/CITINL2X/NAME/Amazon EU S
ARL/REMI/GGFNJSX Amazon Retail/EREF/26-08-2026 23:26 0220434404853870
:61:2608270827C1000,00N654NONREF
:86:/TRTP/SEPA OVERBOEKING/IBAN/NL61ABNA0119875748/BIC/ABNANL2A/NAME/D.V. S
mirnov and/or E. Smirnova/EREF/NOTPROVIDED
:61:2608270827D18,40N426NONREF
:86:BEA, Google Pay                  WOPL,PAS502                     NR:44
661172, 27.08.26/11:36      Amsterdam
:62F:C260827EUR1044,57
"""


def test_mt940_entries_balances_and_descriptions():
    res = Mt940Importer().parse(MT940)
    assert [r.amount for r in res.rows] == [-669, 100000, -1840]
    assert res.rows[0].account_hint == "886956927"
    assert res.rows[0].counterparty == "Amazon EU SARL"
    assert res.rows[1].counterparty_iban == "NL61ABNA0119875748"
    assert res.rows[2].hints["abn"]["kind"] == "card"
    assert res.rows[2].hints["abn"]["card"] == "502"
    assert res.rows[-1].stated_balance == 104457
    assert res.checkpoints == [("account_no", "886956927", date(2026, 8, 27), 104457)]


def test_detect_mt940():
    assert detect("stmt.sta", MT940[:200]) == "abn_mt940"


@pytest.mark.parametrize(
    "text,kind,counterparty",
    [
        ("/TRTP/SEPA Incasso algemeen doorlopend/CSID/NL64ZZZ171589250000/NAME/VERISURE B.V./MARF/12601803/REMI/x/IBAN/NL71BNPA0227754484/BIC/B/EREF/1",
         "direct_debit", "VERISURE B.V."),
        ("BEA, Google Pay   CCV*IJssalon Da Vinci,PAS502    NR:CT828959, 27.08.26/17:57   AMSTELVEEN", "card", "CCV*IJssalon Da Vinci"),
        ("DEPOSIT INV. FUND VANG SP500 ETF FONDSCODE 098007  PER 27/08  UNIT 0,7975 @ EUR 125,39", "invest_buy", "VANG SP500 ETF"),
        ("DIVIDEND ALPHABET A  15.09.2026 OVER ST 1  PAID WITH USD 0,220  TAX EUR 0,03  CURRENCY RATE USD /EUR 0,866330",
         "dividend", "ALPHABET A"),
        ("ABN AMRO Bank N.V.               BasisPakket Betalen 4,30", "fee", "ABN AMRO Bank"),
        ("SEPA Overboeking IBAN: NL05ABNA0886956927 BIC: ABNANL2A Naam: D SMIRNOV Omschrijving: sparen", "sepa_transfer", "D SMIRNOV"),
    ],
)
def test_abn_description(text, kind, counterparty):
    d = abn_desc.parse(text)
    assert d.kind == kind
    assert d.counterparty == counterparty


def test_invest_units_and_price():
    d = abn_desc.parse("DEPOSIT INV. FUND VANG SP500 ETF FONDSCODE 098007 PER 27/08 UNIT 0,7975 @ EUR 125,39")
    assert d.extra == {"code": "098007", "units": "0.7975", "price": "125.39", "ccy": "EUR"}


def test_bunq_csv():
    data = (
        b'"Date","Interest Date","Amount","Account","Counterparty","Name","Description"\n'
        b'"2023-07-23","2023-07-23","15,000.00","NL42BUNQ2094599752","NL05ABNA0886956927","D SMIRNOV CJ","Topup"\n'
        b'"2023-09-30","2023-09-30","-35.00","NL42BUNQ2094599752","NL77BUNQ2084045134","Dmitrii",""\n'
    )
    assert detect("bunq.csv", data) == "bunq_csv"
    rows = BunqCsvImporter().parse(data).rows
    assert [r.amount for r in rows] == [1500000, -3500]
    assert rows[0].account_hint == "NL42BUNQ2094599752"
    assert rows[1].counterparty_iban == "NL77BUNQ2084045134"


@pytest.mark.parametrize(
    "text,value",
    [("-€1,668.16", "-1668.16"), ("20,589 ₽", "20589"), ("1.234,56", "1234.56"), ("0,55", "0.55"), ("692,85", "692.85"),
     ("15,000.00", "15000.00"), ("1.234.567", "1234567")],
)
def test_parse_localized(text, value):
    assert str(parse_localized(text)) == value


@needs_samples
def test_sample_abn_xls_running_balance():
    from app.connectors.abn_xls import AbnXlsImporter

    res = AbnXlsImporter().parse((SAMPLES / "ABN export.xls").read_bytes())
    assert len(res.rows) > 100
    for a, b in zip(res.rows, res.rows[1:], strict=False):
        assert a.stated_balance + b.amount == b.stated_balance


@needs_samples
def test_sample_ics_pdf_balance_check():
    from app.connectors.ics_pdf import IcsPdfImporter

    res = IcsPdfImporter().parse((SAMPLES / "ABN credit.pdf").read_bytes())
    assert res.meta["balance_check_ok"] is True
    payments = [r for r in res.rows if r.hints["card_payment"]]
    assert len(payments) == 1 and payments[0].amount > 0
    center = next(r for r in res.rows if r.counterparty.startswith("CENTER"))
    assert center.counterparty == "CENTER PARCS INTERNET"
    assert center.raw["city"] == "ROTTERDAM" and center.raw["country"] == "NLD"


@needs_samples
def test_sample_invest_xls():
    from app.connectors.abn_xls import AbnXlsImporter

    res = AbnXlsImporter().parse((SAMPLES / "Invest.xls").read_bytes())
    kinds = [r.hints["abn"]["kind"] for r in res.rows]
    assert kinds.count("dividend") == 5 and "invest_buy" in kinds and "invest_fee" in kinds
