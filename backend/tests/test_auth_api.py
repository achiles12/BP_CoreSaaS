"""B03 integration: /auth/* endpoints end to end (design B03 §3.8, §5).

Real Postgres (database `b03`) and Redis containers; the email QUEUE is
replaced by a recorder so tests can read the one-time links (the worker side
is covered in test_worker_jobs.py and by the live script against Mailpit).
"""

import asyncio
import itertools
import json
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, urlparse

import asyncpg
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import mail
from app.core.security import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    CurrentUser,
    current_verified_user,
    hash_password,
)
from app.main import create_app

pytestmark = pytest.mark.integration

PW = "correct-horse-123"
NEW_PW = "brand-new-pass-456"
_n = itertools.count(1)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def sql(url: str, query: str, *args: Any) -> list[asyncpg.Record]:
    """Run one statement on the test DB (sync, own connection)."""

    async def go() -> list[asyncpg.Record]:
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg", "postgresql"))
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return asyncio.run(go())


def new_email(prefix: str = "u") -> str:
    return f"{prefix}{next(_n):04d}@b03.test"


def make_user(
    url: str, email: str, *, password: str = PW, verified: bool = True, active: bool = True
) -> uuid.UUID:
    rows = sql(
        url,
        "insert into users (email, password_hash, full_name, is_verified, is_active) "
        "values ($1, $2, 'Test User', $3, $4) returning id",
        email,
        hash_password(password),
        verified,
        active,
    )
    return rows[0]["id"]


def audit_lines(audit_dir: Path) -> list[dict]:
    f = audit_dir / "audit.log"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def token_from(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


class MailRecorder:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = False

    async def __call__(
        self, redis: Any, template: str, to: str, context: dict, *, org_slug: str | None = None
    ) -> str | None:
        if self.fail:
            return None
        self.sent.append({"template": template, "to": to, "context": context})
        return f"job-{len(self.sent)}"

    def last_for(self, to: str, template: str) -> dict[str, Any]:
        hits = [m for m in self.sent if m["to"] == to and m["template"] == template]
        assert hits, f"no {template} email to {to}: {self.sent}"
        return hits[-1]


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> MailRecorder:
    rec = MailRecorder()
    monkeypatch.setattr(mail, "queue_email", rec)
    return rec


def _with_gate_route(settings: Settings):  # noqa: ANN202
    """App plus a probe route protected by current_verified_user (D1)."""
    app = create_app(settings)

    @app.get("/_probe/verified")
    async def probe(caller: Annotated[CurrentUser, Depends(current_verified_user)]) -> dict:
        return {"user": str(caller.id)}

    return app


@pytest.fixture
def client(b03_settings: Settings, mails: MailRecorder) -> Iterator[TestClient]:
    with TestClient(_with_gate_route(b03_settings)) as c:
        yield c


def login(c: TestClient, email: str, password: str = PW) -> Any:
    return c.post("/auth/login", json={"email": email, "password": password})


def post_with(c: TestClient, path: str, cookies: dict[str, str], **kw: Any) -> Any:
    """POST with exactly these cookies (and no others left from earlier calls)."""
    c.cookies.clear()
    for k, v in cookies.items():
        c.cookies.set(k, v)
    return c.post(path, **kw)


def refresh_with(c: TestClient, raw: str) -> Any:
    """Send the refresh cookie explicitly: its Path is /api/auth (D4), and the
    backend is called without the /api prefix, exactly like the manual test."""
    return post_with(c, "/auth/refresh", {REFRESH_COOKIE: raw})


def cookie_from(resp: Any, name: str) -> str | None:
    for header in resp.headers.get_list("set-cookie"):
        m = re.match(rf"{name}=([^;]*)", header)
        if m:
            return m.group(1).strip('"') or None
    return None


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #
def test_login_sets_cookies_and_returns_user(
    client: TestClient, b03_db_url: str, audit_dir: Path
) -> None:
    email = new_email()
    uid = make_user(b03_db_url, email)
    r = login(client, email.upper())  # emails are case-insensitive
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"] == {
        "id": str(uid),
        "email": email,
        "full_name": "Test User",
        "is_verified": True,
        "is_platform_admin": False,
    }
    assert body["memberships"] == []
    raw_cookies = r.headers.get_list("set-cookie")
    assert any(h.startswith(f"{ACCESS_COOKIE}=") and "HttpOnly" in h for h in raw_cookies)
    assert any(h.startswith(f"{REFRESH_COOKIE}=") and "Path=/api/auth" in h for h in raw_cookies)

    rows = sql(
        b03_db_url, "select token_hash, revoked_at from refresh_tokens where user_id=$1", uid
    )
    assert len(rows) == 1 and rows[0]["revoked_at"] is None
    assert rows[0]["token_hash"] != cookie_from(r, REFRESH_COOKIE)  # only the hash is stored
    assert sql(b03_db_url, "select last_login_at from users where id=$1", uid)[0][0] is not None

    ok = [x for x in audit_lines(audit_dir) if x["action"] == "auth.login" and x["result"] == "ok"]
    assert ok and ok[-1]["actor"] == str(uid)


