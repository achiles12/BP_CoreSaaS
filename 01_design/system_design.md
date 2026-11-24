# System Design

## 1. Components

```
 Dev:   Browser ──▶ Next.js :3200 ──(rewrite /api/*)──▶ FastAPI :8200
 Prod:  not part of the starter (decision 2026-11-23; see deploy/README.md)

 FastAPI ──▶ Postgres (schema per tenant)
         ──▶ Redis ──▶ arq worker ──▶ SMTP (Mailpit in dev)
         ──▶ RustFS (files)
         ──▶ /var/log/app/audit/*.log (flat file)
```

| Component | Role |
|---|---|
| Next.js | UI, route guards, role-based redirect. Calls `/api/*` only through the generated client |
| FastAPI | All business logic, auth, RBAC, tenancy, audit |
| arq worker | Same codebase as FastAPI, runs email and export jobs |
| Postgres | `public` schema (shared) + one schema per tenant |
| Redis | arq queue, rate limit counters, short permission cache |
| RustFS | File objects. Browser uploads and downloads with presigned URLs |
| Mailpit | Dev SMTP sink with web UI (:8025) |

Dev same-origin: Next.js `rewrites()` proxies `/api/:path*` to `http://backend:8200/:path*`, so the browser sees one origin (no CORS, cookies behave as in prod).

## 2. Multi-tenancy (schema per tenant)

- Shared tables in `public`: users, organizations, memberships, tokens, invitations.
- Tenant data in `tenant_<slug>`: roles, permissions, files, notifications, settings, business tables.
- **Resolution (Phase 1):** request header `X-Tenant: <slug>`.

Per-request pipeline:

1. Authenticate the user from the access cookie.
2. `resolve_tenant(request)`: read the header; load the organization by slug from `public.organizations`; reject if missing or inactive (**404** for unknown, **403** if user is not a member: use the same response for both to avoid tenant enumeration).
3. Verify an active `org_memberships` row for the user. Platform_Admin bypasses membership but the bypass is audited.
4. Open a session and bind the schema with `schema_translate_map={"tenant": schema_name}` (`schema_name` comes from the database row, never from the header).
5. Load the user's role(s) and permission set (cached in Redis, 60 s, key `perm:{org}:{user}`).
6. Handler runs. On exit the session closes and the connection's `search_path` is reset.

Routes that need no tenant (`/auth/*`, `/me`, `/health`, `/platform/*`) skip steps 2 to 5.

Tenant provisioning (CLI): insert organization row, `CREATE SCHEMA`, run the tenant Alembic track in it, seed roles/permissions, create the Owner membership. Details in `backend_processes.md`.

## 3. Authentication

- Email + password. Argon2id hashing.
- Access token: JWT, 15 min, httpOnly `Secure` `SameSite=Lax` cookie. Refresh token: opaque random value stored hashed in `refresh_tokens`, 14 days, httpOnly cookie scoped to `/api/auth`, **rotated on every use** with reuse detection (reuse revokes the family).
- Library: FastAPI-Users for user manager flows (verify, reset); custom backend for cookie/refresh handling.
- Login rate limit: 5 attempts/min per IP+email (slowapi, Redis).
- CSRF: `SameSite=Lax` cookies + require `X-Tenant`/JSON content type on state-changing requests (custom header forces a preflight). Optional double-submit token can be added.
- Invite-only registration: `POST /auth/accept-invite` sets a password for an invited email. An existing account with no org can accept with its current password; an account already in an org cannot be invited (one org per user).

## 4. RBAC

- Roles: owner, admin, manager, staff, user per tenant; `platform_admin` is a flag on `users`.
- Permissions are keys like `files:write`. Each module declares its keys in `permissions.py`; provisioning and a `sync-permissions` CLI upsert them.
- Role to permission grants are rows in `role_permissions` and are edited with DBeaver/SQL (no admin UI). Seeds are the source of truth for defaults.
- Enforcement: `Depends(require("files:write"))` returns **403** when missing. Frontend hides menu items using the same keys from `GET /me`.
- A user can hold several roles; permissions are the union. Landing page uses the highest-priority role: owner > admin > manager > staff > user.
- Default matrix:

| Permission | owner | admin | manager | staff | user |
|---|---|---|---|---|---|
| users:read | x | x | x | | |
| users:invite | x | x | | | |
| users:update / deactivate | x | x | | | |
| roles:read | x | x | x | | |
| roles:assign | x | x | | | |
| org:read | x | x | x | x | x |
| org:update | x | | | | |
| files:read | x | x | x | x | x |
| files:write | x | x | x | x | |
| files:delete | x | x | x | | |
| search:use | x | x | x | x | x |
| export:run | x | x | x | | |
| notifications:read | x | x | x | x | x |
| items:* (template) | x | x | read/write | read/write | read |

