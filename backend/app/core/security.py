"""Passwords, one-time tokens, JWT, auth cookies and the current-user dependency.

Design B02 §3.8 (hashing, tokens) and B03 §3.2 (JWT, cookies, dependencies).

- Passwords: Argon2id via argon2-cffi with the library's current defaults
  (RFC 9106 low-memory profile). Hashes embed their parameters, so defaults
  can be raised later; `needs_rehash` tells login when to upgrade.
- Tokens (invites, resets, verification, refresh): 32 random bytes, URL-safe.
  Only the SHA-256 hex digest is stored; the raw value exists only in the
  link / cookie.
- Access token: short-lived HS256 JWT in an httpOnly cookie (B03 D15). The
  user is reloaded on every request, so deactivation takes effect at once.
"""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.db import get_session
from app.core.errors import EmailNotVerified, Unauthenticated
from app.models.public import User

log = structlog.get_logger("app.security")

MIN_PASSWORD_LEN = 12  # ui_screens.md §4
TOKEN_BYTES = 32

_hasher = PasswordHasher()  # Argon2id is the argon2-cffi default type

# --- B03 constants ---------------------------------------------------------- #
# Base cookie names; the real ones carry COOKIE_PREFIX: access_cookie() below.
ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 (claim value, not a secret). "type" claim: rejects any other JWT signed with the same key
RESET_TOKEN_TTL = timedelta(hours=1)  # backend_processes.md §5
VERIFY_TOKEN_TTL = timedelta(hours=24)
# Small clock-skew allowance between API replicas when checking `exp`.
JWT_LEEWAY_S = 5

# Hash of a random password, computed on first use: lets login run one real
# Argon2 verify for unknown emails so response time does not reveal which
# accounts exist (B03 D9).
_dummy_hash: str | None = None


class WeakPasswordError(ValueError):
    """Raised with a user-presentable reason."""


def validate_password_strength(plain: str) -> None:
    """Min 12 chars, at least one letter and one digit (ui_screens.md §4)."""
    if len(plain) < MIN_PASSWORD_LEN:
        raise WeakPasswordError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if not re.search(r"[A-Za-z]", plain) or not re.search(r"\d", plain):
        raise WeakPasswordError("password must contain letters and numbers")


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    """True if `plain` matches. Never raises for a bad/garbled hash: returns False."""
    try:
        return _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """Return (raw token for the link, sha256 hex to store)."""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return raw, hash_token(raw)


def dummy_verify(plain: str) -> None:
    """Spend the same Argon2 time as a real check, for unknown accounts (D9)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(16))
    verify_password(plain, _dummy_hash)


# --------------------------------------------------------------------------- #
# JWT access tokens (B03 D15)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    family_id: uuid.UUID  # refresh family of the session that minted this token
    expires_at: datetime


def create_access_token(user_id: uuid.UUID, family_id: uuid.UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "fam": str(family_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    """Validate signature, expiry and type. Any problem -> Unauthenticated (401).

    The reason is logged at INFO for debugging but never returned to the client.
    """
    try:
        data = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[JWT_ALGORITHM],  # pinned: never accept "none" or RS/HS confusion
            leeway=JWT_LEEWAY_S,
            options={"require": ["sub", "fam", "exp", "type"]},
        )
        if data.get("type") != ACCESS_TOKEN_TYPE:
            raise jwt.InvalidTokenError("wrong token type")
        return AccessClaims(
            user_id=uuid.UUID(data["sub"]),
            family_id=uuid.UUID(data["fam"]),
            expires_at=datetime.fromtimestamp(data["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError) as exc:  # ValueError: malformed UUID in claims
        log.info("auth.access_token_rejected", reason=type(exc).__name__)
        raise Unauthenticated() from exc


# --------------------------------------------------------------------------- #
# Cookies (system_design §3, B03 D4)
# --------------------------------------------------------------------------- #
def access_cookie(settings: Settings) -> str:
    """Name of the access cookie for this deployment (B13 D6)."""
    return settings.cookie_prefix + ACCESS_COOKIE


def refresh_cookie(settings: Settings) -> str:
    """Name of the refresh cookie for this deployment (B13 D6)."""
    return settings.cookie_prefix + REFRESH_COOKIE


def set_auth_cookies(response: Response, access: str, refresh: str, settings: Settings) -> None:
    """httpOnly + SameSite=Lax; Secure follows COOKIE_SECURE (false only in dev)."""
    response.set_cookie(
        access_cookie(settings),
        access,
        max_age=settings.access_token_minutes * 60,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.set_cookie(
        refresh_cookie(settings),
        refresh,
        max_age=settings.refresh_token_days * 86400,
        path=settings.refresh_cookie_path,  # only sent to the auth endpoints
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    """Delete both cookies; path/flags must match how they were set."""
    response.delete_cookie(
        access_cookie(settings),
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.delete_cookie(
        refresh_cookie(settings),
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


# --------------------------------------------------------------------------- #
# Current-user dependencies (build_list B03 #9)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CurrentUser:
    user: User
    family_id: uuid.UUID  # lets change-password keep the caller's own session (D5)

    @property
    def id(self) -> uuid.UUID:
        return self.user.id


def request_settings(request: Request) -> Settings:
    """Settings of the running app (set by create_app; tests inject their own)."""
    return request.app.state.settings


async def current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurrentUser:
    """Authenticated caller from the access cookie, or 401.

    Rejects: no cookie, bad/expired JWT, unknown user, inactive user.
    """
    settings = request_settings(request)
    token = request.cookies.get(access_cookie(settings))
    if not token:
        raise Unauthenticated()
    claims = decode_access_token(token, settings)
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        log.info("auth.user_rejected", user_id=str(claims.user_id), found=user is not None)
        raise Unauthenticated()
    # Every later log line of this request carries the user id.
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return CurrentUser(user=user, family_id=claims.family_id)


async def current_verified_user(
    request: Request,
    caller: Annotated[CurrentUser, Depends(current_user)],
) -> CurrentUser:
    """current_user + email verification gate for tenant features (B03 D1)."""
    if request_settings(request).require_email_verification and not caller.user.is_verified:
        raise EmailNotVerified()
    return caller
