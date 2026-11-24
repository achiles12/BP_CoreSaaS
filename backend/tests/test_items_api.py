"""B06: template module /items (design §3.4, D10–D14; api_spec.md §11).

Shared B04 world: acme4 (one member per role), beta4 (its own owner).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.b04_helpers import audit_lines, call, login
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


def create(c: TestClient, token: str, **body: object) -> dict:
    r = call(c, "POST", "/items", token, T, json={"title": "Item", **body})
    assert r.status_code == 201, r.text
    return r.json()


def test_crud_happy_path(
    client: TestClient, tok: dict, b04_world: B04World, audit_dir: Path
) -> None:
    it = create(client, tok["staff"], title="  First   item ", description="Ünïcode ✓")
    assert it["title"] == "First item" and it["status"] == "open" and it["owner_name"] == "Staff"
    assert call(client, "GET", f"/items/{it['id']}", tok["user"], T).json() == it

    r = call(
        client,
        "PATCH",
        f"/items/{it['id']}",
        tok["staff"],
        T,
        json={"status": "done", "title": "First item"},
    )
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert r.json()["updated_at"] >= it["updated_at"]

    assert call(client, "DELETE", f"/items/{it['id']}", tok["admin"], T).status_code == 204
    assert call(client, "GET", f"/items/{it['id']}", tok["admin"], T).status_code == 404
    assert (
        call(
            client, "PATCH", f"/items/{it['id']}", tok["admin"], T, json={"status": "open"}
        ).status_code
        == 404
    )
    assert call(client, "DELETE", f"/items/{it['id']}", tok["admin"], T).status_code == 404

    lines = [a for a in audit_lines(audit_dir) if a.get("entity_id") == it["id"]]
    assert [a["action"] for a in lines] == ["items.create", "items.update", "items.delete"]
    assert lines[1]["diff"] == {"status": ["open", "done"]}  # unchanged title not in diff
    assert all(a["org"] == T and a["entity"] == "item" for a in lines)


def test_noop_patch_writes_no_audit(client: TestClient, tok: dict, audit_dir: Path) -> None:
    it = create(client, tok["staff"], title="Same")
    r = call(client, "PATCH", f"/items/{it['id']}", tok["staff"], T, json={"title": "Same"})
    assert r.status_code == 200
    assert not [
        a
        for a in audit_lines(audit_dir)
        if a["action"] == "items.update" and a["entity_id"] == it["id"]
    ]


def test_role_matrix(client: TestClient, tok: dict) -> None:
    it = create(client, tok["manager"])
    assert call(client, "GET", "/items", tok["user"], T).status_code == 200
    assert call(client, "POST", "/items", tok["user"], T, json={"title": "x"}).status_code == 403
    assert (
        call(client, "PATCH", f"/items/{it['id']}", tok["user"], T, json={"title": "x"}).status_code
        == 403
    )
    assert call(client, "DELETE", f"/items/{it['id']}", tok["staff"], T).status_code == 403
    assert call(client, "DELETE", f"/items/{it['id']}", tok["manager"], T).status_code == 403
    assert call(client, "DELETE", f"/items/{it['id']}", tok["owner"], T).status_code == 204


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"status": "closed"},
        {"description": "d" * 5001},
        {"title": "x", "owner_id": str(uuid.uuid4())},
    ],
)
def test_create_validation(client: TestClient, tok: dict, body: dict) -> None:
    r = call(client, "POST", "/items", tok["staff"], T, json=body)
    assert r.status_code == 422, (body, r.text)


@pytest.mark.parametrize(
    "body", [{}, {"color": "red"}, {"title": None}, {"status": None}, {"status": "closed"}]
)
def test_patch_validation(client: TestClient, tok: dict, body: dict) -> None:
    it = create(client, tok["staff"])
    r = call(client, "PATCH", f"/items/{it['id']}", tok["staff"], T, json=body)
    assert r.status_code == 422, (body, r.text)


def test_description_can_be_cleared(client: TestClient, tok: dict) -> None:
    it = create(client, tok["staff"], description="something")
    r = call(client, "PATCH", f"/items/{it['id']}", tok["staff"], T, json={"description": None})
    assert r.status_code == 200 and r.json()["description"] is None


def test_list_q_sort_filter(client: TestClient, tok: dict, b04_world: B04World) -> None:
    tag = uuid.uuid4().hex[:8]
    a = create(client, tok["staff"], title=f"{tag} beta", status="done")
    b = create(client, tok["manager"], title=f"{tag} alpha")
    create(client, tok["staff"], title=f"{tag} gamma", status="in_progress")

    def titles(**params: str) -> list[str]:
        r = call(client, "GET", "/items", tok["user"], T, params={"q": tag.upper(), **params})
        assert r.status_code == 200, r.text
        return [i["title"] for i in r.json()["items"]]

    assert titles() == [f"{tag} gamma", f"{tag} alpha", f"{tag} beta"]  # newest first
    assert titles(sort="title") == [f"{tag} alpha", f"{tag} beta", f"{tag} gamma"]
    assert titles(**{"filter[status]": "done,in_progress", "sort": "title"}) == [
        f"{tag} beta",
        f"{tag} gamma",
    ]
    assert titles(**{"filter[owner_id]": b["owner_id"]}) == [f"{tag} alpha"]
    assert (
        titles(**{"filter[created_at][gte]": a["created_at"], "sort": "created_at"})[0]
        == f"{tag} beta"
    )
    assert (
        call(client, "GET", "/items", tok["user"], T, params={"sort": "owner_id"}).status_code
        == 422
    )


def test_other_tenant_is_not_found(client: TestClient, tok: dict, b04_world: B04World) -> None:
    it = create(client, tok["staff"])
    other = tok["other_owner"]
    assert call(client, "GET", f"/items/{it['id']}", other, b04_world.other).status_code == 404
    assert call(client, "DELETE", f"/items/{it['id']}", other, b04_world.other).status_code == 404
    listed = call(client, "GET", "/items", other, b04_world.other, params={"page_size": 100}).json()
    assert it["id"] not in [i["id"] for i in listed["items"]]
