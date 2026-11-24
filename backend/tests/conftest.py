"""Shared fixtures (design B01 D1: host-run pytest + testcontainers).

Unit tests need nothing external. Tests marked `integration` start throwaway
Postgres 16, Redis 7 and RustFS 1.0.5 containers ONCE per session (Docker
must be available to the host user). Run only unit tests with:
    uv run pytest -m "not integration"
"""

import logging
import time
import urllib.request
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import boto3
import pytest
import structlog
from botocore.config import Config as BotoConfig
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from app.config import Settings

# Same images as docker-compose.yml so tests exercise what dev/prod runs.
POSTGRES_IMAGE = "postgres:16-alpine"
REDIS_IMAGE = "redis:7-alpine"
RUSTFS_IMAGE = "rustfs/rustfs:1.0.5"
S3_KEY, S3_SECRET, S3_BUCKET = "testaccesskey", "testsecretkey-123", "test-bucket"


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    """Drop handlers bound to a previous test's captured stdout.

    configure_logging() attaches a StreamHandler to whatever sys.stdout is at
    that moment; under capsys that stream is closed after the test.
    """
    yield
    logging.getLogger().handlers = []
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture
def audit_dir(tmp_path: Path) -> Path:
    d = tmp_path / "audit"
    d.mkdir()
    return d


@pytest.fixture
def unit_settings(audit_dir: Path) -> Settings:
    """Settings for tests that never touch a real dependency."""
    return Settings(app_env="test", audit_log_dir=str(audit_dir))


# --------------------------------------------------------------------------- #
# Integration: containers (session scope, started lazily on first use)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer(REDIS_IMAGE) as r:
        yield r


def _wait_http_ok(url: str, timeout_s: float = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 (test-only http)
                if resp.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"{url} not healthy after {timeout_s}s")


@pytest.fixture(scope="session")
def rustfs_container() -> Iterator[DockerContainer]:
    c = (
        DockerContainer(RUSTFS_IMAGE)
        .with_env("RUSTFS_ACCESS_KEY", S3_KEY)
        .with_env("RUSTFS_SECRET_KEY", S3_SECRET)
        .with_env("RUSTFS_ADDRESS", ":9000")
        .with_exposed_ports(9000)
    )
    with c:
        endpoint = f"http://{c.get_container_host_ip()}:{c.get_exposed_port(9000)}"
        _wait_http_ok(f"{endpoint}/health")
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=S3_KEY,
            aws_secret_access_key=S3_SECRET,
            region_name="us-east-1",
            config=BotoConfig(s3={"addressing_style": "path"}),
        )
        s3.create_bucket(Bucket=S3_BUCKET)
        yield c


def rustfs_endpoint(c: DockerContainer) -> str:
    return f"http://{c.get_container_host_ip()}:{c.get_exposed_port(9000)}"


def redis_url(r: RedisContainer) -> str:
    return f"redis://{r.get_container_host_ip()}:{r.get_exposed_port(6379)}/0"


@pytest.fixture
def integration_settings(
    audit_dir: Path,
    pg_container: PostgresContainer,
    redis_container: RedisContainer,
    rustfs_container: DockerContainer,
) -> Settings:
    """Settings wired to the session containers."""
    return Settings(
        app_env="test",
        audit_log_dir=str(audit_dir),
        database_url=pg_container.get_connection_url(),
        redis_url=redis_url(redis_container),
        s3_endpoint=rustfs_endpoint(rustfs_container),
        s3_access_key=S3_KEY,
        s3_secret_key=S3_SECRET,
        s3_bucket=S3_BUCKET,
    )


# --------------------------------------------------------------------------- #
# B02: dedicated databases inside the session Postgres container
# --------------------------------------------------------------------------- #
async def create_database_async(pg: PostgresContainer, name: str) -> str:
    """CREATE DATABASE `name` (if missing) and return its asyncpg URL.

    Separate databases keep tracks/tests from seeing each other's tables
    (e.g. B01's scratch table t6 would show up as drift in public).
    """
    import asyncpg

    base = pg.get_connection_url()  # postgresql+asyncpg://user:pw@host:port/test
    conn = await asyncpg.connect(base.replace("postgresql+asyncpg", "postgresql"))
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
    return base.rsplit("/", 1)[0] + "/" + name


def create_database(pg: PostgresContainer, name: str) -> str:
    """Sync wrapper for session-scoped (non-async) fixtures."""
    import asyncio

    return asyncio.run(create_database_async(pg, name))


@pytest.fixture(scope="session")
def b02_db_url(pg_container: PostgresContainer) -> str:
    return create_database(pg_container, "b02")


@pytest.fixture
def audit_log(audit_dir: Path) -> Iterator[Path]:
    """Initialised audit writer (provisioning writes sensitive audit lines)."""
    from app.core import audit

    path = audit.init_audit(str(audit_dir), fail_closed=True)
    yield path
    audit.close_audit()


@pytest.fixture
async def migrated(b02_db_url: str, audit_log: Path) -> AsyncIterator[str]:
    """Engine on the b02 database with the public track at head."""
    from app.core import db, migrations

    db.init_engine(b02_db_url)
    await migrations.upgrade_public()
    yield b02_db_url
    await db.dispose_engine()


_slug_counter = iter(range(1, 10_000))


@pytest.fixture
def new_slug() -> Callable[[str], str]:
    """Unique slug factory: tests share one database, so names must not clash."""
    return lambda prefix="org": f"{prefix}_{next(_slug_counter):04d}"


