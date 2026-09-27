"""Importer contract (Backend.md §5.1). Parsers are pure: bytes in, ParsedRow list out. No DB access."""

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol


@dataclass
class ParsedRow:
    date: date
    amount: int  # minor units, signed from the account's perspective
    currency: str
    description: str = ""
    counterparty: str | None = None
    counterparty_iban: str | None = None
    account_hint: str | None = None  # IBAN / account number / card last-4 found in the file
    account_hint_kind: str | None = None  # iban | account_no | card_last4
    external_id: str | None = None
    stated_balance: int | None = None  # balance after this row, if the source provides it
    raw: dict[str, Any] = field(default_factory=dict)
    hints: dict[str, Any] = field(default_factory=dict)  # parser-level classification hints


@dataclass
class ParseResult:
    rows: list[ParsedRow]
    checkpoints: list[tuple[str, str, date, int]] = field(default_factory=list)  # (hint_kind, hint, date, balance)
    meta: dict[str, Any] = field(default_factory=dict)


class Importer(Protocol):
    source: str

    def sniff(self, filename: str, head: bytes) -> bool: ...

    def parse(self, data: bytes) -> ParseResult: ...


def dedupe_key(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def norm_text(s: str | None) -> str:
    return " ".join((s or "").lower().split())


def normalise_iban(s: str | None) -> str | None:
    if not s:
        return None
    s = s.replace(" ", "").upper()
    return s or None
