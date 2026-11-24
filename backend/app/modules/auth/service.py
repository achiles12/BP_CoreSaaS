"""Auth business rules (design B03 §3.8, D1–D10).

Services take an AsyncSession plus plain values, COMMIT their own transaction
and only then write the audit line, so an audit "ok" always describes a
committed change. Where a request must fail but a change must persist
(refresh-token reuse revokes the family, then 401), the service commits
before raising, because the request dependency rolls back on exceptions.
"""

import ipaddress
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import structlog
from arq.connections import ArqRedis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import audit, mail
from app.core.errors import (
    BadRequest,
    Conflict,
    ServiceUnavailable,
    Unauthenticated,
    ValidationFailed,
)
from app.core.security import (
    RESET_TOKEN_TTL,
    VERIFY_TOKEN_TTL,
    WeakPasswordError,
    create_access_token,
    dummy_verify,
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    validate_password_strength,
    verify_password,
)
from app.models.public import (
    EmailVerificationToken,
    Organization,
    OrgMembership,
    PasswordResetToken,
    RefreshToken,
    User,
)

log = structlog.get_logger("app.auth")

INVALID_LOGIN = "Invalid email or password"  # one message for every login failure (D9)
INVALID_TOKEN = "Invalid or expired token"  # noqa: S105 (message, not a secret)
MAX_USER_AGENT_LEN = 512


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Membership:
    org_id: uuid.UUID
    slug: str
    name: str


@dataclass(frozen=True)
class IssuedSession:
    """Everything the router needs to answer a login/refresh."""

    user: User
    access_token: str
    refresh_token: str  # raw value: goes into the cookie, never stored
    family_id: uuid.UUID


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _check_strength(new_password: str, field: str = "new_password") -> None:
    """Weak password -> 422 in the standard error shape with error.fields."""
    try:
        validate_password_strength(new_password)
    except WeakPasswordError as exc:
        raise ValidationFailed(
            str(exc), fields=[{"loc": ["body", field], "msg": str(exc), "type": "weak_password"}]
        ) from exc


def _inet_or_none(ip: str | None) -> str | None:
    """refresh_tokens.ip is `inet`: a non-IP peer (unix socket, test client) is stored as NULL
    instead of failing the whole login with a 500."""
    if not ip:
        return None
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        log.debug("auth.client_ip_not_an_ip", value=ip[:64])
        return None


async def _issue_refresh(
    s: AsyncSession,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    settings: Settings,
    ip: str | None,
    user_agent: str | None,
) -> tuple[RefreshToken, str]:
    raw, digest = new_token()
    row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        family_id=family_id,
        token_hash=digest,
        expires_at=_now() + timedelta(days=settings.refresh_token_days),
        ip=_inet_or_none(ip),
        user_agent=(user_agent or "")[:MAX_USER_AGENT_LEN] or None,
    )
    s.add(row)
    await s.flush()
    return row, raw


async def revoke_family(s: AsyncSession, family_id: uuid.UUID) -> int:
    res = await s.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    return res.rowcount  # type: ignore[attr-defined]  # CursorResult


async def revoke_user_sessions(
    s: AsyncSession, user_id: uuid.UUID, *, except_family: uuid.UUID | None = None
) -> int:
    """Revoke every live refresh token of a user (optionally keeping one family)."""
    stmt = update(RefreshToken).where(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    )
    if except_family is not None:
        stmt = stmt.where(RefreshToken.family_id != except_family)
    res = await s.execute(stmt.values(revoked_at=_now()))
    return res.rowcount  # type: ignore[attr-defined]


async def active_memberships(s: AsyncSession, user_id: uuid.UUID) -> list[Membership]:
    """Active memberships in ACTIVE organizations (suspended orgs are hidden)."""
    rows = (
        await s.execute(
            select(Organization.id, Organization.slug, Organization.name)
            .join(OrgMembership, OrgMembership.org_id == Organization.id)
            .where(
                OrgMembership.user_id == user_id,
                OrgMembership.status == "active",
                Organization.status == "active",
            )
            .order_by(Organization.name)
        )
    ).all()
    return [Membership(org_id=r[0], slug=r[1], name=r[2]) for r in rows]