`platform:manage` is not granted to any tenant role; it is implied by `is_platform_admin`.

## 5. Role-based landing page

`GET /me` returns user, memberships, current org, role keys, permission keys and `landing_path`. After login the frontend routes to `/post-login`, which:

1. Calls `/me` (no header needed: **One organization per user** (decision 2026-11-12, B04 D1); enforced by a unique `org_memberships.user_id`).
2. Sets the org from `/me` in client state (`X-Tenant` header for all tenant calls).
3. (step removed: no org picker)
4. Redirects to `landing_path` (from `roles.landing_path` of the top role; `/platform` for Platform_Admin without org context).

Landing pages share a shell and differ in content cards, which are filled by business modules later.

## 6. Notifications and email

- Application code calls `notifications.send_email(template, to, context)`. It enqueues `send_email`; the worker renders Jinja2 and sends over SMTP with retry (3 tries, exponential backoff: 30 s, 2 min, 10 min).
- Phase 1 SMTP target is Mailpit. Mail is not delivered to real inboxes. For real use later, change env vars only.
- In-app notifications: table exists, endpoints exist, UI bell is optional.

## 7. Audit

- Append-only JSON lines: `{ts, org, actor, action, entity, entity_id, diff, ip, request_id, result}`.
- Written by `core.audit.record(...)`, called from the service layer for every mutation and by a middleware for auth events.
- File: `/var/log/app/audit/audit.log` (bind-mounted to `./logs/audit`), `WatchedFileHandler` so `logrotate` works. Permissions 0640. Read by SFTP/PuTTY.
- Failure to write the audit line is logged and surfaces as a 500 for sensitive actions (config flag `AUDIT_FAIL_CLOSED=true`).
- No secrets, passwords or tokens in `diff`; the writer strips known sensitive keys.

## 8. Files

- Upload: `POST /files/presign-upload` (validates size/type, creates a `pending` row) returns a presigned PUT URL; the browser uploads to RustFS; `POST /files/{id}/confirm` verifies the object (HEAD) and marks it `active`.
- Download: `GET /files/{id}/download-url` returns a short-lived (60 s) presigned GET URL after permission and tenant checks.
- Object key: `{org_slug}/{yyyy}/{mm}/{file_uuid}` in a single bucket. Filename kept only in the database.
- RustFS must be reachable from the browser: `S3_PUBLIC_ENDPOINT=http://localhost:9000` in dev.
- ClamAV is optional and not in Phase 1.

## 9. Search, filter, export

- Postgres full text (`tsvector` generated column + GIN) and `pg_trgm` for fuzzy name matching, inside the tenant schema.
- Standard query params: `q`, `page`, `page_size` (max 100), `sort`, `filter[field]=value`.
- Export: `POST /exports` queues `build_export` (CSV or XLSX streamed to RustFS, result via presigned URL). Small exports (<5 000 rows) may stream directly.

## 10. Errors, logging, config

- Error body: `{ "error": { "code": "permission_denied", "message": "...", "request_id": "..." } }`, same everywhere.
- Every request gets a `request_id` (header `X-Request-ID`, generated if missing) included in logs and audit lines.
- App logs: structlog JSON to stdout. Config: pydantic-settings reading env. Secrets from `.env` (dev) / Docker secrets (prod).

## 11. Security checklist

- Validate input with Pydantic; no raw SQL with user input; schema names only from the database.
- Argon2id, httpOnly cookies, rate limiting on auth routes, generic messages for login and reset.
- Presigned URLs short-lived; bucket private.
- Tenant isolation test suite (see `critical_user_flow.md`).
- Dependencies pinned; `pip-audit` and `pnpm audit` in CI.

## 12. Extending (business modules)

1. Copy `_template` (backend and frontend).
2. Define tenant-model, schemas, service (business rules), router.
3. Declare permission keys; add to the role matrix seed.
4. Add a tenant Alembic revision; run `migrate-all`.
5. Register the router and the navigation entry. Regenerate the API client.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Header tenancy can be spoofed | Mandatory membership check; tests |
| `search_path` leaking across pooled connections | Use `schema_translate_map`; reset on checkin; test |
| Tenant migrations failing partway | `migrate-all` is per tenant, resumable, reports failures |
| Audit file lost with container | Bind mount to host; backup the folder |
| Mailpit mistaken for real email | README + UI banner in dev; relay is an env change later |
