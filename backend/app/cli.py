"""Developer / operator CLI (design B02 §3.10, backend_processes.md §3).

Run inside the backend container (the Makefile does this for you):
    python -m app.cli <command> [options]
    python -m app.cli --help

Conventions:
- Human-readable summary on STDOUT; JSON logs on STDERR (WARNING and up,
  or everything with `-v`).
- Mutating commands write an audit line with actor "cli:<user>", where the
  user is $CLI_USER (set by make to the host login) or the OS user.
- Exit codes: 0 ok, 1 handled error, 2 bad usage (click).
"""

import asyncio
import getpass
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import click
import structlog
from arq.connections import ArqRedis
from pydantic import ValidationError
from sqlalchemy import func, select, update

from app.config import Settings, get_settings
from app.core import audit, db, mail, migrations
from app.core.errors import AppError, Conflict, NotFound
from app.core.logging import configure_logging
from app.core.permissions import PLATFORM_ADMIN_RANK
from app.core.security import WeakPasswordError, hash_password, validate_password_strength
from app.core.tenancy import TenantContext, tenant_session
from app.models.public import Organization, OrgMembership, User
from app.modules.auth.schemas import normalise_email
from app.modules.auth.service import create_verification, revoke_user_sessions
from app.modules.exports.cleanup import expire_exports
from app.modules.files.cleanup import purge_orphan_files
from app.modules.organizations import demo_seed
from app.modules.organizations.provisioning import provision_tenant
from app.modules.rbac.seed import sync_permissions
from app.modules.users.service import create_invitation

log = structlog.get_logger("app.cli")

# Statuses whose schemas exist and must follow tenant migrations.
MIGRATABLE_STATUSES = ("active", "suspended")


def cli_actor() -> str:
    return "cli:" + (os.environ.get("CLI_USER") or getpass.getuser())


# Set by the group's --verbose flag. CLI output is for humans: JSON logs are
# shown from WARNING up unless -v asks for the full INFO stream.
_verbose = False


def _run(coro_fn: Callable[[Settings], Awaitable[Any]]) -> Any:
    """Common wrapper: logging, audit, engine lifecycle and error -> exit code."""
    settings = get_settings()
    configure_logging(settings.log_level if _verbose else "WARNING", stream=sys.stderr)

    async def main() -> Any:
        audit.init_audit(settings.audit_log_dir, fail_closed=settings.audit_fail_closed)
        db.init_engine(settings.database_url)
        try:
            return await coro_fn(settings)
        finally:
            await db.dispose_engine()
            audit.close_audit()

    try:
        return asyncio.run(main())
    except AppError as exc:
        click.secho(f"error: {exc.message}", fg="red", err=True)
        sys.exit(1)
    except Exception as exc:
        log.exception("cli.unexpected_error")
        click.secho(f"error: {type(exc).__name__}: {exc}", fg="red", err=True)
        sys.exit(1)


# Shared by the single commands and `init`.
async def _migrate_all(_: Settings) -> int:
    before = await migrations.current_public_revision()
    after = await migrations.upgrade_public()
    click.echo(f"public: {before or 'base'} -> {after}")
    async with db.get_session_factory()() as s:
        orgs = (
            await s.execute(
                select(Organization.slug, Organization.schema_name)
                .where(Organization.status.in_(MIGRATABLE_STATUSES))
                .order_by(Organization.slug)
            )
        ).all()
    failed = 0
    for slug, schema in orgs:
        # One tenant failing must not stop the others (system_design §13).
        try:
            t_before = await migrations.current_tenant_revision(schema)
            t_after = await migrations.upgrade_tenant(schema)
            click.echo(f"{slug}: {t_before or 'base'} -> {t_after} ok")
        except Exception as exc:
            failed += 1
            log.exception("cli.tenant_migration_failed", slug=slug)
            click.secho(f"{slug}: FAILED {type(exc).__name__}: {exc}", fg="red")
    click.echo(f"{len(orgs)} tenant(s), {failed} failed")
    audit.record(
        "migrations.all",
        actor=cli_actor(),
        result="ok" if not failed else "error",
        diff={"tenants": len(orgs), "failed": failed},
    )
    return failed


