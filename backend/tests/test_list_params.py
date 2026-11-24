"""B06 D9: /users and /files on the shared list helper (sort, filter[...], 422);
the old parameters (/users?status=, /files?mine=) keep working."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.b04_helpers import add_member, call, login, sql
from tests.conftest import B04World
from tests.test_files_api import upload

pytestmark = pytest.mark.integration
T = "acme4"


@pytest.fixture
def client(b05_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(b05_settings)) as c:
        yield c


@pytest.fixture
def owner(client: TestClient, b04_world: B04World) -> str:
    return login(client, b04_world.users["owner"])


# ------------------------------------------------------------------ users -- #
def test_users_sort_and_filter(client: TestClient, owner: str, b04_world: B04World) -> None:
    uid, _ = add_member(b04_world.db_url, T, "user")
    sql(b04_world.db_url, "update org_memberships set status='inactive' where user_id=$1", uid)

    emails = [
        i["email"]
        for i in call(client, "GET", "/users", owner, T, params={"page_size": 100}).json()["items"]
    ]
    assert emails == sorted(emails)  # default sort: email
    desc = [
        i["email"]
        for i in call(
            client, "GET", "/users", owner, T, params={"page_size": 100, "sort": "-email"}
        ).json()["items"]
    ]
    assert desc == sorted(emails, reverse=True)

    new = call(
        client, "GET", "/users", owner, T, params={"filter[status]": "inactive", "page_size": 100}
    ).json()
    old = call(
        client, "GET", "/users", owner, T, params={"status": "inactive", "page_size": 100}
    ).json()
    assert str(uid) in [i["id"] for i in new["items"]]
    assert new["total"] == old["total"] and all(i["status"] == "inactive" for i in new["items"])


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "password_hash"},
        {"filter[status]": "gone"},
        {"filter[email]": "x"},
        {"sort": "a,b,c,d"},
    ],
)
def test_users_bad_list_params_422(client: TestClient, owner: str, params: dict) -> None:
    r = call(client, "GET", "/users", owner, T, params=params)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


# ------------------------------------------------------------------ files -- #
def test_files_sort_filter_and_mine(client: TestClient, b04_world: B04World) -> None:
    tag = uuid.uuid4().hex[:8]
    _, email = add_member(b04_world.db_url, T, "staff")
    me = login(client, email)
    staff = login(client, b04_world.users["staff"])
    a = upload(client, me, name=f"L-{tag}-a.txt", body=b"12345", mime="text/plain")
    b = upload(
        client, me, name=f"L-{tag}-b.pdf", body=b"%PDF-1.4 1234567890", mime="application/pdf"
    )
    upload(client, staff, name=f"L-{tag}-c.txt", body=b"1", mime="text/plain")

    def names(**params: str) -> list[str]:
        r = call(client, "GET", "/files", me, T, params={"q": tag, **params})
        assert r.status_code == 200, r.text
        return [i["name"] for i in r.json()["items"]]

    assert names(sort="size_bytes") == [f"L-{tag}-c.txt", f"L-{tag}-a.txt", f"L-{tag}-b.pdf"]
    assert names(sort="-name") == [f"L-{tag}-c.txt", f"L-{tag}-b.pdf", f"L-{tag}-a.txt"]
    assert names(**{"filter[mime_type]": "text/plain", "sort": "name"}) == [
        f"L-{tag}-a.txt",
        f"L-{tag}-c.txt",
    ]
    assert names(**{"filter[uploaded_by]": a["uploaded_by"], "sort": "name"}) == [
        f"L-{tag}-a.txt",
        f"L-{tag}-b.pdf",
    ]
    assert names(mine="true", sort="name") == [f"L-{tag}-a.txt", f"L-{tag}-b.pdf"]  # old param
    today = datetime.now(UTC).date()
    assert len(names(**{"filter[created_at][gte]": today.isoformat()})) == 3
    assert names(**{"filter[created_at][lte]": (today - timedelta(days=1)).isoformat()}) == []
    assert b["id"]  # (b used above via names)


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "object_key"},
        {"filter[status]": "deleted"},
        {"filter[uploaded_by]": "me"},
        {"filter[created_at]": "2026-11-19"},
    ],
)
def test_files_bad_list_params_422(client: TestClient, b04_world: B04World, params: dict) -> None:
    t = login(client, b04_world.users["staff"])
    r = call(client, "GET", "/files", t, T, params=params)
    assert r.status_code == 422, r.text


def test_openapi_documents_list_params(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    users = {p["name"] for p in spec["paths"]["/users"]["get"]["parameters"]}
    files = {p["name"] for p in spec["paths"]["/files"]["get"]["parameters"]}
    assert {"sort", "filter[status]", "status", "q", "page", "page_size"} <= users
    assert {
        "sort",
        "filter[mime_type]",
        "filter[uploaded_by]",
        "filter[created_at][gte]",
        "mine",
    } <= files
