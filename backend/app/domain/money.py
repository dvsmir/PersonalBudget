"""Money helpers. Inside the backend, amounts are int minor units; at the API edge they are decimal strings."""

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

MINOR_UNITS: dict[str, int] = {"EUR": 2, "RUB": 2, "USD": 2, "GBP": 2}


class MoneyError(ValueError):
    pass


def minor_units(currency: str) -> int:
    return MINOR_UNITS.get(currency, 2)


def to_minor(amount: str | Decimal | int | float, currency: str) -> int:
    """'-12.34' EUR -> -1234. Rejects more precision than the currency allows."""
    try:
        value = Decimal(str(amount))
    except InvalidOperation as e:
        raise MoneyError(f"Invalid amount: {amount!r}") from e
    scaled = value.scaleb(minor_units(currency))
    if scaled != scaled.to_integral_value():
        raise MoneyError(f"Too many decimals for {currency}: {amount}")
    return int(scaled)


def from_minor(amount: int, currency: str) -> str:
    """-1234 EUR -> '-12.34'."""
    digits = minor_units(currency)
    return str(Decimal(amount).scaleb(-digits).quantize(Decimal(1).scaleb(-digits)))


def round_minor(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_EVEN))


def parse_localized(text: str) -> Decimal:
    """Parse '1.234,56', '1,234.56', '-€1,668.16', '20,589 ₽', '1234' into a Decimal."""
    s = text.strip().replace(" ", "").replace(" ", "")
    negative = s.startswith("-") or s.startswith("−") or (s.startswith("(") and s.endswith(")"))
    s = "".join(ch for ch in s if ch.isdigit() or ch in ",.")
    if not s:
        raise MoneyError(f"Not a number: {text!r}")
    if "," in s and "." in s:
        # the last separator is the decimal one
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # one comma followed by 1-2 digits is a decimal comma ('12,5', '0,55');
        # otherwise commas are thousands separators ('1,234', '1,234,567')
        tail = s.rpartition(",")[2]
        s = s.replace(",", ".") if s.count(",") == 1 and len(tail) in (1, 2) else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")  # '1.234.567' thousands dots
    value = Decimal(s)
    return -value if negative else value
