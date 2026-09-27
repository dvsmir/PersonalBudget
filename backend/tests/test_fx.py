from datetime import date
from decimal import Decimal

import httpx

from app.db.models import FxRate
from app.services import fx

ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time="2026-09-25"><Cube currency="USD" rate="1.1652"/><Cube currency="GBP" rate="0.86055"/></Cube></Cube>
</gesmes:Envelope>"""


def test_cbr_blocked_falls_back_to_mirror(db):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "ecb.europa.eu" in url:
            return httpx.Response(200, text=ECB_XML)
        if "cbr.ru/scripts" in url:
            return httpx.Response(502)
        if "2026/09/25" in url:
            return httpx.Response(200, json={"Date": "2026-09-25T11:30:00+03:00",
                                             "Valute": {"EUR": {"Nominal": 1, "Value": 99.2525}}})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    n = fx.fetch_rates(db, date(2026, 9, 24), {"USD", "GBP", "RUB"}, client)
    assert n == 3
    rub = db.get(FxRate, (date(2026, 9, 25), "EUR", "RUB"))
    assert rub.rate == Decimal("99.2525") and rub.source == "cbr"


def test_rate_book_falls_back_to_previous_day(db):
    book = fx.RateBook(db)
    rate, estimated = book.rate("RUB", date(2025, 1, 3))  # fixture rate on 2025-01-01
    assert rate == Decimal(100) and not estimated
    assert book.to_ref(10000, "RUB", date(2025, 1, 3)).amount == 100
    assert book.convert(10000, "EUR", "RUB", date(2025, 1, 3)).amount == 1000000
