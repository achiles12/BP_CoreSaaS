"""Shared helpers for the B04 API tests (not a test module)."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import asyncpg
from fastapi.testclient import TestClient

from app.core.security import ACCESS_COOKIE, hash_password
from tests.conftest import B04_PW

_n = iter(range(1, 100_000))


def sql(url: str, query: str, *args: Any) -> list[asyncpg.Record]:
    async def go() -> list[asyncpg.Record]:
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg", "postgresql"))
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return asyncio.run(go())


def unique_email(prefix: str = "m") -> str:
    return f"{prefix}{next(_n):05d}-{uuid.uuid4().hex[:4]}@b04.test"


def add_member(
    url: str, slug: str, role: str | None, email: str | None = None, *, verified: bool = True
) -> tuple[uuid.UUID, str]:
    """Fresh member for tests that mutate state (keeps the shared world intact)."""
    email = email or unique_email(role or "norole")
    uid = sql(
        url,
        "insert into users (email, password_hash, full_name, is_verified) "
        "values ($1,$2,'Temp Member',$3) returning id",
        email,
        hash_password(B04_PW),
        verified,
    )[0][0]
    org_id = sql(url, "select id from organizations where slug=$1", slug)[0][0]
    sql(url, "insert into org_memberships (user_id, org_id) values ($1,$2)", uid, org_id)
    if role:
        sql(
            url,
            f'insert into "tenant_{slug}".user_roles (user_id, role_id) '  # noqa: S608
            f'select $1, id from "tenant_{slug}".roles where key=$2',
            uid,
            role,
        )
    return uid, email


def login(c: TestClient, email: str, password: str = B04_PW) -> str:
    c.cookies.clear()  # one access_token in the jar at a time
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = c.cookies.get(ACCESS_COOKIE)
    assert token
    return token


def call(
    c: TestClient, method: str, path: str, token: str | None, tenant: str | None = None, **kw: Any
) -> Any:
    """One request as a given user (access cookie) in a given tenant."""
    c.cookies.clear()
    if token:
        c.cookies.set(ACCESS_COOKIE, token)
    headers = dict(kw.pop("headers", {}) or {})
    if tenant is not None:
        headers["X-Tenant"] = tenant
    return c.request(method, path, headers=headers, **kw)


def audit_lines(audit_dir: Path) -> list[dict]:
    f = audit_dir / "audit.log"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []
