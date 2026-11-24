"""B05: files API (design §3.4, D5–D16; critical_user_flow C2, C3, C6).

Runs against the shared B04 world (acme4 with one member per role, beta4 with
its own owner) and the session RustFS container.
"""

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import storage
from app.core.errors import ValidationFailed
from app.main import create_app
from app.modules.files.service import clean_name
from tests.b04_helpers import add_member, audit_lines, call, login, sql
from tests.conftest import B04World

pytestmark = pytest.mark.integration

T = "acme4"
PDF = b"%PDF-1.4 b05 test body"


@pytest.fixture
def client(b05_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(b05_settings)) as c:
        yield c


@pytest.fixture
def tok(client: TestClient, b04_world: B04World) -> dict[str, str]:
    """Access token per role (+ the beta4 owner)."""
    return {k: login(client, e) for k, e in b04_world.users.items() if k not in {"unverified"}}


def presign(
    c: TestClient,
    token: str,
    name: str = "report.pdf",
    mime: str = "application/pdf",
    size: int = len(PDF),
):  # noqa: ANN201
    return call(
        c,
        "POST",
        "/files/presign-upload",
        token,
        T,
        json={"name": name, "mime_type": mime, "size_bytes": size},
    )


def upload(
    c: TestClient,
    token: str,
    name: str = "report.pdf",
    body: bytes = PDF,
    mime: str = "application/pdf",
) -> dict:
    r = presign(c, token, name, mime, len(body))
    assert r.status_code == 201, r.text
    p = r.json()
    put = httpx.put(p["upload_url"], content=body, headers=p["headers"])
    assert put.status_code == 200, put.text
    r = call(c, "POST", f"/files/{p['file_id']}/confirm", token, T)
    assert r.status_code == 200, r.text
    return r.json()


def rows(world: B04World, file_id: str) -> list:
    return sql(
        world.db_url,
        "select status, object_key from tenant_acme4.files where id=$1",
        uuid.UUID(file_id),
    )


# ------------------------------------------------------------------ C6 ---- #
def test_c6_upload_confirm_list_download(
    client: TestClient, tok: dict, b04_world: B04World, audit_dir: Path
) -> None:
    name = f"Résumé {uuid.uuid4().hex[:6]}.pdf"
    r = presign(client, tok["staff"], name)
    assert r.status_code == 201
    p = r.json()
    assert p["expires_in"] == 900 and p["headers"] == {"Content-Type": "application/pdf"}
    assert rows(b04_world, p["file_id"])[0]["status"] == "pending"
    assert httpx.put(p["upload_url"], content=PDF, headers=p["headers"]).status_code == 200

    r = call(client, "POST", f"/files/{p['file_id']}/confirm", tok["staff"], T)
    assert r.status_code == 200
    f = r.json()
    assert f["status"] == "active" and f["name"] == name and f["size_bytes"] == len(PDF)
    assert f["uploader_name"] == "Staff"
    key = rows(b04_world, p["file_id"])[0]["object_key"]
    assert key.startswith(f"{T}/") and key.endswith(p["file_id"])

    listed = call(client, "GET", "/files", tok["user"], T, params={"q": name[:8]}).json()
    assert p["file_id"] in [i["id"] for i in listed["items"]]
    assert call(client, "GET", f"/files/{p['file_id']}", tok["user"], T).json()["name"] == name

    d = call(client, "GET", f"/files/{p['file_id']}/download-url", tok["user"], T)
    assert d.status_code == 200 and d.json()["expires_in"] == 60
    g = httpx.get(d.json()["url"])
    assert g.status_code == 200 and g.content == PDF
    assert "filename*=UTF-8''R%C3%A9sum%C3%A9" in g.headers["content-disposition"]

    ups = [
        a
        for a in audit_lines(audit_dir)
        if a["action"] == "files.upload" and a["entity_id"] == p["file_id"]
    ]
    assert len(ups) == 1 and ups[0]["org"] == T and ups[0]["result"] == "ok"
    assert "X-Amz" not in (audit_dir / "audit.log").read_text()


# ------------------------------------------------------------ validation -- #
def _count(world: B04World) -> int:
    return sql(world.db_url, "select count(*) from tenant_acme4.files")[0][0]


@pytest.mark.parametrize(
    ("body", "code", "err"),
    [
        (
            {"name": "big.pdf", "mime_type": "application/pdf", "size_bytes": 1024 * 1024 + 1},
            413,
            "file_too_large",
        ),
        (
            {"name": "x.exe", "mime_type": "application/x-msdownload", "size_bytes": 10},
            415,
            "unsupported_file_type",
        ),
        (
            {"name": "  \x00 ", "mime_type": "application/pdf", "size_bytes": 10},
            422,
            "validation_error",
        ),
        (
            {"name": "a" * 300, "mime_type": "application/pdf", "size_bytes": 10},
            422,
            "validation_error",
        ),
        (
            {"name": "zero.pdf", "mime_type": "application/pdf", "size_bytes": 0},
            422,
            "validation_error",
        ),
    ],
)
def test_presign_rejects_before_storing(
    client: TestClient, tok: dict, b04_world: B04World, body: dict, code: int, err: str
) -> None:
    before = _count(b04_world)
    r = call(client, "POST", "/files/presign-upload", tok["staff"], T, json=body)
    assert r.status_code == code, r.text
    assert r.json()["error"]["code"] == err
    assert _count(b04_world) == before


