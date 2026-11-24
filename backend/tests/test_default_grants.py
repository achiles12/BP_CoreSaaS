"""B06 D1/D2: modules declare default grants; the derived matrix is unchanged.

The B02 matrix below is a literal copy of what rbac/seed.py hard-coded until
B06 (system_design.md §4). Moving it into the modules must not change it.
"""

import pytest

from app.core.permissions import PermissionDef, register
from app.modules.rbac.seed import SYSTEM_ROLES, default_grants

ALL = {"owner", "admin", "manager", "staff", "user"}
B02_MATRIX: dict[str, set[str]] = {
    "users:read": {"owner", "admin", "manager"},
    "users:invite": {"owner", "admin"},
    "users:update": {"owner", "admin"},
    "users:deactivate": {"owner", "admin"},
    "roles:read": {"owner", "admin", "manager"},
    "roles:assign": {"owner", "admin"},
    "org:read": ALL,
    "org:update": {"owner"},
    "files:read": ALL,
    "files:write": {"owner", "admin", "manager", "staff"},
    "files:delete": {"owner", "admin", "manager"},
    "search:use": ALL,
    "export:run": {"owner", "admin", "manager"},
    "notifications:read": ALL,
}
# B06 D12 (system_design.md §4 "items:* (template)")
ITEMS: dict[str, set[str]] = {
    "items:read": ALL,
    "items:write": {"owner", "admin", "manager", "staff"},
    "items:delete": {"owner", "admin"},
}


def _by_role(matrix: dict[str, set[str]]) -> dict[str, set[str]]:
    return {r: {k for k, roles in matrix.items() if r in roles} for r in ALL}


def test_derived_matrix_equals_b02_plus_items() -> None:
    got = {r: set(keys) for r, keys in default_grants().items()}
    assert got == _by_role({**B02_MATRIX, **ITEMS})
    assert all("platform:manage" not in keys for keys in got.values())


def test_system_roles_match_core_role_keys() -> None:
    assert {r.key for r in SYSTEM_ROLES} == ALL


def test_unknown_default_role_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown default roles"):
        register([PermissionDef("typo:read", "x", frozenset({"boss"}))])


# --------------------------------------------------------------------------- #
# sync-permissions grants defaults for NEW keys only (D1; plan review focus 4)
# --------------------------------------------------------------------------- #
@pytest.mark.integration
async def test_sync_grants_defaults_for_new_keys_only(b04_world, audit_log) -> None:  # noqa: ANN001
    from sqlalchemy import text

    from app.core import db
    from app.core.tenancy import tenant_session
    from app.modules.rbac.seed import sync_permissions

    s = "tenant_beta4"
    grants_sql = text(
        f"select r.key from {s}.role_permissions rp join {s}.roles r on r.id = rp.role_id "  # noqa: S608
        f"join {s}.permissions p on p.id = rp.permission_id where p.key = :k"
    )
    db.init_engine(b04_world.db_url)
    try:
        async with db.get_engine().begin() as c:
            # an operator removed files:read from user (an OLD key) ...
            await c.execute(
                text(
                    f"delete from {s}.role_permissions where "  # noqa: S608
                    f"role_id = (select id from {s}.roles where key='user') and "
                    f"permission_id = (select id from {s}.permissions where key='files:read')"
                )
            )
            # ... and search:use disappears, as if its module were new (grants cascade)
            await c.execute(text(f"delete from {s}.permissions where key='search:use'"))  # noqa: S608

        async with tenant_session(s) as ts:
            assert await sync_permissions(ts) == 1
        async with db.get_engine().connect() as c:
            assert {r[0] for r in await c.execute(grants_sql, {"k": "search:use"})} == ALL
            assert "user" not in {r[0] for r in await c.execute(grants_sql, {"k": "files:read"})}

        async with tenant_session(s) as ts:
            assert await sync_permissions(ts) == 0  # second run: nothing new, nothing granted
        async with db.get_engine().connect() as c:
            assert "user" not in {r[0] for r in await c.execute(grants_sql, {"k": "files:read"})}
    finally:
        async with db.get_engine().begin() as c:  # restore the shared world
            await c.execute(
                text(
                    f"insert into {s}.role_permissions (role_id, permission_id) "  # noqa: S608
                    f"select r.id, p.id from {s}.roles r, {s}.permissions p "
                    "where r.key='user' and p.key='files:read' on conflict do nothing"
                )
            )
        await db.dispose_engine()
