# Suggested Tech Stack

Based on `saas_functionality.md` (updated). Constraints: **self-hosted, Docker Compose**. Dev has no proxy; prod adds one.

## Architecture Overview

```
 Dev:   Browser ──▶ Next.js :3000 ──(rewrite /api/*)──▶ FastAPI :8000
 Prod:  Browser ──▶ Caddy (TLS) ──▶ Next.js / FastAPI

 FastAPI ──▶ Postgres (schema per tenant)
         ──▶ Redis ──▶ arq worker ──▶ SMTP (Mailpit in dev)
         ──▶ MinIO (files)
         ──▶ /var/log/app/audit/*.log (flat file)
```

- `compose.yml` (dev): published ports, bind-mounted source, Mailpit, MinIO, Redis, Postgres.
- `compose.prod.yml`: adds Caddy (automatic HTTPS, tiny Caddyfile) for TLS and routing; SMTP points at a real relay.

## Core Stack

| Layer | Choice | Notes |
|---|---|---|
| Deployment | Docker Compose | |
| Frontend | Next.js + React (TypeScript) | App Router. `next.config.js` rewrite proxies `/api/*` to FastAPI in dev (same origin, no CORS) |
| UI / Styling | shadcn/ui + Tailwind CSS | |
| Server state | TanStack Query | |
| API client | OpenAPI-generated (`orval` → typed TanStack Query hooks) | FastAPI emits the schema |
| Forms | React Hook Form + Zod | |
| Backend | FastAPI (Python 3.12+), Pydantic v2 | |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic | Multi-schema setup, see below |
| Database | PostgreSQL 16+ | |
| Cache / queue | Redis + **arq** | Background jobs (email with retries) |
| Email | **Mailpit** (dev) + plain SMTP config | |
| Files | **MinIO** via `aioboto3` | Presigned URLs |

## Per-Functionality Decisions

### User Authentication & Account Management — *Needed*
- FastAPI-Users: email/password, verification, password reset. Argon2 hashing, short-lived JWT access token + refresh token in httpOnly cookies.
- Users live in the shared `public` schema (one user can belong to several orgs).
- Add Authlib only if generic OIDC/SSO is needed; Keycloak/Authentik is the later upgrade path.

### Organization / Tenant Management — *Needed* (schema-separated)
- **Schema per tenant** (`tenant_<slug>`); shared tables (`users`, `organizations`, memberships, platform config) in `public`.
- **Scale:** MVP plans for 1–2 tenants, growing only if needed. Schema-per-tenant is comfortable at that size; migration time only matters at hundreds of tenants.
- **Tenant resolution:**
  - **Phase 1: `X-Tenant: acme` header**, set globally by the generated API client from app state. Works on plain `localhost:3000` and in prod, no DNS, wildcard cert or proxy rules needed.
  - Later phases: not planned. Phase 2 may never happen, so nothing is designed beyond the header. Keeping the logic in one small `resolve_tenant(request)` function is enough.
  - Always verify the authenticated user is a member of the resolved org. The identifier only selects the schema; never trust it on its own.
  - Header caveat: plain browser navigations, `<img>` tags and download links can't send custom headers. Files use MinIO presigned URLs (no header needed), and any other direct links must go through `fetch` with the header.
- Per request: bind the schema using SQLAlchemy `schema_translate_map` (or `SET LOCAL search_path`) on the session. Validate the schema name against the `organizations` table, never from raw input.
- **Alembic** with two migration tracks: `public` (once) and `tenant` (applied to every tenant schema). Provisioning a tenant = `CREATE SCHEMA` + run tenant migrations. Write a small CLI to migrate all tenants.
- Watch connection pool behavior: always reset `search_path` on connection return.

### RBAC — *Needed*
- Roles: `Platform_Admin`, `Owner`, `Admin`, `Manager`, `Staff`, `User` (extensible).
- `roles`, `permissions`, `role_permissions` tables in each tenant schema; `Platform_Admin` is a `public`-level flag/role.
- Enforced via FastAPI dependencies, e.g. `Depends(require("files:write"))`. Seed default roles during tenant provisioning.
- No admin UI: roles and permissions are maintained with **DBeaver + SQL** (keep seed/migration scripts as the source of truth). Casbin only if policies outgrow simple checks.

### Subscription & Billing — *Can wait (Phase 3)*
- Only prepare: `plan` column on `organizations`, feature-flag/limits table. Later: Stripe or self-hosted Lago.

