"""ICS (ABN AMRO credit card) monthly PDF statement. Dates carry no year: it is taken from the statement date.
Description, city and country are fixed columns, so they are separated by word x-positions, not by text."""

import io
import re
from collections import Counter
from datetime import date

import pdfplumber

from app.connectors.base import ParsedRow, ParseResult
from app.domain.money import parse_localized, to_minor

MONTHS = {
    "jan": 1, "feb": 2, "mrt": 3, "mar": 3, "apr": 4, "mei": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dec": 12,
}
FULL_MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}
_STATEMENT_DATE = re.compile(r"^(\d{1,2}) (" + "|".join(FULL_MONTHS) + r") (\d{4})\s+(\d{8,})", re.M | re.I)
_CARD = re.compile(r"laatste vier cijfers (\d{4})", re.I)
_ROW = re.compile(
    r"^(?P<td>\d{2}) (?P<tm>[a-z]{3})\.? (?P<bd>\d{2}) (?P<bm>[a-z]{3})\.? (?P<rest>.+?) "
    r"(?:(?P<fx>[\d.]+,\d{2}) (?P<fxccy>[A-Z]{3}) )?(?P<amount>[\d.]+,\d{2}) (?P<dc>Af|Bij)$",
    re.I,
)
_BALANCES = re.compile(
    r"Vorig openstaand saldo.*?\n€ ?(?P<prev>[\d.]+,\d{2}) (?P<prev_dc>Af|Bij) € ?(?P<paid>[\d.]+,\d{2}) (?:Af|Bij) "
    r"€ ?(?P<spent>[\d.]+,\d{2}) (?:Af|Bij) € ?(?P<new>[\d.]+,\d{2}) (?P<new_dc>Af|Bij)",
    re.S,
)
_AMOUNTISH = re.compile(r"^([\d.]+,\d{2}|Af|Bij|[A-Z]{3})$")


def _money(s: str) -> int:
    return to_minor(parse_localized(s), "EUR")


def _word_lines(page) -> list[list[dict]]:  # type: ignore[no-untyped-def]
    """Words grouped into visual lines, left to right."""
    lines: dict[int, list[dict]] = {}
    for w in page.extract_words():
        lines.setdefault(round(w["top"]), []).append(w)
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in sorted(lines.items())]


def _line_text(ws: list[dict]) -> str:
    return " ".join(w["text"] for w in ws)


def _columns(lines: list[list[dict]]) -> tuple[float | None, float | None]:
    """x of the city and country columns: country = the 3-letter code column,
    city = the most common word start between the description start and the country column."""
    country_xs: Counter = Counter()
    rows = [ws for ws in lines if _ROW.match(_line_text(ws))]
    for ws in rows:
        for w in ws[4:]:
            if re.fullmatch(r"[A-Z]{3}", w["text"]) and w["x0"] > 250:
                country_xs[round(w["x0"])] += 1
    if not country_xs:
        return None, None
    country_x = country_xs.most_common(1)[0][0]
    starts: Counter = Counter()
    for ws in rows:
        body = ws[4:]
        desc_x = body[0]["x0"] if body else 0
        for w in body:
            if desc_x + 60 < w["x0"] < country_x - 5:
                starts[round(w["x0"])] += 1
    city_x = starts.most_common(1)[0][0] if starts else None
    return city_x, country_x


class IcsPdfImporter:
    source = "ics_pdf"

    def sniff(self, filename: str, head: bytes) -> bool:
        return filename.lower().endswith(".pdf") and head.startswith(b"%PDF")

    def parse(self, data: bytes) -> ParseResult:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            lines = [line for p in pdf.pages for line in _word_lines(p)]
        if "International Card Services" not in text:
            raise ValueError("Not an ICS credit card statement")
        m = _STATEMENT_DATE.search(text)
        if not m:
            raise ValueError("Statement date not found")
        stmt_date = date(int(m.group(3)), FULL_MONTHS[m.group(2).lower()], int(m.group(1)))
        customer_no = m.group(4)

        first_card = _CARD.search(text)
        default_card = first_card.group(1) if first_card else None
        city_x, country_x = _columns(lines)
        rows: list[ParsedRow] = []
        card: str | None = None
        for words in lines:
            line = _line_text(words)
            if c := _CARD.search(line):
                card = c.group(1)
                continue
            r = _ROW.match(line)
            if not r:
                continue
            tm, bm = MONTHS.get(r["tm"].lower()), MONTHS.get(r["bm"].lower())
            if not tm or not bm:
                continue
            year = stmt_date.year - (1 if tm > stmt_date.month else 0)
            txn_date = date(year, tm, int(r["td"]))
            amount = _money(r["amount"]) * (1 if r["dc"].lower() == "bij" else -1)
            body = words[4:]  # skip the two dates
            if city_x is None:
                desc = " ".join(w["text"] for w in body if not _AMOUNTISH.match(w["text"]))
                city, country = "", None
            else:
                right = country_x if country_x is not None else 1e9
                desc = " ".join(w["text"] for w in body if w["x0"] < city_x - 2)
                city = " ".join(w["text"] for w in body if city_x - 2 <= w["x0"] < right - 2)
                country = next((w["text"] for w in body if abs(w["x0"] - right) < 3), None)
            if not desc:  # e.g. the payment line has no city column; everything left of the amounts
                desc = " ".join(w["text"] for w in body if not _AMOUNTISH.match(w["text"]))
            is_payment = desc.upper().startswith("IDEAL BETALING") or "DANK U" in desc.upper()
            if is_payment:
                desc = " ".join(w["text"] for w in body if not _AMOUNTISH.match(w["text"]))
                city, country = "", None
            rows.append(
                ParsedRow(
                    date=txn_date,
                    amount=amount,
                    currency="EUR",
                    description=" ".join(x for x in (desc, city) if x),
                    counterparty=desc,
                    account_hint=card or default_card,
                    account_hint_kind="card_last4",
                    raw={
                        "line": line,
                        "statement_date": stmt_date.isoformat(),
                        "customer_no": customer_no,
                        "city": city or None,
                        "country": country,
                        "foreign": f"{r['fx']} {r['fxccy']}" if r["fx"] else None,
                    },
                    hints={"card_payment": is_payment, "booking_date": f"{bm:02d}-{r['bd']}"},
                )
            )
        checkpoints = []
        meta: dict = {"statement_date": stmt_date, "customer_no": customer_no}
        b = _BALANCES.search(text)
        if b:
            new_balance = _money(b["new"]) * (-1 if b["new_dc"] == "Af" else 1)
            prev_balance = _money(b["prev"]) * (-1 if b["prev_dc"] == "Af" else 1)
            meta.update(previous_balance=prev_balance, new_balance=new_balance)
            meta["balance_check_ok"] = prev_balance + sum(r.amount for r in rows) == new_balance
            if default_card:
                checkpoints.append(("card_last4", default_card, stmt_date, new_balance))
        return ParseResult(rows=rows, checkpoints=checkpoints, meta=meta)
