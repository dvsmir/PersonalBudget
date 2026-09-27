"""File importers. `detect` picks the importer from the file name and first bytes."""

from app.connectors.abn_xls import AbnXlsImporter
from app.connectors.base import Importer, ParsedRow, ParseResult
from app.connectors.bunq_csv import BunqCsvImporter
from app.connectors.ics_pdf import IcsPdfImporter
from app.connectors.mt940 import Mt940Importer

IMPORTERS: dict[str, Importer] = {
    "abn_mt940": Mt940Importer("abn_mt940"),
    "bunq_mt940": Mt940Importer("bunq_mt940"),
    "abn_xls": AbnXlsImporter(),
    "bunq_csv": BunqCsvImporter(),
    "ics_pdf": IcsPdfImporter(),
}


def detect(filename: str, head: bytes) -> str | None:
    for source in ("abn_xls", "ics_pdf", "bunq_csv", "abn_mt940"):
        if IMPORTERS[source].sniff(filename, head):
            if source == "abn_mt940" and b"BUNQ" in head.upper():
                return "bunq_mt940"
            return source
    return None


__all__ = ["IMPORTERS", "detect", "ParsedRow", "ParseResult"]
