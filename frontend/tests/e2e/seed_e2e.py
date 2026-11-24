"""Seed the e2e tenant for the Playwright suite (B12 D9).

Run INSIDE the backend container, reading this file from stdin:
    docker compose exec -T backend python - < frontend/tests/e2e/seed_e2e.py

Idempotent; every run leaves the same known state:
- tenant `e2e` exists (provisioned on first run, owner owner@e2e.test)
- one user per role + reset@e2e.test (role user) + e2e-platform@e2e.test
  (platform admin, no org), all active, verified, password E2E_PASSWORD
- each member has exactly its one role
- rate-limit counters and cached permission sets are cleared
"""

import asyncio
import sys

from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings
from app.core import audit, db
from app.core.security import hash_password
from app.modules.organizations.provisioning import provision_tenant

SLUG = "e2e"
SCHEMA = f'"tenant_{SLUG}"'
E2E_PASSWORD = "E2e-pass-2026-ok"
MEMBERS = {  # email -> (role, full name)
    "owner@e2e.test": ("owner", "E2E Owner"),
    "admin@e2e.test": ("admin", "E2E Admin"),
    "manager@e2e.test": ("manager", "E2E Manager"),
    "staff@e2e.test": ("staff", "E2E Staff"),
    "user@e2e.test": ("user", "E2E User"),
    "reset@e2e.test": ("user", "E2E Reset"),
}
PLATFORM = "e2e-platform@e2e.test"


async def upsert_user(conn, email: str, name: str, pw_hash: str, platform: bool = False):  # noqa: ANN001, ANN201
    return (
        await conn.execute(
            text(
                "insert into public.users (email, password_hash, full_name, is_verified, is_active, is_platform_admin) "
                "values (:e, :h, :n, true, true, :p) "
                "on conflict (email) do update set password_hash = :h, full_name = :n, "
                "is_verified = true, is_active = true, is_platform_admin = :p returning id"
            ),
            {"e": email, "h": pw_hash, "n": name, "p": platform},
        )
    ).scalar_one()


async def main() -> int:
    settings = get_settings()
    audit.init_audit(settings.audit_log_dir, fail_closed=settings.audit_fail_closed)
    db.init_engine(settings.database_url)
    try:
        result = await provision_tenant(
            SLUG,
            "E2E Org",
            "owner@e2e.test",
            owner_password=E2E_PASSWORD,
            actor="e2e-seed",
            frontend_url=settings.frontend_url,
        )
        print(f"tenant {SLUG}: {result.outcome}")
        pw_hash = hash_password(E2E_PASSWORD)
        async with db.get_engine().begin() as conn:
            org_id = (
                await conn.execute(text("select id from public.organizations where slug=:s"), {"s": SLUG})
            ).scalar_one()
            for email, (role, name) in MEMBERS.items():
                uid = await upsert_user(conn, email, name, pw_hash)
                await conn.execute(
                    text(
                        "insert into public.org_memberships (user_id, org_id, status) values (:u, :o, 'active') "
                        "on conflict (user_id) do update set org_id = :o, status = 'active'"
                    ),
                    {"u": uid, "o": org_id},
                )
                await conn.execute(text(f"delete from {SCHEMA}.user_roles where user_id = :u"), {"u": uid})  # noqa: S608
                await conn.execute(
                    text(
                        f"insert into {SCHEMA}.user_roles (user_id, role_id) "  # noqa: S608
                        f"select :u, id from {SCHEMA}.roles where key = :r"
                    ),
                    {"u": uid, "r": role},
                )
                print(f"  {email}: {role}")
            await upsert_user(conn, PLATFORM, "E2E Platform", pw_hash, platform=True)
            print(f"  {PLATFORM}: platform admin")
        redis = Redis.from_url(settings.redis_url)
        try:
            n = 0
            for pattern in ("rl:*", "perm:*"):
                async for key in redis.scan_iter(pattern):
                    await redis.delete(key)
                    n += 1
            print(f"  cleared {n} rate-limit / permission-cache keys")
        finally:
            await redis.aclose()
        return 0
    finally:
        await db.dispose_engine()
        audit.close_audit()


sys.exit(asyncio.run(main()))
