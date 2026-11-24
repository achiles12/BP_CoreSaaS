"""Database engine and sessions (design B01 §3.4, object S02).

One async engine per process (asyncpg). B01 provides public-schema sessions;
B02 adds tenant binding with `schema_translate_map` on top of the same engine.
"""

import asyncio
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

log = structlog.get_logger("app.db")

# Deterministic constraint names (used by app/models/base.py) so migrations
# and the drift test see stable, readable names instead of generated ones.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

POOL_SIZE = 5
POOL_MAX_OVERFLOW = 10


# Module state, set by init_engine() from the app lifespan / worker startup.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _reset_search_path(dbapi_conn, _record) -> None:  # noqa: ANN001 (DBAPI types)
    """Pool checkin hook: never hand a tenant-bound connection to the next user.

    Tenancy uses schema_translate_map (no search_path change), but any raw
    `SET search_path` (migrations, CLI, a careless query) would otherwise leak
    to whoever gets this pooled connection next (system_design §13).
    """
    if dbapi_conn is None:
        # SQLAlchemy passes None for a connection that was invalidated (e.g.
        # a cancelled query); it is being discarded, nothing to reset.
        return
    try:
        # asyncpg's sync adapter exposes a DBAPI-style cursor.
        cur = dbapi_conn.cursor()
        cur.execute("RESET search_path")
        cur.close()
    except Exception:
        # A broken connection is discarded by the pool anyway; never block checkin.
        log.warning("db.reset_search_path_failed", exc_info=True)


def init_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Create the process-wide engine and session factory (idempotent per URL).

    Calling it again with a DIFFERENT URL while an engine exists is a bug
    (a leaked engine from an earlier failure would silently be reused), so it
    raises instead of returning the old engine.
    """
    global _engine, _session_factory
    if _engine is not None:
        if _engine.url.render_as_string(hide_password=False) != url:
            raise RuntimeError(
                "init_engine called with a different URL while an engine exists; "
                "call dispose_engine() first"
            )
        return _engine
    _engine = create_async_engine(
        url,
        echo=echo,
        pool_pre_ping=True,  # drop connections killed by a Postgres restart
        pool_size=POOL_SIZE,
        max_overflow=POOL_MAX_OVERFLOW,
    )
    event.listen(_engine.sync_engine.pool, "checkin", _reset_search_path)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    # Log host/db only: the URL contains the password.
    log.info("db.engine_created", host=_engine.url.host, database=_engine.url.database)
    return _engine


async def dispose_engine() -> None:
    """Close all pooled connections (app shutdown, tests)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        log.info("db.engine_disposed")
    _engine, _session_factory = None, None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("database engine not initialised; call init_engine() first")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("database engine not initialised; call init_engine() first")
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, public schema.

    Commits when the handler returns normally, rolls back on any exception,
    always closes (returns the connection to the pool).
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            log.info("db.session_rolled_back")
            raise


async def ping(timeout_s: float = 2.0) -> None:
    """`SELECT 1` within a timeout. Raises on failure (startup, readiness)."""

    async def _q() -> None:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))

    await asyncio.wait_for(_q(), timeout=timeout_s)
