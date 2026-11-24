"""B04: invitations (C4), member management, role assignment, org, /me updates.

Mutating tests use fresh members (tests.b04_helpers.add_member) so the shared
world (one user per role in acme4) stays intact for the matrix tests.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import mail
from app.core.security import hash_password
from app.main import create_app
from tests.b04_helpers import add_member, audit_lines, call, login, sql, unique_email
from tests.conftest import B04_PW, B04World

pytestmark = pytest.mark.integration

NEW_PW = "invited-pass-12345"


class MailRecorder:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def __call__(
        self, redis: Any, template: str, to: str, context: dict, *, org_slug: str | None = None
    ) -> str:
        self.sent.append({"template": template, "to": to, "context": context, "org": org_slug})
        return f"job-{len(self.sent)}"

    def token_for(self, to: str) -> str:
        hits = [m for m in self.sent if m["to"] == to and m["template"] == "invite_user"]
        assert hits, f"no invite to {to}"
        return parse_qs(urlparse(hits[-1]["context"]["link"]).query)["token"][0]


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> MailRecorder:
    rec = MailRecorder()
    monkeypatch.setattr(mail, "queue_email", rec)
    return rec


@pytest.fixture
def client(b04_settings: Settings, mails: MailRecorder) -> Iterator[TestClient]:
    with TestClient(create_app(b04_settings)) as c:
        yield c


@pytest.fixture
def owner(client: TestClient, b04_world: B04World) -> str:
    return login(client, b04_world.users["owner"])


@pytest.fixture
def admin(client: TestClient, b04_world: B04World) -> str:
    return login(client, b04_world.users["admin"])


T = "acme4"


# --------------------------------------------------------------------------- #
# C4: invite -> accept -> login
# --------------------------------------------------------------------------- #
def test_invite_accept_login_new_account(
    client: TestClient, owner: str, mails: MailRecorder, audit_dir: Path, b04_world: B04World
) -> None:
    email = unique_email("new")
    r = call(
        client,
        "POST",
        "/users/invite",
        owner,
        T,
        json={"email": email.upper(), "role_key": "staff"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email_queued"] is True
    assert body["invitation"]["email"] == email and body["invitation"]["role_key"] == "staff"
    assert body["invitation"]["invited_by"] == b04_world.users["owner"]
    sent = [m for m in mails.sent if m["to"] == email][-1]
    assert sent["context"]["org_name"] == "Acme Four" and sent["org"] == T
    assert sent["context"]["link"].startswith("http://fe.test/accept-invite?token=")
    token = mails.token_for(email)

    info = call(client, "POST", "/auth/invitation", None, json={"token": token})
    assert info.json() == {
        "email": email,
        "org_name": "Acme Four",
        "role_key": "staff",
        "existing_account": False,
    }

    weak = call(
        client,
        "POST",
        "/auth/accept-invite",
        None,
        json={"token": token, "password": "short", "full_name": "New Person"},
    )
    assert weak.status_code == 422
    noname = call(
        client, "POST", "/auth/accept-invite", None, json={"token": token, "password": NEW_PW}
    )
    assert (
        noname.status_code == 422 and noname.json()["error"]["fields"][0]["loc"][-1] == "full_name"
    )

    ok = call(
        client,
        "POST",
        "/auth/accept-invite",
        None,
        json={"token": token, "password": NEW_PW, "full_name": "  New   Person "},
    )
    assert ok.status_code == 200 and ok.json() == {"status": "accepted", "email": email}
    again = call(
        client,
        "POST",
        "/auth/accept-invite",
        None,
        json={"token": token, "password": NEW_PW, "full_name": "X"},
    )
    assert again.status_code == 400  # single use

    me = call(client, "GET", "/me", login(client, email, NEW_PW)).json()
    assert me["landing_path"] == "/home/staff" and me["roles"] == ["staff"]
    assert me["user"]["full_name"] == "New Person" and me["is_verified"] is True  # B03 D3

    actions = [x["action"] for x in audit_lines(audit_dir)]
    for needed in ("users.invite", "auth.invite_accepted", "auth.login"):
        assert needed in actions
    assert token not in (audit_dir / "audit.log").read_text()


def test_accept_existing_account_without_org(
    client: TestClient, owner: str, mails: MailRecorder, b04_world: B04World
) -> None:
    email = unique_email("loner")
    sql(
        b04_world.db_url,
        "insert into users (email, password_hash) values ($1, $2)",
        email,
        hash_password(B04_PW),
    )
    call(client, "POST", "/users/invite", owner, T, json={"email": email, "role_key": "user"})
    token = mails.token_for(email)
    assert (
        call(client, "POST", "/auth/invitation", None, json={"token": token}).json()[
            "existing_account"
        ]
        is True
    )
    # D8: an invite link can NEVER set a password on an existing account.
    bad = call(
        client,
        "POST",
        "/auth/accept-invite",
        None,
        json={"token": token, "password": NEW_PW, "full_name": "Hijack"},
    )
    assert bad.status_code == 400
    assert login(client, email, B04_PW)  # old password still works
    ok = call(
        client, "POST", "/auth/accept-invite", None, json={"token": token, "password": B04_PW}
    )
    assert ok.status_code == 200
    me = call(client, "GET", "/me", login(client, email)).json()
    assert me["org"]["slug"] == T and me["roles"] == ["user"] and me["is_verified"] is True


def test_invitation_expired_and_reissued(
    client: TestClient, owner: str, mails: MailRecorder, b04_world: B04World
) -> None:
    email = unique_email("exp")
    call(client, "POST", "/users/invite", owner, T, json={"email": email, "role_key": "user"})
    first = mails.token_for(email)
    r = call(client, "POST", "/users/invite", owner, T, json={"email": email, "role_key": "staff"})
    assert r.status_code == 201
    second = mails.token_for(email)
    assert first != second
    assert call(client, "POST", "/auth/invitation", None, json={"token": first}).status_code == 400
    info = call(client, "POST", "/auth/invitation", None, json={"token": second}).json()
    assert info["role_key"] == "staff"  # D11: re-issue updates the role
    pending = [
        i for i in call(client, "GET", "/invitations", owner, T).json() if i["email"] == email
    ]
    assert len(pending) == 1
    sql(
        b04_world.db_url,
        "update invitations set expires_at = now() - interval '1 s' where email=$1",
        email,
    )
    assert (
        call(
            client,
            "POST",
            "/auth/accept-invite",
            None,
            json={"token": second, "password": NEW_PW, "full_name": "Late"},
        ).status_code
        == 400
    )
    listed = [
        i for i in call(client, "GET", "/invitations", owner, T).json() if i["email"] == email
    ]
    assert listed[0]["expired"] is True


def test_invite_conflicts_and_rank_rules(
    client: TestClient, owner: str, admin: str, b04_world: B04World
) -> None:
    def invite(token: str, email: str, role: str) -> Any:
        return call(
            client, "POST", "/users/invite", token, T, json={"email": email, "role_key": role}
        )

    other = invite(owner, b04_world.users["other_owner"], "user")  # member of beta4
    assert other.status_code == 409 and "already a member" in other.json()["error"]["message"]
    assert invite(owner, b04_world.users["staff"], "user").status_code == 409  # same org
    assert invite(owner, b04_world.users["platform"], "user").status_code == 409  # D2
    assert invite(admin, unique_email(), "owner").status_code == 403  # D6
    assert invite(admin, unique_email(), "admin").status_code == 201  # same rank is fine
    assert invite(owner, unique_email(), "nope").status_code == 422


def test_revoke_invitation(client: TestClient, owner: str, admin: str, mails: MailRecorder) -> None:
    owner_inv = call(
        client,
        "POST",
        "/users/invite",
        owner,
        T,
        json={"email": unique_email("own"), "role_key": "owner"},
    ).json()["invitation"]
    staff_email = unique_email("st")
    staff_inv = call(
        client, "POST", "/users/invite", owner, T, json={"email": staff_email, "role_key": "staff"}
    ).json()["invitation"]
    assert call(client, "DELETE", f"/invitations/{owner_inv['id']}", admin, T).status_code == 403
    assert call(client, "DELETE", f"/invitations/{staff_inv['id']}", admin, T).status_code == 204
    assert call(client, "DELETE", f"/invitations/{staff_inv['id']}", admin, T).status_code == 404
    token = mails.token_for(staff_email)
    assert call(client, "POST", "/auth/invitation", None, json={"token": token}).status_code == 400


# --------------------------------------------------------------------------- #
# members: list / get / patch / (de)activate
# --------------------------------------------------------------------------- #
def test_list_members_search_filter_paginate(
    client: TestClient, owner: str, b04_world: B04World
) -> None:
    r = call(client, "GET", "/users?page_size=2&page=1", owner, T).json()
    assert len(r["items"]) == 2 and r["total"] >= 6 and r["page_size"] == 2
    emails = [m["email"] for m in r["items"]]
    assert emails == sorted(emails)
    q = call(client, "GET", "/users?q=MANAGER@acme4", owner, T).json()
    assert [m["email"] for m in q["items"]] == [b04_world.users["manager"]]
    assert q["items"][0]["roles"] == ["manager"]
    wildcard = call(client, "GET", "/users?q=%25", owner, T).json()  # literal '%', not "all"
    assert wildcard["total"] == 0
    assert call(client, "GET", "/users?page_size=101", owner, T).status_code == 422
    assert call(client, "GET", "/users?status=weird", owner, T).status_code == 422


def test_patch_member_and_rank_guard(
    client: TestClient, owner: str, admin: str, b04_world: B04World
) -> None:
    uid, _ = add_member(b04_world.db_url, T, "staff")
    r = call(client, "PATCH", f"/users/{uid}", admin, T, json={"full_name": "Renamed Staff"})
    assert r.status_code == 200 and r.json()["full_name"] == "Renamed Staff"
    owner_id = sql(
        b04_world.db_url, "select id from users where email=$1", b04_world.users["owner"]
    )[0][0]
    assert (
        call(
            client, "PATCH", f"/users/{owner_id}", admin, T, json={"full_name": "Hacked"}
        ).status_code
        == 403
    )
    assert call(client, "GET", f"/users/{uid}", admin, T).json()["full_name"] == "Renamed Staff"


def test_deactivate_is_immediate_and_reversible(
    client: TestClient, owner: str, b04_world: B04World, audit_dir: Path
) -> None:
    uid, email = add_member(b04_world.db_url, T, "staff")
    staff_token = login(client, email)
    assert call(client, "GET", "/org", staff_token, T).status_code == 200

    r = call(client, "POST", f"/users/{uid}/deactivate", owner, T)
    assert r.status_code == 200 and r.json()["status"] == "inactive"
    # C3: the still-unexpired access token is useless at once.
    assert call(client, "GET", "/org", staff_token, T).status_code == 401
    assert client.post("/auth/login", json={"email": email, "password": B04_PW}).status_code == 401
    assert (
        sql(
            b04_world.db_url,
            "select count(*) from refresh_tokens where user_id=$1 and revoked_at is null",
            uid,
        )[0][0]
        == 0
    )
    listed = call(client, "GET", "/users?status=inactive", owner, T).json()
    assert email in {m["email"] for m in listed["items"]}

    assert call(client, "POST", f"/users/{uid}/activate", owner, T).json()["status"] == "active"
    assert call(client, "GET", "/org", login(client, email), T).status_code == 200
    acts = [x["action"] for x in audit_lines(audit_dir)]
    assert "users.deactivate" in acts and "users.activate" in acts


def test_deactivate_guards(client: TestClient, b04_world: B04World) -> None:
    # A private tenant setup inside acme4: two owners + an admin.
    o1, e1 = add_member(b04_world.db_url, T, "owner")
    o2, e2 = add_member(b04_world.db_url, T, "owner")
    _, ea = add_member(b04_world.db_url, T, "admin")
    t1, ta = login(client, e1), login(client, ea)
    assert call(client, "POST", f"/users/{o1}/deactivate", t1, T).status_code == 409  # self
    assert call(client, "POST", f"/users/{o2}/deactivate", ta, T).status_code == 403  # rank
    # Several owners exist (world owner + o1 + o2), so o2 can go.
    assert call(client, "POST", f"/users/{o2}/deactivate", t1, T).status_code == 200


def test_last_owner_is_protected(client: TestClient, b04_world: B04World) -> None:
    """beta4 has exactly one owner."""
    token = login(client, b04_world.users["other_owner"])
    owner_id = sql(
        b04_world.db_url, "select id from users where email=$1", b04_world.users["other_owner"]
    )[0][0]
    r = call(
        client, "PUT", f"/users/{owner_id}/roles", token, "beta4", json={"role_keys": ["admin"]}
    )
    assert r.status_code == 409 and "last active owner" in r.json()["error"]["message"]
    uid, _ = add_member(b04_world.db_url, "beta4", "admin")
    assert call(client, "POST", f"/users/{owner_id}/deactivate", token, "beta4").status_code == 409


# --------------------------------------------------------------------------- #
# roles
# --------------------------------------------------------------------------- #
def test_assign_roles_updates_permissions_at_once(
    client: TestClient, owner: str, admin: str, b04_world: B04World
) -> None:
    uid, email = add_member(b04_world.db_url, T, "staff")
    member = login(client, email)
    before = call(client, "GET", "/me", member, T).json()
    assert "users:read" not in before["permissions"]  # warms the permission cache

    r = call(
        client,
        "PUT",
        f"/users/{uid}/roles",
        admin,
        T,
        json={"role_keys": ["manager", "staff", "manager"]},
    )
    assert r.status_code == 200 and r.json()["roles"] == ["manager", "staff"]
    after = call(client, "GET", "/me", member, T).json()
    assert "users:read" in after["permissions"]  # D12: cache dropped, no 60 s wait
    assert after["landing_path"] == "/home/manager"

    assert (
        call(
            client, "PUT", f"/users/{uid}/roles", admin, T, json={"role_keys": ["owner"]}
        ).status_code
        == 403
    )  # D6
    assert (
        call(client, "PUT", f"/users/{uid}/roles", admin, T, json={"role_keys": []}).status_code
        == 422
    )
    assert (
        call(
            client, "PUT", f"/users/{uid}/roles", admin, T, json={"role_keys": ["boss"]}
        ).status_code
        == 422
    )
    assert (
        call(
            client, "PUT", f"/users/{uid}/roles", owner, T, json={"role_keys": ["owner"]}
        ).status_code
        == 200
    )
    owner_id = sql(
        b04_world.db_url, "select id from users where email=$1", b04_world.users["owner"]
    )[0][0]
    assert (
        call(
            client, "PUT", f"/users/{owner_id}/roles", admin, T, json={"role_keys": ["user"]}
        ).status_code
        == 403
    )


def test_roles_and_permissions_lists(client: TestClient, owner: str) -> None:
    roles = call(client, "GET", "/roles", owner, T).json()
    assert [r["key"] for r in roles] == ["owner", "admin", "manager", "staff", "user"]
    assert "org:update" in roles[0]["permissions"] and "org:update" not in roles[1]["permissions"]
    perms = {p["key"] for p in call(client, "GET", "/permissions", owner, T).json()}
    assert {"users:invite", "platform:manage"} <= perms


# --------------------------------------------------------------------------- #
# org + me
# --------------------------------------------------------------------------- #
def test_org_read_and_update(client: TestClient, owner: str, audit_dir: Path) -> None:
    org = call(client, "GET", "/org", owner, T).json()
    assert org["slug"] == T and org["display_name"] == "Acme Four"
    new = f"Acme Display {uuid.uuid4().hex[:4]}"
    r = call(client, "PATCH", "/org", owner, T, json={"display_name": new})
    assert r.status_code == 200 and r.json()["display_name"] == new and r.json()["slug"] == T
    assert call(client, "PATCH", "/org", owner, T, json={}).status_code == 422
    assert call(client, "PATCH", "/org", owner, T, json={"name": "   "}).status_code == 422
    assert any(x["action"] == "org.update" for x in audit_lines(audit_dir))


def test_patch_me(client: TestClient, b04_world: B04World) -> None:
    _, email = add_member(b04_world.db_url, T, "user")
    token = login(client, email)
    r = call(client, "PATCH", "/me", token, json={"full_name": "Me Myself"})
    assert r.status_code == 200 and r.json()["full_name"] == "Me Myself"
    assert call(client, "PATCH", "/me", token, json={"full_name": ""}).status_code == 422


def test_me_without_org(client: TestClient, b04_world: B04World) -> None:
    email = unique_email("orphan")
    sql(
        b04_world.db_url,
        "insert into users (email, password_hash, is_verified) values ($1, $2, true)",
        email,
        hash_password(B04_PW),
    )
    me = call(client, "GET", "/me", login(client, email)).json()
    assert me["org"] is None and me["landing_path"] is None and me["permissions"] == []  # D15
