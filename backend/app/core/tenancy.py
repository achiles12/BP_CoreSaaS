"""Tenant resolution and schema binding (design B02 §3.4, system_design §2).

Security rules enforced here:
- The X-Tenant header is only ever used as a LOOKUP KEY (bound parameter).
  The schema name used for SQL comes from the organizations row.
- Unknown, inactive and not-a-member tenants produce the SAME NotFound, so a
  caller cannot probe which tenants exist (design D5).
- Tenant tables are reached only through tenant_session(), which maps the
  placeholder schema "tenant" to exactly one real schema per session.
"""

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import structlog
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import audit, db
from app.core.errors import BadRequest, NotFound
from app.models.base import TENANT_SCHEMA_PLACEHOLDER
from app.models.public import Organization, OrgMembership

log = structlog.get_logger("app.tenancy")

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
SCHEMA_PREFIX = "tenant_"
SCHEMA_PATTERN = re.compile(r"^tenant_[a-z][a-z0-9_]{2,30}$")
# Slugs that would be confusing or dangerous as tenant names / schema suffixes.
RESERVED_SLUGS = frozenset(
    {
        "public",
        "admin",
        "platform",
        "api",
        "www",
        "app",
        "system",
        "root",
        "postgres",
        "information_schema",
        "pg_catalog",
        "tenant",
        "default",
        "test",
    }
)
NOT_FOUND_MESSAGE = "Organization not found"


@dataclass(frozen=True)
class TenantContext:
    org_id: uuid.UUID
    slug: str
    name: str
    schema_name: str


def validate_slug(slug: str) -> str:
    """Normalise and validate a NEW slug (provisioning). Raises BadRequest."""
    s = (slug or "").strip().lower()
    if not SLUG_PATTERN.fullmatch(s):
        raise BadRequest(
            "slug must be 3-31 chars: a lowercase letter, then letters, digits or underscore"
        )
    if s in RESERVED_SLUGS:
        raise BadRequest(f"slug {s!r} is reserved")
    return s


def schema_for(slug: str) -> str:
    """Schema name for a validated slug. Only provisioning calls this."""
    return SCHEMA_PREFIX + validate_slug(slug)


def read_tenant_header(request: Request) -> str:
    """Raw X-Tenant value; 400 when absent on a tenant-scoped route."""
    header = get_settings().tenant_header
    value = request.headers.get(header)
    if not value:
        raise BadRequest(f"{header} header required")
    return value


async def resolve_tenant(
    session: AsyncSession, slug: str, *, user_id: uuid.UUID, is_platform_admin: bool = False
) -> TenantContext:
    """Map a header slug to an active tenant the user may access.

    `session` is a PUBLIC-schema session. Any failure raises the same
    NotFound (D5). Platform_Admin may enter without membership; audited (D6).
    """
    candidate = (slug or "").strip().lower()
    # A malformed value can never match a slug; reject before touching the DB
    # (and before it can reach a log line unescaped in a weird form).
    if not SLUG_PATTERN.fullmatch(candidate):
        log.info("tenancy.rejected", reason="malformed_slug")
        raise NotFound(NOT_FOUND_MESSAGE)

    org = await session.scalar(
        select(Organization).where(Organization.slug == candidate, Organization.status == "active")
    )
    if org is None:
        log.info("tenancy.rejected", reason="unknown_or_inactive", slug=candidate)
        raise NotFound(NOT_FOUND_MESSAGE)

    is_member = await session.scalar(
        select(OrgMembership.id).where(
            OrgMembership.org_id == org.id,
            OrgMembership.user_id == user_id,
            OrgMembership.status == "active",
        )
    )
    if is_member is None:
        if not is_platform_admin:
            log.info("tenancy.rejected", reason="not_member", slug=candidate, user_id=str(user_id))
            raise NotFound(NOT_FOUND_MESSAGE)
        # Platform_Admin bypass is allowed but always leaves a trace.
        audit.record(
            "tenancy.platform_admin_access",
            entity="organization",
            entity_id=str(org.id),
            org=org.slug,
            actor=str(user_id),
            sensitive=True,
        )

    return TenantContext(org_id=org.id, slug=org.slug, name=org.name, schema_name=org.schema_name)


@asynccontextmanager
async def tenant_session(target: TenantContext | str) -> AsyncIterator[AsyncSession]:
    """Session bound to ONE tenant schema via schema_translate_map.

    Accepts a TenantContext (request path) or a schema name taken from the
    organizations table (CLI, jobs). Commits on success, rolls back on error.
    The translate map lives on an engine *view* (execution_options), so it
    never changes the shared pool connections' state.
    """
    schema = target.schema_name if isinstance(target, TenantContext) else target
    if not SCHEMA_PATTERN.fullmatch(schema):
        # Defence in depth: a schema name reaches SQL text via the translate map.
        raise ValueError(f"refusing to bind invalid schema name {schema!r}")
    bound = db.get_engine().execution_options(
        schema_translate_map={TENANT_SCHEMA_PLACEHOLDER: schema}
    )
    async with AsyncSession(bind=bound, expire_on_commit=False) as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            log.info("tenancy.session_rolled_back", schema=schema)
            raise
