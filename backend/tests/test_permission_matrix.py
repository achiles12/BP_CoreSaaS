"""C3: permission matrix GENERATED from the app (B12 D2–D4).

For every route that depends on the tenant, the key its require() declares is
checked against each of the 5 tenant roles of the shared B04 world (acme4):
holding the key -> anything but 403; lacking it -> 403. Path ids are random
UUIDs and bodies are empty, so an allowed role gets 404/422 at worst and a
denied role must be stopped by the permission check before anything else.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.modules.rbac.seed import DEFAULT_GRANTS
from tests.b04_helpers import call, login
from tests.conftest import B04_ROLES, B04World
from tests.route_catalog import fill_path, tenant_routes

pytestmark = pytest.mark.integration
T = "acme4"

# Built once at import time from the module registry (the routers main.py mounts).
ROUTES = tenant_routes()


def test_catalog_sees_every_module() -> None:
    paths = {r.path for r in ROUTES}
    assert len(ROUTES) >= 30, len(ROUTES)
    for p in ("/users", "/files", "/items", "/search", "/exports", "/notifications", "/org"):
        assert p in paths, p


def test_every_tenant_route_requires_a_permission() -> None:
    """A tenant route without require() would be open to every member."""
    missing = [r.id for r in ROUTES if r.key is None]
    assert missing == [], f"tenant routes without require(): {missing}"


# api_spec.md "Perm" column for the core modules (checked 2026-11-20). The
# generated matrix proves each route ENFORCES what it declares; this table
# proves the declaration matches the spec (a route quietly weakened from
# items:delete to items:read passes the matrix but fails here). Routes of
# modules added later (key prefixes not listed in CORE_MODULES) are skipped,
# so a copied module needs no edit here.
SPEC_KEYS: dict[tuple[str, str], str] = {
    ("GET", "/exports"): "export:run",
    ("POST", "/exports"): "export:run",
    ("GET", "/exports/{export_id}"): "export:run",
    ("GET", "/files"): "files:read",
    ("POST", "/files/presign-upload"): "files:write",
    ("DELETE", "/files/{file_id}"): "files:delete",
    ("GET", "/files/{file_id}"): "files:read",
    ("POST", "/files/{file_id}/confirm"): "files:write",
    ("GET", "/files/{file_id}/download-url"): "files:read",
    ("GET", "/invitations"): "users:invite",
    ("DELETE", "/invitations/{invitation_id}"): "users:invite",
    ("GET", "/items"): "items:read",
    ("POST", "/items"): "items:write",
    ("DELETE", "/items/{item_id}"): "items:delete",
    ("GET", "/items/{item_id}"): "items:read",
    ("PATCH", "/items/{item_id}"): "items:write",
    ("GET", "/notifications"): "notifications:read",
    ("POST", "/notifications/read-all"): "notifications:read",
    ("POST", "/notifications/{notification_id}/read"): "notifications:read",
    ("GET", "/org"): "org:read",
    ("PATCH", "/org"): "org:update",
    ("GET", "/permissions"): "roles:read",
    ("GET", "/roles"): "roles:read",
    ("GET", "/search"): "search:use",
    ("GET", "/users"): "users:read",
    ("POST", "/users/invite"): "users:invite",
    ("GET", "/users/{user_id}"): "users:read",
    ("PATCH", "/users/{user_id}"): "users:update",
    ("POST", "/users/{user_id}/activate"): "users:deactivate",
    ("POST", "/users/{user_id}/deactivate"): "users:deactivate",
    ("PUT", "/users/{user_id}/roles"): "roles:assign",
}
CORE_MODULES = {k.split(":")[0] for k in SPEC_KEYS.values()}


def test_declared_keys_match_api_spec() -> None:
    declared = {(r.method, r.path): r.key for r in ROUTES}
    core = {k: v for k, v in declared.items() if (v or "").split(":")[0] in CORE_MODULES}
    assert core == SPEC_KEYS


@pytest.fixture(scope="module")
def client(b04_world: B04World, redis_container, tmp_path_factory) -> Iterator[TestClient]:  # noqa: ANN001
    from tests.conftest import redis_url

    settings = Settings(
        app_env="test",
        secret_key="b12-matrix-secret-key-0123456789abcdef",
        audit_log_dir=str(tmp_path_factory.mktemp("b12_matrix_audit")),
        database_url=b04_world.db_url,
        redis_url=redis_url(redis_container),
        frontend_url="http://fe.test",
    )
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(scope="module")
def tokens(client: TestClient, b04_world: B04World) -> dict[str, str]:
    return {role: login(client, b04_world.users[role]) for role in B04_ROLES}


CASES = [
    pytest.param(role, r, id=f"{role}-{r.method}-{r.path}") for r in ROUTES for role in B04_ROLES
]


@pytest.mark.parametrize(("role", "route"), CASES)
def test_matrix(client: TestClient, tokens: dict[str, str], role: str, route) -> None:  # noqa: ANN001
    allowed = route.key in DEFAULT_GRANTS[role]
    kw = {"json": {}} if route.method in ("POST", "PUT", "PATCH") else {}
    r = call(client, route.method, fill_path(route.path), tokens[role], T, **kw)
    if allowed:
        assert r.status_code != 403, f"{role} holds {route.key} but got 403: {r.text}"
    else:
        assert r.status_code == 403, f"{role} lacks {route.key} but got {r.status_code}"
        assert r.json()["error"]["code"] == "permission_denied"
