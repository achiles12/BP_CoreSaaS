"""T6 database sessions, T7 readiness (integration: real containers)."""

import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

from app.config import Settings
from app.core import db
from app.main import create_app

pytestmark = pytest.mark.integration


# ---------------------------------- T6 ------------------------------------- #
@pytest.fixture
async def engine(pg_container: PostgresContainer) -> AsyncIterator[None]:
    db.init_engine(pg_container.get_connection_url())
    async with db.get_engine().begin() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS t6 (v int)"))
        await conn.execute(text("TRUNCATE t6"))
    yield
    await db.dispose_engine()  # never leak this loop's engine into TestClient tests


async def _count() -> int:
    async with db.get_engine().connect() as conn:
        return (await conn.execute(text("SELECT count(*) FROM t6"))).scalar_one()


async def test_ping(engine: None) -> None:
    await db.ping()


async def test_session_commits_on_success(engine: None) -> None:
    gen = db.get_session()
    session = await anext(gen)
    await session.execute(text("INSERT INTO t6 VALUES (1)"))
    with pytest.raises(StopAsyncIteration):
        await anext(gen)  # normal exit -> commit
    assert await _count() == 1


async def test_session_rolls_back_on_exception(engine: None) -> None:
    gen = cast(AsyncGenerator[AsyncSession], db.get_session())  # athrow needs Generator type
    session = await anext(gen)
    await session.execute(text("INSERT INTO t6 VALUES (2)"))
    with pytest.raises(ValueError):
        await gen.athrow(ValueError("handler failed"))  # what FastAPI does on error
    assert await _count() == 0


async def test_search_path_reset_on_checkin(engine: None) -> None:
    eng = db.get_engine()
    async with eng.connect() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS leak_test"))
        await conn.execute(text("SET search_path TO leak_test"))
        await conn.commit()
        pid = (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()
    # Checked in; the next checkout must get a clean search_path. Loop until
    # we provably reuse the same backend connection.
    for _ in range(10):
        async with eng.connect() as conn:
            if (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one() == pid:
                path = (await conn.execute(text("SHOW search_path"))).scalar_one()
                assert "leak_test" not in path
                assert path == '"$user", public'
                return
    pytest.fail("pooled connection was not reused; cannot verify reset")


# ---------------------------------- T7 ------------------------------------- #
def _ready(settings: Settings) -> tuple[int, dict, float]:
    with TestClient(create_app(settings)) as c:
        started = time.monotonic()
        resp = c.get("/health/ready")
        return resp.status_code, resp.json(), time.monotonic() - started


def test_ready_all_ok(integration_settings: Settings) -> None:
    status, body, _ = _ready(integration_settings)
    assert status == 200, body
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"postgres", "redis", "storage"}
    assert all(c["ok"] and c["error"] is None for c in body["checks"].values())


def test_ready_redis_unreachable(integration_settings: Settings) -> None:
    s = integration_settings.model_copy(update={"redis_url": "redis://127.0.0.1:1/0"})
    status, body, _ = _ready(s)
    assert status == 503 and body["status"] == "fail"
    assert body["checks"]["redis"]["ok"] is False and body["checks"]["redis"]["error"]
    assert body["checks"]["postgres"]["ok"] and body["checks"]["storage"]["ok"]


def test_ready_bucket_missing(integration_settings: Settings) -> None:
    s = integration_settings.model_copy(update={"s3_bucket": "no-such-bucket"})
    status, body, _ = _ready(s)
    assert status == 503
    assert body["checks"]["storage"]["ok"] is False
    assert body["checks"]["postgres"]["ok"] and body["checks"]["redis"]["ok"]


def test_ready_bad_storage_credentials(integration_settings: Settings) -> None:
    s = integration_settings.model_copy(update={"s3_secret_key": "wrong-secret"})
    status, body, _ = _ready(s)
    assert status == 503 and body["checks"]["storage"]["ok"] is False


def test_ready_hung_postgres_times_out(
    integration_settings: Settings, pg_container: PostgresContainer
) -> None:
    """A frozen (paused) Postgres must not hang the probe beyond the 2 s budget."""
    with TestClient(create_app(integration_settings)) as c:
        docker_c = pg_container.get_wrapped_container()
        docker_c.pause()
        try:
            started = time.monotonic()
            resp = c.get("/health/ready")
            elapsed = time.monotonic() - started
        finally:
            docker_c.unpause()
    body = resp.json()
    assert resp.status_code == 503
    assert body["checks"]["postgres"]["ok"] is False
    assert "timeout" in body["checks"]["postgres"]["error"]
    assert body["checks"]["redis"]["ok"] and body["checks"]["storage"]["ok"]
    assert elapsed < 3.5, f"probe took {elapsed:.1f}s"


def test_startup_fails_when_db_unreachable(
    integration_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4: retry, then refuse to start (delay shortened for the test)."""
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "DB_CONNECT_DELAY_S", 0.05)
    s = integration_settings.model_copy(
        update={"database_url": "postgresql+asyncpg://x:y@127.0.0.1:1/none"}
    )
    with pytest.raises(RuntimeError, match="database unreachable"), TestClient(create_app(s)):
        pass
