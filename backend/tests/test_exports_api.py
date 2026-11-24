"""B07: exports API (design §3.4, D3–D9, D18; api_spec.md §8).

The worker is not run here (test_export_job.py does that): the queue call is
replaced by a recorder so each test sees exactly what would be enqueued.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.b04_helpers import audit_lines, call, login, sql
from tests.b07_helpers import drop_test_roles, member_with_perms
from tests.conftest import B04World

pytestmark = pytest.mark.integration
T = "acme4"


class Queue:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.fail = False

    async def enqueue_job(self, name: str, *args: Any, **kw: Any) -> Any:
        if self.fail:
            raise ConnectionError("redis down")
        self.calls.append((name, *args))
        return type("Job", (), {"job_id": "j1"})()


@pytest.fixture
def queue() -> Queue:
    return Queue()


@pytest.fixture
def client(b05_settings: Settings, queue: Queue) -> Iterator[TestClient]:
    with TestClient(create_app(b05_settings)) as c:
        c.app.state.redis.enqueue_job = queue.enqueue_job  # type: ignore[attr-defined]
        yield c


@pytest.fixture(autouse=True)
def _drop_roles(b04_world: B04World) -> Iterator[None]:
    yield
    drop_test_roles(b04_world.db_url, T)


@pytest.fixture
def tok(client: TestClient, b04_world: B04World) -> dict[str, str]:
    return {k: login(client, e) for k, e in b04_world.users.items() if k != "unverified"}


def post(c: TestClient, token: str, **body: Any) -> Any:
    return call(
        c, "POST", "/exports", token, T, json={"resource": "items", "format": "csv", **body}
    )


def job_row(url: str, job_id: str) -> Any:
    rows = sql(url, "select * from tenant_acme4.export_jobs where id=$1", uuid.UUID(job_id))
    return rows[0] if rows else None


def test_create_queues_job(
    client: TestClient, tok: dict, queue: Queue, b04_world: B04World, audit_dir: Path
) -> None:
    filters = {"q": "plan", "filter[status]": "open,done", "sort": "-title"}
    r = post(client, tok["manager"], filters=filters)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued" and body["resource"] == "items" and body["format"] == "csv"
    assert body["filters"] == filters and body["download_url"] is None
    assert queue.calls == [("build_export", body["id"], T)]
    assert job_row(b04_world.db_url, body["id"])["status"] == "queued"
    line = [x for x in audit_lines(audit_dir) if x["action"] == "exports.create"][-1]
    assert line["entity_id"] == body["id"] and line["diff"]["resource"] == "items"


def test_needs_export_run(client: TestClient, tok: dict) -> None:
    """Staff and user have items:read but not export:run (system_design §4)."""
    for role in ("staff", "user"):
        assert post(client, tok[role]).status_code == 403


def test_needs_read_key_of_the_resource(client: TestClient, b04_world: B04World) -> None:
    """D3: export:run alone is not enough to export users."""
    _, email = member_with_perms(
        b04_world.db_url, T, "b7_export_only", ["export:run", "items:read"]
    )
    token = login(client, email)
    assert post(client, token).status_code == 202
    r = post(client, token, resource="users")
    assert r.status_code == 403 and "users:read" in r.text


def test_manager_may_export_users_and_files(client: TestClient, tok: dict) -> None:
    assert (
        post(client, tok["manager"], resource="users", filters={"status": "active"}).status_code
        == 202
    )
    assert (
        post(
            client, tok["manager"], resource="files", format="xlsx", filters={"mine": "true"}
        ).status_code
        == 202
    )


@pytest.mark.parametrize(
    "body",
    [
        {"resource": "bogus"},
        {"format": "pdf"},
        {"filters": {"filter[nope]": "x"}},
        {"filters": {"mine": "true"}},  # mine is a files-only extra
        {"filters": {"sort": "owner_id"}},
        {"filters": {"filter[created_at][gte]": "yesterday"}},
        {"filters": {"q": "x" * 101}},
        {"resource": "files", "filters": {"mine": "perhaps"}},
    ],
)
def test_bad_request_is_422_and_creates_nothing(
    client: TestClient, tok: dict, queue: Queue, b04_world: B04World, body: dict
) -> None:
    before = sql(b04_world.db_url, "select count(*) from tenant_acme4.export_jobs")[0][0]
    r = post(client, tok["manager"], **body)
    assert r.status_code == 422, r.text
    assert queue.calls == []
    assert sql(b04_world.db_url, "select count(*) from tenant_acme4.export_jobs")[0][0] == before


def test_page_keys_are_ignored(client: TestClient, tok: dict) -> None:
    """The list's page/page_size may come along with "current filters"; an export is all pages."""
    assert post(client, tok["manager"], filters={"page": "3", "page_size": "10"}).status_code == 202


