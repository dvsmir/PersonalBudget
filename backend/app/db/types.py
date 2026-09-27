"""Column types that map onto SQLite STRICT storage classes (INTEGER / TEXT only)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


class ISODate(TypeDecorator[date]):
    """Calendar date stored as TEXT 'YYYY-MM-DD'."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: date | str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return date.fromisoformat(value).isoformat()
        return value.isoformat()

    def process_result_value(self, value: str | None, dialect: Any) -> date | None:
        return date.fromisoformat(value) if value is not None else None


class UTCDateTime(TypeDecorator[datetime]):
    """Timestamp stored as TEXT ISO-8601 in UTC."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat(timespec="seconds")

    def process_result_value(self, value: str | None, dialect: Any) -> datetime | None:
        return datetime.fromisoformat(value) if value is not None else None


class DecimalText(TypeDecorator[Decimal]):
    """Exact decimal (rates, prices, units) stored as TEXT."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Decimal | str | int | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return str(Decimal(value))

    def process_result_value(self, value: str | None, dialect: Any) -> Decimal | None:
        return Decimal(value) if value is not None else None
