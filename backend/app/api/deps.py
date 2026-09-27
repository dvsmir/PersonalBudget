from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.db.models import User
from app.services.auth import decode_access_token
from app.services.common import DomainError


def get_db() -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DB = Annotated[Session, Depends(get_db)]


def current_user(db: DB, authorization: Annotated[str | None, Header()] = None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise DomainError("unauthenticated", "Login required", status=401)
    user = db.get(User, decode_access_token(authorization.split(" ", 1)[1]))
    if user is None or not user.is_active:
        raise DomainError("unauthenticated", "Login required", status=401)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser) -> User:
    if user.role != "admin":
        raise DomainError("forbidden", "Admin only", status=403)
    return user


AdminUser = Annotated[User, Depends(admin_user)]