def test_own_exports_only(client: TestClient, tok: dict) -> None:
    mine = post(client, tok["manager"]).json()["id"]
    theirs = post(client, tok["admin"]).json()["id"]
    assert call(client, "GET", f"/exports/{mine}", tok["manager"], T).status_code == 200
    assert call(client, "GET", f"/exports/{theirs}", tok["manager"], T).status_code == 404
    listed = call(client, "GET", "/exports", tok["manager"], T).json()
    ids = [e["id"] for e in listed["items"]]
    assert mine in ids and theirs not in ids
    newer = post(client, tok["manager"]).json()["id"]
    assert call(client, "GET", "/exports", tok["manager"], T).json()["items"][0]["id"] == newer


def test_enqueue_failure_is_503_and_marks_failed(
    client: TestClient, tok: dict, queue: Queue, b04_world: B04World
) -> None:
    queue.fail = True
    r = post(client, tok["manager"])
    assert r.status_code == 503, r.text
    rows = sql(
        b04_world.db_url,
        "select status, error from tenant_acme4.export_jobs order by created_at desc limit 1",
    )
    assert rows[0]["status"] == "failed" and "queue" in rows[0]["error"]


def test_other_tenant_export_is_404(client: TestClient, tok: dict) -> None:
    r = call(
        client,
        "POST",
        "/exports",
        tok["other_owner"],
        "beta4",
        json={"resource": "items", "format": "csv"},
    )
    assert r.status_code == 202
    assert call(client, "GET", f"/exports/{r.json()['id']}", tok["owner"], T).status_code == 404


def _done_job(url: str, user_email: str, status: str, key: str | None) -> str:
    uid = sql(url, "select id from users where email=$1", user_email)[0]["id"]
    return str(
        sql(
            url,
            "insert into tenant_acme4.export_jobs "
            "(requested_by, resource, format, status, object_key, row_count, finished_at) "
            "values ($1, 'items', 'csv', $2, $3, 1, now()) returning id",
            uid,
            status,
            key,
        )[0]["id"]
    )


def test_download_link_only_for_existing_file(
    client: TestClient, tok: dict, b04_world: B04World, b05_settings: Settings
) -> None:
    """Review focus 5: expired or vanished file -> status, never a dead link."""
    import asyncio

    import httpx

    from app.core import storage

    url, who = b04_world.db_url, b04_world.users["manager"]
    key = f"exports/acme4/2026/11/{uuid.uuid4()}.csv"
    src = Path(f"/tmp/{uuid.uuid4()}.csv")  # noqa: S108
    src.write_bytes(b"id\r\n1\r\n")
    asyncio.run(storage.put_file(b05_settings, key, src, "text/csv"))
    src.unlink()

    ok = call(
        client, "GET", f"/exports/{_done_job(url, who, 'done', key)}", tok["manager"], T
    ).json()
    assert ok["status"] == "done" and ok["download_expires_in"] == 60
    assert ok["expires_at"] is not None
    got = httpx.get(ok["download_url"])
    assert got.status_code == 200 and got.content == b"id\r\n1\r\n"
    assert "items-export-" in got.headers["content-disposition"]

    vanished = _done_job(url, who, "done", f"exports/acme4/2026/11/{uuid.uuid4()}.csv")
    v = call(client, "GET", f"/exports/{vanished}", tok["manager"], T).json()
    assert v["status"] == "done" and v["download_url"] is None

    expired = call(
        client, "GET", f"/exports/{_done_job(url, who, 'expired', None)}", tok["manager"], T
    )
    assert expired.json()["status"] == "expired" and expired.json()["download_url"] is None
    assert expired.json()["expires_at"] is None
