"""B03 integration: Redis fixed-window rate limiter (design B03 §3.4, D7)."""

import uuid

import pytest
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer

from app.core import ratelimit
from app.core.errors import RateLimited
from tests.conftest import redis_url

pytestmark = pytest.mark.integration


async def test_limit_then_429_with_retry_after(redis_container: RedisContainer) -> None:
    r = Redis.from_url(redis_url(redis_container))
    ident = f"1.2.3.4|{uuid.uuid4()}@x.test"
    try:
        for _ in range(5):
            await ratelimit.hit(r, "t", ident, limit=5, window_s=60)
        with pytest.raises(RateLimited) as exc:
            await ratelimit.hit(r, "t", ident, limit=5, window_s=60)
        assert exc.value.headers and 1 <= int(exc.value.headers["Retry-After"]) <= 60
        # Other identity / other bucket are independent.
        await ratelimit.hit(r, "t", ident + "x", limit=5)
        await ratelimit.hit(r, "other", ident, limit=5)
        # Raw email never appears in Redis keys (hashed).
        keys = [k.decode() async for k in r.scan_iter("rl:*")]
        assert keys and not any("@" in k for k in keys)
    finally:
        await r.aclose()


async def test_window_expires(redis_container: RedisContainer) -> None:
    r = Redis.from_url(redis_url(redis_container))
    ident = str(uuid.uuid4())
    try:
        await ratelimit.hit(r, "w", ident, limit=1, window_s=1)
        with pytest.raises(RateLimited):
            await ratelimit.hit(r, "w", ident, limit=1, window_s=1)
        # Simulate the window passing without sleeping.
        await r.delete(ratelimit._key("w", ident))
        await ratelimit.hit(r, "w", ident, limit=1, window_s=1)
    finally:
        await r.aclose()


async def test_check_and_count_only(redis_container: RedisContainer) -> None:
    """Login pattern: check() blocks, hit(enforce=False) only counts failures."""
    r = Redis.from_url(redis_url(redis_container))
    ident = str(uuid.uuid4())
    try:
        for _ in range(3):
            await ratelimit.check(r, "c", ident, limit=3)
            await ratelimit.hit(r, "c", ident, limit=3, enforce=False)
        with pytest.raises(RateLimited) as exc:
            await ratelimit.check(r, "c", ident, limit=3)
        assert exc.value.headers and int(exc.value.headers["Retry-After"]) >= 1
        await ratelimit.hit(r, "c", ident, limit=3, enforce=False)  # never raises
        await ratelimit.check(r, "c", "fresh-" + ident, limit=3)  # untouched ident passes
    finally:
        await r.aclose()


async def test_fails_open_when_redis_is_down() -> None:
    r = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)
    try:
        for _ in range(10):  # never raises, even far over the limit
            await ratelimit.hit(r, "down", "x", limit=1)
            await ratelimit.check(r, "down", "x", limit=1)
    finally:
        await r.aclose()
