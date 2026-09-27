"""Authentication: argon2 passwords, short-lived JWT access tokens, rotating refresh sessions, optional TOTP."""

import base64
import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuthSession, User
from app.services.common import DomainError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise DomainError("weak_password", "Password must be at least 10 characters")
    return _hasher.hash(password)


def verify_password(user: User, password: str) -> bool:
    try:
        return _hasher.verify(user.password_hash, password)
    except VerifyMismatchError:
        return False


def _fernet() -> Fernet:
    key = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


# ---------------------------------------------------------------- rate limiting

_attempts: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, limit: int = 5, window_s: int = 60) -> None:
    now = time.monotonic()
    q = _attempts[key]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        raise DomainError("rate_limited", "Too many login attempts, try again in a minute", status=429)
    q.append(now)


def reset_rate_limit(key: str) -> None:
    _attempts.pop(key, None)


# ---------------------------------------------------------------- tokens

def create_access_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": str(user.id), "role": user.role, "iat": now, "exp": now + timedelta(minutes=s.access_token_minutes)}
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise DomainError("invalid_token", "Invalid or expired token", status=401) from e
    return int(payload["sub"])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_refresh_session(session: Session, user: User, client: str) -> str:
    token = secrets.token_urlsafe(48)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=_hash_token(token),
            client=client,
            expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days),
        )
    )
    return token


def rotate_refresh(session: Session, token: str) -> tuple[User, str]:
    row = session.execute(select(AuthSession).where(AuthSession.token_hash == _hash_token(token))).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.revoked_at is not None or row.expires_at < now:
        raise DomainError("invalid_refresh", "Session expired, please log in again", status=401)
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise DomainError("invalid_refresh", "Session expired, please log in again", status=401)
    row.revoked_at = now
    return user, create_refresh_session(session, user, row.client)


def revoke_refresh(session: Session, token: str) -> None:
    row = session.execute(select(AuthSession).where(AuthSession.token_hash == _hash_token(token))).scalar_one_or_none()
    if row and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)


def login(session: Session, email: str, password: str, totp: str | None, client: str) -> tuple[User, str, str]:
    check_rate_limit(f"login:{email.lower()}")
    user = session.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(user, password):
        raise DomainError("invalid_credentials", "Wrong e-mail or password", status=401)
    if user.totp_secret:
        if not totp:
            raise DomainError("totp_required", "Enter the code from your authenticator app", status=401)
        if not pyotp.TOTP(decrypt_secret(user.totp_secret)).verify(totp, valid_window=1):
            raise DomainError("invalid_totp", "Wrong authenticator code", status=401)
    reset_rate_limit(f"login:{email.lower()}")
    return user, create_access_token(user), create_refresh_session(session, user, client)


def create_user(session: Session, email: str, name: str, password: str, role: str = "member", locale: str = "en") -> User:
    if session.execute(select(User).where(User.email == email.lower())).scalar_one_or_none():
        raise DomainError("duplicate_email", f"User {email} already exists", status=409)
    user = User(email=email.lower(), display_name=name, password_hash=hash_password(password), role=role, locale=locale)
    session.add(user)
    session.flush()
    return user


def totp_begin(user: User) -> tuple[str, str]:
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="Budget")
    return secret, uri


def totp_enable(user: User, secret: str, code: str) -> None:
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        raise DomainError("invalid_totp", "Wrong authenticator code")
    user.totp_secret = encrypt_secret(secret)
