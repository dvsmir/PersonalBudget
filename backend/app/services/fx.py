"""FX rates: lookup with fallback to the previous business day, conversion to the reporting currency,
and fetching from ECB (EUR/USD, EUR/GBP, ...) and CBR (EUR/RUB)."""

import logging
import xml.etree.ElementTree as ET
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db.models import Account, FxRate, Txn, TxnLeg, TxnSplit
from app.domain.money import minor_units, round_minor

log = logging.getLogger(__name__)
REF = "EUR"


@dataclass
class Converted:
    amount: int
    estimated: bool


class RateBook:
    """In-memory view of fx_rate for fast repeated lookups within one request."""

    def __init__(self, session: Session, ref: str = REF) -> None:
        self.ref = ref
        self._dates: dict[str, list[date]] = {}
        self._rates: dict[str, list[Decimal]] = {}
        rows = session.execute(
            select(FxRate.quote, FxRate.date, FxRate.rate).where(FxRate.base == ref).order_by(FxRate.quote, FxRate.date)
        ).all()
        for quote, d, rate in rows:
            self._dates.setdefault(quote, []).append(d)
            self._rates.setdefault(quote, []).append(rate)

    def rate(self, currency: str, d: date) -> tuple[Decimal | None, bool]:
        """Units of `currency` per 1 ref on date d. Returns (rate, estimated)."""
        if currency == self.ref:
            return Decimal(1), False
        dates = self._dates.get(currency)
        if not dates:
            return None, True
        i = bisect_right(dates, d)
        if i == 0:
            return self._rates[currency][0], True  # before first known rate
        found = dates[i - 1]
        # more than 5 days old (long weekend + holiday) counts as estimated
        return self._rates[currency][i - 1], (d - found).days > 5

    def to_ref(self, amount: int, currency: str, d: date) -> Converted:
        if currency == self.ref:
            return Converted(amount, False)
        rate, estimated = self.rate(currency, d)
        if rate is None:
            return Converted(0, True)
        scale = Decimal(10) ** (minor_units(self.ref) - minor_units(currency))
        return Converted(round_minor(Decimal(amount) * scale / rate), estimated)

    def convert(self, amount: int, from_ccy: str, to_ccy: str, d: date) -> Converted:
        if from_ccy == to_ccy:
            return Converted(amount, False)
        ref = self.to_ref(amount, from_ccy, d)
        if to_ccy == self.ref:
            return ref
        rate, estimated = self.rate(to_ccy, d)
        if rate is None:
            return Converted(0, True)
        scale = Decimal(10) ** (minor_units(to_ccy) - minor_units(self.ref))
        return Converted(round_minor(Decimal(ref.amount) * rate * scale), ref.estimated or estimated)


def upsert_rates(session: Session, rows: list[tuple[date, str, Decimal, str]]) -> int:
    """rows: (date, quote, rate, source) with base = EUR."""
    for d, quote, rate, source in rows:
        stmt = insert(FxRate).values(date=d, base=REF, quote=quote, rate=rate, source=source)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "base", "quote"],
            set_={"rate": stmt.excluded.rate, "source": stmt.excluded.source},
            where=FxRate.source != "manual",
        )
        session.execute(stmt)
    return len(rows)


# ---------------------------------------------------------------- providers

ECB_HIST = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
ECB_90D = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
CBR_DYNAMIC = "https://www.cbr.ru/scripts/XML_dynamic.asp"
CBR_EUR_CODE = "R01239"


def parse_ecb(xml_text: str, currencies: set[str], since: date) -> list[tuple[date, str, Decimal, str]]:
    ns = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
    root = ET.fromstring(xml_text)
    out = []
    for day in root.iterfind(".//e:Cube/e:Cube[@time]", ns):
        d = date.fromisoformat(day.attrib["time"])
        if d < since:
            continue
        for c in day.iterfind("e:Cube", ns):
            if c.attrib["currency"] in currencies:
                out.append((d, c.attrib["currency"], Decimal(c.attrib["rate"]), "ecb"))
    return out


def parse_cbr(xml_text: str) -> list[tuple[date, str, Decimal, str]]:
    """CBR returns RUB per 1 EUR (Nominal=1) per date: exactly our EUR->RUB rate."""
    root = ET.fromstring(xml_text)
    out = []
    for rec in root.iter("Record"):
        d = date(*reversed([int(x) for x in rec.attrib["Date"].split(".")]))
        nominal = Decimal(rec.findtext("Nominal", "1"))
        value = Decimal(rec.findtext("Value", "0").replace(",", "."))
        out.append((d, "RUB", value / nominal, "cbr"))
    return out


def fetch_rates(session: Session, since: date, currencies: set[str], client: httpx.Client | None = None) -> int:
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    count = 0
    ecb_ccy = currencies - {"RUB", REF}
    if ecb_ccy:
        url = ECB_90D if (date.today() - since).days < 85 else ECB_HIST
        resp = client.get(url)
        resp.raise_for_status()
        count += upsert_rates(session, parse_ecb(resp.text, ecb_ccy, since))
    if "RUB" in currencies:
        params = {
            "date_req1": since.strftime("%d/%m/%Y"),
            "date_req2": date.today().strftime("%d/%m/%Y"),
            "VAL_NM_RQ": CBR_EUR_CODE,
        }
        resp = client.get(CBR_DYNAMIC, params=params)
        resp.raise_for_status()
        count += upsert_rates(session, parse_cbr(resp.text))
    return count


def recompute_estimated(session: Session) -> int:
    """Re-value legs/splits whose EUR amount was computed with a missing or stale rate."""
    book = RateBook(session)
    changed = 0
    for leg, txn_date, currency in session.execute(
        select(TxnLeg, Txn.date, Account.currency)
        .join(Txn, Txn.id == TxnLeg.txn_id)
        .join(Account, Account.id == TxnLeg.account_id)
        .where(TxnLeg.ref_estimated == 1)
    ).all():
        conv = book.to_ref(leg.amount, currency, txn_date)
        if not conv.estimated:
            leg.amount_ref, leg.ref_estimated = conv.amount, 0
            changed += 1
    for split, txn_date in session.execute(
        select(TxnSplit, Txn.date).join(Txn, Txn.id == TxnSplit.txn_id).where(TxnSplit.ref_estimated == 1)
    ).all():
        conv = book.to_ref(split.amount, split.currency, txn_date)
        if not conv.estimated:
            split.amount_ref, split.ref_estimated = conv.amount, 0
            changed += 1
    return changed


def default_since(session: Session) -> date:
    last = session.execute(select(FxRate.date).where(FxRate.source != "manual").order_by(FxRate.date.desc())).first()
    return (last[0] - timedelta(days=7)) if last else date(2020, 11, 1)