def test_exact_limit_and_mime_params_accepted(client: TestClient, tok: dict) -> None:
    r = presign(client, tok["staff"], "edge.pdf", "Application/PDF; charset=binary", 1024 * 1024)
    assert r.status_code == 201
    assert r.json()["headers"]["Content-Type"] == "application/pdf"


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("C:\\x\\a.pdf", "a.pdf"),
        ("../../etc/passwd", "passwd"),
        ("a\x00b.txt", "ab.txt"),
        ("  spaced.txt ", "spaced.txt"),
        ("e\u0301.txt", "\u00e9.txt"),
    ],
)
def test_clean_name(raw: str, clean: str) -> None:
    assert clean_name(raw) == clean


@pytest.mark.parametrize("raw", ["", " ", "..", "dir/", "a" * 256])
def test_clean_name_rejects(raw: str) -> None:
    with pytest.raises(ValidationFailed):
        clean_name(raw)


# ---------------------------------------------------------------- confirm -- #
def test_confirm_before_put_is_409_and_stays_pending(
    client: TestClient, tok: dict, b04_world: B04World
) -> None:
    p = presign(client, tok["staff"]).json()
    r = call(client, "POST", f"/files/{p['file_id']}/confirm", tok["staff"], T)
    assert r.status_code == 409 and r.json()["error"]["code"] == "upload_incomplete"
    assert rows(b04_world, p["file_id"])[0]["status"] == "pending"
    # the client may still PUT and retry
    httpx.put(p["upload_url"], content=PDF, headers=p["headers"])
    assert (
        call(client, "POST", f"/files/{p['file_id']}/confirm", tok["staff"], T).status_code == 200
    )


def test_confirm_size_mismatch_deletes_object(
    client: TestClient, tok: dict, b04_world: B04World, b05_settings: Settings, audit_dir: Path
) -> None:
    p = presign(client, tok["staff"], size=20).json()
    httpx.put(p["upload_url"], content=b"0123456789", headers=p["headers"])
    r = call(client, "POST", f"/files/{p['file_id']}/confirm", tok["staff"], T)
    assert r.status_code == 422 and r.json()["error"]["code"] == "upload_mismatch"
    status, key = rows(b04_world, p["file_id"])[0]
    assert status == "deleted"
    assert asyncio.run(storage.head(b05_settings, key)) is None
    rej = [
        a
        for a in audit_lines(audit_dir)
        if a["action"] == "files.upload" and a["entity_id"] == p["file_id"]
    ]
    assert rej[0]["result"] == "rejected"


def test_put_with_other_type_fails_then_confirm_409(client: TestClient, tok: dict) -> None:
    p = presign(client, tok["staff"]).json()
    bad = httpx.put(p["upload_url"], content=PDF, headers={"Content-Type": "text/plain"})
    assert bad.status_code == 403
    assert (
        call(client, "POST", f"/files/{p['file_id']}/confirm", tok["staff"], T).status_code == 409
    )


def test_confirm_twice_and_by_other_user(
    client: TestClient, tok: dict, b04_world: B04World
) -> None:
    f = upload(client, tok["staff"])
    again = call(client, "POST", f"/files/{f['id']}/confirm", tok["staff"], T)
    assert again.status_code == 200 and again.json() == f
    p = presign(client, tok["staff"]).json()
    httpx.put(p["upload_url"], content=PDF, headers=p["headers"])
    assert (
        call(client, "POST", f"/files/{p['file_id']}/confirm", tok["manager"], T).status_code == 404
    )
    assert rows(b04_world, p["file_id"])[0]["status"] == "pending"


# ------------------------------------------------------------ permissions -- #
def test_permission_matrix(client: TestClient, tok: dict) -> None:
    f = upload(client, tok["staff"])
    assert presign(client, tok["user"]).status_code == 403
    assert (
        presign(client, tok["user"]).json()["error"]["message"] == "Missing permission files:write"
    )
    assert call(client, "GET", "/files", tok["user"], T).status_code == 200
    assert call(client, "GET", f"/files/{f['id']}/download-url", tok["user"], T).status_code == 200
    assert call(client, "DELETE", f"/files/{f['id']}", tok["user"], T).status_code == 403
    assert call(client, "DELETE", f"/files/{f['id']}", tok["staff"], T).status_code == 403
    assert call(client, "DELETE", f"/files/{f['id']}", tok["manager"], T).status_code == 204


