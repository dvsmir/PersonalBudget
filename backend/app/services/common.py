import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog, Setting


class DomainError(Exception):
    """Business-rule violation. Rendered as RFC 7807 problem JSON by the API."""

    def __init__(self, code: str, message: str, status: int = 422, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


class NotFound(DomainError):
    def __init__(self, entity: str, entity_id: Any) -> None:
        super().__init__("not_found", f"{entity} {entity_id} not found", status=404)


def get_or_404(session: Session, model: type, entity_id: Any):  # type: ignore[no-untyped-def]
    obj = session.get(model, entity_id)
    if obj is None:
        raise NotFound(model.__name__, entity_id)
    return obj


SETTING_DEFAULTS: dict[str, Any] = {
    "reporting_currency": "EUR",
    "ai_model": None,  # falls back to config.ai_model_default
    "ai_monthly_soft_budget_usd": 20,
    "bank_cutover_date": "2025-03-01",
    "card_cutover_date": "2024-08-01",
    "history_start_date": "2020-11-21",
    "lock_date": None,
}


def get_setting(session: Session, key: str) -> Any:
    row = session.get(Setting, key)
    if row is None:
        return SETTING_DEFAULTS.get(key)
    return json.loads(row.value)


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=json.dumps(value)))
    else:
        row.value = json.dumps(value)


def all_settings(session: Session) -> dict[str, Any]:
    result = dict(SETTING_DEFAULTS)
    for row in session.query(Setting).all():
        result[row.key] = json.loads(row.value)
    return result


def audit(
    session: Session,
    user_id: int | None,
    entity: str,
    entity_id: int,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    diff = None
    if before is not None or after is not None:
        diff = json.dumps({"before": before, "after": after}, default=str, ensure_ascii=False)
    session.add(AuditLog(user_id=user_id, entity=entity, entity_id=entity_id, action=action, diff=diff))
