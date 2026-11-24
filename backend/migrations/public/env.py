"""Alembic environment: PUBLIC track (shared schema).

Two ways in:
1. Programmatic (normal): app.core.migrations passes an open SYNC connection
   in config.attributes["connection"] (obtained via AsyncConnection.run_sync),
   so migrations run inside the caller's event loop and transaction.
2. Command line (`alembic -n public ...`): builds its own async engine from
   DATABASE_URL and runs via asyncio.run.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models import public  # noqa: F401  (registers tables on PublicBase.metadata)
from app.models.base import PUBLIC_SCHEMA, PublicBase

VERSION_TABLE = "alembic_version_public"
target_metadata = PublicBase.metadata


def _include_object(obj, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    # Only ever compare/emit objects of the public track: tenant schemas and
    # the other track's version table are not ours.
    if type_ == "table" and name in {"alembic_version_public", "alembic_version_tenant"}:
        return False
    return True


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        version_table_schema=PUBLIC_SCHEMA,
        include_schemas=False,
        include_object=_include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run() -> None:
    if context.is_offline_mode():
        raise SystemExit("offline (SQL script) mode is not supported for this project")
    connection = context.config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
    else:
        asyncio.run(_run_async())


run()
