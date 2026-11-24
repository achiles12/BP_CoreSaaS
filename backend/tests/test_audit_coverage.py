"""C7: one audit line for every mutation (B12 D5, critical_user_flow C7).

Every POST/PUT/PATCH/DELETE route the app mounts must be classified:
- RECIPES: a setup plus ONE valid call, and the exact audit action(s) that call
  must append (with the right org and actor, and without the password or token
  that was sent);
- NO_AUDIT: routes that write no line on purpose, each with its reason.
A new route that is in neither fails test_every_mutation_route_is_classified.

Uses the B04 world (acme4) + the session RustFS (file confirm). Members whose
state changes are created fresh, so the shared world stays intact.
"""

import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import mail
from app.main import create_app
from tests.b04_helpers import B04_PW, add_member, call, login, sql
from tests.conftest import B04World
from tests.route_catalog import mutation_routes

pytestmark = pytest.mark.integration
T = "acme4"
NEW_PW = "b12-new-pass-2026-x"

# Routes that write no audit line on purpose (critical_user_flow C7 asks for
# one per MUTATION; these change nothing a person would audit).
NO_AUDIT: dict[tuple[str, str], str] = {
    (
        "POST",
        "/auth/refresh",
    ): "token rotation, not a business change; reuse IS audited (auth.refresh_reuse)",
    ("POST", "/auth/invitation"): "read only: shows the org/role of an invitation token",
    (
        "POST",
        "/files/presign-upload",
    ): "only a pending row; the upload is audited at confirm (files.upload)",
}


@dataclass
class Call:
    method: str
    path: str
    token: str | None
    tenant: str | None
    actions: list[str]  # exactly these new lines, in order
    actor: str | None = None  # expected actor (user id), None = not checked
    org: str | None = None  # expected org slug, None = not checked
    kw: dict[str, Any] = field(default_factory=dict)
    secrets: list[str] = field(default_factory=list)  # must not appear in the lines
    # Undo a change to the SHARED B04 world after the check (other modules
    # assert its original state, e.g. acme4's display name).
    cleanup: Callable[[], Any] | None = None


class Mails:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def __call__(
        self, redis: Any, template: str, to: str, context: dict, *, org_slug: str | None = None
    ) -> str:
        self.sent.append({"template": template, "to": to, "context": context})
        return f"job-{len(self.sent)}"

    def token(self, to: str, template: str) -> str:
        hits = [m for m in self.sent if m["to"] == to and m["template"] == template]
        assert hits, f"no {template} mail to {to}"
        return parse_qs(urlparse(hits[-1]["context"]["link"]).query)["token"][0]


@dataclass
class Ctx:
    c: TestClient
    world: B04World
    mails: Mails
    owner: str  # token
    owner_id: str

    def member(self, role: str = "user", verified: bool = True) -> tuple[str, str]:
        uid, email = add_member(self.world.db_url, T, role, verified=verified)
        return str(uid), email


@pytest.fixture
def ctx(
    b05_settings: Settings, b04_world: B04World, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Ctx]:
    mails = Mails()
    monkeypatch.setattr(mail, "queue_email", mails)
    with TestClient(create_app(b05_settings)) as c:
        owner = login(c, b04_world.users["owner"])
        oid = str(
            sql(b04_world.db_url, "select id from users where email=$1", b04_world.users["owner"])[
                0
            ]["id"]
        )
        yield Ctx(c, b04_world, mails, owner, oid)


def _uuid() -> str:
    return uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------- #
# recipes: setup + one call
# --------------------------------------------------------------------------- #
def r_login(x: Ctx) -> Call:
    uid, email = x.member()
    return Call(
        "POST",
        "/auth/login",
        None,
        None,
        ["auth.login"],
        actor=uid,
        kw={"json": {"email": email, "password": B04_PW}},
        secrets=[B04_PW],
    )


