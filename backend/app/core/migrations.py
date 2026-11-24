"""Programmatic Alembic API (design B02 §3.3).

The CLI, provisioning and tests call these instead of shelling out to
`alembic`. Each call opens one transaction on the app engine and hands its
sync connection to the track's env.py (config.attributes["connection"]), so
migrations run inside the caller's event loop: no nested asyncio.run.
"""

from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core import db

log = structlog.get_logger("app.migrations")

# backend/alembic.ini, resolved from this file so the CWD does not matter.
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
PUBLIC_VERSION_TABLE = "alembic_version_public"
TENANT_VERSION_TABLE = "alembic_version_tenant"


def _config(track: str) -> Config:
    if not ALEMBIC_INI.is_file():
        raise RuntimeError(f"alembic.ini not found at {ALEMBIC_INI}")
    return Config(str(ALEMBIC_INI), ini_section=track)


def head_revision(track: str) -> str | None:
    return ScriptDirectory.from_config(_config(track)).get_current_head()


def _upgrade(sync_conn: Connection, track: str, schema: str | None) -> None:
    cfg = _config(track)
    cfg.attributes["connection"] = sync_conn
    if schema is not None:
        cfg.attributes["schema"] = schema
    command.upgrade(cfg, "head")


def _downgrade(sync_conn: Connection, track: str, schema: str | None, target: str) -> None:
    cfg = _config(track)
    cfg.attributes["connection"] = sync_conn
    if schema is not None:
        cfg.attributes["schema"] = schema
    command.downgrade(cfg, target)


def _current(sync_conn: Connection, version_table: str, schema: str) -> str | None:
    ctx = MigrationContext.configure(
        sync_conn, opts={"version_table": version_table, "version_table_schema": schema}
    )
    return ctx.get_current_revision()


async def upgrade_public() -> str | None:
    """Apply the public track up to head. Returns the head revision."""
    async with db.get_engine().begin() as conn:
        await conn.run_sync(_upgrade, "public", None)
    head = head_revision("public")
    log.info("migrations.public_upgraded", revision=head)
    return head


async def upgrade_tenant(schema: str) -> str | None:
    """Apply the tenant track to one schema (env.py validates the name)."""
    async with db.get_engine().begin() as conn:
        await conn.run_sync(_upgrade, "tenant", schema)
    head = head_revision("tenant")
    log.info("migrations.tenant_upgraded", schema=schema, revision=head)
    return head


async def downgrade_public(target: str = "base") -> None:
    """Tests only: roll the public track back (destroys shared data)."""
    async with db.get_engine().begin() as conn:
        await conn.run_sync(_downgrade, "public", None, target)


async def downgrade_tenant(schema: str, target: str = "base") -> None:
    """Tests only: roll one tenant schema back (destroys that tenant's data)."""
    async with db.get_engine().begin() as conn:
        await conn.run_sync(_downgrade, "tenant", schema, target)


async def current_public_revision() -> str | None:
    async with db.get_engine().connect() as conn:
        return await conn.run_sync(_current, PUBLIC_VERSION_TABLE, "public")


async def current_tenant_revision(schema: str) -> str | None:
    """Revision applied in `schema`, or None if the tenant track never ran there."""
    async with db.get_engine().connect() as conn:
        exists = await conn.scalar(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": schema, "t": TENANT_VERSION_TABLE},
        )
        if not exists:
            return None
        return await conn.run_sync(_current, TENANT_VERSION_TABLE, schema)
