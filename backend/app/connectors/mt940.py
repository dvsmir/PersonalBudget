"""SWIFT MT940 statements (ABN AMRO, bunq). Own minimal parser: :25: account, :60F:/:60M: opening balance,
:61: entry, :86: description, :62F:/:62M: closing balance."""

import re
from datetime import date
from decimal import Decimal

from app.connectors import abn_desc
from app.connectors.base import ParsedRow, ParseResult
from app.domain.money import to_minor

_TAG = re.compile(r"^:(\d{2}[A-Z]?):", re.M)
_BAL = re.compile(r"(?P<dc>[CD])(?P<date>\d{6})(?P<ccy>[A-Z]{3})(?P<amount>[\d,]+)")
_ENTRY = re.compile(
    r"^(?P<vdate>\d{6})(?P<edate>\d{4})?(?P<dc>R?[CD])(?P<fund>[A-Z])?(?P<amount>\d+,\d*)"
    r"(?P<type>[NFS][A-Z0-9]{3})(?P<ref>[^/\n]*)(?://(?P<bref>[^\n]*))?"
)


def _amount(s: str) -> Decimal:
    return Decimal(s.replace(",", "."))


def _date(yymmdd: str) -> date:
    return date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6]))


class Mt940Importer:
    source = "abn_mt940"

    def __init__(self, source: str = "abn_mt940") -> None:
        self.source = source

    def sniff(self, filename: str, head: bytes) -> bool:
        text = head.decode("latin-1", errors="ignore")
        return ":20:" in text and (":25:" in text or ":60F:" in text)

    def parse(self, data: bytes) -> ParseResult:
        text = data.decode("utf-8", errors="replace") if b"\xc3" in data else data.decode("latin-1")
        text = text.replace("\r\n", "\n")
        tokens = _TAG.split(text)
        # tokens: [preamble, tag1, value1, tag2, value2, ...]
        fields = [(tokens[i], tokens[i + 1].strip("\n")) for i in range(1, len(tokens) - 1, 2)]
        rows: list[ParsedRow] = []
        checkpoints = []
        account: str | None = None
        currency = "EUR"
        pending: dict | None = None
        running: int | None = None

        def flush() -> None:
            nonlocal pending
            if pending is None:
                return
            desc = " ".join(pending.get("desc", "").split())
            details = abn_desc.parse(desc)
            rows.append(
                ParsedRow(
                    date=pending["date"],
                    amount=pending["amount"],
                    currency=currency,
                    description=abn_desc.summary(details) or desc,
                    counterparty=details.counterparty,
                    counterparty_iban=details.counterparty_iban,
                    account_hint=account,
                    account_hint_kind="iban" if account and account[:2].isalpha() else "account_no",
                    external_id=pending.get("ref") or None,
                    stated_balance=pending.get("balance"),
                    raw={"61": pending["raw61"], "86": desc},
                    hints={"abn": details.__dict__},
                )
            )
            pending = None

        for tag, value in fields:
            if tag == "25":
                flush()
                acc = value.strip().split("/")[0].split()[0]
                # ABN writes "ABNANL2A/0886956927" or the IBAN; bunq writes the IBAN
                account = value.strip().split("/")[-1].replace(" ", "") if "/" in value else acc
                if account.isdigit():
                    account = str(int(account))
            elif tag in ("60F", "60M"):
                flush()
                m = _BAL.search(value)
                if m:
                    currency = m["ccy"]
                    running = to_minor(_amount(m["amount"]), currency) * (-1 if m["dc"] == "D" else 1)
            elif tag == "61":
                flush()
                m = _ENTRY.match(value.split("\n")[0])
                if not m:
                    continue
                sign = -1 if m["dc"] in ("D", "RC") else 1
                amount = sign * to_minor(_amount(m["amount"]), currency)
                if running is not None:
                    running += amount
                ref = (m["ref"] or "").strip()
                pending = {
                    "date": _date(m["vdate"]),
                    "amount": amount,
                    "ref": None if ref in ("", "NONREF") else ref,
                    "raw61": value,
                    "balance": running,
                }
            elif tag == "86":
                if pending is not None:
                    pending["desc"] = pending.get("desc", "") + " " + value.replace("\n", "")
            elif tag in ("62F", "62M"):
                flush()
                m = _BAL.search(value)
                if m and account:
                    bal = to_minor(_amount(m["amount"]), m["ccy"]) * (-1 if m["dc"] == "D" else 1)
                    kind = "iban" if account[:2].isalpha() else "account_no"
                    checkpoints.append((kind, account, _date(m["date"]), bal))
                    running = bal
        flush()
        return ParseResult(rows=rows, checkpoints=checkpoints)