async def _sync_permissions(_: Settings) -> None:
    async with db.get_session_factory()() as s:
        orgs = (
            await s.execute(
                select(Organization.slug, Organization.schema_name)
                .where(Organization.status.in_(MIGRATABLE_STATUSES))
                .order_by(Organization.slug)
            )
        ).all()
    total = 0
    for slug, schema in orgs:
        async with tenant_session(schema) as ts:
            added = await sync_permissions(ts)
        total += added
        click.echo(f"{slug}: {added} new permission key(s)")
    audit.record(
        "rbac.permissions_synced",
        actor=cli_actor(),
        diff={"tenants": len(orgs), "added": total},
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Show INFO-level JSON logs on stderr.")
def cli(verbose: bool) -> None:
    """Core SaaS scaffold: platform administration commands."""
    global _verbose
    _verbose = verbose


# --------------------------------------------------------------------------- #
@cli.command("create-tenant")
@click.option("--slug", required=True, help="Tenant slug: X-Tenant value, schema tenant_<slug>.")
@click.option("--name", required=True, help="Organization display name.")
@click.option("--owner-email", required=True, help="Email of the Owner.")
@click.option(
    "--owner-password",
    "prompt_password",
    is_flag=True,
    help="Prompt for a password and create an ACTIVE owner now (default: invitation link).",
)
def create_tenant(slug: str, name: str, owner_email: str, prompt_password: bool) -> None:
    """Create a tenant (idempotent: re-run to resume a failed attempt)."""
    password: str | None = None
    if prompt_password:
        password = click.prompt("Owner password", hide_input=True, confirmation_prompt=True)
        try:
            validate_password_strength(password)
        except WeakPasswordError as exc:
            raise click.ClickException(str(exc)) from exc

    async def go(settings: Settings) -> None:
        r = await provision_tenant(
            slug,
            name,
            owner_email,
            owner_password=password,
            actor=cli_actor(),
            frontend_url=settings.frontend_url,
        )
        if r.outcome == "already_active":
            click.echo(f"{r.slug}: already active (schema {r.schema_name}); nothing to do")
            return
        click.secho(f"{r.slug}: {r.outcome}, schema {r.schema_name}, org id {r.org_id}", fg="green")
        click.echo(
            f"  seeded: {r.seed.roles_added} roles, {r.seed.permissions_added} permissions, "
            f"{r.seed.grants_added} grants, {r.seed.settings_added} settings"
        )
        click.echo(f"  owner {owner_email}: {r.owner_status}")
        for note in r.notes:
            click.secho(f"  note: {note}", fg="yellow")
        if r.invite_url:
            click.echo("  invitation link (valid 7 days, shown once):")
            click.secho(f"  {r.invite_url}", fg="cyan")
            # B04 (B02 D1 "from B04"): the owner invite is also emailed.
            job = await _queue(
                settings,
                "invite_user",
                owner_email.strip().lower(),
                {"link": r.invite_url, "org_name": name, "role_key": "Owner", "inviter_name": None},
                r.slug,
            )
            click.echo(
                "  invitation email queued" if job else "  invitation email NOT queued (Redis?)"
            )

    _run(go)


async def _queue(
    settings: Settings, template: str, to: str, context: dict[str, Any], org_slug: str | None
) -> str | None:
    """Queue one email from the CLI (own short-lived Redis client)."""
    redis = ArqRedis.from_url(settings.redis_url)
    try:
        return await mail.queue_email(redis, template, to, context, org_slug=org_slug)
    finally:
        await redis.aclose()


# --------------------------------------------------------------------------- #
@cli.command("migrate-public")
def migrate_public() -> None:
    """Apply shared (public schema) migrations."""

    async def go(_: Settings) -> None:
        before = await migrations.current_public_revision()
        after = await migrations.upgrade_public()
        click.echo(f"public: {before or 'base'} -> {after}")
        audit.record("migrations.public", actor=cli_actor(), diff={"from": before, "to": after})

    _run(go)


@cli.command("migrate-all")
def migrate_all() -> None:
    """Public migrations, then the tenant track for every active/suspended org."""

    if _run(_migrate_all):
        sys.exit(1)


# --------------------------------------------------------------------------- #
@cli.command("list-orgs")
def list_orgs() -> None:
    """List organizations with status and active member count."""

    async def go(_: Settings) -> None:
        members = (
            select(func.count())
            .where(OrgMembership.org_id == Organization.id, OrgMembership.status == "active")
            .scalar_subquery()
        )
        async with db.get_session_factory()() as s:
            rows = (
                await s.execute(
                    select(
                        Organization.slug,
                        Organization.name,
                        Organization.status,
                        Organization.schema_name,
                        Organization.created_at,
                        members,
                    ).order_by(Organization.slug)
                )
            ).all()
        if not rows:
            click.echo("no organizations")
            return
        click.echo(f"{'SLUG':<16}{'STATUS':<14}{'MEMBERS':<9}{'SCHEMA':<24}{'CREATED':<12}NAME")
        for slug, name, status, schema, created, count in rows:
            click.echo(f"{slug:<16}{status:<14}{count:<9}{schema:<24}{created:%Y-%m-%d}  {name}")

    _run(go)


def _status_command(slug: str, target: str, allowed_from: tuple[str, ...], action: str) -> None:
    async def go(_: Settings) -> None:
        async with db.get_session_factory()() as s, s.begin():
            org = await s.scalar(select(Organization).where(Organization.slug == slug.lower()))
            if org is None:
                raise NotFound(f"organization {slug!r} not found")
            if org.status == target:
                click.echo(f"{org.slug}: already {target}")
                return
            if org.status not in allowed_from:
                raise Conflict(f"organization {org.slug!r} is {org.status}; cannot set {target}")
            previous = org.status
            await s.execute(
                update(Organization).where(Organization.id == org.id).values(status=target)
            )
        audit.record(
            action,
            entity="organization",
            entity_id=str(org.id),
            org=org.slug,
            actor=cli_actor(),
            diff={"status": [previous, target]},
            sensitive=True,
        )
        click.echo(f"{org.slug}: {previous} -> {target}")

    _run(go)


@cli.command("suspend-org")
@click.option("--slug", required=True)
def suspend_org(slug: str) -> None:
    """Suspend an active organization (its users get 404 for the tenant)."""
    _status_command(slug, "suspended", ("active",), "org.suspended")


@cli.command("activate-org")
@click.option("--slug", required=True)
def activate_org(slug: str) -> None:
    """Re-activate a suspended organization."""
    _status_command(slug, "active", ("suspended",), "org.activated")


# --------------------------------------------------------------------------- #
@cli.command("sync-permissions")
def sync_permissions_cmd() -> None:
    """Upsert module permission keys into every active tenant (grants untouched)."""

    _run(_sync_permissions)


# --------------------------------------------------------------------------- #
# Fresh clone (B13 D7, D8)
# --------------------------------------------------------------------------- #
def _seed_summary(r: demo_seed.SeedResult) -> None:
    click.echo(f"demo org: {r.outcome}, {len(r.users_added)} user(s) added")
    for w in r.warnings:
        click.secho(f"warning: {w}", fg="yellow")


@cli.command("init")
def init_cmd() -> None:
    """Prepare the stack: migrate, sync permissions, seed the demo org (dev only).

    The compose service `init` runs this on every `up`, before the API and the
    worker start. Safe to repeat. Migration failures stop the stack; a demo
    seed that cannot be applied is only a warning.
    """

    async def go(settings: Settings) -> int:
        click.echo("[init] 1/3 migrations")
        if failed := await _migrate_all(settings):
            return failed
        click.echo("[init] 2/3 permissions")
        await _sync_permissions(settings)
        click.echo("[init] 3/3 demo data")
        if settings.is_prod and (emails := await demo_seed.active_demo_logins()):
            # The demo password is printed in README.md: refuse to go live with it.
            log.error("init.demo_logins_in_prod", emails=emails)
            click.secho(
                "error: APP_ENV=prod, but these users still have the public demo password: "
                + ", ".join(emails)
                + "\nDeactivate each one: docker compose run --rm init "
                "python -m app.cli set-user-status --email <email> --inactive",
                fg="red",
            )
            return 1
        if settings.app_env != "dev" or not settings.seed_demo:
            click.echo("demo seed skipped (needs APP_ENV=dev and SEED_DEMO=true)")
            return 0
        try:
            _seed_summary(await demo_seed.seed_demo(settings, cli_actor()))
        except AppError as exc:
            log.warning("init.seed_conflict", error=exc.message)
            click.secho(f"warning: demo seed skipped: {exc.message}", fg="yellow")
            return 0
        click.secho(
            f"[init] ready. Log in at {settings.frontend_url} as {demo_seed.DEMO_OWNER} "
            f"/ {demo_seed.DEMO_PASSWORD} (dev only)",
            fg="green",
        )
        return 0

    if _run(go):
        sys.exit(1)


@cli.command("seed-demo")
def seed_demo_cmd() -> None:
    """Create the demo org and users (APP_ENV=dev only; never changes existing users)."""

    async def go(settings: Settings) -> None:
        if settings.app_env != "dev":
            raise Conflict("seed-demo runs only with APP_ENV=dev (the demo password is public)")
        _seed_summary(await demo_seed.seed_demo(settings, cli_actor()))

    _run(go)


# --------------------------------------------------------------------------- #
# Users (B03 §3.9, D16)
# --------------------------------------------------------------------------- #
def _email_arg(email: str) -> str:
    try:
        return normalise_email(email)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--email") from exc


@cli.command("create-user")
@click.option("--email", required=True)
@click.option("--full-name", default=None)
@click.option("--platform-admin", is_flag=True, help="Grant the Platform_Admin flag.")
@click.option(
    "--send-verification",
    is_flag=True,
    help="Create the user UNVERIFIED and email a verification link.",
)
def create_user(
    email: str, full_name: str | None, platform_admin: bool, send_verification: bool
) -> None:
    """Create a user with a password (prompted). Existing user + --platform-admin: promote."""
    email = _email_arg(email)

    async def promote(_: Settings) -> None:
        async with db.get_session_factory()() as s, s.begin():
            user = await s.scalar(select(User).where(User.email == email))
            if user is None:  # deleted between the two steps; practically impossible
                raise NotFound(f"user {email} not found")
            if user.is_platform_admin:
                click.echo(f"{email}: already platform admin")
                return
            user.is_platform_admin = True
        audit.record(
            "user.platform_admin_granted",
            entity="user",
            entity_id=str(user.id),
            actor=cli_actor(),
            diff={"is_platform_admin": [False, True]},
            sensitive=True,
        )
        click.secho(f"{email}: promoted to platform admin", fg="green")

    async def exists(_: Settings) -> User | None:
        async with db.get_session_factory()() as s:
            return await s.scalar(select(User).where(User.email == email))

    existing = _run(exists)
    if existing is not None:
        if not platform_admin:
            raise click.ClickException(f"user {email} already exists")
        _run(promote)
        return

    # Prompt OUTSIDE the event loop (click.prompt is blocking).
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        validate_password_strength(password)
    except WeakPasswordError as exc:
        raise click.ClickException(str(exc)) from exc

    async def go(settings: Settings) -> None:
        async with db.get_session_factory()() as s:
            user = User(
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
                is_active=True,
                is_verified=not send_verification,
                is_platform_admin=platform_admin,
            )
            s.add(user)
            await s.commit()
            audit.record(
                "user.created",
                entity="user",
                entity_id=str(user.id),
                actor=cli_actor(),
                diff={
                    "email": email,
                    "is_platform_admin": platform_admin,
                    "is_verified": not send_verification,
                },
                sensitive=True,
            )
            flags = ", ".join(
                f
                for f, on in (
                    ("platform admin", platform_admin),
                    ("verified", not send_verification),
                )
                if on
            )
            click.secho(
                f"{email}: created (id {user.id}{', ' + flags if flags else ''})", fg="green"
            )
            if send_verification:
                redis = ArqRedis.from_url(settings.redis_url)
                try:
                    job = await create_verification(s, redis, user, settings)
                finally:
                    await redis.aclose()
                if job:
                    click.echo(f"  verification email queued (job {job})")
                else:
                    click.secho("  verification email could NOT be queued (Redis?)", fg="yellow")

    _run(go)


@cli.command("invite-user")
@click.option("--org", "slug", required=True, help="Organization slug.")
@click.option("--email", required=True)
@click.option("--role", "role_key", required=True, help="owner, admin, manager, staff or user.")
def invite_user(slug: str, email: str, role_key: str) -> None:
    """Invite someone to an organization (emails the link, also printed here)."""
    email = _email_arg(email)

    async def go(settings: Settings) -> None:
        async with db.get_session_factory()() as s:
            org = await s.scalar(
                select(Organization).where(
                    Organization.slug == slug.lower(), Organization.status == "active"
                )
            )
        if org is None:
            raise NotFound(f"active organization {slug!r} not found")
        tenant = TenantContext(org.id, org.slug, org.name, org.schema_name)
        redis = ArqRedis.from_url(settings.redis_url)
        try:
            async with tenant_session(tenant) as ts:
                created = await create_invitation(
                    ts,
                    redis,
                    tenant=tenant,
                    email=email,
                    role_key=role_key,
                    inviter=None,
                    inviter_rank=PLATFORM_ADMIN_RANK,  # the operator may invite any role
                    actor=cli_actor(),
                    frontend_url=settings.frontend_url,
                )
        finally:
            await redis.aclose()
        verb = "re-issued (previous link invalid)" if created.reissued else "created"
        click.secho(f"{email}: invitation to {org.slug} as {role_key} {verb}", fg="green")
        click.echo("  link (valid 7 days, shown once):")
        click.secho(f"  {created.link}", fg="cyan")
        click.echo("  email queued" if created.job_id else "  email NOT queued (Redis?)")

    _run(go)


@cli.command("set-user-status")
@click.option("--email", required=True)
@click.option("--active/--inactive", "active", required=True, help="Target status.")
def set_user_status(email: str, active: bool) -> None:
    """Activate or deactivate a user. Deactivating also ends all their sessions."""
    email = _email_arg(email)

    async def go(_: Settings) -> None:
        async with db.get_session_factory()() as s:
            user = await s.scalar(select(User).where(User.email == email))
            if user is None:
                raise NotFound(f"user {email} not found")
            if user.is_active == active:
                click.echo(f"{email}: already {'active' if active else 'inactive'}")
                return
            user.is_active = active
            revoked = 0 if active else await revoke_user_sessions(s, user.id)
            await s.commit()
        audit.record(
            "user.status_changed",
            entity="user",
            entity_id=str(user.id),
            actor=cli_actor(),
            diff={"is_active": [not active, active], "revoked_tokens": revoked},
            sensitive=True,
        )
        state = "active" if active else f"inactive ({revoked} session token(s) revoked)"
        click.secho(f"{email}: {state}", fg="green")

    _run(go)


@cli.command("cleanup-files")
@click.option("--org", "org_slug", default=None, help="Only this tenant (default: all).")
def cleanup_files(org_slug: str | None) -> None:
    """Run J04 now: purge deleted files and uploads pending for over 24 h (B05 D12)."""

    async def go(settings: Settings) -> bool:
        result = await purge_orphan_files(settings, org_slug, actor=cli_actor())
        for slug, c in result.items():
            colour = "red" if c["errors"] else "green"
            click.secho(
                f"{slug}: pending {c['pending_purged']}, deleted {c['deleted_purged']}, "
                f"errors {c['errors']}",
                fg=colour,
            )
        return any(c["errors"] for c in result.values())

    if _run(go):
        sys.exit(1)


@cli.command("cleanup-exports")
@click.option("--org", "org_slug", default=None, help="Only this tenant (default: all).")
def cleanup_exports(org_slug: str | None) -> None:
    """Run the export retention now: expire old export files, fail stuck jobs (B07 D2)."""

    async def go(settings: Settings) -> bool:
        result = await expire_exports(settings, org_slug, actor=cli_actor())
        for slug, c in result.items():
            colour = "red" if c["errors"] else "green"
            click.secho(
                f"{slug}: expired {c['expired']}, stuck failed {c['stuck_failed']}, "
                f"errors {c['errors']}",
                fg=colour,
            )
        return any(c["errors"] for c in result.values())

    if _run(go):
        sys.exit(1)


@cli.command("rotate-secret-check")
def rotate_secret_check() -> None:
    """Check the current configuration against the production rules (read-only)."""
    current = get_settings().model_dump()
    try:
        Settings.model_validate({**current, "app_env": "prod"})
    except ValidationError as exc:
        for err in exc.errors():
            click.secho(f"FAIL {err['msg'].removeprefix('Value error, ')}", fg="red")
        sys.exit(1)
    click.secho("OK   configuration passes production checks", fg="green")


if __name__ == "__main__":
    cli()
