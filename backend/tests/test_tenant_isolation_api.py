"""B04 C2: tenant isolation through the real API (critical_user_flow.md C2)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.b04_helpers import audit_lines, call, login
from tests.conftest import B04World

pytestmark = pytest.mark.integration


@pytest.fixture
def client(b04_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(b04_settings)) as c:
        yield c


def test_other_tenant_unknown_tenant_and_injection_look_identical(
    client: TestClient, b04_world: B04World
) -> None:
    token = login(client, b04_world.users["owner"])  # acme4 owner
    bodies = set()
    for forged in (
        b04_world.other,  # a real tenant the user is NOT in
        "no_such_org",
        "acme4; DROP SCHEMA public",
        'x" or "1"="1',
        "acme-4",  # malformed (dash) -> rejected before the DB
        "a" * 64,  # too long
    ):
        r = call(client, "GET", "/users", token, forged)
        assert r.status_code == 404, (forged, r.text)
        err = r.json()["error"]
        bodies.add((err["code"], err["message"]))
    assert bodies == {("not_found", "Organization not found")}  # nothing to tell apart
    # Schema still intact after the "injection".
    assert call(client, "GET", "/users", token, b04_world.tenant).status_code == 200


def test_missing_header_is_400(client: TestClient, b04_world: B04World) -> None:
    token = login(client, b04_world.users["owner"])
    r = call(client, "GET", "/users", token)
    assert r.status_code == 400 and "X-Tenant" in r.json()["error"]["message"]


def test_lists_only_own_tenant_rows(client: TestClient, b04_world: B04World) -> None:
    a = call(
        client,
        "GET",
        "/users?page_size=100",
        login(client, b04_world.users["owner"]),
        b04_world.tenant,
    ).json()
    b = call(
        client,
        "GET",
        "/users?page_size=100",
        login(client, b04_world.users["other_owner"]),
        b04_world.other,
    ).json()
    emails_a = {m["email"] for m in a["items"]}
    emails_b = {m["email"] for m in b["items"]}
    assert b04_world.users["other_owner"] in emails_b and not emails_a & emails_b
    assert all(e.endswith("@beta4.test") for e in emails_b)


def test_me_with_foreign_header_is_404(client: TestClient, b04_world: B04World) -> None:
    token = login(client, b04_world.users["staff"])
    assert call(client, "GET", "/me", token, b04_world.other).status_code == 404


def test_platform_admin_entry_is_audited(
    client: TestClient, b04_world: B04World, audit_dir: Path
) -> None:
    token = login(client, b04_world.users["platform"])
    r = call(client, "GET", "/users", token, b04_world.other)
    assert r.status_code == 200  # D13: full access...
    entries = [x for x in audit_lines(audit_dir) if x["action"] == "tenancy.platform_admin_access"]
    assert entries and entries[-1]["org"] == b04_world.other  # ...but always on record
