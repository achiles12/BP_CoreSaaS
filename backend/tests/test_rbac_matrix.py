"""B04 C1/C3: /me per role and the permission matrix on every B04 endpoint.

Expected outcomes are GENERATED from rbac.seed.DEFAULT_GRANTS (the
system_design §4 matrix), so a grant change shows up here automatically.
Requests are chosen so an ALLOWED call never mutates shared state (unknown
ids -> 404, invalid role -> 422, unchanged org name -> 200).
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.modules.rbac.seed import DEFAULT_GRANTS, SYSTEM_ROLES
from tests.b04_helpers import call, login
from tests.conftest import B04_ROLES, B04World

pytestmark = pytest.mark.integration

LANDING = {r.key: r.landing_path for r in SYSTEM_ROLES}
GHOST = str(uuid.uuid4())


@pytest.fixture(scope="module")
def client_and_tokens(
    b04_world: B04World,
    redis_container,
    tmp_path_factory: pytest.TempPathFactory,  # noqa: ANN001
) -> Iterator[tuple[TestClient, dict[str, str]]]:
    from tests.conftest import redis_url

    settings = Settings(
        app_env="test",
        secret_key="b04-test-secret-key-0123456789abcdef",
        audit_log_dir=str(tmp_path_factory.mktemp("matrix_audit")),
        database_url=b04_world.db_url,
        redis_url=redis_url(redis_container),
        frontend_url="http://fe.test",
    )
    with TestClient(create_app(settings)) as c:
        tokens = {k: login(c, email) for k, email in b04_world.users.items()}
        yield c, tokens


# --------------------------------------------------------------------------- #
# /me (C1 backend part)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", B04_ROLES)
def test_me_per_role(client_and_tokens, b04_world: B04World, role: str) -> None:  # noqa: ANN001
    c, tokens = client_and_tokens
    for tenant in (None, b04_world.tenant):  # D4: same answer with or without X-Tenant
        r = call(c, "GET", "/me", tokens[role], tenant)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["roles"] == [role]
        assert me["landing_path"] == LANDING[role]
        assert set(me["permissions"]) == DEFAULT_GRANTS[role]
        assert me["org"]["slug"] == b04_world.tenant
        assert me["is_platform_admin"] is False


def test_me_platform_admin(client_and_tokens, b04_world: B04World) -> None:  # noqa: ANN001
    c, tokens = client_and_tokens
    me = call(c, "GET", "/me", tokens["platform"]).json()
    assert me["org"] is None and me["landing_path"] == "/platform"
    assert me["permissions"] == ["platform:manage"]
    inside = call(c, "GET", "/me", tokens["platform"], b04_world.tenant).json()  # D13
    assert inside["org"]["slug"] == b04_world.tenant and inside["landing_path"] == "/platform"
    assert set(DEFAULT_GRANTS["owner"]) | {"platform:manage"} <= set(inside["permissions"])


def test_me_unverified_still_works(client_and_tokens) -> None:  # noqa: ANN001
    c, tokens = client_and_tokens
    me = call(c, "GET", "/me", tokens["unverified"]).json()
    assert me["is_verified"] is False and me["landing_path"] == "/home/staff"  # D14


def test_me_requires_login(client_and_tokens) -> None:  # noqa: ANN001
    c, _ = client_and_tokens
    assert call(c, "GET", "/me", None).status_code == 401


# --------------------------------------------------------------------------- #
# C3: generated permission matrix
# --------------------------------------------------------------------------- #
# (method, path, required key, json body, status when ALLOWED)
ENDPOINTS = [
    ("GET", "/users", "users:read", None, 200),
    ("GET", f"/users/{GHOST}", "users:read", None, 404),
    ("PATCH", f"/users/{GHOST}", "users:update", {"full_name": "X"}, 404),
    ("POST", f"/users/{GHOST}/deactivate", "users:deactivate", None, 404),
    ("POST", f"/users/{GHOST}/activate", "users:deactivate", None, 404),
    ("POST", "/users/invite", "users:invite", {"email": "x@y.test", "role_key": "nope"}, 422),
    ("GET", "/invitations", "users:invite", None, 200),
    ("DELETE", f"/invitations/{GHOST}", "users:invite", None, 404),
    ("GET", "/roles", "roles:read", None, 200),
    ("GET", "/permissions", "roles:read", None, 200),
    ("PUT", f"/users/{GHOST}/roles", "roles:assign", {"role_keys": ["user"]}, 404),
    ("GET", "/org", "org:read", None, 200),
    ("PATCH", "/org", "org:update", {"name": "Acme Four"}, 200),  # unchanged: no-op
]
CASES = [
    pytest.param(role, *ep, id=f"{role}-{ep[0]}-{ep[1].replace(GHOST, 'id')}")
    for role in B04_ROLES
    for ep in ENDPOINTS
]


@pytest.mark.parametrize(("role", "method", "path", "key", "body", "allowed_status"), CASES)
def test_permission_matrix(
    client_and_tokens,
    b04_world: B04World,  # noqa: ANN001
    role: str,
    method: str,
    path: str,
    key: str,
    body: dict | None,
    allowed_status: int,
) -> None:
    c, tokens = client_and_tokens
    r = call(c, method, path, tokens[role], b04_world.tenant, json=body)
    if key in DEFAULT_GRANTS[role]:
        assert r.status_code == allowed_status, (role, path, r.text)
    else:
        assert r.status_code == 403, (role, path, r.text)
        assert r.json()["error"] == {
            **r.json()["error"],
            "code": "permission_denied",
            "message": f"Missing permission {key}",
        }


def test_unverified_member_blocked_from_tenant_endpoints(client_and_tokens, b04_world) -> None:  # noqa: ANN001
    c, tokens = client_and_tokens
    r = call(c, "GET", "/org", tokens["unverified"], b04_world.tenant)
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"


@pytest.mark.parametrize("path", ["/platform/orgs", "/platform/stats"])
def test_platform_endpoints(client_and_tokens, path: str) -> None:  # noqa: ANN001
    c, tokens = client_and_tokens
    assert call(c, "GET", path, tokens["owner"]).status_code == 403
    r = call(c, "GET", path, tokens["platform"])
    assert r.status_code == 200
    if path == "/platform/orgs":
        slugs = {o["slug"]: o for o in r.json()}
        assert slugs["acme4"]["members_active"] >= 6
    else:
        assert r.json()["platform_admins"] >= 1


def test_orgs_list(client_and_tokens, b04_world: B04World) -> None:  # noqa: ANN001
    c, tokens = client_and_tokens
    mine = call(c, "GET", "/orgs", tokens["staff"]).json()
    assert [o["slug"] for o in mine] == [b04_world.tenant]  # D1: exactly one
    every = {o["slug"] for o in call(c, "GET", "/orgs", tokens["platform"]).json()}
    assert {b04_world.tenant, b04_world.other} <= every