### Dashboard & Analytics — *Can wait (Phase 2–3)*
- Postgres aggregates + shadcn/ui charts (Recharts). Metabase later if ad-hoc reporting is needed. Note: cross-tenant analytics with schema-per-tenant needs a union/ETL step.

### Notifications & Communication — *Needed*
- **Phase 1:** Mailpit in Docker (SMTP `mailpit:1025`, web UI `:8025`). It captures mail and never delivers it, so real users receive nothing. Fine for the MVP, but anything that depends on email (verification, password reset) must be handled by a developer reading Mailpit.
- Sender is plain SMTP config: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`. Sending goes through an arq job with retries so a slow SMTP server never blocks a request. Templates: Jinja2.
- **Phase 2:** undecided and not planned. Because the sender is plain SMTP config, a real relay can be dropped in later with env vars only.
- In-app notifications (table + SSE) are optional and not yet in scope.

### Audit Logs & Activity Tracking — *Needed*
- **Flat file on the host**, in a dedicated log directory. The "append-only Postgres table" idea from the spec is not used.
- Format: **JSON lines** (timestamp, org, actor, action, entity, diff, IP), written by a service layer/middleware through Python `logging` (`WatchedFileHandler`, or `RotatingFileHandler` / `structlog`) to `/var/log/app/audit/audit.log`.
- Docker: bind-mount a host directory (e.g. `./logs/audit:/var/log/app/audit`) so the file is readable on the host; rotate with `logrotate`; app user can append but not rewrite.
- **Reading:** via PuTTY/SFTP on the host (`less`, `grep`, `jq`). No in-app reader for now.
- In-app reader: not planned (Phase 3 may never happen).
- Timing: the spec names no phase for writing the log. Plan it for Phase 1, since adding audit events later means touching every write path.

### File & Document Management — *Needed*
- MinIO bucket layout `tenant-<slug>/…` (or one bucket with per-tenant prefixes); metadata (name, size, owner, version) in the tenant schema. Presigned URLs for direct upload/download.
- ClamAV scanning is optional; add if user uploads are untrusted.

### Search, Filtering & Data Export — *Needed*
- Postgres full-text search (`tsvector` + GIN) and `pg_trgm`, scoped to the tenant schema, which makes search isolation automatic. Meilisearch only if needed later.
- Filtering/pagination via query-param schemas; TanStack Table on the frontend.
- Export: CSV/XLSX streamed from FastAPI; large exports as arq jobs delivered via a MinIO link.

### Platform Administration — *Needed*
- No admin UI. **DBeaver + SQL** for data/role maintenance, plus developer-run backend scripts/CLI (tenant provisioning, migrations, user management).
- Keep operations as versioned CLI commands (`python -m app.cli create-tenant …`) so they are repeatable and not ad hoc SQL against production.

## Cross-Cutting

| Concern | Choice |
|---|---|
| Reverse proxy (prod only) | Caddy (automatic HTTPS; nginx is the alternative) |
| Config / secrets | `pydantic-settings` + `.env`; Docker secrets in prod |
| Logging | structlog JSON to stdout (app) + audit file (see above) |
| Backups | `pg_dump` (all schemas) + MinIO volume backup via cron container |
| Rate limiting | `slowapi` |

## Dev Tooling
uv + ruff + pyright; pnpm; pytest + httpx + testcontainers; Vitest; Playwright; pre-commit. Layout: `/backend`, `/frontend`, `/deploy`, `/docs`.

## Compose Services
- **Dev:** `frontend`, `backend`, `worker`, `postgres`, `redis`, `minio`, `mailpit`
- **Prod:** same minus Mailpit, plus `caddy` (+ optional `clamav`)

## Phasing
1. **Phase 1:** auth, orgs (schema per tenant), RBAC, files (MinIO), search/export, email via Mailpit, audit log to flat file, tenant header, SQL/CLI admin.
2. **Phase 2 (may not happen):** dashboards/analytics, production email, tenant resolution beyond the header. Not planned in detail.
3. **Phase 3 (may not happen):** billing, advanced analytics. Only the `plan` column hook is prepared.

## Open Questions
- Audit log: is a host flat file enough for any compliance needs, given there is no in-app reader?
- Who reads Mailpit for verification/reset emails during the MVP, or should email verification be disabled and accounts created by a developer?
