from datetime import date
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, AdminUser, CurrentUser
from app.db.models import AiCallLog, Currency, FxRate
from app.services import fx
from app.services.common import all_settings, set_setting

router = APIRouter(tags=["settings"])

EDITABLE = {"ai_model", "ai_monthly_soft_budget_usd", "bank_cutover_date", "card_cutover_date", "history_start_date",
            "lock_date", "ignored_own_ibans", "card_payee_ibans", "sheet_account_map"}


@router.get("/settings")
def get_settings_(user: CurrentUser, db: DB) -> dict[str, Any]:
    return all_settings(db)


@router.patch("/settings")
def patch_settings(body: dict[str, Any], admin: AdminUser, db: DB) -> dict[str, Any]:
    for k, v in body.items():
        if k in EDITABLE:
            set_setting(db, k, v)
    db.flush()
    return all_settings(db)


@router.get("/currencies")
def currencies(user: CurrentUser, db: DB) -> list[dict]:
    return [{"code": c.code, "name": c.name, "symbol": c.symbol, "minor_units": c.minor_units}
            for c in db.scalars(select(Currency).order_by(Currency.code))]


@router.get("/fx/rate")
def fx_rate(user: CurrentUser, db: DB, date: date, currency: str) -> dict:
    rate, estimated = fx.RateBook(db).rate(currency, date)
    return {"date": date, "base": "EUR", "quote": currency, "rate": str(rate) if rate else None, "estimated": estimated}


@router.get("/fx/rates")
def fx_rates(user: CurrentUser, db: DB, currency: str, start: date, end: date) -> list[dict]:
    rows = db.execute(select(FxRate).where(FxRate.quote == currency, FxRate.date >= start, FxRate.date <= end)
                      .order_by(FxRate.date)).scalars()
    return [{"date": r.date, "rate": str(r.rate), "source": r.source} for r in rows]


@router.put("/fx/rates")
def fx_manual(body: dict, admin: AdminUser, db: DB) -> dict:
    """Manual override: {"date": "2026-01-02", "currency": "RUB", "rate": "95.1"}."""
    from decimal import Decimal

    from sqlalchemy.dialects.sqlite import insert

    stmt = insert(FxRate).values(date=date.fromisoformat(body["date"]), base="EUR", quote=body["currency"],
                                 rate=Decimal(str(body["rate"])), source="manual")
    db.execute(stmt.on_conflict_do_update(index_elements=["date", "base", "quote"],
                                          set_={"rate": stmt.excluded.rate, "source": "manual"}))
    return {"recomputed": fx.recompute_estimated(db)}


@router.post("/fx/fetch")
def fx_fetch(admin: AdminUser, db: DB, since: date | None = None) -> dict:
    since = since or fx.default_since(db)
    try:
        n, errors = fx.fetch_rates(db, since, {"USD", "GBP", "RUB"}), []
    except fx.FxFetchError as e:
        n, errors = e.stored, e.errors
    return {"stored": n, "since": since, "errors": errors, "recomputed": fx.recompute_estimated(db)}


@router.get("/ai/usage")
def ai_usage(user: CurrentUser, db: DB) -> dict:
    month = date.today().strftime("%Y-%m")
    row = db.execute(
        select(func.count(), func.coalesce(func.sum(AiCallLog.input_tokens), 0), func.coalesce(func.sum(AiCallLog.output_tokens), 0),
               func.coalesce(func.sum(AiCallLog.cache_read_tokens), 0))
        .where(func.substr(AiCallLog.created_at, 1, 7) == month)
    ).one()
    return {"month": month, "calls": row[0], "input_tokens": row[1], "output_tokens": row[2], "cache_read_tokens": row[3]}


@router.get("/health")
def health(db: DB) -> dict:
    db.execute(select(1))
    return {"status": "ok"}
