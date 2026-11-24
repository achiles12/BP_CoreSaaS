"""B07: in-app notifications (design §3.7, D12, D13; api_spec.md §9).

Shared B04 world: acme4 (one member per role), beta4 (its own owner).
Rows are inserted with SQL; notify() itself is covered by the export job tests.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.b04_helpers import audit_lines, call, login, sql
from tests.conftest import B04World

pytestmark = pytest.mark.integration
T = "acme4"


@pytest.fixture
def client(b04_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(b04_settings)) as c:
        yield c


@pytest.fixture
def tok(client: TestClient, b04_world: B04World) -> dict[str, str]:
    return {k: login(client, e) for k, e in b04_world.users.items() if k != "unverified"}


def uid(world: B04World, who: str) -> uuid.UUID:
    return sql(world.db_url, "select id from users where email=$1", world.users[who])[0]["id"]


def add(world: B04World, who: str, title: str, schema: str = "tenant_acme4") -> uuid.UUID:
    return sql(
        world.db_url,
        f"insert into {schema}.notifications (user_id, type, title, body, data) "  # noqa: S608
        "values ($1, 'test.note', $2, 'b', '{\"k\": 1}'::jsonb) returning id",
        uid(world, who),
        title,
    )[0]["id"]


@pytest.fixture(autouse=True)
def _clean(b04_world: B04World) -> None:
    for s in ("tenant_acme4", "tenant_beta4"):
        sql(b04_world.db_url, f"delete from {s}.notifications")  # noqa: S608


def test_list_own_only_newest_first(client: TestClient, tok: dict, b04_world: B04World) -> None:
    a1 = add(b04_world, "staff", "first")
    a2 = add(b04_world, "staff", "second")
    add(b04_world, "user", "someone else's")
    r = call(client, "GET", "/notifications", tok["staff"], T)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert [n["id"] for n in body["items"]] == [str(a2), str(a1)]
    n = body["items"][0]
    assert n["type"] == "test.note" and n["body"] == "b" and n["data"] == {"k": 1}
    assert n["read_at"] is None


def test_every_role_may_read(client: TestClient, tok: dict) -> None:
    for role in ("owner", "admin", "manager", "staff", "user"):
        assert call(client, "GET", "/notifications", tok[role], T).status_code == 200


def test_mark_read_is_idempotent_and_audited_once(
    client: TestClient, tok: dict, b04_world: B04World, audit_dir: Path
) -> None:
    nid = add(b04_world, "staff", "x")
    r1 = call(client, "POST", f"/notifications/{nid}/read", tok["staff"], T)
    assert r1.status_code == 200, r1.text
    first = r1.json()["read_at"]
    assert first is not None
    r2 = call(client, "POST", f"/notifications/{nid}/read", tok["staff"], T)
    assert r2.status_code == 200 and r2.json()["read_at"] == first
    lines = [x for x in audit_lines(audit_dir) if x["action"] == "notifications.read"]
    assert len(lines) == 1 and lines[0]["entity_id"] == str(nid)
    unread = call(client, "GET", "/notifications?unread=true", tok["staff"], T).json()
    assert unread["total"] == 0
    assert call(client, "GET", "/notifications", tok["staff"], T).json()["total"] == 1


def test_others_notification_is_404(client: TestClient, tok: dict, b04_world: B04World) -> None:
    nid = add(b04_world, "user", "theirs")
    assert call(client, "POST", f"/notifications/{nid}/read", tok["staff"], T).status_code == 404
    assert (
        call(client, "POST", f"/notifications/{uuid.uuid4()}/read", tok["staff"], T).status_code
        == 404
    )


def test_read_all_counts_and_audits(
    client: TestClient, tok: dict, b04_world: B04World, audit_dir: Path
) -> None:
    add(b04_world, "staff", "a")
    add(b04_world, "staff", "b")
    add(b04_world, "user", "not mine")
    r = call(client, "POST", "/notifications/read-all", tok["staff"], T)
    assert r.status_code == 200 and r.json() == {"updated": 2}
    assert call(client, "POST", "/notifications/read-all", tok["staff"], T).json() == {"updated": 0}
    assert call(client, "GET", "/notifications?unread=true", tok["user"], T).json()["total"] == 1
    lines = [x for x in audit_lines(audit_dir) if x["action"] == "notifications.read_all"]
    assert [x["diff"]["count"] for x in lines] == [2, 0]


def test_other_tenant_rows_invisible(client: TestClient, tok: dict, b04_world: B04World) -> None:
    """C2: a beta4 notification id is not found from acme4."""
    nid = add(b04_world, "other_owner", "beta", schema="tenant_beta4")
    assert call(client, "POST", f"/notifications/{nid}/read", tok["owner"], T).status_code == 404
    assert call(client, "GET", "/notifications", tok["other_owner"], "beta4").json()["total"] == 1
