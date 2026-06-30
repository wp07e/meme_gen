"""Login/session dependencies and user CRUD for FastAPI.

- seed_admin(): idempotently ensures the configured admin account exists.
- current_user / require_user / require_admin: request-scoped dependencies
  that verify the signed session cookie and look the user up in the DB.
- list/create/delete_user: the admin screen's only operations.
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.config import Settings
from app.db import session_scope
from app.models import User
from app.security import SESSION_COOKIE, SESSION_TTL, create_session_cookie, hash_password, parse_session_cookie, verify_password


@dataclass(frozen=True)
class Principal:
    """The logged-in identity attached to a request (plain object — no ORM
    session needed to read its fields, so it survives past session_scope())."""
    username: str
    is_admin: bool


def seed_admin(settings: Settings) -> None:
    """Ensure the configured admin user exists. Only sets the password hash
    when the row is missing — it will not overwrite an admin you re-passworded
    via the admin screen. Idempotent and safe on every startup."""
    with session_scope() as s:
        existing = s.get(User, settings.admin_username)
        if existing is not None:
            return
        user = User(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            is_admin=True,
        )
        s.add(user)


def _read_cookie_principal(request: Request, settings: Settings) -> Principal | None:
    """Resolve the request's signed cookie to a Principal, or None.

    Reads all needed columns while the session is open — SQLAlchemy expires
    attributes on commit, so a detached row would raise if read afterwards."""
    value = request.cookies.get(SESSION_COOKIE)
    username = parse_session_cookie(value, settings.secret_key)
    if username is None:
        return None
    with session_scope() as s:
        row = s.get(User, username)
        if row is None:
            return None
        return Principal(username=row.username, is_admin=bool(row.is_admin))


def current_user(request: Request) -> Principal:
    """Dependency: the logged-in identity, or 401."""
    from app.config import get_settings
    principal = _read_cookie_principal(request, get_settings())
    if principal is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return principal


def require_user(user: Principal = Depends(current_user)) -> Principal:
    return user


def require_admin(user: Principal = Depends(current_user)) -> Principal:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return user


def authenticate(username: str, password: str) -> Principal | None:
    """Verify credentials. Returns a Principal on success, None otherwise.

    Column reads happen inside the session block (see _read_cookie_principal)."""
    with session_scope() as s:
        row = s.get(User, username)
        if row is None or not verify_password(password, row.password_hash):
            return None
        return Principal(username=row.username, is_admin=bool(row.is_admin))


def set_session_cookie_value(username: str, secret: str) -> tuple[str, str, int]:
    """Return (cookie_name, cookie_value, max_age) for a successful login."""
    return SESSION_COOKIE, create_session_cookie(username, secret, ttl=SESSION_TTL), SESSION_TTL


# --------------------------------------------------------------------------- #
# User CRUD (admin screen)
# --------------------------------------------------------------------------- #

def list_users() -> list[User]:
    from sqlmodel import select
    with session_scope() as s:
        return list(s.exec(select(User)).all())


def create_user(username: str, password: str) -> User:
    username = (username or "").strip()
    if not username or not password:
        raise ValueError("username and password are required")
    with session_scope() as s:
        if s.get(User, username) is not None:
            raise ValueError("username already exists")
        user = User(username=username, password_hash=hash_password(password), is_admin=False)
        s.add(user)
        s.commit()
        s.refresh(user)
    return user


def delete_user(username: str, settings: Settings) -> None:
    """Delete a user. Raises ValueError for the seeded admin or a missing user."""
    with session_scope() as s:
        user = s.get(User, username)
        if user is None:
            raise ValueError("user not found")
        if username == settings.admin_username:
            raise ValueError("the seeded admin cannot be deleted")
        s.delete(user)
