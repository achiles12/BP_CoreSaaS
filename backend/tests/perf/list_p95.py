"""p95 gate for list endpoints on 10 000 rows (critical_user_flow.md, B13).

Run INSIDE the backend container against the running API (make perf):
    docker compose exec -T backend python - < backend/tests/perf/list_p95.py

Uses a throwaway tenant `perf`, removed at the end. Refuses to run if an org
`perf`, its schema or its user already exists, so it can never delete real data.
Exit: 0 all p95 < LIMIT_MS, 1 over the limit or a non-200 answer, 2 refused.
"""

import asyncio
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings
from app.core import audit, db
from app.core.security import access_cookie
from app.modules.organizations.provisioning import provision_tenant

API = "http://localhost:8200"
SLUG, SCHEMA, EMAIL, PW = "perf", "tenant_perf", "owner@perf.test", "Perf-pass-2026-ok"  # noqa: S105
ROWS, REQUESTS, LIMIT_MS = 10_000, 100, 300.0

PATHS = [
    "/items?page_size=50",
    "/items?page_size=50&sort=title",
    "/items?page_size=50&filter%5Bstatus%5D=open",
    "/items?page_size=50&q=number%2042",
    f"/items?page_size=50&page={ROWS // 50}",
    "/files?page_size=50",
    "/notifications?page_size=50",
    "/search?q=number",
]

INSERTS = [
    "insert into {s}._template_items (title, description, status, owner_id) "
    "select 'Item number ' || g, 'Perf row ' || g, "
    "(array['open','in_progress','done'])[1 + g % 3], :u from generate_series(1, :n) g",
    "insert into {s}.files (name, mime_type, size_bytes, object_key, status, uploaded_by) "
    "select 'file number ' || g || '.txt', 'text/plain', g, 'perf/' || g, 'active', :u "
    "from generate_series(1, :n) g",
    "insert into {s}.notifications (user_id, type, title) "
    "select :u, 'perf.row', 'Notice number ' || g from generate_series(1, :n) g",
]


def login(cookie: str) -> str:
    body = f'{{"email":"{EMAIL}","password":"{PW}"}}'.encode()
    req = urllib.request.Request(
        f"{API}/auth/login", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        for h in r.headers.get_all("Set-Cookie"):
            if h.startswith(f"{cookie}="):
                return h.split(";", 1)[0]
    raise RuntimeError("login set no access cookie")


def measure(path: str, cookie_header: str) -> tuple[float, float]:
    times = []
    for i in range(REQUESTS + 3):
        req = urllib.request.Request(
            API + path, headers={"X-Tenant": SLUG, "Cookie": cookie_header}
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req) as r:
            r.read()
        if i >= 3:  # the first calls warm caches
            times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times), statistics.quantiles(times, n=20)[18]


async def main() -> int:
    s = get_settings()
    audit.init_audit(s.audit_log_dir, fail_closed=s.audit_fail_closed)
    db.init_engine(s.database_url)
    try:
        async with db.get_engine().connect() as c:
            taken = await c.scalar(
                text(
                    "select (select count(*) from public.organizations where slug=:s) "
                    "+ (select count(*) from public.users where email=:e) "
                    "+ (select count(*) from pg_namespace where nspname=:n)"
                ),
                {"s": SLUG, "e": EMAIL, "n": SCHEMA},
            )
        if taken:
            print(f"refused: org {SLUG!r}, schema {SCHEMA} or user {EMAIL} already exists")
            return 2
        try:
            return await run(s)
        finally:
            await cleanup(s)
    finally:
        await db.dispose_engine()
        audit.close_audit()


async def run(s) -> int:  # noqa: ANN001
    await provision_tenant(
        SLUG, "Perf", EMAIL, owner_password=PW, actor="perf", frontend_url=s.frontend_url
    )
    async with db.get_engine().begin() as c:
        uid = await c.scalar(text("select id from public.users where email=:e"), {"e": EMAIL})
        for q in INSERTS:
            await c.execute(text(q.format(s=SCHEMA)), {"u": uid, "n": ROWS})
    async with db.get_engine().connect() as c:
        await c.execution_options(isolation_level="AUTOCOMMIT")
        await c.execute(text("analyze"))
    cookie = await asyncio.to_thread(login, access_cookie(s))
    bad = 0
    print(f"{ROWS} rows, {REQUESTS} requests each, limit p95 < {LIMIT_MS:.0f} ms")
    for path in PATHS:
        try:
            p50, p95 = await asyncio.to_thread(measure, path, cookie)
        except urllib.error.HTTPError as exc:
            print(f"FAIL  {urllib.parse.unquote(path)}: HTTP {exc.code}")
            bad += 1
            continue
        ok = p95 < LIMIT_MS
        bad += not ok
        print(
            f"{'OK  ' if ok else 'FAIL'}  p50 {p50:6.1f}  p95 {p95:6.1f}  "
            f"{urllib.parse.unquote(path)}"
        )
    return 1 if bad else 0


async def cleanup(s) -> None:  # noqa: ANN001
    async with db.get_engine().begin() as c:
        await c.execute(text(f'drop schema if exists "{SCHEMA}" cascade'))
        for q in (
            "delete from public.org_memberships where org_id in "
            "(select id from public.organizations where slug=:s)",
            "delete from public.invitations where org_id in "
            "(select id from public.organizations where slug=:s)",
            "delete from public.refresh_tokens where user_id in "
            "(select id from public.users where email=:e)",
            "delete from public.organizations where slug=:s",
            "delete from public.users where email=:e",
        ):
            names = {"s": SLUG, "e": EMAIL}
            await c.execute(text(q), {k: v for k, v in names.items() if f":{k}" in q})
    redis = Redis.from_url(s.redis_url)
    try:
        async for key in redis.scan_iter("perm:*"):
            await redis.delete(key)
    finally:
        await redis.aclose()
    print("perf tenant removed")


sys.exit(asyncio.run(main()))