# --------------------------------------------------------------------------- #
# B03: auth database (public track only) + app client
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def b03_db_url(pg_container: PostgresContainer) -> str:
    """Dedicated database with the public track migrated (users, tokens, orgs)."""
    import asyncio

    from app.core import db, migrations

    url = create_database(pg_container, "b03")

    async def _migrate() -> None:
        db.init_engine(url)
        try:
            await migrations.upgrade_public()
        finally:
            await db.dispose_engine()

    asyncio.run(_migrate())
    return url


@pytest.fixture
def b03_settings(audit_dir: Path, b03_db_url: str, redis_container: RedisContainer) -> Settings:
    return Settings(
        app_env="test",
        secret_key="b03-test-secret-key-0123456789abcdef",
        audit_log_dir=str(audit_dir),
        database_url=b03_db_url,
        redis_url=redis_url(redis_container),
        frontend_url="http://fe.test",
    )


# --------------------------------------------------------------------------- #
# B04: two provisioned tenants with one user per role
# --------------------------------------------------------------------------- #
B04_PW = "b04-test-pass-123"
B04_ROLES = ("owner", "admin", "manager", "staff", "user")


@dataclass(frozen=True)
class B04World:
    db_url: str
    tenant: str  # "acme4": one member per role
    other: str  # "beta4": its own owner only
    users: dict[str, str]  # role/kind -> email
    password: str = B04_PW


def b04_email(kind: str, slug: str = "acme4") -> str:
    return f"{kind}@{slug}.test"


async def _b04_add_member(
    conn,
    slug: str,
    email: str,
    role: str | None,
    *,  # noqa: ANN001
    verified: bool = True,
) -> uuid.UUID:
    """Insert user + membership (+ role) with plain SQL (asyncpg connection)."""
    from app.core.security import hash_password

    uid = await conn.fetchval(
        "insert into users (email, password_hash, full_name, is_verified) values ($1,$2,$3,$4) "
        "on conflict (email) do update set email=excluded.email returning id",
        email,
        hash_password(B04_PW),
        email.split("@")[0].title(),
        verified,
    )
    org_id = await conn.fetchval("select id from organizations where slug=$1", slug)
    await conn.execute(
        "insert into org_memberships (user_id, org_id) values ($1,$2) on conflict do nothing",
        uid,
        org_id,
    )
    if role:
        await conn.execute(
            f'insert into "tenant_{slug}".user_roles (user_id, role_id) '  # noqa: S608 (test slug)
            f'select $1, id from "tenant_{slug}".roles where key=$2 on conflict do nothing',
            uid,
            role,
        )
    return uid


@pytest.fixture(scope="session")
def b04_world(
    pg_container: PostgresContainer, tmp_path_factory: pytest.TempPathFactory
) -> B04World:
    import asyncio

    import asyncpg

    from app.core import audit, db, migrations
    from app.core.security import hash_password
    from app.modules.organizations.provisioning import provision_tenant

    url = create_database(pg_container, "b04")
    audit_tmp = tmp_path_factory.mktemp("b04_setup_audit")

    async def setup() -> dict[str, str]:
        audit.init_audit(str(audit_tmp))
        db.init_engine(url)
        try:
            await migrations.upgrade_public()
            for slug, name in (("acme4", "Acme Four"), ("beta4", "Beta Four")):
                await provision_tenant(
                    slug,
                    name,
                    b04_email("owner", slug),
                    owner_password=B04_PW,
                    actor="pytest",
                    frontend_url="http://fe.test",
                )
        finally:
            await db.dispose_engine()
            audit.close_audit()
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg", "postgresql"))
        try:
            users = {"owner": b04_email("owner"), "other_owner": b04_email("owner", "beta4")}
            for role in B04_ROLES[1:]:
                users[role] = b04_email(role)
                await _b04_add_member(conn, "acme4", users[role], role)
            users["unverified"] = b04_email("unverified")
            await _b04_add_member(conn, "acme4", users["unverified"], "staff", verified=False)
            users["platform"] = "root@platform4.test"
            await conn.execute(
                "insert into users (email, password_hash, is_verified, is_platform_admin) "
                "values ($1,$2,true,true) on conflict do nothing",
                users["platform"],
                hash_password(B04_PW),
            )
        finally:
            await conn.close()
        return users

    users = asyncio.run(setup())
    return B04World(db_url=url, tenant="acme4", other="beta4", users=users)


@pytest.fixture
def b04_settings(audit_dir: Path, b04_world: B04World, redis_container: RedisContainer) -> Settings:
    return Settings(
        app_env="test",
        secret_key="b04-test-secret-key-0123456789abcdef",
        audit_log_dir=str(audit_dir),
        database_url=b04_world.db_url,
        redis_url=redis_url(redis_container),
        frontend_url="http://fe.test",
    )


# --------------------------------------------------------------------------- #
# B05: the B04 world plus the session RustFS (files API, J04)
# --------------------------------------------------------------------------- #
@pytest.fixture
def b05_settings(b04_settings: Settings, rustfs_container: DockerContainer) -> Settings:
    ep = rustfs_endpoint(rustfs_container)
    return b04_settings.model_copy(
        update={
            "s3_endpoint": ep,
            # Tests reach RustFS at the same address the backend does.
            "s3_public_endpoint": ep,
            "s3_access_key": S3_KEY,
            "s3_secret_key": S3_SECRET,
            "s3_bucket": S3_BUCKET,
            "max_upload_mb": 1,  # small limit so the 413 test needs no big body
        }
    )
