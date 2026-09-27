import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="budget-test-"))
os.environ["BUDGET_DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["BUDGET_SCHEDULER_ENABLED"] = "false"
os.environ["BUDGET_SECRET_KEY"] = "test-secret-key-test-secret-key-0123456789"

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.db.models import Account, Category, FxRate  # noqa: E402
from app.seed import seed  # noqa: E402
from app.services import auth  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed(session)
        # EUR->RUB 100 on every day we use, USD 1.1
        for d in (date(2020, 11, 1), date(2025, 1, 1)):
            session.add(FxRate(date=d, base="EUR", quote="RUB", rate=Decimal("100"), source="manual"))
            session.add(FxRate(date=d, base="EUR", quote="USD", rate=Decimal("1.1"), source="manual"))
        session.commit()
        yield session
        session.rollback()


@pytest.fixture()
def user(db):
    u = auth.create_user(db, "dima@example.com", "Dima", "correct horse battery", role="admin")
    db.commit()
    return u


def acc(db, name: str) -> Account:
    return db.execute(select(Account).where(Account.name == name)).scalar_one()


def cat(db, name: str, kind: str = "expense") -> Category:
    return db.execute(select(Category).where(Category.name == name, Category.kind == kind)).scalars().first()
