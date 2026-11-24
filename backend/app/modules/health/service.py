"""Readiness checks (design B01 §3.6, backend_processes §9).

Each check runs under CHECK_TIMEOUT_S so a hung dependency cannot hang the
probe (D6); all three run concurrently, so the probe takes ~max(check) time.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

import structlog
from redis.asyncio import Redis

from app.config import Settings
from app.core import db, storage
from app.modules.health.schemas import CheckResult, ReadyResponse

log = structlog.get_logger("app.health")

CHECK_TIMEOUT_S = 2.0


def _consume_result(task: "asyncio.Task[None]") -> None:
    """Retrieve a background check's outcome so asyncio never warns about it."""
    if not task.cancelled():
        task.exception()


async def _timed(name: str, fn: Callable[[], Awaitable[None]]) -> CheckResult:
    """Run one check with a HARD deadline; convert any failure into a CheckResult.

    asyncio.wait_for() is not enough: after the timeout it cancels the check
    and then WAITS for the cancellation to finish. With a frozen Postgres the
    driver's cleanup alone took ~2 s more (found by
    test_ready_hung_postgres_times_out). Here the probe answers at the
    deadline and the cancelled check winds down in the background.
    """
    started = time.perf_counter()
    task: asyncio.Task[None] = asyncio.ensure_future(fn())
    done, _ = await asyncio.wait({task}, timeout=CHECK_TIMEOUT_S)
    ms = round((time.perf_counter() - started) * 1000, 1)
    if not done:
        task.cancel()
        task.add_done_callback(_consume_result)
        error = f"timeout after {CHECK_TIMEOUT_S:g}s"
    else:
        exc = task.exception()
        if exc is None:
            return CheckResult(ok=True, ms=ms)
        # Type + first line only: enough to diagnose, never a full traceback
        # (and boto/asyncpg messages do not contain credentials).
        first = str(exc).splitlines()[0] if str(exc) else ""
        error = f"{type(exc).__name__}: {first}".strip()
    log.warning("health.check_failed", check=name, error=error, ms=ms)
    return CheckResult(ok=False, ms=ms, error=error)


async def check_postgres() -> None:
    await db.ping(timeout_s=CHECK_TIMEOUT_S)


def make_redis_check(client: Redis) -> Callable[[], Awaitable[None]]:
    async def check_redis() -> None:
        if not await client.ping():
            raise RuntimeError("PING returned false")

    return check_redis


def make_storage_check(settings: Settings) -> Callable[[], Awaitable[None]]:
    """Signed HeadBucket against RustFS (D7) through core.storage (B05: one storage resolver)."""

    async def check_storage() -> None:
        await storage.check_bucket(settings)

    return check_storage


async def readiness(redis_client: Redis, settings: Settings) -> ReadyResponse:
    """Run all checks concurrently and aggregate."""
    names = ("postgres", "redis", "storage")
    results = await asyncio.gather(
        _timed("postgres", check_postgres),
        _timed("redis", make_redis_check(redis_client)),
        _timed("storage", make_storage_check(settings)),
    )
    checks: dict[str, CheckResult] = dict(zip(names, results, strict=True))
    status = "ok" if all(c.ok for c in checks.values()) else "fail"
    return ReadyResponse(status=status, checks=checks)
