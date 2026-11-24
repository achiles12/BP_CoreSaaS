"""C2: tenant isolation across every tenant resource (B12 D6, critical_user_flow C2).

Shared B04 world: acme4 and beta4, one owner each (every permission). Each
tenant gets marker rows (items, files, notifications, export jobs) whose
titles start with its own marker, so any leak is visible in a response.
"""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.b04_helpers import call, login, sql
from tests.b07_helpers import insert_file, insert_item, user_id
from tests.conftest import B04World
from tests.route_catalog import tenant_routes

pytestmark = pytest.mark.integration
A, B = "acme4", "beta4"
PARALLEL = 50  # critical_user_flow C2: "load test with 50 parallel requests"


@dataclass
class Tenant:
    slug: str
    owner: uuid.UUID
    marker: str
    ids: dict[str, uuid.UUID]


@pytest.fixture(scope="module")
def client(b04_world: B04World, redis_container, tmp_path_factory) -> Iterator[TestClient]:  # noqa: ANN001
    from tests.conftest import redis_url

    settings = Settings(
        app_env="test",
        secret_key="b12-isolation-secret-key-0123456789abcd",
        audit_log_dir=str(tmp_path_factory.mktemp("b12_iso_audit")),
        database_url=b04_world.db_url,
        redis_url=redis_url(redis_container),
        frontend_url="http://fe.test",
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _seed(url: str, slug: str, owner: uuid.UUID) -> Tenant:
    marker = f"iso{slug}{uuid.uuid4().hex[:6]}"
    s = f'"tenant_{slug}"'
    ids = {
        "item_id": insert_item(url, slug, owner, f"{marker} item", f"{marker} body"),
        "file_id": insert_file(url, slug, owner, f"{marker}-file.txt"),
        "notification_id": sql(
            url,
            f"insert into {s}.notifications (user_id, type, title) "  # noqa: S608
            "values ($1, 'test', $2) returning id",
            owner,
            f"{marker} note",
        )[0]["id"],
        "export_id": sql(
            url,
            f"insert into {s}.export_jobs (requested_by, resource, format) "  # noqa: S608
            "values ($1, 'items', 'csv') returning id",
            owner,
        )[0]["id"],
        "user_id": owner,
        "invitation_id": sql(
            url,
            "insert into invitations (org_id, email, role_key, token_hash, invited_by, expires_at) "
            "select id, $2, 'user', $3, $1, now() + interval '7 days' from organizations "
            "where slug=$4 returning id",
            owner,
            f"{marker}@inv.test",
            uuid.uuid4().hex,
            slug,
        )[0]["id"],
    }
    return Tenant(slug, owner, marker, ids)


@pytest.fixture(scope="module")
def world(b04_world: B04World) -> dict[str, Tenant]:
    url = b04_world.db_url
    return {
        A: _seed(url, A, user_id(url, b04_world.users["owner"])),
        B: _seed(url, B, user_id(url, b04_world.users["other_owner"])),
    }


@pytest.fixture(scope="module")
def tok(client: TestClient, b04_world: B04World) -> dict[str, str]:
    return {
        A: login(client, b04_world.users["owner"]),
        B: login(client, b04_world.users["other_owner"]),
    }


# --------------------------------------------------------------------------- #
# every route with an id: the other tenant's real id is 404, row untouched
# --------------------------------------------------------------------------- #
# Valid bodies, so a missing row (404) is what answers, not validation (422).
BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", "/items/{item_id}"): {"title": "hijacked"},
    ("PATCH", "/users/{user_id}"): {"full_name": "hijacked"},
    ("PUT", "/users/{user_id}/roles"): {"role_keys": ["user"]},
}
ID_ROUTES = [r for r in tenant_routes() if "{" in r.path]


def test_every_id_route_is_covered() -> None:
    params = {p.split("}")[0] for r in ID_ROUTES for p in r.path.split("{")[1:]}
    known = {"item_id", "file_id", "notification_id", "export_id", "user_id", "invitation_id"}
    assert params <= known, f"new id parameter(s) without a seeded row: {params - known}"


