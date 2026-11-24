"""T1 public track, T2 tenant track, T3 drift (design B02 §5, D3, D4)."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import BLANK_SCHEMA, MetaData, inspect, text
from sqlalchemy.engine import Connection
from testcontainers.postgres import PostgresContainer

from app.core import db, migrations
from app.core.db import NAMING_CONVENTION
from app.models import public as _public  # noqa: F401  (register tables)
from app.models import tenant as _tenant  # noqa: F401
from app.models.base import PublicBase, TenantBase
from app.modules import registry
from tests.conftest import create_database_async

pytestmark = pytest.mark.integration

PUBLIC_TABLES = {
    "users",
    "organizations",
    "org_memberships",
    "refresh_tokens",
    "invitations",
    "email_verification_tokens",
    "password_reset_tokens",
    "alembic_version_public",
}
TENANT_TABLES = {
    "_template_items",
    "export_jobs",
    "notifications",
    "files",
    "roles",
    "permissions",
    "role_permissions",
    "user_roles",
    "settings",
    "alembic_version_tenant",
}

# Head of the public track; bump when a public revision is added (B04: 0002).
PUBLIC_HEAD = "0002_one_org_per_user"
# Head of the tenant track (B07: 0004).
TENANT_HEAD = "0004_exports_notifications"


async def _tables(schema: str) -> set[str]:
    async with db.get_engine().connect() as c:
        rows = await c.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"),
            {"s": schema},
        )
        return {r[0] for r in rows}


async def _create_schema(name: str) -> None:
    async with db.get_engine().begin() as c:
        await c.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{name}"'))


# ---------------------------------- T1 ------------------------------------- #
async def test_public_upgrade_downgrade_upgrade(pg_container: PostgresContainer) -> None:
    url = await create_database_async(pg_container, "t1_cycle")  # private DB: we destroy it
    db.init_engine(url)
    try:
        assert await migrations.upgrade_public() == PUBLIC_HEAD
        assert await _tables("public") == PUBLIC_TABLES
        assert await migrations.current_public_revision() == PUBLIC_HEAD
        await migrations.downgrade_public("base")
        assert await _tables("public") == {"alembic_version_public"}
        assert await migrations.current_public_revision() is None
        await migrations.upgrade_public()
        assert await _tables("public") == PUBLIC_TABLES
        await migrations.upgrade_public()  # at head: no-op, no error
    finally:
        await db.dispose_engine()


BAD_SLUG_SQL = "INSERT INTO organizations (name, slug, schema_name) VALUES ('x', 'Bad-Slug', 's1')"
BAD_STATUS_SQL = (
    "INSERT INTO organizations (name, slug, schema_name, status) "
    + "VALUES ('x', 'okslug', 's2', 'weird')"
)


async def test_public_constraints_enforced(migrated: str) -> None:
    async with db.get_engine().connect() as c:
        with pytest.raises(Exception, match="ck_organizations_slug_format"):
            await c.execute(text(BAD_SLUG_SQL))
        await c.rollback()
        with pytest.raises(Exception, match="ck_organizations_status"):
            await c.execute(text(BAD_STATUS_SQL))


# ---------------------------------- T2 ------------------------------------- #
async def test_tenant_track_lands_in_its_schema_only(migrated: str) -> None:
    await _create_schema("tenant_t2a")
    await _create_schema("tenant_t2b")
    await migrations.upgrade_tenant("tenant_t2a")
    assert await _tables("tenant_t2a") == TENANT_TABLES
    assert await _tables("tenant_t2b") == set()  # independent
    assert "roles" not in await _tables("public")  # nothing leaked into public
    assert await migrations.current_tenant_revision("tenant_t2a") == TENANT_HEAD
    assert await migrations.current_tenant_revision("tenant_t2b") is None
    await migrations.upgrade_tenant("tenant_t2b")
    assert await _tables("tenant_t2b") == TENANT_TABLES


async def test_tenant_migration_does_not_leak_search_path(migrated: str) -> None:
    await _create_schema("tenant_t2c")
    await migrations.upgrade_tenant("tenant_t2c")
    async with db.get_engine().connect() as c:
        assert await c.scalar(text("SHOW search_path")) == '"$user", public'


@pytest.mark.parametrize(
    "bad", ["public", "tenant_", "tenant_A", 'tenant_x"; DROP SCHEMA public; --', "acme"]
)
async def test_tenant_env_refuses_bad_schema(migrated: str, bad: str) -> None:
    with pytest.raises(SystemExit, match="valid -x schema"):
        await migrations.upgrade_tenant(bad)
    assert "users" in await _tables("public")


# ---------------------------------- T3 ------------------------------------- #
def _cancel_default_schema_fk_noise(diffs: list) -> list:
    """Drop remove_fk/add_fk pairs that differ ONLY by an explicit 'public.' prefix.

    Alembic reflects FKs that point into the default schema without a schema,
    while our models name `public` explicitly. Same name, same columns, same
    target table => not drift.
    """

    def key(fk) -> tuple:  # noqa: ANN001
        return (
            fk.name,
            tuple(c.name for c in fk.columns),
            fk.elements[0].target_fullname.removeprefix("public."),
            fk.ondelete,
        )

    removed = {key(d[1]) for d in diffs if isinstance(d, tuple) and d[0] == "remove_fk"}
    added = {key(d[1]) for d in diffs if isinstance(d, tuple) and d[0] == "add_fk"}
    noise = removed & added
    return [
        d
        for d in diffs
        if not (isinstance(d, tuple) and d[0] in {"remove_fk", "add_fk"} and key(d[1]) in noise)
    ]


def _diff(conn: Connection, metadata: MetaData, skip_schema: str | None = None) -> list:
    ctx = MigrationContext.configure(
        conn,
        opts={
            "compare_type": True,
            "compare_server_default": True,
            # Skip version tables, and any public table when comparing a tenant
            # schema (public.users is only present as a foreign-key target).
            "include_object": lambda o, n, t, r, c: (
                not (
                    t == "table"
                    and (
                        n.startswith("alembic_version") or getattr(o, "schema", None) == skip_schema
                    )
                )
            ),
        },
    )
    return _cancel_default_schema_fk_noise(compare_metadata(ctx, metadata))


def _checks(conn: Connection, schema: str | None, tables: list[str]) -> set[tuple[str, str | None]]:
    insp = inspect(conn)
    return {(t, c["name"]) for t in tables for c in insp.get_check_constraints(t, schema=schema)}


async def test_public_schema_matches_models(migrated: str) -> None:
    async with db.get_engine().connect() as c:
        diffs = await c.run_sync(_diff, PublicBase.metadata)
        assert diffs == [], f"public drift: {diffs}"
        # Alembic does not compare CHECK constraints: compare names ourselves.
        db_checks = await c.run_sync(_checks, "public", ["organizations", "org_memberships"])
    model_checks = {
        (t.name, ck.name)
        for t in PublicBase.metadata.sorted_tables
        for ck in t.constraints
        if ck.__class__.__name__ == "CheckConstraint"
    }
    assert db_checks == model_checks


async def test_tenant_schema_matches_models(migrated: str) -> None:
    await _create_schema("tenant_t3x")
    await migrations.upgrade_tenant("tenant_t3x")
    # Models use the placeholder schema "tenant"; compare a copy with no
    # schema against a connection whose default schema IS tenant_t3.
    meta = MetaData(naming_convention=NAMING_CONVENTION)
    PublicBase.metadata.tables["public.users"].to_metadata(meta)  # FK target, schema public
    registry.load_models()  # module tables (B06 D4), e.g. _template_items
    for t in TenantBase.metadata.sorted_tables:
        # Rewrite FKs to sibling tenant tables (tenant.roles -> roles); keep public.users.
        t.to_metadata(
            meta,
            schema=None,  # pyright: ignore[reportArgumentType]  (None = no schema; works at runtime)
            # BLANK_SCHEMA = "no schema"; returning None would mean "keep 'tenant'".
            referred_schema_fn=lambda _t, _to, _c, ref: BLANK_SCHEMA if ref == "tenant" else ref,  # pyright: ignore[reportArgumentType]
        )
    async with db.get_engine().begin() as c:
        await c.execute(text('SET LOCAL search_path TO "tenant_t3x"'))
        diffs = await c.run_sync(_diff, meta, "public")
    assert diffs == [], f"tenant drift: {diffs}"


async def test_one_org_per_user_migration_refuses_duplicates(
    pg_container: PostgresContainer,
) -> None:
    """B04 D1: 0002 stops with a readable error if a user already has 2 memberships."""
    url = await create_database_async(pg_container, "t_0002_dupes")
    db.init_engine(url)
    try:
        await migrations.upgrade_public()
        await migrations.downgrade_public("0001_public_initial")
        async with db.get_engine().begin() as c:
            await c.execute(text("DELETE FROM org_memberships"))
            uid = (
                await c.execute(
                    text(
                        "INSERT INTO users (email, password_hash) VALUES ('dup@x.test', 'x') "
                        "RETURNING id"
                    )
                )
            ).scalar_one()
            for slug in ("dupa", "dupb"):
                oid = (
                    await c.execute(
                        text(
                            "INSERT INTO organizations (name, slug, schema_name) "
                            "VALUES (:n, :s, :schema) RETURNING id"
                        ),
                        {"n": slug, "s": slug, "schema": f"tenant_{slug}"},
                    )
                ).scalar_one()
                await c.execute(
                    text("INSERT INTO org_memberships (user_id, org_id) VALUES (:u, :o)"),
                    {"u": uid, "o": oid},
                )
        with pytest.raises(Exception, match="dup@x.test"):
            await migrations.upgrade_public()
        assert await migrations.current_public_revision() == "0001_public_initial"
    finally:
        await db.dispose_engine()


# ---------------------------------- B05 ------------------------------------ #
async def test_files_table_indexes_checks_and_search_vector(migrated: str) -> None:
    await _create_schema("tenant_b5f")
    await migrations.upgrade_tenant("tenant_b5f")
    async with db.get_engine().begin() as c:
        idx = {
            r[0]: r[1]
            for r in await c.execute(
                text("select indexname, indexdef from pg_indexes where schemaname='tenant_b5f'")
            )
        }
        assert "USING gin (search_vector)" in idx["ix_files_search_vector"]
        assert "USING gin (name gin_trgm_ops)" in idx["ix_files_name_trgm"]
        assert "(status, created_at DESC)" in idx["ix_files_status_created_at"]
        assert "(uploaded_by, created_at DESC)" in idx["ix_files_uploaded_by_created_at"]
        uid = await c.scalar(
            text(
                "insert into public.users (email, password_hash) "
                "values ('f@b5.test','x') returning id"
            )
        )
        ins = (
            "insert into tenant_b5f.files "
            "(name, mime_type, size_bytes, object_key, uploaded_by, status) "
            "values (:n, 'text/plain', :sz, :k, :u, :st)"
        )
        await c.execute(
            text(ins), {"n": "Annual Report", "sz": 5, "k": "k1", "u": uid, "st": "pending"}
        )
        hit = await c.scalar(
            text(
                "select count(*) from tenant_b5f.files "
                "where search_vector @@ to_tsquery('simple','annual')"
            )
        )
        assert hit == 1
    for bad, ck in (
        ({"sz": 5, "st": "bogus"}, "ck_files_status"),
        ({"sz": 0, "st": "active"}, "ck_files_size_bytes_positive"),
    ):
        async with db.get_engine().begin() as c:
            with pytest.raises(Exception, match=ck):
                await c.execute(text(ins), {"n": "x", "k": f"k-{ck}", "u": uid, **bad})
    await migrations.downgrade_tenant("tenant_b5f", "0001_tenant_initial")
    assert "files" not in await _tables("tenant_b5f")


async def test_b07_tables_indexes_and_checks(migrated: str) -> None:
    """B07 §3.1: notifications + export_jobs, their indexes and checks."""
    await _create_schema("tenant_b7t")
    await migrations.upgrade_tenant("tenant_b7t")
    async with db.get_engine().begin() as c:
        idx = {
            r[0]: r[1]
            for r in await c.execute(
                text("select indexname, indexdef from pg_indexes where schemaname='tenant_b7t'")
            )
        }
        assert "(user_id, read_at, created_at DESC)" in idx["ix_notifications_user_read_created"]
        assert "(requested_by, created_at DESC)" in idx["ix_export_jobs_requested_by_created_at"]
        assert "(status, finished_at)" in idx["ix_export_jobs_status_finished_at"]
        uid = await c.scalar(
            text(
                "insert into public.users (email, password_hash) "
                "values ('n@b7.test','x') returning id"
            )
        )
        await c.execute(
            text("insert into tenant_b7t.notifications (user_id, type, title) values (:u,'t','T')"),
            {"u": uid},
        )
        assert await c.scalar(text("select data::text from tenant_b7t.notifications")) == "{}"
        ins = "insert into tenant_b7t.export_jobs (requested_by, resource, format, status) "
        await c.execute(text(ins + "values (:u, 'items', 'csv', default)"), {"u": uid})
        assert await c.scalar(text("select status from tenant_b7t.export_jobs")) == "queued"
    for name, fmt, st in (("format", "pdf", "queued"), ("status", "csv", "bogus")):
        with pytest.raises(Exception, match=f"ck_export_jobs_{name}"):
            async with db.get_engine().begin() as c:
                await c.execute(
                    text(ins + "values (:u, 'items', :f, :s)"), {"u": uid, "f": fmt, "s": st}
                )