def test_login_lists_active_memberships_only(client: TestClient, b03_db_url: str) -> None:
    """A membership in a suspended org is not listed (one org per user since B04)."""
    n = next(_n)
    shown = {}
    for slug, status in ((f"mact_{n}", "active"), (f"msus_{n}", "suspended")):
        email = new_email()
        uid = make_user(b03_db_url, email)
        org_id = sql(
            b03_db_url,
            "insert into organizations (name, slug, schema_name, status) "
            "values ($1, $2, $3, $4) returning id",
            slug,
            slug,
            f"tenant_{slug}",
            status,
        )[0]["id"]
        sql(
            b03_db_url, "insert into org_memberships (user_id, org_id) values ($1, $2)", uid, org_id
        )
        shown[status] = [m["slug"] for m in login(client, email).json()["memberships"]]
    assert shown == {"active": [f"mact_{n}"], "suspended": []}


@pytest.mark.parametrize("case", ["wrong_password", "unknown_email", "inactive"])
def test_login_failures_are_identical(
    client: TestClient, b03_db_url: str, audit_dir: Path, case: str
) -> None:
    email = new_email()
    if case != "unknown_email":
        make_user(b03_db_url, email, active=case != "inactive")
    r = login(client, email, "wrong-pass-999" if case == "wrong_password" else PW)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"
    assert r.json()["error"]["message"] == "Invalid email or password"
    assert not r.headers.get_list("set-cookie")
    denied = [x for x in audit_lines(audit_dir) if x["action"] == "auth.login"]
    reason = {"wrong_password": "bad_password"}.get(case, case)
    assert denied[-1]["result"] == "denied" and denied[-1]["diff"]["reason"] == reason


