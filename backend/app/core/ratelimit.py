"""Fixed-window rate limiter on Redis (design B03 §3.4, D7).

Why not slowapi (named in system_design §3): slowapi derives its key from the
Request object only, but the auth limit is per IP **and email**, and the email
lives in the JSON body. A 20-line INCR/EXPIRE counter covers the need.

Behaviour:
- key  rl:<bucket>:<sha256(ident)[:24]>   (ident hashed: no emails in Redis keys)
- INCR; on the first hit set EXPIRE window_s; over `limit` -> 429 + Retry-After.
- Redis unavailable -> log a warning and ALLOW the request (fail open): an
  outage of the limiter must not lock every user out of login.
- Login counts FAILED attempts only (backend_processes.md §8): `check()`
  before the attempt, `hit(enforce=False)` after a failure. A user who logs in
  successfully many times is never blocked.
"""

import hashlib

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import RateLimited

log = structlog.get_logger("app.ratelimit")

KEY_PREFIX = "rl"


def _key(bucket: str, ident: str) -> str:
    digest = hashlib.sha256(ident.encode()).hexdigest()[:24]
    return f"{KEY_PREFIX}:{bucket}:{digest}"


def _too_many(bucket: str, count: int, limit: int, ttl: int) -> RateLimited:
    log.info("ratelimit.exceeded", bucket=bucket, count=count, limit=limit)
    return RateLimited(
        "Too many attempts, try again later",
        headers={"Retry-After": str(max(int(ttl), 1))},
    )


async def check(redis: Redis, bucket: str, ident: str, limit: int) -> None:
    """Raise RateLimited if (bucket, ident) already used up `limit`; count nothing."""
    key = _key(bucket, ident)
    try:
        raw = await redis.get(key)
        count = int(raw) if raw else 0
        ttl = await redis.ttl(key) if count >= limit else 0
    except (RedisError, OSError) as exc:
        log.warning("ratelimit.redis_unavailable", bucket=bucket, error=str(exc))
        return  # fail open (D7)
    if count >= limit:
        raise _too_many(bucket, count, limit, ttl)


async def hit(
    redis: Redis,
    bucket: str,
    ident: str,
    limit: int,
    window_s: int = 60,
    *,
    enforce: bool = True,
) -> None:
    """Count one request for (bucket, ident); raise RateLimited when over `limit`.

    bucket:  endpoint family, e.g. "login", "forgot".
    ident:   what is limited, e.g. "<ip>|<email>".
    enforce: False = only count (login failures; `check()` does the blocking).
    """
    key = _key(bucket, ident)
    try:
        # One round trip: INCR + TTL. EXPIRE only when the key is new (count==1)
        # so the window is fixed from the first attempt, not sliding.
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = await pipe.execute()
        if count == 1 or ttl == -1:  # ttl -1: key exists without expiry (lost EXPIRE)
            await redis.expire(key, window_s)
            ttl = window_s
    except (RedisError, OSError) as exc:
        log.warning("ratelimit.redis_unavailable", bucket=bucket, error=str(exc))
        return  # fail open (D7)

    if enforce and count > limit:
        raise _too_many(bucket, count, limit, ttl)