def r_logout(x: Ctx) -> Call:
    uid, email = x.member()
    return Call("POST", "/auth/logout", login(x.c, email), None, ["auth.logout"], actor=uid)


def r_forgot(x: Ctx) -> Call:
    uid, email = x.member()
    return Call(
        "POST",
        "/auth/forgot-password",
        None,
        None,
        ["auth.password_reset_requested"],
        kw={"json": {"email": email}},
    )


def r_reset(x: Ctx) -> Call:
    uid, email = x.member()
    x.c.post("/auth/forgot-password", json={"email": email})
    token = x.mails.token(email, "reset_password")
    return Call(
        "POST",
        "/auth/reset-password",
        None,
        None,
        ["auth.password_reset"],
        actor=uid,
        kw={"json": {"token": token, "new_password": NEW_PW}},
        secrets=[token, NEW_PW],
    )


def r_resend(x: Ctx) -> Call:
    uid, email = x.member(verified=False)
    return Call(
        "POST",
        "/auth/resend-verification",
        login(x.c, email),
        None,
        ["auth.verification_sent"],
        actor=uid,
    )


def r_verify(x: Ctx) -> Call:
    uid, email = x.member(verified=False)
    call(x.c, "POST", "/auth/resend-verification", login(x.c, email))
    token = x.mails.token(email, "verify_email")
    return Call(
        "POST",
        "/auth/verify-email",
        None,
        None,
        ["auth.email_verified"],
        actor=uid,
        kw={"json": {"token": token}},
        secrets=[token],
    )


def r_change_pw(x: Ctx) -> Call:
    uid, email = x.member()
    return Call(
        "POST",
        "/auth/change-password",
        login(x.c, email),
        None,
        ["auth.password_changed"],
        actor=uid,
        kw={"json": {"current_password": B04_PW, "new_password": NEW_PW}},
        secrets=[B04_PW, NEW_PW],
    )


def r_accept(x: Ctx) -> Call:
    email = f"b12acc-{_uuid()}@b12.test"
    r = call(x.c, "POST", "/users/invite", x.owner, T, json={"email": email, "role_key": "user"})
    assert r.status_code == 201, r.text
    token = x.mails.token(email, "invite_user")
    return Call(
        "POST",
        "/auth/accept-invite",
        None,
        None,
        ["auth.invite_accepted"],
        org=T,
        kw={"json": {"token": token, "full_name": "B12 Accept", "password": NEW_PW}},
        secrets=[token, NEW_PW],
    )


def r_update_me(x: Ctx) -> Call:
    uid, email = x.member()
    return Call(
        "PATCH",
        "/me",
        login(x.c, email),
        None,
        ["users.update_self"],
        actor=uid,
        kw={"json": {"full_name": f"B12 {_uuid()}"}},
    )


def r_export(x: Ctx) -> Call:
    return Call(
        "POST",
        "/exports",
        x.owner,
        T,
        ["exports.create"],
        actor=x.owner_id,
        org=T,
        kw={"json": {"resource": "items", "format": "csv"}},
    )