def test_login_validation(client: TestClient) -> None:
    r = client.post("/auth/login", json={"email": "not-an-email", "password": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_login_rate_limited_per_ip_and_email(client: TestClient, b03_db_url: str) -> None:
    email, other = new_email(), new_email()
    make_user(b03_db_url, other)
    codes = [login(client, email, "bad-pass-000").status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]
    r = login(client, email, "bad-pass-000")
    assert r.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert login(client, other).status_code == 200  # another email is not affected


def test_successful_logins_are_not_rate_limited(client: TestClient, b03_db_url: str) -> None:
    """Only FAILED attempts count (backend_processes.md §8)."""
    email = new_email()
    make_user(b03_db_url, email)
    assert [login(client, email).status_code for _ in range(8)] == [200] * 8


# --------------------------------------------------------------------------- #
# refresh / reuse / logout
# --------------------------------------------------------------------------- #
def test_refresh_rotates(client: TestClient, b03_db_url: str) -> None:
    email = new_email()
    uid = make_user(b03_db_url, email)
    first = cookie_from(login(client, email), REFRESH_COOKIE)
    assert first
    r = refresh_with(client, first)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == str(uid)
    second = cookie_from(r, REFRESH_COOKIE)
    assert second and second != first and cookie_from(r, ACCESS_COOKIE)

    rows = sql(
        b03_db_url,
        "select id, revoked_at, replaced_by, family_id from refresh_tokens "
        "where user_id=$1 order by created_at",
        uid,
    )
    assert len(rows) == 2
    assert rows[0]["revoked_at"] is not None and rows[0]["replaced_by"] == rows[1]["id"]
    assert rows[1]["revoked_at"] is None and rows[0]["family_id"] == rows[1]["family_id"]
    assert refresh_with(client, second).status_code == 200  # the new one works


def test_reuse_revokes_family(client: TestClient, b03_db_url: str, audit_dir: Path) -> None:
    email = new_email()
    uid = make_user(b03_db_url, email)
    old = cookie_from(login(client, email), REFRESH_COOKIE)
    other_session = cookie_from(login(client, email), REFRESH_COOKIE)  # another device
    assert old and other_session
    new = cookie_from(refresh_with(client, old), REFRESH_COOKIE)
    assert new

    r = refresh_with(client, old)  # attacker replays the rotated token
    assert r.status_code == 401
    assert cookie_from(r, REFRESH_COOKIE) is None  # cleared in the response
    assert refresh_with(client, new).status_code == 401  # legit holder is out too
    assert refresh_with(client, other_session).status_code == 200  # other family untouched

    reuse = [x for x in audit_lines(audit_dir) if x["action"] == "auth.refresh_reuse"]
    assert reuse and reuse[-1]["actor"] == str(uid)
    live = sql(
        b03_db_url,
        "select count(*) from refresh_tokens t join refresh_tokens o on o.family_id=t.family_id "
        "where o.token_hash = encode(sha256($1::bytea), 'hex') and t.revoked_at is null",
        old.encode(),
    )[0][0]
    assert live == 0


def test_refresh_rejects_missing_unknown_expired_inactive(
    client: TestClient, b03_db_url: str
) -> None:
    client.cookies.clear()
    assert client.post("/auth/refresh").status_code == 401
    assert refresh_with(client, "unknown-token").status_code == 401

    email = new_email()
    uid = make_user(b03_db_url, email)
    raw = cookie_from(login(client, email), REFRESH_COOKIE)
    assert raw
    sql(
        b03_db_url,
        "update refresh_tokens set expires_at = now() - interval '1 s' where user_id=$1",
        uid,
    )
    assert refresh_with(client, raw).status_code == 401

    email2 = new_email()
    uid2 = make_user(b03_db_url, email2)
    raw2 = cookie_from(login(client, email2), REFRESH_COOKIE)
    assert raw2
    sql(b03_db_url, "update users set is_active=false where id=$1", uid2)
    assert refresh_with(client, raw2).status_code == 401


def test_logout_revokes_and_clears(client: TestClient, b03_db_url: str) -> None:
    email = new_email()
    uid = make_user(b03_db_url, email)
    raw = cookie_from(login(client, email), REFRESH_COOKIE)
    assert raw
    r = post_with(client, "/auth/logout", {REFRESH_COOKIE: raw})
    assert r.status_code == 204
    cleared = r.headers.get_list("set-cookie")
    assert any(h.startswith(f"{ACCESS_COOKIE}=") and "Max-Age=0" in h for h in cleared)
    assert any(h.startswith(f"{REFRESH_COOKIE}=") and "Max-Age=0" in h for h in cleared)
    assert (
        sql(
            b03_db_url,
            "select count(*) from refresh_tokens where user_id=$1 and revoked_at is null",
            uid,
        )[0][0]
        == 0
    )
    assert refresh_with(client, raw).status_code == 401


def test_logout_with_access_cookie_only_and_with_nothing(
    client: TestClient, b03_db_url: str
) -> None:
    email = new_email()
    uid = make_user(b03_db_url, email)
    access = cookie_from(login(client, email), ACCESS_COOKIE)
    assert post_with(client, "/auth/logout", {ACCESS_COOKIE: access or ""}).status_code == 204
    assert (
        sql(
            b03_db_url,
            "select count(*) from refresh_tokens where user_id=$1 and revoked_at is null",
            uid,
        )[0][0]
        == 0
    )
    client.cookies.clear()
    assert client.post("/auth/logout").status_code == 204  # no session at all: still fine


# --------------------------------------------------------------------------- #
# current user + verification
# --------------------------------------------------------------------------- #
def test_current_user_requires_valid_active_session(client: TestClient, b03_db_url: str) -> None:
    client.cookies.clear()
    assert client.post("/auth/resend-verification").status_code == 401
    email = new_email()
    uid = make_user(b03_db_url, email, verified=False)
    login(client, email)
    sql(b03_db_url, "update users set is_active=false where id=$1", uid)
    r = client.post("/auth/resend-verification")  # access JWT still valid, user is not
    assert r.status_code == 401


def test_unverified_user_limited_then_verified(
    client: TestClient, b03_db_url: str, mails: MailRecorder, audit_dir: Path
) -> None:
    email = new_email()
    make_user(b03_db_url, email, verified=False)
    r = login(client, email)
    assert r.status_code == 200 and r.json()["user"]["is_verified"] is False  # D1: allowed in

    gate = client.get("/_probe/verified")
    assert gate.status_code == 403 and gate.json()["error"]["code"] == "email_not_verified"

    assert client.post("/auth/resend-verification").status_code == 202
    first = token_from(mails.last_for(email, "verify_email")["context"]["link"])
    assert client.post("/auth/resend-verification").status_code == 202
    link = mails.last_for(email, "verify_email")["context"]["link"]
    assert link.startswith("http://fe.test/verify-email?token=")
    second = token_from(link)

    # Only the newest link works.
    assert client.post("/auth/verify-email", json={"token": first}).status_code == 400
    r = client.post("/auth/verify-email", json={"token": second})
    assert r.status_code == 200 and r.json() == {"status": "verified"}
    assert client.post("/auth/verify-email", json={"token": second}).status_code == 400  # once
    assert client.get("/_probe/verified").status_code == 200
    assert client.post("/auth/resend-verification").status_code == 409  # already verified
    assert any(x["action"] == "auth.email_verified" for x in audit_lines(audit_dir))


def test_verification_gate_can_be_switched_off(
    b03_settings: Settings, b03_db_url: str, mails: MailRecorder
) -> None:
    settings = b03_settings.model_copy(update={"require_email_verification": False})
    email = new_email()
    make_user(b03_db_url, email, verified=False)
    with TestClient(_with_gate_route(settings)) as c:
        login(c, email)
        assert c.get("/_probe/verified").status_code == 200


def test_resend_verification_queue_failure_is_503(
    client: TestClient, b03_db_url: str, mails: MailRecorder
) -> None:
    email = new_email()
    make_user(b03_db_url, email, verified=False)
    login(client, email)
    mails.fail = True
    r = client.post("/auth/resend-verification")
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# forgot / reset
# --------------------------------------------------------------------------- #
def test_forgot_password_identical_for_all_inputs(
    client: TestClient, b03_db_url: str, mails: MailRecorder
) -> None:
    known, inactive, unknown = new_email(), new_email(), new_email()
    make_user(b03_db_url, known)
    make_user(b03_db_url, inactive, active=False)
    responses = [
        client.post("/auth/forgot-password", json={"email": e}) for e in (known, inactive, unknown)
    ]
    assert {r.status_code for r in responses} == {202}
    assert len({r.text for r in responses}) == 1
    assert [m["to"] for m in mails.sent] == [known]
    ctx = mails.sent[0]["context"]
    assert ctx["link"].startswith("http://fe.test/reset-password?token=")
    assert ctx["expires_minutes"] == 60


def test_forgot_password_hides_queue_failure(
    client: TestClient, b03_db_url: str, mails: MailRecorder
) -> None:
    email = new_email()
    make_user(b03_db_url, email)
    mails.fail = True
    assert client.post("/auth/forgot-password", json={"email": email}).status_code == 202


def test_reset_password_full_flow(
    client: TestClient, b03_db_url: str, mails: MailRecorder, audit_dir: Path
) -> None:
    email = new_email()
    uid = make_user(b03_db_url, email, verified=False)
    session_a = cookie_from(login(client, email), REFRESH_COOKIE)
    session_b = cookie_from(login(client, email), REFRESH_COOKIE)

    client.post("/auth/forgot-password", json={"email": email})
    old_token = token_from(mails.last_for(email, "reset_password")["context"]["link"])
    client.post("/auth/forgot-password", json={"email": email})
    token = token_from(mails.last_for(email, "reset_password")["context"]["link"])

    weak = client.post("/auth/reset-password", json={"token": token, "new_password": "short"})
    assert weak.status_code == 422
    assert weak.json()["error"]["fields"][0]["loc"] == ["body", "new_password"]

    stale = client.post("/auth/reset-password", json={"token": old_token, "new_password": NEW_PW})
    assert stale.status_code == 400  # superseded by the newer request

    r = client.post("/auth/reset-password", json={"token": token, "new_password": NEW_PW})
    assert r.status_code == 204
    again = client.post("/auth/reset-password", json={"token": token, "new_password": NEW_PW})
    assert again.status_code == 400  # single use

    assert login(client, email, PW).status_code == 401  # old password gone
    assert login(client, email, NEW_PW).status_code == 200
    for raw in (session_a, session_b):  # D5: every old session revoked
        assert raw and refresh_with(client, raw).status_code == 401
    assert sql(b03_db_url, "select is_verified from users where id=$1", uid)[0][0] is True  # D3
    assert any(x["action"] == "auth.password_reset" for x in audit_lines(audit_dir))


def test_reset_password_expired_token(
    client: TestClient, b03_db_url: str, mails: MailRecorder
) -> None:
    email = new_email()
    uid = make_user(b03_db_url, email)
    client.post("/auth/forgot-password", json={"email": email})
    token = token_from(mails.last_for(email, "reset_password")["context"]["link"])
    sql(
        b03_db_url,
        "update password_reset_tokens set expires_at = now() - interval '1 s' where user_id=$1",
        uid,
    )
    r = client.post("/auth/reset-password", json={"token": token, "new_password": NEW_PW})
    assert r.status_code == 400 and r.json()["error"]["message"] == "Invalid or expired token"


# --------------------------------------------------------------------------- #
# change password
# --------------------------------------------------------------------------- #
def test_change_password(client: TestClient, b03_db_url: str, audit_dir: Path) -> None:
    email = new_email()
    make_user(b03_db_url, email)
    other = cookie_from(login(client, email), REFRESH_COOKIE)  # e.g. a phone
    r = login(client, email)  # this browser; client keeps its access cookie
    mine = cookie_from(r, REFRESH_COOKIE)
    access = cookie_from(r, ACCESS_COOKIE)
    assert other and mine and access

    def change(current: str, new: str) -> Any:
        return post_with(
            client,
            "/auth/change-password",
            {ACCESS_COOKIE: access},
            json={"current_password": current, "new_password": new},
        )

    assert change("wrong-pass-000", NEW_PW).status_code == 400
    assert change(PW, "short").status_code == 422
    assert change(PW, PW).status_code == 422  # must differ
    assert change(PW, NEW_PW).status_code == 204

    assert refresh_with(client, other).status_code == 401  # other sessions ended
    assert refresh_with(client, mine).status_code == 200  # this one kept (D5)
    assert login(client, email, NEW_PW).status_code == 200
    assert any(
        x["action"] == "auth.password_changed" and x["result"] == "ok"
        for x in audit_lines(audit_dir)
    )


# --------------------------------------------------------------------------- #
# audit hygiene
# --------------------------------------------------------------------------- #
def test_audit_has_no_secrets(
    client: TestClient, b03_db_url: str, mails: MailRecorder, audit_dir: Path
) -> None:
    email = new_email()
    make_user(b03_db_url, email)
    raw = cookie_from(login(client, email), REFRESH_COOKIE)
    login(client, email, "wrong-but-secret-777")
    client.post("/auth/forgot-password", json={"email": email})
    token = token_from(mails.last_for(email, "reset_password")["context"]["link"])
    client.post("/auth/reset-password", json={"token": token, "new_password": NEW_PW})
    text = (audit_dir / "audit.log").read_text()
    for secret in (PW, NEW_PW, "wrong-but-secret-777", token, raw or "x" * 40):
        assert secret not in text


def test_prefixed_cookies_round_trip(b03_settings: Settings, mails: MailRecorder) -> None:
    """B13 D6: with COOKIE_PREFIX every auth endpoint uses the prefixed names only."""
    settings = b03_settings.model_copy(update={"cookie_prefix": "acme_"})
    email = f"prefix-{uuid.uuid4().hex[:8]}@t.test"
    make_user(settings.database_url, email)
    with TestClient(_with_gate_route(settings)) as c:
        r = login(c, email)
        access = cookie_from(r, "acme_access_token")
        refresh = cookie_from(r, "acme_refresh_token")
        assert access and refresh
        assert cookie_from(r, "access_token") is None

        c.cookies.clear()
        assert c.get("/me", headers={"Cookie": f"acme_access_token={access}"}).status_code == 200
        assert c.get("/me", headers={"Cookie": f"access_token={access}"}).status_code == 401

        r = post_with(c, "/auth/refresh", {"acme_refresh_token": refresh})
        assert r.status_code == 200
        refresh = cookie_from(r, "acme_refresh_token")
        assert refresh
        r = post_with(c, "/auth/logout", {"acme_refresh_token": refresh})
        assert r.status_code == 204
        cleared = r.headers.get_list("set-cookie")
        for name in ("acme_access_token", "acme_refresh_token"):
            assert any(h.startswith(f"{name}=") and "Max-Age=0" in h for h in cleared)
        assert post_with(c, "/auth/refresh", {"acme_refresh_token": refresh}).status_code == 401