# --------------------------------------------------------------------------- #
# login / refresh / logout
# --------------------------------------------------------------------------- #
async def login(
    s: AsyncSession,
    email: str,
    password: str,
    settings: Settings,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[IssuedSession, list[Membership]]:
    user = await s.scalar(select(User).where(User.email == email))
    if user is None:
        dummy_verify(password)  # equal timing for unknown accounts (D9)
        _login_denied(email, None, "unknown_email")
    elif not verify_password(password, user.password_hash):
        _login_denied(email, user.id, "bad_password")
    elif not user.is_active:
        # Checked AFTER the password so an inactive account is only revealed to
        # someone who knows its password, and even then with the generic 401.
        _login_denied(email, user.id, "inactive")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        log.info("auth.password_rehashed", user_id=str(user.id))
    user.last_login_at = _now()

    family_id = uuid.uuid4()  # each login starts a new token family
    _, refresh_raw = await _issue_refresh(s, user.id, family_id, settings, ip, user_agent)
    memberships = await active_memberships(s, user.id)
    await s.commit()

    audit.record(
        "auth.login",
        entity="user",
        entity_id=str(user.id),
        actor=str(user.id),
        diff={"family_id": str(family_id)},
        sensitive=True,
    )
    log.info("auth.login_ok", user_id=str(user.id), memberships=len(memberships))
    access = create_access_token(user.id, family_id, settings)
    return IssuedSession(user, access, refresh_raw, family_id), memberships


def _login_denied(email: str, user_id: uuid.UUID | None, reason: str) -> NoReturn:
    """Audit + log the failure (reason stays server-side), then raise 401."""
    audit.record(
        "auth.login",
        entity="user",
        entity_id=str(user_id) if user_id else None,
        actor=str(user_id) if user_id else None,
        diff={"email": email, "reason": reason},
        result="denied",
        sensitive=True,
    )
    log.info("auth.login_denied", reason=reason)
    raise Unauthenticated(INVALID_LOGIN)


async def refresh(
    s: AsyncSession,
    raw: str | None,
    settings: Settings,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedSession:
    """Rotate the refresh token (D10). Any failure -> Unauthenticated."""
    if not raw:
        raise Unauthenticated("No session")
    digest = hash_token(raw)
    now = _now()

    # Atomic claim: only ONE request can move this row from live to revoked.
    claimed = (
        await s.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == digest,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .values(revoked_at=now)
            .returning(RefreshToken.id, RefreshToken.user_id, RefreshToken.family_id)
        )
    ).first()

    if claimed is None:
        existing = await s.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest))
        if existing is None:
            log.info("auth.refresh_unknown_token")
            raise Unauthenticated("Session expired")
        if existing.revoked_at is None:
            # Not revoked, so the claim failed because it is expired.
            log.info("auth.refresh_expired", family_id=str(existing.family_id))
            raise Unauthenticated("Session expired")
        # Already revoked: a rotated (old) token was presented again -> treat
        # as theft. Kill the whole family and COMMIT before the 401 rollback.
        revoked = await revoke_family(s, existing.family_id)
        await s.commit()
        audit.record(
            "auth.refresh_reuse",
            entity="refresh_family",
            entity_id=str(existing.family_id),
            actor=str(existing.user_id),
            diff={"revoked_tokens": revoked},
            result="denied",
            sensitive=True,
        )
        log.warning(
            "auth.refresh_reuse_detected",
            family_id=str(existing.family_id),
            user_id=str(existing.user_id),
            revoked=revoked,
        )
        raise Unauthenticated("Session revoked")

    old_id, user_id, family_id = claimed
    user = await s.get(User, user_id)
    if user is None or not user.is_active:
        await revoke_family(s, family_id)
        await s.commit()
        log.info("auth.refresh_user_inactive", user_id=str(user_id))
        raise Unauthenticated("Session expired")

    new_row, new_raw = await _issue_refresh(s, user_id, family_id, settings, ip, user_agent)
    await s.execute(
        update(RefreshToken).where(RefreshToken.id == old_id).values(replaced_by=new_row.id)
    )
    await s.commit()
    log.info("auth.refresh_rotated", user_id=str(user_id), family_id=str(family_id))
    # Rotation is routine and frequent: logged, not audited (not a mutation of
    # user data; reuse IS audited above).
    return IssuedSession(
        user, create_access_token(user_id, family_id, settings), new_raw, family_id
    )


async def logout(
    s: AsyncSession,
    raw_refresh: str | None,
    access_family: uuid.UUID | None,
    access_user: uuid.UUID | None,
) -> None:
    """D6: revoke the session family named by the refresh cookie or the access JWT.

    Never raises for a missing/unknown token: logout must always succeed.
    """
    family_id, user_id = access_family, access_user
    if raw_refresh:
        row = await s.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_refresh))
        )
        if row is not None:
            family_id, user_id = row.family_id, row.user_id
    if family_id is None:
        log.info("auth.logout_without_session")
        return
    revoked = await revoke_family(s, family_id)
    await s.commit()
    audit.record(
        "auth.logout",
        entity="refresh_family",
        entity_id=str(family_id),
        actor=str(user_id) if user_id else None,
        diff={"revoked_tokens": revoked},
    )
    log.info("auth.logout", family_id=str(family_id), revoked=revoked)


# --------------------------------------------------------------------------- #
# email verification
# --------------------------------------------------------------------------- #
async def verify_email(s: AsyncSession, raw: str) -> User:
    now = _now()
    row = await s.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == hash_token(raw),
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
    )
    if row is None:
        log.info("auth.verify_token_invalid")
        raise BadRequest(INVALID_TOKEN)
    user = await s.get(User, row.user_id)
    if user is None or not user.is_active:
        raise BadRequest(INVALID_TOKEN)
    row.used_at = now
    was_verified = user.is_verified
    user.is_verified = True
    await s.commit()
    audit.record(
        "auth.email_verified",
        entity="user",
        entity_id=str(user.id),
        actor=str(user.id),
        diff={"is_verified": [was_verified, True]},
    )
    return user


