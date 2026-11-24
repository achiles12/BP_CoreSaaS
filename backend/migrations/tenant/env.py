"""Alembic environment: TENANT track (one schema per organization).

The target schema arrives as `-x schema=tenant_<slug>` (command line) or
config.attributes["schema"] (programmatic, app.core.migrations).

Revisions are written WITHOUT a schema. This env sets
    SET LOCAL search_path TO "<schema>"
inside the migration transaction, so every CREATE lands in that schema, and
the version table alembic_version_tenant lives there too. SET LOCAL ends with
the transaction, so nothing leaks into pooled connections (design B02 D3).
Cross-schema references are written explicitly as public.users.
"""

import asyncio
import re

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

VERSION_TABLE = "alembic_version_tenant"
# Same rule as core.tenancy (duplicated on purpose: env.py must refuse a bad
# name even when invoked directly from the command line).
SCHEMA_RE = re.compile(r"^tenant_[a-z][a-z0-9_]{2,30}$")


def _schema() -> str:
    schema = context.config.attributes.get("schema") or context.get_x_argument(
        as_dictionary=True
    ).get("schema")
    if not schema or not SCHEMA_RE.fullmatch(schema):
        # Interpolated into SQL below, so it MUST be validated first.
        raise SystemExit(f"tenant migrations need a valid -x schema=tenant_<slug>, got {schema!r}")
    return schema


def do_run_migrations(connection: Connection, schema: str) -> None:
    # Quoted identifier, validated above; parameters cannot be used for identifiers.
    connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    context.configure(
        connection=connection,
        target_metadata=None,  # tenant revisions are hand-written; drift is checked by tests
        version_table=VERSION_TABLE,
        version_table_schema=schema,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async(schema: str) -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations, schema)
    await engine.dispose()


def run() -> None:
    if context.is_offline_mode():
        raise SystemExit("offline (SQL script) mode is not supported for this project")
    schema = _schema()
    connection = context.config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection, schema)
    else:
        asyncio.run(_run_async(schema))


run()
