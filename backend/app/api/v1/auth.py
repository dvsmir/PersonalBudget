from typing import Annotated

from fastapi import APIRouter, Cookie, Response
from sqlalchemy import select

from app.api.deps import DB, AdminUser, CurrentUser
from app.api.schemas import LoginIn, MePatch, TokenOut, TotpBeginOut, TotpConfirmIn, UserIn, UserOut, UserPatch
from app.config import get_settings
from app.db.models import User
from app.services import auth
from app.services.common import DomainError, get_or_404

router = APIRouter(tags=["auth"])
COOKIE = "budget_refresh"


def _user_out(u: User) -> UserOut:
    out = UserOut.model_validate(u)
    out.totp_enabled = bool(u.totp_secret)
    return out


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="strict",
                        max_age=s.refresh_token_days * 86400, path="/api/v1/auth")


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, response: Response, db: DB) -> TokenOut:
    user, access, refresh = auth.login(db, body.email, body.password, body.totp, body.client)
    expires = get_settings().access_token_minutes * 60
    if body.client == "web":
        _set_cookie(response, refresh)
        return TokenOut(access_token=access, expires_in=expires)
    return TokenOut(access_token=access, expires_in=expires, refresh_token=refresh)


@router.post("/auth/refresh", response_model=TokenOut)
def refresh(response: Response, db: DB, budget_refresh: Annotated[str | None, Cookie()] = None,
            refresh_token: str | None = None) -> TokenOut:
    token = budget_refresh or refresh_token
    if not token:
        raise DomainError("invalid_refresh", "Session expired, please log in again", status=401)
    user, new_refresh = auth.rotate_refresh(db, token)
    expires = get_settings().access_token_minutes * 60
    if budget_refresh:
        _set_cookie(response, new_refresh)
        return TokenOut(access_token=auth.create_access_token(user), expires_in=expires)
    return TokenOut(access_token=auth.create_access_token(user), expires_in=expires, refresh_token=new_refresh)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, db: DB, budget_refresh: Annotated[str | None, Cookie()] = None) -> None:
    if budget_refresh:
        auth.revoke_refresh(db, budget_refresh)
    response.delete_cookie(COOKIE, path="/api/v1/auth")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)


@router.patch("/me", response_model=UserOut)
def patch_me(body: MePatch, user: CurrentUser, db: DB) -> UserOut:
    if body.display_name:
        user.display_name = body.display_name
    if body.locale:
        user.locale = body.locale
    if body.new_password:
        if not body.current_password or not auth.verify_password(user, body.current_password):
            raise DomainError("invalid_credentials", "Current password is wrong", status=400)
        user.password_hash = auth.hash_password(body.new_password)
    return _user_out(user)


@router.post("/me/totp/begin", response_model=TotpBeginOut)
def totp_begin(user: CurrentUser) -> TotpBeginOut:
    secret, uri = auth.totp_begin(user)
    return TotpBeginOut(secret=secret, uri=uri)


@router.post("/me/totp/confirm", response_model=UserOut)
def totp_confirm(body: TotpConfirmIn, user: CurrentUser, db: DB) -> UserOut:
    auth.totp_enable(user, body.secret, body.code)
    return _user_out(user)


@router.delete("/me/totp", response_model=UserOut)
def totp_disable(user: CurrentUser, db: DB) -> UserOut:
    user.totp_secret = None
    return _user_out(user)


@router.get("/users", response_model=list[UserOut])
def list_users(user: CurrentUser, db: DB) -> list[UserOut]:
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, admin: AdminUser, db: DB) -> UserOut:
    return _user_out(auth.create_user(db, body.email, body.display_name, body.password, body.role, body.locale))


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(user_id: int, body: UserPatch, admin: AdminUser, db: DB) -> UserOut:
    u = get_or_404(db, User, user_id)
    if body.display_name is not None:
        u.display_name = body.display_name
    if body.locale is not None:
        u.locale = body.locale
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = int(body.is_active)
    if body.password:
        u.password_hash = auth.hash_password(body.password)
    return _user_out(u)
