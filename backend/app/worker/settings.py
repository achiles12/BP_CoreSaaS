"""arq worker settings (design B01 §3.8, B03 §3.7; object C03).

Uses the same Settings and JSON logging as the API. Jobs live in jobs.py:
`send_email` (J01, own retry schedule) and the daily crons
`cleanup_expired_tokens` (J03) and `cleanup_orphan_files` (J04). The worker
owns its own DB engine and audit writer.

Run: arq app.worker.settings.WorkerSettings
"""

from typing import Any

import structlog
from arq import cron, func
from arq.connections import RedisSettings

from app.config import get_settings
from app.core import audit, db
from app.core.logging import configure_logging
from app.worker.jobs import (
    SEND_EMAIL_MAX_TRIES,
    build_export,
    cleanup_expired_tokens,
    cleanup_exports,
    cleanup_orphan_files,
    ping,
    send_email,
)

_settings = get_settings()
configure_logging(_settings.log_level)
log = structlog.get_logger("app.worker")

# Passed to the CLI as `--custom-log-dict app.worker.settings.ARQ_LOG_CONFIG`.
# arq applies its logging config AFTER importing this module; its default adds
# a plain-text handler ("12:25:34: Starting worker ..."). This config adds no
# handler, so arq's records propagate to our JSON root handler instead.
ARQ_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {"arq": {"level": _settings.log_level, "handlers": [], "propagate": True}},
}


def _redis_settings(url: str) -> RedisSettings:
    """Parse REDIS_URL into arq settings, failing loudly on a malformed value.

    A bad URL would otherwise surface as an obscure connection error, so the
    worker exits at import time with a message naming the variable.
    """
    try:
        settings = RedisSettings.from_dsn(url)
    except Exception as exc:  # arq/urllib raise varied types for bad DSNs
        log.error("worker.invalid_redis_url", error=str(exc))
        raise SystemExit("invalid REDIS_URL") from exc
    log.info("worker.redis_config", host=settings.host, port=settings.port, db=settings.database)
    return settings


async def startup(ctx: dict[str, Any]) -> None:
    """Called once when the worker has connected to Redis.

    Fails fast (worker exits) if the audit dir is not writable, like the API.
    The DB engine is lazy: an outage only fails the cleanup job, not mail.
    """
    audit.init_audit(_settings.audit_log_dir, fail_closed=_settings.audit_fail_closed)
    db.init_engine(_settings.database_url)
    log.info("worker connected to redis and ready", env=_settings.app_env)


async def shutdown(ctx: dict[str, Any]) -> None:
    await db.dispose_engine()
    audit.close_audit()
    log.info("worker.stopped")


class WorkerSettings:
    """Discovered by the `arq` CLI by dotted path."""

    functions = [
        ping,
        func(send_email, max_tries=SEND_EMAIL_MAX_TRIES),
        cleanup_orphan_files,
        # D17: an export runs once; a failure is recorded on the job, not retried.
        func(build_export, max_tries=1),
    ]
    # Container TZ is UTC, so 03:00 UTC (backend_processes.md J03).
    # J04 at 03:30 UTC (backend_processes.md), after J03.
    cron_jobs = [
        cron(cleanup_expired_tokens, hour={3}, minute={0}, run_at_startup=False),
        cron(cleanup_orphan_files, hour={3}, minute={30}, run_at_startup=False),
        # B07 D2: export retention; the time is configurable (default 03:45 UTC).
        cron(
            cleanup_exports,
            hour={_settings.export_cleanup_hour},
            minute={_settings.export_cleanup_minute},
            run_at_startup=False,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _redis_settings(_settings.redis_url)