def r_confirm(x: Ctx) -> Call:
    r = call(
        x.c,
        "POST",
        "/files/presign-upload",
        x.owner,
        T,
        json={"name": f"b12-{_uuid()}.txt", "mime_type": "text/plain", "size_bytes": 5},
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert httpx.put(p["upload_url"], content=b"hello", headers=p["headers"]).status_code == 200
    return Call(
        "POST",
        f"/files/{p['file_id']}/confirm",
        x.owner,
        T,
        ["files.upload"],
        actor=x.owner_id,
        org=T,
    )


def r_file_delete(x: Ctx) -> Call:
    fid = sql(
        x.world.db_url,
        'insert into "tenant_acme4".files '
        "(name, mime_type, size_bytes, object_key, uploaded_by, status) "
        "values ('b12-del.txt', 'text/plain', 5, $1, $2, 'active') returning id",
        f"b12/{uuid.uuid4()}",
        uuid.UUID(x.owner_id),
    )[0]["id"]
    return Call("DELETE", f"/files/{fid}", x.owner, T, ["files.delete"], actor=x.owner_id, org=T)


def r_revoke(x: Ctx) -> Call:
    r = call(
        x.c,
        "POST",
        "/users/invite",
        x.owner,
        T,
        json={"email": f"b12rev-{_uuid()}@b12.test", "role_key": "user"},
    )
    assert r.status_code == 201, r.text
    return Call(
        "DELETE",
        f"/invitations/{r.json()['invitation']['id']}",
        x.owner,
        T,
        ["users.invitation_revoked"],
        actor=x.owner_id,
        org=T,
    )


def _item(x: Ctx) -> str:
    r = call(x.c, "POST", "/items", x.owner, T, json={"title": f"b12 {_uuid()}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def r_item_create(x: Ctx) -> Call:
    return Call(
        "POST",
        "/items",
        x.owner,
        T,
        ["items.create"],
        actor=x.owner_id,
        org=T,
        kw={"json": {"title": f"b12 {_uuid()}"}},
    )


def r_item_update(x: Ctx) -> Call:
    return Call(
        "PATCH",
        f"/items/{_item(x)}",
        x.owner,
        T,
        ["items.update"],
        actor=x.owner_id,
        org=T,
        kw={"json": {"status": "done"}},
    )


def r_item_delete(x: Ctx) -> Call:
    return Call(
        "DELETE", f"/items/{_item(x)}", x.owner, T, ["items.delete"], actor=x.owner_id, org=T
    )


def _notification(x: Ctx) -> str:
    return str(
        sql(
            x.world.db_url,
            'insert into "tenant_acme4".notifications (user_id, type, title) '
            "values ($1, 'b12', 'b12') returning id",
            uuid.UUID(x.owner_id),
        )[0]["id"]
    )


def r_note_read(x: Ctx) -> Call:
    return Call(
        "POST",
        f"/notifications/{_notification(x)}/read",
        x.owner,
        T,
        ["notifications.read"],
        actor=x.owner_id,
        org=T,
    )


def r_note_read_all(x: Ctx) -> Call:
    _notification(x)
    return Call(
        "POST",
        "/notifications/read-all",
        x.owner,
        T,
        ["notifications.read_all"],
        actor=x.owner_id,
        org=T,
    )


def r_org(x: Ctx) -> Call:
    original = call(x.c, "GET", "/org", x.owner, T).json()["display_name"]
    return Call(
        "PATCH",
        "/org",
        x.owner,
        T,
        ["org.update"],
        actor=x.owner_id,
        org=T,
        kw={"json": {"display_name": f"Acme {_uuid()}"}},
        cleanup=lambda: call(x.c, "PATCH", "/org", x.owner, T, json={"display_name": original}),
    )


def r_invite(x: Ctx) -> Call:
    return Call(
        "POST",
        "/users/invite",
        x.owner,
        T,
        ["users.invite"],
        actor=x.owner_id,
        org=T,
        kw={"json": {"email": f"b12inv-{_uuid()}@b12.test", "role_key": "user"}},
    )


def r_user_update(x: Ctx) -> Call:
    uid, _ = x.member()
    return Call(
        "PATCH",
        f"/users/{uid}",
        x.owner,
        T,
        ["users.update"],
        actor=x.owner_id,
        org=T,
        kw={"json": {"full_name": f"B12 {_uuid()}"}},
    )


def r_deactivate(x: Ctx) -> Call:
    uid, _ = x.member()
    return Call(
        "POST",
        f"/users/{uid}/deactivate",
        x.owner,
        T,
        ["users.deactivate"],
        actor=x.owner_id,
        org=T,
    )


def r_activate(x: Ctx) -> Call:
    uid, _ = x.member()
    assert call(x.c, "POST", f"/users/{uid}/deactivate", x.owner, T).status_code == 200
    return Call(
        "POST", f"/users/{uid}/activate", x.owner, T, ["users.activate"], actor=x.owner_id, org=T
    )


def r_roles(x: Ctx) -> Call:
    uid, _ = x.member("staff")
    return Call(
        "PUT",
        f"/users/{uid}/roles",
        x.owner,
        T,
        ["roles.assign"],
        actor=x.owner_id,
        org=T,
        kw={"json": {"role_keys": ["user"]}},
    )


RECIPES: dict[tuple[str, str], Callable[[Ctx], Call]] = {
    ("POST", "/auth/login"): r_login,
    ("POST", "/auth/logout"): r_logout,
    ("POST", "/auth/forgot-password"): r_forgot,
    ("POST", "/auth/reset-password"): r_reset,
    ("POST", "/auth/resend-verification"): r_resend,
    ("POST", "/auth/verify-email"): r_verify,
    ("POST", "/auth/change-password"): r_change_pw,
    ("POST", "/auth/accept-invite"): r_accept,
    ("PATCH", "/me"): r_update_me,
    ("POST", "/exports"): r_export,
    ("POST", "/files/{file_id}/confirm"): r_confirm,
    ("DELETE", "/files/{file_id}"): r_file_delete,
    ("DELETE", "/invitations/{invitation_id}"): r_revoke,
    ("POST", "/items"): r_item_create,
    ("PATCH", "/items/{item_id}"): r_item_update,
    ("DELETE", "/items/{item_id}"): r_item_delete,
    ("POST", "/notifications/{notification_id}/read"): r_note_read,
    ("POST", "/notifications/read-all"): r_note_read_all,
    ("PATCH", "/org"): r_org,
    ("POST", "/users/invite"): r_invite,
    ("PATCH", "/users/{user_id}"): r_user_update,
    ("POST", "/users/{user_id}/deactivate"): r_deactivate,
    ("POST", "/users/{user_id}/activate"): r_activate,
    ("PUT", "/users/{user_id}/roles"): r_roles,
}


def test_every_mutation_route_is_classified() -> None:
    routes = {(r.method, r.path) for r in mutation_routes()}
    both = set(RECIPES) & set(NO_AUDIT)
    assert not both, f"in RECIPES and NO_AUDIT: {both}"
    unclassified = routes - set(RECIPES) - set(NO_AUDIT)
    assert not unclassified, (
        f"mutation routes with no audit recipe and no NO_AUDIT reason: {sorted(unclassified)}"
    )
    stale = (set(RECIPES) | set(NO_AUDIT)) - routes
    assert not stale, f"recipes for routes that no longer exist: {sorted(stale)}"


def _lines(audit_dir: Path) -> list[dict[str, Any]]:
    f = audit_dir / "audit.log"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


@pytest.mark.parametrize("route", sorted(RECIPES), ids=lambda k: f"{k[0]} {k[1]}")
def test_mutation_writes_its_audit_line(ctx: Ctx, audit_dir: Path, route: tuple[str, str]) -> None:
    spec = RECIPES[route](ctx)  # setup may write lines of its own; count after it
    try:
        _check(ctx, audit_dir, spec)
    finally:
        if spec.cleanup:
            spec.cleanup()


def _check(ctx: Ctx, audit_dir: Path, spec: Call) -> None:
    before = len(_lines(audit_dir))
    r = call(ctx.c, spec.method, spec.path, spec.token, spec.tenant, **spec.kw)
    assert r.status_code < 300, f"{spec.method} {spec.path} -> {r.status_code}: {r.text}"
    new = _lines(audit_dir)[before:]
    assert [ln["action"] for ln in new] == spec.actions, new
    for ln in new:
        if spec.actor:
            assert ln["actor"] == spec.actor, ln
        if spec.org:
            assert ln["org"] == spec.org, ln
        text = json.dumps(ln)
        for secret in spec.secrets:
            assert secret not in text, f"{ln['action']} line contains a secret value"
