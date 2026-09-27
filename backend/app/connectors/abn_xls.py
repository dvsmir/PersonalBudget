"""ABN AMRO XLS export (legacy BIFF .xls): one row per transaction with running balance.
Columns: Rekeningnummer, Muntsoort, Transactiedatum, Rentedatum, Beginsaldo, Eindsaldo, Transactiebedrag, Omschrijving."""

from datetime import datetime
from decimal import Decimal

import xlrd

from app.connectors import abn_desc
from app.connectors.base import ParsedRow, ParseResult
from app.domain.money import to_minor

HEADER = ["Rekeningnummer", "Muntsoort", "Transactiedatum", "Rentedatum", "Beginsaldo", "Eindsaldo", "Transactiebedrag", "Omschrijving"]


class AbnXlsImporter:
    source = "abn_xls"

    def sniff(self, filename: str, head: bytes) -> bool:
        return filename.lower().endswith(".xls") and head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

    def parse(self, data: bytes) -> ParseResult:
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)
        header = [str(c).strip() for c in sheet.row_values(0)]
        if header[: len(HEADER)] != HEADER:
            raise ValueError(f"Not an ABN AMRO export (header {header})")
        rows: list[ParsedRow] = []
        checkpoints = []
        for i in range(1, sheet.nrows):
            v = sheet.row_values(i)
            if not v[0]:
                continue
            account_no = str(int(v[0])) if isinstance(v[0], float) else str(v[0]).strip()
            ccy = str(v[1]).strip()
            d = datetime.strptime(str(int(v[2])) if isinstance(v[2], float) else str(v[2]), "%Y%m%d").date()
            amount = to_minor(Decimal(str(v[6])).quantize(Decimal("0.01")), ccy)
            end_balance = to_minor(Decimal(str(v[5])).quantize(Decimal("0.01")), ccy)
            desc = str(v[7])
            details = abn_desc.parse(desc)
            rows.append(
                ParsedRow(
                    date=d,
                    amount=amount,
                    currency=ccy,
                    description=abn_desc.summary(details),
                    counterparty=details.counterparty,
                    counterparty_iban=details.counterparty_iban,
                    account_hint=account_no,
                    account_hint_kind="account_no",
                    stated_balance=end_balance,
                    raw={"row": i, "values": [str(x) for x in v]},
                    hints={"abn": details.__dict__},
                )
            )
            checkpoints.append(("account_no", account_no, d, end_balance))
        # keep only the last checkpoint per account per day
        last: dict[tuple[str, object], tuple] = {}
        for cp in checkpoints:
            last[(cp[1], cp[2])] = cp
        return ParseResult(rows=rows, checkpoints=list(last.values()))
