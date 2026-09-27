"""Parse ABN AMRO transaction descriptions (shared by the MT940 `:86:` field and the XLS 'Omschrijving')."""

import re
from dataclasses import dataclass
from decimal import Decimal

SEPA_TAGS = (
    "TRTP", "CSID", "IBAN", "BIC", "NAME", "MARF", "REMI", "EREF", "ORDP", "ID", "RTRN", "BENM",
    "ADDR", "CNTP", "ISDT", "SVCL", "PREF", "ULTC", "ULTD", "PURP", "CREF",
)
_TAG_RE = re.compile(r"/(" + "|".join(SEPA_TAGS) + r")/")
_CARD_RE = re.compile(
    r"^(?P<kind>BEA|GEA),?\s+(?:(?P<wallet>Apple Pay|Google Pay)\s+)?(?P<merchant>.+?),PAS(?P<card>\d+)\s+"
    r"NR:(?P<nr>\S+?),?\s+(?P<dt>\d\d\.\d\d\.\d\d/\d\d[:.]\d\d)\s*(?P<city>.*)$"
)
# older ABN layout: "BEA   NR:xxxx 27.08.26/17:57 Merchant name,PAS502"
_CARD_OLD_RE = re.compile(
    r"^(?P<kind>BEA|GEA),?\s+NR:(?P<nr>\S+)\s+(?P<dt>\d\d\.\d\d\.\d\d/\d\d[:.]\d\d)\s+(?P<merchant>.+?),PAS(?P<card>\d+)\s*(?P<city>.*)$"
)
_KV_RE = re.compile(r"(IBAN|BIC|Naam|Omschrijving|Kenmerk|Machtiging|Incassant|Betalingskenm\.):\s*")
_INVEST_DEPOSIT = re.compile(
    r"DEPOSIT INV\. FUND (?P<name>.+?) FONDSCODE (?P<code>\d+).*?UNIT (?P<units>[\d.,]+) @ (?P<ccy>[A-Z]{3}) (?P<price>[\d.,]+)"
)
_INVEST_WITHDRAW = re.compile(
    r"(?:WITHDRAWAL|SALE|VERKOOP) INV\. FUND (?P<name>.+?) FONDSCODE (?P<code>\d+).*?UNIT (?P<units>[\d.,]+) @ (?P<ccy>[A-Z]{3}) (?P<price>[\d.,]+)"
)
_DIVIDEND = re.compile(
    r"DIVIDEND (?P<name>.+?) (?P<date>\d\d\.\d\d\.\d{4}) OVER ST (?P<shares>[\d.,]+)\s+PAID WITH (?P<ccy>[A-Z]{3}) (?P<per_share>[\d.,]+)"
    r"(?:\s+TAX (?P<tax_ccy>[A-Z]{3}) (?P<tax>[\d.,]+))?"
)


@dataclass
class AbnDetails:
    kind: str  # sepa_transfer | direct_debit | ideal | card | atm | fee | invest_buy | invest_sell | dividend | invest_fee | other
    counterparty: str | None = None
    counterparty_iban: str | None = None
    remittance: str | None = None
    reference: str | None = None
    mandate: str | None = None
    card: str | None = None
    city: str | None = None
    extra: dict | None = None


def _dec(s: str) -> Decimal:
    return Decimal(s.replace(".", "").replace(",", ".")) if "," in s else Decimal(s)


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = " ".join(s.split())
    return s or None


def parse(desc: str) -> AbnDetails:
    text = " ".join((desc or "").split())
    if text.startswith("/TRTP/") or text.startswith("/RTRN/"):
        parts = _TAG_RE.split(text)
        fields: dict[str, str] = {}
        for i in range(1, len(parts) - 1, 2):
            fields[parts[i]] = parts[i + 1].strip().rstrip("/")
        trtp = fields.get("TRTP", "").lower()
        kind = (
            "direct_debit" if "incasso" in trtp
            else "ideal" if "ideal" in trtp
            else "sepa_transfer"
        )
        return AbnDetails(
            kind=kind,
            counterparty=_clean(fields.get("NAME")),
            counterparty_iban=(fields.get("IBAN") or "").replace(" ", "").upper() or None,
            remittance=_clean(fields.get("REMI")),
            reference=_clean(fields.get("EREF")),
            mandate=_clean(fields.get("MARF")),
            extra={"trtp": fields.get("TRTP"), "csid": fields.get("CSID")},
        )
    m = _CARD_RE.match(text) or _CARD_OLD_RE.match(text)
    if m:
        return AbnDetails(
            kind="atm" if m["kind"] == "GEA" else "card",
            counterparty=_clean(m["merchant"]),
            card=m["card"],
            city=_clean(m["city"]),
            reference=m["nr"],
            extra={"datetime": m["dt"], "wallet": m.groupdict().get("wallet")},
        )
    if text.startswith("GEA"):
        return AbnDetails(kind="atm", counterparty="ATM", remittance=text)
    if m := _INVEST_DEPOSIT.search(text):
        return AbnDetails(
            kind="invest_buy",
            counterparty=_clean(m["name"]),
            extra={"code": m["code"], "units": str(_dec(m["units"])), "price": str(_dec(m["price"])), "ccy": m["ccy"]},
        )
    if m := _INVEST_WITHDRAW.search(text):
        return AbnDetails(
            kind="invest_sell",
            counterparty=_clean(m["name"]),
            extra={"code": m["code"], "units": str(_dec(m["units"])), "price": str(_dec(m["price"])), "ccy": m["ccy"]},
        )
    if m := _DIVIDEND.search(text):
        return AbnDetails(
            kind="dividend",
            counterparty=_clean(m["name"]),
            extra={
                "shares": str(_dec(m["shares"])),
                "ccy": m["ccy"],
                "per_share": str(_dec(m["per_share"])),
                "tax": str(_dec(m["tax"])) if m["tax"] else None,
            },
        )
    if text.upper().startswith("ABNAMRO INVESTMENTS") or text.upper().startswith("ABN AMRO INVESTMENTS"):
        return AbnDetails(kind="invest_fee", counterparty="ABN AMRO Investments", remittance=text)
    if text.startswith("ABN AMRO Bank N.V."):
        return AbnDetails(kind="fee", counterparty="ABN AMRO Bank", remittance=text.removeprefix("ABN AMRO Bank N.V.").strip())
    if _KV_RE.search(text):
        parts = _KV_RE.split(text)
        fields = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
        return AbnDetails(
            kind="sepa_transfer",
            counterparty=_clean(fields.get("Naam") or fields.get("Incassant")),
            counterparty_iban=(fields.get("IBAN") or "").replace(" ", "").upper() or None,
            remittance=_clean(fields.get("Omschrijving")),
            reference=_clean(fields.get("Kenmerk")),
            mandate=_clean(fields.get("Machtiging")),
        )
    return AbnDetails(kind="other", counterparty=None, remittance=_clean(text))


def summary(d: AbnDetails) -> str:
    """Short human description for the ledger."""
    if d.kind in ("card", "atm"):
        return " ".join(x for x in (d.counterparty, d.city) if x)
    return " — ".join(x for x in (d.counterparty, d.remittance) if x) or ""
