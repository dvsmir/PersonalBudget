"""Scheduled jobs (Backend.md §9), run in-process by APScheduler."""

import logging
import sqlite3
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings
from app.db import SessionLocal
from app.services import fx
from app.services.budget import generate_month

log = logging.getLogger(__name__)


def fetch_fx() -> None:
    with SessionLocal() as session:
        try:
            n = fx.fetch_rates(session, fx.default_since(session), {"USD", "GBP", "RUB"})
        except fx.FxFetchError as e:
            n = e.stored
            log.error("fx fetch partly failed: %s", e)
        except Exception:
            log.exception("fx fetch failed")
            return
        fixed = fx.recompute_estimated(session)
        session.commit()
        log.info("fx: %s rates, %s rows re-valued", n, fixed)


def budget_rollover() -> None:
    with SessionLocal() as session:
        n = generate_month(session, date.today().strftime("%Y-%m"))
        session.commit()
        log.info("budget: %s lines generated", n)


def backup() -> str:
    """Consistent online copy of the SQLite file (sqlite3 backup API); keeps the last 48 hourly copies."""
    settings = get_settings()
    src_path = settings.database_url.removeprefix("sqlite:///")
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    target = settings.backup_dir / f"budget-{datetime.now():%Y%m%d-%H%M}.db"
    with sqlite3.connect(src_path) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    copies = sorted(settings.backup_dir.glob("budget-*.db"))
    for old in copies[:-48]:
        old.unlink()
    return str(target)


def start() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Europe/Amsterdam")
    scheduler.add_job(fetch_fx, "cron", hour=17, minute=30, id="fx_fetch")
    scheduler.add_job(fetch_fx, "date", id="fx_startup")
    scheduler.add_job(budget_rollover, "cron", day=1, hour=0, minute=5, id="budget_rollover")
    scheduler.add_job(backup, "cron", minute=7, id="backup")
    scheduler.start()
    return scheduler
