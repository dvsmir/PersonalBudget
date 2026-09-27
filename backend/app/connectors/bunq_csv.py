"""bunq CSV export: "Date","Interest Date","Amount","Account","Counterparty","Name","Description"."""

import csv
import io
from datetime import date

from app.connectors.base import ParsedRow, ParseResult, normalise_iban
from app.domain.money import parse_localized, to_minor

REQUIRED = {"Date", "Amount", "Account", "Counterparty", "Name", "Description"}


class BunqCsvImporter:
    source = "bunq_csv"

    def sniff(self, filename: str, head: bytes) -> bool:
        first = head.decode("utf-8-sig", errors="ignore").splitlines()[0] if head else ""
        return filename.lower().endswith(".csv") and all(f'"{c}"' in first or c in first for c in ("Interest Date", "Counterparty"))

    def parse(self, data: bytes) -> ParseResult:
        text = data.decode("utf-8-sig")
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not REQUIRED <= set(reader.fieldnames or []):
            raise ValueError(f"Not a bunq export (columns {reader.fieldnames})")
        rows = []
        for i, r in enumerate(reader, start=1):
            amount = to_minor(parse_localized(r["Amount"]), "EUR")
            rows.append(
                ParsedRow(
                    date=date.fromisoformat(r["Date"]),
                    amount=amount,
                    currency="EUR",
                    description=" ".join(x for x in (r.get("Name"), r.get("Description")) if x).strip(),
                    counterparty=(r.get("Name") or "").strip() or None,
                    counterparty_iban=normalise_iban(r.get("Counterparty")),
                    account_hint=normalise_iban(r["Account"]),
                    account_hint_kind="iban",
                    raw={"row": i, **r},
                )
            )
        return ParseResult(rows=rows)