def test_unauthenticated_and_missing_tenant(client: TestClient, tok: dict) -> None:
    assert call(client, "GET", "/files", None, T).status_code == 401
    assert call(client, "GET", "/files", tok["staff"], None).status_code == 400


# ---------------------------------------------------------------- delete --- #
def test_delete_is_soft_and_audited(
    client: TestClient, tok: dict, b04_world: B04World, audit_dir: Path
) -> None:
    f = upload(client, tok["staff"], name=f"gone-{uuid.uuid4().hex[:6]}.pdf")
    assert call(client, "DELETE", f"/files/{f['id']}", tok["owner"], T).status_code == 204
    assert rows(b04_world, f["id"])[0]["status"] == "deleted"
    assert f["id"] not in [
        i["id"]
        for i in call(client, "GET", "/files", tok["owner"], T, params={"page_size": 100}).json()[
            "items"
        ]
    ]
    assert call(client, "GET", f"/files/{f['id']}", tok["owner"], T).status_code == 404
    assert call(client, "GET", f"/files/{f['id']}/download-url", tok["owner"], T).status_code == 404
    assert call(client, "DELETE", f"/files/{f['id']}", tok["owner"], T).status_code == 404
    dl = [
        a
        for a in audit_lines(audit_dir)
        if a["action"] == "files.delete" and a["entity_id"] == f["id"]
    ]
    assert len(dl) == 1 and dl[0]["diff"] == {"status": ["active", "deleted"]}


# ------------------------------------------------------------------- C2 ---- #
def test_other_tenant_file_is_not_found(client: TestClient, tok: dict, b04_world: B04World) -> None:
    f = upload(client, tok["staff"])
    other = tok["other_owner"]
    for method, path in (
        ("GET", f"/files/{f['id']}"),
        ("GET", f"/files/{f['id']}/download-url"),
        ("DELETE", f"/files/{f['id']}"),
    ):
        r = call(client, method, path, other, b04_world.other)
        assert r.status_code == 404, (method, path, r.status_code)
    # and the acme4 header with a beta4 user is refused by tenancy itself
    assert call(client, "GET", "/files", other, T).status_code in (403, 404)


# ------------------------------------------------------------------ list --- #
def test_list_q_mine_pending_and_paging(client: TestClient, tok: dict, b04_world: B04World) -> None:
    tag = uuid.uuid4().hex[:8]
    uid, email = add_member(b04_world.db_url, T, "staff")
    mine_tok = login(client, email)
    for i in range(3):
        upload(client, mine_tok, name=f"Q-{tag}-{i}.pdf")
    upload(client, tok["staff"], name=f"q-{tag}-other.PDF")
    presign(client, mine_tok, name=f"Q-{tag}-pending.pdf")  # never confirmed

    r = call(client, "GET", "/files", mine_tok, T, params={"q": f"q-{tag}"}).json()
    assert r["total"] == 4  # case-insensitive, pending excluded
    r = call(client, "GET", "/files", mine_tok, T, params={"q": tag, "mine": "true"}).json()
    assert r["total"] == 3 and all(i["uploaded_by"] == str(uid) for i in r["items"])
    assert [i["name"] for i in r["items"]] == [
        f"Q-{tag}-{i}.pdf" for i in (2, 1, 0)
    ]  # newest first
    p2 = call(
        client,
        "GET",
        "/files",
        mine_tok,
        T,
        params={"q": tag, "mine": "true", "page": 2, "page_size": 2},
    ).json()
    assert p2["total"] == 3 and len(p2["items"]) == 1 and p2["page"] == 2


def test_like_wildcards_are_literal(client: TestClient, tok: dict) -> None:
    tag = uuid.uuid4().hex[:8]
    upload(client, tok["staff"], name=f"w-{tag}-100%.pdf")
    upload(client, tok["staff"], name=f"w-{tag}-1000.pdf")
    r = call(client, "GET", "/files", tok["staff"], T, params={"q": f"{tag}-100%"}).json()
    assert [i["name"] for i in r["items"]] == [f"w-{tag}-100%.pdf"]


# ------------------------------------------------------------ storage down - #
def test_storage_down(b05_settings: Settings, b04_world: B04World) -> None:
    down = b05_settings.model_copy(update={"s3_endpoint": "http://127.0.0.1:1"})
    with TestClient(create_app(down)) as c:
        t = login(c, b04_world.users["staff"])
        p = presign(c, t)
        assert p.status_code == 201  # presigning is offline
        r = call(c, "POST", f"/files/{p.json()['file_id']}/confirm", t, T)
        assert r.status_code == 503 and r.json()["error"]["code"] == "storage_unavailable"