async def create_verification(
    s: AsyncSession, redis: ArqRedis, user: User, settings: Settings
) -> str | None:
    """Invalidate older verify tokens, create a fresh one, queue the email.

    Shared by resend-verification and `cli create-user --send-verification`.
    Commits. Returns the job id (None when queueing failed).
    """
    now = _now()
    await s.execute(
        update(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user.id, EmailVerificationToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw, digest = new_token()
    s.add(
        EmailVerificationToken(
            user_id=user.id, token_hash=digest, expires_at=now + VERIFY_TOKEN_TTL
        )
    )
    await s.commit()
    link = f"{settings.frontend_url.rstrip('/')}/verify-email?token={raw}"
    job_id = await mail.queue_email(
        redis, "verify_email", user.email, {"link": link, "full_name": user.full_name}
    )
    audit.record(
        "auth.verification_sent",
        entity="user",
        entity_id=str(user.id),
        actor=str(user.id),
        result="ok" if job_id else "error",
    )
    return job_id


async def resend_verification(
    s: AsyncSession, redis: ArqRedis, user: User, settings: Settings
) -> None:
    if user.is_verified:
        raise Conflict("Email already verified")
    if await create_verification(s, redis, user, settings) is None:
        raise ServiceUnavailable("Email could not be queued, try again later")


# --------------------------------------------------------------------------- #
# passwords
# --------------------------------------------------------------------------- #
async def forgot_password(s: AsyncSession, redis: ArqRedis, email: str, settings: Settings) -> None:
    """D8: same outcome for every input; details only in logs/audit."""
    user = await s.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        log.info("auth.forgot_password_no_account", found=user is not None)
        audit.record(
            "auth.password_reset_requested",
            entity="user",
            entity_id=str(user.id) if user else None,
            diff={"email": email, "sent": False},
            result="denied",
        )
        return

    now = _now()
    # Only the newest link works: older unused ones are retired.
    await s.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw, digest = new_token()
    s.add(PasswordResetToken(user_id=user.id, token_hash=digest, expires_at=now + RESET_TOKEN_TTL))
    await s.commit()

    link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={raw}"
    job_id = await mail.queue_email(
        redis,
        "reset_password",
        user.email,
        {
            "link": link,
            "full_name": user.full_name,
            "expires_minutes": int(RESET_TOKEN_TTL.total_seconds() // 60),
        },
    )
    audit.record(
        "auth.password_reset_requested",
        entity="user",
        entity_id=str(user.id),
        actor=str(user.id),
        diff={"email": email, "sent": job_id is not None},
        result="ok" if job_id else "error",
    )


async def reset_password(s: AsyncSession, raw: str, new_password: str) -> None:
    _check_strength(new_password)
    now = _now()
    row = await s.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(raw),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    user = await s.get(User, row.user_id) if row else None
    if row is None or user is None or not user.is_active:
        log.info("auth.reset_token_invalid")
        raise BadRequest(INVALID_TOKEN)

    row.used_at = now
    user.password_hash = hash_password(new_password)
    user.is_verified = True  # D3: the reset link proved ownership of the address
    revoked = await revoke_user_sessions(s, user.id)  # D5: sign out everywhere
    await s.commit()
    audit.record(
        "auth.password_reset",
        entity="user",
        entity_id=str(user.id),
        actor=str(user.id),
        diff={"revoked_tokens": revoked},
        sensitive=True,
    )
    log.info("auth.password_reset", user_id=str(user.id), revoked=revoked)


async def change_password(
    s: AsyncSession, user: User, keep_family: uuid.UUID, current: str, new: str
) -> None:
    if not verify_password(current, user.password_hash):
        # 400, not 401: a 401 would make the frontend try a silent refresh.
        audit.record(
            "auth.password_changed",
            entity="user",
            entity_id=str(user.id),
            actor=str(user.id),
            diff={"reason": "bad_current_password"},
            result="denied",
        )
        raise BadRequest("Current password is incorrect")
    _check_strength(new)
    if verify_password(new, user.password_hash):
        raise ValidationFailed(
            "new password must differ from the current one",
            fields=[{"loc": ["body", "new_password"], "msg": "unchanged", "type": "same_password"}],
        )
    user.password_hash = hash_password(new)
    revoked = await revoke_user_sessions(s, user.id, except_family=keep_family)  # D5
    await s.commit()
    audit.record(
        "auth.password_changed",
        entity="user",
        entity_id=str(user.id),
        actor=str(user.id),
        diff={"revoked_tokens": revoked},
        sensitive=True,
    )
    log.info("auth.password_changed", user_id=str(user.id), revoked_other_sessions=revoked)
