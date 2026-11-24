"""arq jobs (design B03 §3.7, B05 §3.5, B07 §3.5; backend_processes.md §1 J01–J04).

Jobs receive plain values only (never request state) and open their own DB
sessions. They are idempotent: re-running cleanup deletes nothing new, and a
retried send_email at worst delivers a duplicate email (acceptable for
verify/reset links, which stay single-use on the server).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from arq import Retry
from sqlalchemy import delete, or_

from app.config import get_settings
from app.core import audit, db, mail
from app.models.public import (
    EmailVerificationToken,
    Invitation,
    PasswordResetToken,
    RefreshToken,
)
from app.modules.exports.builder import run_export
from app.modules.exports.cleanup import expire_exports
from app.modules.files.cleanup import purge_orphan_files

log = structlog.get_logger("app.worker.jobs")

# B03 D12: wait 30 s, 2 min, 10 min between attempts -> 4 attempts in total.
RETRY_DELAYS_S = (30, 120, 600)
SEND_EMAIL_MAX_TRIES = len(RETRY_DELAYS_S) + 1


async def ping(ctx: dict[str, Any]) -> str:
    """Trivial job used to prove the queue round-trip works (B00)."""
    log.info("worker.ping", job_id=ctx.get("job_id"))
    return "pong"


async def send_email(
    ctx: dict[str, Any],
    template: str,
    to: str,
    context: dict[str, Any],
    org_slug: str | None = None,
) -> str:
    """J01: render + SMTP send, with the D12 retry schedule.

    Returns "sent", or "failed" after the last attempt / on a template error.
    Raises arq.Retry to schedule the next attempt.
    """
    settings = get_settings()
    job_try: int = ctx.get("job_try", 1)
    bound = log.bind(job_id=ctx.get("job_id"), template=template, to=to, attempt=job_try)

    try:
        rendered = mail.render(template, context, settings)
    except mail.TemplateError as exc:
        # A bad template will not fix itself: fail now, no retry.
        bound.error("mail.render_failed", error=str(exc))
        _audit_failure(template, to, org_slug, f"render: {exc}", job_try)
        return "failed"

    try:
        await mail.send(settings, to, rendered)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        if job_try < SEND_EMAIL_MAX_TRIES:
            delay = RETRY_DELAYS_S[job_try - 1]
            bound.warning("mail.send_retry", error=err, retry_in_s=delay)
            raise Retry(defer=delay) from exc
        bound.error("mail.send_failed", error=err)
        _audit_failure(template, to, org_slug, err, job_try)
        return "failed"

    bound.info("mail.job_done")
    return "sent"


def _audit_failure(template: str, to: str, org_slug: str | None, error: str, tries: int) -> None:
    # Not `sensitive`: the job must finish even if the audit file is broken
    # (the failure is already in the error log).
    audit.record(
        "email.failed",
        entity="email",
        org=org_slug,
        actor="worker",
        diff={"template": template, "to": to, "error": error[:500], "tries": tries},
        result="error",
    )


async def cleanup_expired_tokens(ctx: dict[str, Any]) -> dict[str, int]:
    """J03 (cron 03:00 UTC): delete dead tokens and expired invitations (D11).

    Refresh tokens are deleted only once EXPIRED: revoked-but-unexpired rows
    are what reuse detection matches a stolen token against.
    """
    now = datetime.now(UTC)
    counts: dict[str, int] = {}
    async with db.get_session_factory()() as s, s.begin():
        for name, model in (
            ("email_verification_tokens", EmailVerificationToken),
            ("password_reset_tokens", PasswordResetToken),
        ):
            res = await s.execute(
                delete(model).where(or_(model.expires_at < now, model.used_at.is_not(None)))
            )
            counts[name] = res.rowcount  # type: ignore[attr-defined]  # CursorResult
        res = await s.execute(delete(RefreshToken).where(RefreshToken.expires_at < now))
        counts["refresh_tokens"] = res.rowcount  # type: ignore[attr-defined]
        res = await s.execute(
            delete(Invitation).where(Invitation.expires_at < now, Invitation.accepted_at.is_(None))
        )
        counts["invitations"] = res.rowcount  # type: ignore[attr-defined]
    log.info("worker.cleanup_expired_tokens", job_id=ctx.get("job_id"), **counts)
    return counts


async def cleanup_orphan_files(
    ctx: dict[str, Any], org_slug: str | None = None
) -> dict[str, dict[str, int]]:
    """J04 (cron 03:30 UTC): purge deleted and abandoned uploads (design B05 D12).

    The logic lives in modules/files/cleanup.py so the CLI can run it too.
    """
    result = await purge_orphan_files(get_settings(), org_slug)
    log.info("worker.cleanup_orphan_files", job_id=ctx.get("job_id"), tenants=len(result))
    return result


async def build_export(ctx: dict[str, Any], export_id: str, org_slug: str) -> str:
    """J02: build one export file (design B07 §3.5). Runs once (max_tries=1, D17).

    The logic lives in modules/exports/builder.py; it records every outcome on
    the job row, so this wrapper only logs.
    """
    status = await run_export(get_settings(), org_slug, uuid.UUID(export_id))
    log.info("worker.build_export", job_id=ctx.get("job_id"), export_id=export_id, status=status)
    return status


async def cleanup_exports(ctx: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Export retention (B07 D2, D17): expire old export files, fail stuck jobs.

    Cron at EXPORT_CLEANUP_HOUR:EXPORT_CLEANUP_MINUTE UTC (default 03:45).
    """
    result = await expire_exports(get_settings())
    log.info("worker.cleanup_exports", job_id=ctx.get("job_id"), tenants=len(result))
    return result
