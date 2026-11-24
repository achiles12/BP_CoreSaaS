"""Auth HTTP endpoints (design B03 §3.8, api_spec.md §2).

Routers only parse requests, apply the rate limit and set/clear cookies; all
rules live in service.py. Paths have no /api prefix (Next.js strips it).
"""

from typing import Annotated

import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import ratelimit
from app.core.db import get_session
from app.core.errors import AppError, Unauthenticated, error_body
from app.core.security import (
    CurrentUser,
    access_cookie,
    clear_auth_cookies,
    current_user,
    decode_access_token,
    hash_token,
    refresh_cookie,
    request_settings,
    set_auth_cookies,
)
from app.modules.auth import service
from app.modules.auth.schemas import (
    ChangePasswordIn,
    EmailIn,
    LoginIn,
    LoginOut,
    MembershipOut,
    ResetPasswordIn,
    SessionOut,
    StatusOut,
    TokenIn,
    UserOut,
)
from app.modules.users import service as users_service
from app.modules.users.schemas import (
    AcceptedOut,
    AcceptInviteIn,
    InvitationInfoOut,
    InvitationTokenIn,
)

log = structlog.get_logger("app.auth.router")

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(request_settings)]
CallerDep = Annotated[CurrentUser, Depends(current_user)]


def _redis(request: Request) -> ArqRedis:
    """Shared lazy client: rate-limit counters + arq queue (B03 D13)."""
    return request.app.state.redis


RedisDep = Annotated[ArqRedis, Depends(_redis)]


def _client(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


async def _limit(request: Request, settings: Settings, bucket: str, ident: str) -> None:
    ip, _ = _client(request)
    await ratelimit.hit(
        _redis(request), bucket, f"{ip}|{ident}", settings.auth_rate_limit_per_minute
    )


# --------------------------------------------------------------------------- #
@router.post("/login", response_model=LoginOut)
async def login(
    body: LoginIn, request: Request, response: Response, s: SessionDep, settings: SettingsDep
) -> LoginOut:
    """Email + password -> session cookies. Generic 401 on any failure.

    Rate limit counts FAILED attempts per IP+email (backend_processes.md §8).
    """
    ip, ua = _client(request)
    ident = f"{ip}|{body.email}"
    limit = settings.auth_rate_limit_per_minute
    await ratelimit.check(_redis(request), "login", ident, limit)
    try:
        issued, memberships = await service.login(
            s, body.email, body.password, settings, ip=ip, user_agent=ua
        )
    except Unauthenticated:
        await ratelimit.hit(_redis(request), "login", ident, limit, enforce=False)
        raise
    set_auth_cookies(response, issued.access_token, issued.refresh_token, settings)
    return LoginOut(
        user=UserOut.model_validate(issued.user),
        memberships=[MembershipOut(org_id=m.org_id, slug=m.slug, name=m.name) for m in memberships],
    )


@router.post("/refresh", response_model=SessionOut)
async def refresh(
    request: Request, response: Response, s: SessionDep, settings: SettingsDep
) -> SessionOut | JSONResponse:
    """Rotate the refresh cookie. On failure the cookies are cleared too."""
    ip, ua = _client(request)
    try:
        issued = await service.refresh(
            s, request.cookies.get(refresh_cookie(settings)), settings, ip=ip, user_agent=ua
        )
    except Unauthenticated as exc:
        # Build the 401 here (not via the global handler) so it can carry the
        # cookie-clearing headers: a dead refresh cookie must not be resent.
        return _error_with_cleared_cookies(exc, settings)
    set_auth_cookies(response, issued.access_token, issued.refresh_token, settings)
    return SessionOut(user=UserOut.model_validate(issued.user))


def _error_with_cleared_cookies(exc: AppError, settings: Settings) -> JSONResponse:
    log.info("request.error", status=exc.status, code=exc.code, message=exc.message)
    resp = JSONResponse(error_body(exc.code, exc.message), status_code=exc.status)
    clear_auth_cookies(resp, settings)
    return resp


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, s: SessionDep, settings: SettingsDep) -> Response:
    """D6: works with an expired access token; always clears the cookies."""
    family = user_id = None
    access = request.cookies.get(access_cookie(settings))
    if access:
        try:
            claims = decode_access_token(access, settings)
            family, user_id = claims.family_id, claims.user_id
        except Unauthenticated:
            pass  # expired/garbled: fall back to the refresh cookie
    await service.logout(s, request.cookies.get(refresh_cookie(settings)), family, user_id)
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(resp, settings)
    return resp


# --------------------------------------------------------------------------- #
@router.post("/verify-email", response_model=StatusOut)
async def verify_email(body: TokenIn, s: SessionDep) -> StatusOut:
    await service.verify_email(s, body.token)
    return StatusOut(status="verified")


@router.post("/resend-verification", response_model=StatusOut, status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    request: Request, caller: CallerDep, s: SessionDep, redis: RedisDep, settings: SettingsDep
) -> StatusOut:
    await _limit(request, settings, "resend", caller.user.email)
    await service.resend_verification(s, redis, caller.user, settings)
    return StatusOut(status="accepted")


@router.post("/forgot-password", response_model=StatusOut, status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: EmailIn, request: Request, s: SessionDep, redis: RedisDep, settings: SettingsDep
) -> StatusOut:
    """Always 202 with the same body (D8)."""
    await _limit(request, settings, "forgot", body.email)
    await service.forgot_password(s, redis, body.email, settings)
    return StatusOut(status="accepted")


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordIn, request: Request, s: SessionDep, settings: SettingsDep
) -> Response:
    # Keyed on a token-hash prefix: limits guessing per token and per IP.
    await _limit(request, settings, "reset", hash_token(body.token)[:16])
    await service.reset_password(s, body.token, body.new_password)
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(resp, settings)  # every session was revoked, incl. this browser's
    return resp


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    caller: CallerDep,
    s: SessionDep,
    settings: SettingsDep,
) -> Response:
    await _limit(request, settings, "change", caller.user.email)
    await service.change_password(
        s, caller.user, caller.family_id, body.current_password, body.new_password
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# invitations (B04 D8-D10; the rules live in users/service.py)
# --------------------------------------------------------------------------- #
@router.post("/invitation", response_model=InvitationInfoOut)
async def invitation_info(
    body: InvitationTokenIn, request: Request, s: SessionDep, settings: SettingsDep
) -> InvitationInfoOut:
    """What the accept page shows before submitting (D9). 400 when invalid."""
    await _limit(request, settings, "invite", hash_token(body.token)[:16])
    inv, org, exists = await users_service.invitation_info(s, body.token)
    return InvitationInfoOut(
        email=inv.email, org_name=org.name, role_key=inv.role_key, existing_account=exists
    )


@router.post("/accept-invite", response_model=AcceptedOut)
async def accept_invite(
    body: AcceptInviteIn, request: Request, settings: SettingsDep
) -> AcceptedOut:
    """Create/attach the account and join the org. Does NOT log in (D10)."""
    await _limit(request, settings, "invite", hash_token(body.token)[:16])
    user = await users_service.accept_invitation(body.token, body.password, body.full_name)
    return AcceptedOut(status="accepted", email=user.email)