@pytest.mark.parametrize("route", ID_ROUTES, ids=lambda r: r.id)
def test_other_tenants_id_is_404(
    client: TestClient, tok: dict, world: dict, b04_world: B04World, route
) -> None:  # noqa: ANN001
    theirs = world[B]
    path = route.path
    for name, value in theirs.ids.items():
        path = path.replace("{" + name + "}", str(value))
    kw = (
        {"json": BODIES.get((route.method, route.path), {})}
        if route.method in ("POST", "PUT", "PATCH")
        else {}
    )
    r = call(client, route.method, path, tok[A], A, **kw)
    assert r.status_code == 404, f"{route.id} with a {B} id answered {r.status_code}: {r.text}"
    # and nothing changed on the other side
    s = f'"tenant_{B}"'
    item = sql(
        b04_world.db_url,
        f"select title, deleted_at from {s}._template_items where id=$1",  # noqa: S608
        theirs.ids["item_id"],
    )[0]
    assert item["title"] == f"{theirs.marker} item" and item["deleted_at"] is None
    f = sql(b04_world.db_url, f"select status from {s}.files where id=$1", theirs.ids["file_id"])[0]  # noqa: S608
    assert f["status"] == "active"


# --------------------------------------------------------------------------- #
# headers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "header",
    [B, "nosuchtenant", "acme4; DROP SCHEMA tenant_beta4", 'x" or "1"="1', "../beta4"],
)
def test_foreign_unknown_or_injected_tenant_header_is_404(
    client: TestClient, tok: dict, world: dict, header: str
) -> None:
    r = call(client, "GET", "/items", tok[A], header)
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "not_found"
    assert world[B].marker not in r.text


def test_missing_tenant_header_is_400(client: TestClient, tok: dict) -> None:
    assert call(client, "GET", "/items", tok[A], None).status_code == 400


# --------------------------------------------------------------------------- #
# lists and search only ever show the caller's tenant
# --------------------------------------------------------------------------- #
LISTS = ["/items", "/files", "/notifications", "/exports", "/users", "/invitations"]


@pytest.mark.parametrize("path", LISTS)
def test_lists_show_only_own_rows(client: TestClient, tok: dict, world: dict, path: str) -> None:
    for me, other in ((A, B), (B, A)):
        r = call(
            client,
            "GET",
            path,
            tok[me],
            me,
            params={"page_size": 100} if path != "/invitations" else None,
        )
        assert r.status_code == 200, r.text
        assert world[other].marker not in r.text, f"{path} as {me} shows {other} rows"
        if path in ("/items", "/files", "/notifications", "/invitations"):
            assert world[me].marker in r.text, f"{path} as {me} misses its own rows"


def test_search_shows_only_own_rows(client: TestClient, tok: dict, world: dict) -> None:
    for me, other in ((A, B), (B, A)):
        for q in (world[me].marker, world[other].marker):
            r = call(client, "GET", "/search", tok[me], me, params={"q": q})
            assert r.status_code == 200
            assert world[other].marker not in r.text


# --------------------------------------------------------------------------- #
# 50 parallel requests on the shared connection pool
# --------------------------------------------------------------------------- #
def test_parallel_requests_never_cross_tenants(client: TestClient, tok: dict, world: dict) -> None:
    """Pooled connections are reused across tenants (schema_translate_map per
    session). Interleave both tenants and three endpoints; every answer must
    hold only its own tenant's marker."""
    client.cookies.clear()  # each request carries its own cookie header

    def one(i: int) -> tuple[str, int, str]:
        me = A if i % 2 else B
        path = ("/items", "/files", "/search")[i % 3]
        params = {"q": "iso", "page_size": 100} if path == "/search" else {"page_size": 100}
        r = client.get(
            path, params=params, headers={"X-Tenant": me, "Cookie": f"access_token={tok[me]}"}
        )
        return me, r.status_code, r.text

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        results = list(pool.map(one, range(PARALLEL * 2)))
    assert len(results) == PARALLEL * 2
    for me, status, text in results:
        other = B if me == A else A
        assert status == 200, text
        assert world[other].marker not in text, f"{me} saw {other}'s rows under load"
        assert world[me].marker in text
