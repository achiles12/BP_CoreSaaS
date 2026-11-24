"""B07: GET /search over files + items (design §3.3, D10, D11; api_spec.md §7).

Every test uses its own random word, so rows from other tests never match.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.b04_helpers import call, login
from tests.b07_helpers import drop_test_roles, insert_file, insert_item, member_with_perms, user_id
from tests.conftest import B04World

pytestmark = pytest.mark.integration
T = "acme4"


@pytest.fixture
def client(b04_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(b04_settings)) as c:
        yield c


@pytest.fixture(autouse=True)
def _drop_roles(b04_world: B04World) -> Iterator[None]:
    yield
    drop_test_roles(b04_world.db_url, T)


@pytest.fixture
def tok(client: TestClient, b04_world: B04World) -> dict[str, str]:
    return {k: login(client, e) for k, e in b04_world.users.items() if k != "unverified"}


@pytest.fixture
def word() -> str:
    # letters only: "simple" text search splits on digits/punctuation differently
    return "zq" + "".join(chr(97 + b % 26) for b in uuid.uuid4().bytes[:8])


@pytest.fixture
def owner_id(b04_world: B04World) -> uuid.UUID:
    return user_id(b04_world.db_url, b04_world.users["staff"])


def search(c: TestClient, token: str, q: str, **params: str) -> dict:
    r = call(c, "GET", "/search", token, T, params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_finds_files_and_items(
    client: TestClient, tok: dict, b04_world: B04World, word: str, owner_id: uuid.UUID
) -> None:
    url = b04_world.db_url
    fid = insert_file(url, T, owner_id, f"{word}-report.pdf")
    iid = insert_item(url, T, owner_id, f"{word} plan", "long text about the " + word + " budget")
    body = search(client, tok["user"], word)
    hits = {(h["type"], h["id"]) for h in body["items"]}
    assert hits == {("files", str(fid)), ("items", str(iid))}
    assert body["total"] == 2
    by_type = {h["type"]: h for h in body["items"]}
    assert by_type["files"]["title"] == f"{word}-report.pdf" and by_type["files"]["snippet"] is None
    snip = by_type["items"]["snippet"]
    assert word in snip and "<" not in snip  # D11: plain text
    assert all(h["score"] > 0 for h in body["items"])


def test_types_param_limits_and_unknown_type_is_422(
    client: TestClient, tok: dict, b04_world: B04World, word: str, owner_id: uuid.UUID
) -> None:
    insert_file(b04_world.db_url, T, owner_id, f"{word}.txt")
    insert_item(b04_world.db_url, T, owner_id, f"{word} item")
    assert {h["type"] for h in search(client, tok["user"], word, types="items")["items"]} == {
        "items"
    }
    r = call(client, "GET", "/search", tok["user"], T, params={"q": word, "types": "items,bogus"})
    assert r.status_code == 422 and "bogus" in r.text


def test_typo_matches_by_trigram(
    client: TestClient, tok: dict, b04_world: B04World, owner_id: uuid.UUID
) -> None:
    tag = "".join(chr(97 + b % 26) for b in uuid.uuid4().bytes[:4])
    fid = insert_file(b04_world.db_url, T, owner_id, f"quarterly-{tag}.pdf")
    ids = {h["id"] for h in search(client, tok["user"], f"quartrly-{tag}")["items"]}
    assert str(fid) in ids


def test_only_live_rows(
    client: TestClient, tok: dict, b04_world: B04World, word: str, owner_id: uuid.UUID
) -> None:
    url = b04_world.db_url
    insert_file(url, T, owner_id, f"{word}-pending.txt", status="pending")
    insert_file(url, T, owner_id, f"{word}-gone.txt", status="deleted")
    insert_item(url, T, owner_id, f"{word} gone", deleted=True)
    assert search(client, tok["user"], word)["total"] == 0


def test_type_without_read_permission_is_dropped(
    client: TestClient, b04_world: B04World, word: str, owner_id: uuid.UUID
) -> None:
    url = b04_world.db_url
    insert_file(url, T, owner_id, f"{word}.txt")
    iid = insert_item(url, T, owner_id, f"{word} item")
    _, email = member_with_perms(url, T, "b7_search_items", ["search:use", "items:read"])
    token = login(client, email)
    body = search(client, token, word)  # asks for every type; files silently dropped
    assert [(h["type"], h["id"]) for h in body["items"]] == [("items", str(iid))]
    assert search(client, token, word, types="files")["total"] == 0


def test_needs_search_use(client: TestClient, b04_world: B04World) -> None:
    _, email = member_with_perms(b04_world.db_url, T, "b7_no_search", ["items:read"])
    r = call(client, "GET", "/search", login(client, email), T, params={"q": "abc"})
    assert r.status_code == 403


@pytest.mark.parametrize("q", ["a", "x" * 101, " "])
def test_bad_q_is_422(client: TestClient, tok: dict, q: str) -> None:
    assert call(client, "GET", "/search", tok["user"], T, params={"q": q}).status_code == 422


@pytest.mark.parametrize("q", ["!!", "--", "&|"])
def test_punctuation_only_q_never_500(client: TestClient, tok: dict, q: str) -> None:
    """Review focus 2: plainto_tsquery of no words is empty; still a 200."""
    r = call(client, "GET", "/search", tok["user"], T, params={"q": q})
    assert r.status_code == 200, r.text


def test_pagination_and_order(
    client: TestClient, tok: dict, b04_world: B04World, word: str, owner_id: uuid.UUID
) -> None:
    for i in range(3):
        insert_item(b04_world.db_url, T, owner_id, f"{word} n{i}")
    p1 = search(client, tok["user"], word, page_size="2")
    p2 = search(client, tok["user"], word, page_size="2", page="2")
    assert p1["total"] == 3 and len(p1["items"]) == 2 and len(p2["items"]) == 1
    ids = [h["id"] for h in p1["items"] + p2["items"]]
    assert len(set(ids)) == 3
    scores = [h["score"] for h in p1["items"] + p2["items"]]
    assert scores == sorted(scores, reverse=True)


def test_other_tenant_rows_never_found(
    client: TestClient, tok: dict, b04_world: B04World, word: str
) -> None:
    beta_owner = user_id(b04_world.db_url, b04_world.users["other_owner"])
    insert_item(b04_world.db_url, "beta4", beta_owner, f"{word} beta secret")
    assert search(client, tok["owner"], word)["total"] == 0


def test_code_like_query_matches_exactly_not_neighbours(
    client: TestClient, tok: dict, b04_world: B04World, owner_id: uuid.UUID
) -> None:
    """Code-like queries (mostly digits) skip typo matching (user decision 2026-11-20):
    an invoice number must not surface its neighbours."""
    n = str(uuid.uuid4().int)[:8]
    url = b04_world.db_url
    hit = insert_item(url, T, owner_id, f"INV-{n}-0412 invoice")
    insert_item(url, T, owner_id, f"INV-{n}-0413 invoice")
    fid = insert_file(url, T, owner_id, f"INV-{n}-0412.pdf")
    insert_file(url, T, owner_id, f"INV-{n}-0413.pdf")
    body = search(client, tok["user"], f"INV-{n}-0412")
    found = {(h["type"], h["id"]) for h in body["items"]}
    assert found == {("items", str(hit)), ("files", str(fid))}


def test_mixed_query_with_a_year_keeps_typo_matching(
    client: TestClient, tok: dict, b04_world: B04World, owner_id: uuid.UUID
) -> None:
    tag = "".join(chr(97 + b % 26) for b in uuid.uuid4().bytes[:6])
    iid = insert_item(b04_world.db_url, T, owner_id, f"quarterly{tag} 2026")
    ids = {h["id"] for h in search(client, tok["user"], f"quartrly{tag} 2026")["items"]}
    assert str(iid) in ids
