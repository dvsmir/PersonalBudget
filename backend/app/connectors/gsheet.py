"""Google Sheet 'Бюджет' workbook (xlsx export). Parses transaction sheets, year-end State blocks and
total-funds anchors. Pure parsing: mapping to accounts/categories happens in services/migration.py.

Layouts (Import.md §5.2):
- 'Transactions YYYY'  : date | € | ₽ | Categorie | Omschrijving           (signed amounts)
- '2021'               : Maand | Datum | Kosten € | ₽ | Omschr. | Cat | Incomen € | ₽ | Omschr. | Cat | ...
- '2020 - Amster'      : Maand | Datum | Kosten € | Omschr. | Cat | Incomen € | Omschr. | Cat | ...
  (block layouts: costs positive, date only on the first row of a day)
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import openpyxl

from app.domain.money import to_minor

TXN_SHEET = re.compile(r"^Transactions (\d{4})$")
DASHBOARD_SHEET = re.compile(r"^Dashboard (\d{4})$")
BLOCK_SHEETS = ("2020 - Amster", "2021")
SKIPPED_SHEETS = ("2022 old", "2020", "2019")


@dataclass
class SheetRow:
    sheet: str
    row_no: int
    date: date
    amount: int  # minor units, signed (cost negative)
    currency: str
    category: str | None
    description: str | None


@dataclass
class StateBlock:
    year: int
    funds: dict[str, tuple[Decimal | None, Decimal | None]] = field(default_factory=dict)  # label -> (€, ₽)
    debts: dict[str, Decimal] = field(default_factory=dict)
    assets: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class Workbook:
    rows: list[SheetRow]
    states: list[StateBlock]
    total_anchors: list[tuple[date, Decimal | None, Decimal | None]]  # (date, € total, ₽ total) end-of-day
    sheets_parsed: list[str]
    warnings: list[str]


def _dec(v: object) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(round(float(v), 2)))
    s = str(v).strip().replace("€", "").replace("₽", "").replace(" ", "").replace(" ", "")
    if not s:
        return None
    try:
        return Decimal(s.replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def _date(v: object) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(v.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _text(v: object) -> str | None:
    if v is None:
        return None
    s = " ".join(str(v).split())
    return s or None


def _minor(value: Decimal, currency: str) -> int:
    return to_minor(value.quantize(Decimal("0.01")), currency)


def parse_std(ws, sheet: str, warnings: list[str]) -> list[SheetRow]:  # type: ignore[no-untyped-def]
    out = []
    for i, row in enumerate(ws.iter_rows(min_row=4, max_col=5, values_only=True), start=4):
        d = _date(row[0])
        if d is None:
            if any(row[1:3]):
                warnings.append(f"{sheet} row {i}: amount without date")
            continue
        for col, ccy in ((1, "EUR"), (2, "RUB")):
            amount = _dec(row[col])
            if amount:
                out.append(SheetRow(sheet, i, d, _minor(amount, ccy), ccy, _text(row[3]), _text(row[4])))
    return out


def parse_block(ws, sheet: str, warnings: list[str]) -> list[SheetRow]:  # type: ignore[no-untyped-def]
    header3 = [c for c in next(ws.iter_rows(min_row=3, max_row=3, values_only=True))]
    has_rub = "₽" in [str(c) for c in header3 if c]
    # column indexes (0-based)
    if has_rub:
        cost = {"EUR": 2, "RUB": 3, "desc": 4, "cat": 5}
        inc = {"EUR": 6, "RUB": 7, "desc": 8, "cat": 9}
        start = 4
    else:
        cost = {"EUR": 2, "desc": 3, "cat": 4}
        inc = {"EUR": 5, "desc": 6, "cat": 7}
        start = 3
    out: list[SheetRow] = []
    current: date | None = None
    pending_undated: list[tuple[int, tuple]] = []
    for i, row in enumerate(ws.iter_rows(min_row=start, values_only=True), start=start):
        row = tuple(row) + (None,) * 12
        if _text(row[1]) == "Totaal":
            continue
        d = _date(row[1])
        if d is not None:
            current = d
        for spec, sign in ((cost, -1), (inc, 1)):
            for ccy in ("EUR", "RUB"):
                if ccy not in spec:
                    continue
                amount = _dec(row[spec[ccy]])
                if not amount:
                    continue
                item = (ccy, sign * amount, _text(row[spec["cat"]]), _text(row[spec["desc"]]))
                if current is None:
                    pending_undated.append((i, item))  # e.g. 'Euros meegebracht' above the first dated row
                    continue
                out.append(SheetRow(sheet, i, current, _minor(item[1], ccy), ccy, item[2], item[3]))
    first = min((r.date for r in out), default=None)
    for i, (ccy, amount, cat, desc) in pending_undated:
        if first is None:
            warnings.append(f"{sheet} row {i}: undated row skipped")
            continue
        out.append(SheetRow(sheet, i, first, _minor(amount, ccy), ccy, cat, desc))
    return out


def parse_state(ws, year: int) -> StateBlock:  # type: ignore[no-untyped-def]
    block = StateBlock(year)
    for row in ws.iter_rows(min_row=3, max_row=16, max_col=14, values_only=True):
        row = tuple(row) + (None,) * 14
        if _text(row[0]) == "Year summary":
            break
        label = _text(row[1])
        if label and label.lower() not in ("total", "total available", "funds"):
            block.funds[label] = (_dec(row[2]), _dec(row[3]))
        debt = _text(row[6])
        if debt and _dec(row[7]) is not None:
            block.debts[debt] = _dec(row[7])  # type: ignore[assignment]
        asset = _text(row[12])
        if asset and _dec(row[13]) is not None:
            block.assets[asset] = _dec(row[13])  # type: ignore[assignment]
    return block


def parse_total_anchors(wb) -> list[tuple[date, Decimal | None, Decimal | None]]:  # type: ignore[no-untyped-def]
    """End-of-year totals of available funds before per-account State blocks existed:
    - '2021' first row: Beschikbare fondsen at the start of 2021 (= end of 2020)
    - 'Баланс - old': 'На начало' of each year (= end of the previous year)."""
    out = []
    if "Баланс - old" in wb.sheetnames:
        year = None
        for row in wb["Баланс - old"].iter_rows(values_only=True):
            row = tuple(row) + (None,) * 12
            if isinstance(row[0], (int, float)) and 2000 < row[0] < 2100:
                year = int(row[0])
            if _text(row[1]) == "На начало":
                pending = (_dec(row[8]), _dec(row[9]))
                # the year label is on the next row; remember and resolve lazily
                out.append(("pending", pending))
            elif out and out[-1][0] == "pending" and year:
                eur, rub = out.pop()[1]
                out.append((date(year - 1, 12, 31), eur, rub))
    return [x for x in out if x[0] != "pending" and (x[1] is not None or x[2] is not None)]  # type: ignore[misc]


def parse_workbook(data: bytes, years: set[int] | None = None) -> Workbook:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    rows: list[SheetRow] = []
    states: list[StateBlock] = []
    warnings: list[str] = []
    parsed: list[str] = []
    for name in wb.sheetnames:
        if m := TXN_SHEET.match(name):
            if years and int(m.group(1)) not in years:
                continue
            rows += parse_std(wb[name], name, warnings)
            parsed.append(name)
        elif name in BLOCK_SHEETS:
            year = 2021 if name == "2021" else 2020
            if years and year not in years:
                continue
            rows += parse_block(wb[name], name, warnings)
            parsed.append(name)
        elif m := DASHBOARD_SHEET.match(name):
            states.append(parse_state(wb[name], int(m.group(1))))
    anchors = parse_total_anchors(wb)
    wb.close()
    rows.sort(key=lambda r: (r.date, r.sheet, r.row_no))
    return Workbook(rows, sorted(states, key=lambda s: s.year), anchors, parsed, warnings)
