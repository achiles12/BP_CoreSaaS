# Object Master List

One place that names every object in the scaffold. IDs are referenced from other documents.

**Build status** (updated 2026-11-20 evening by the daily summary): `Built` = complete for Phase 1; `Partial` = the part delivered so far, with the remaining part and batch named; `Planned` = not started. Batches refer to `build_list.md`. Previous version: `20261120_object_msterlist.md`.

## A. Data entities

### `public` schema (shared)

| ID | Entity | Purpose | Status | Batch | Completed |
|---|---|---|---|---|---|
| E01 | `users` | Accounts: email, password hash, status, `is_platform_admin`, `is_verified` | Built | B02 | 2026-11-11 |
| E02 | `organizations` | Tenants: name, slug, `schema_name`, status, `plan`, `limits` | Built | B02 | 2026-11-11 |
| E03 | `org_memberships` | User belongs to org, with status | Built; one org per user (unique `user_id`, migration 0002) | B02, B04 | 2026-11-12 |
| E04 | `refresh_tokens` | Rotating refresh tokens (hashed) | Built: rotation + reuse detection, cleanup cron | B02, B03 | 2026-11-12 |
| E05 | `invitations` | Pending invites: email, org, role key, token hash, expiry | Built: API, CLI invite-user, emailed invites | B02, B04 | 2026-11-12 |
| E06 | `password_reset_tokens` / `email_verification_tokens` | One-time tokens (hashed) | Built: reset/verify flows, single use, cleanup cron | B02, B03 | 2026-11-12 |
| E07 | `alembic_version_public` | Migration state, shared track | Built | B02 | 2026-11-11 |

### Tenant schema (`tenant_<slug>`)

| ID | Entity | Purpose | Status | Batch | Completed |
|---|---|---|---|---|---|
| T01 | `roles` | Role key, name, `landing_path`, `is_system` | Built | B02 | 2026-11-11 |
| T02 | `permissions` | Permission key, description, module | Built | B02 | 2026-11-11 |
| T03 | `role_permissions` | Role to permission grants | Built | B02 | 2026-11-11 |
| T04 | `user_roles` | User (public id) to role | Built | B02 | 2026-11-11 |
| T05 | `files` | File metadata: name, size, mime, object key, uploader, status | Built: tenant migration `0002_files` (GIN tsvector, trigram, status/uploader indexes) | B05 | 2026-11-19 |
| T06 | `notifications` | In-app notifications (optional UI, table ready) | Built: tenant migration `0004_exports_notifications`, model in `modules/notifications/models.py` | B07 | 2026-11-20 |
| T07 | `settings` | Key/value tenant settings | Built | B02 | 2026-11-11 |
| T08 | `export_jobs` | Export requests and result object key | Built: migration `0004`, model in `modules/exports/models.py`; status adds `expired` (retention) | B07 | 2026-11-20 |
| T09 | `_template_items` | Sample business entity used by the module template | Built: tenant migration `0003_items`, model in `modules/_template/models.py` | B06 | 2026-11-19 |
| T10 | `alembic_version_tenant` | Migration state per tenant | Built | B02 | 2026-11-11 |

## B. Roles (seeded per tenant)

| ID | Key | Landing page | Status | Batch | Completed |
|---|---|---|---|---|---|
| R01 | `platform_admin` (flag on user, not a tenant role) | `/platform` | Built: flag + `/me` landing `/platform` (B04); page built B09 | B02, B04, B09 | 2026-11-13 |
| R02 | `owner` | `/home/owner` | Built: seeded; `/me` returns landing path (B04); page built B09 | B02, B04, B09 | 2026-11-13 |
| R03 | `admin` | `/home/admin` | Built: seeded; `/me` returns landing path (B04); page built B09 | B02, B04, B09 | 2026-11-13 |
| R04 | `manager` | `/home/manager` | Built: seeded; `/me` returns landing path (B04); page built B09 | B02, B04, B09 | 2026-11-13 |
| R05 | `staff` | `/home/staff` | Built: seeded; `/me` returns landing path (B04); page built B09 | B02, B04, B09 | 2026-11-13 |
| R06 | `user` | `/home/user` | Built: seeded; `/me` returns landing path (B04); page built B09 | B02, B04, B09 | 2026-11-13 |

## C. Permission keys (core)

| Module | Keys | Status | Batch | Completed |
|---|---|---|---|---|
| users | `users:read`, `users:invite`, `users:update`, `users:deactivate` | Built: seeded and enforced by `require()` | B02, B04 | 2026-11-12 |
| rbac | `roles:read`, `roles:assign` | Built: seeded and enforced by `require()` | B02, B04 | 2026-11-12 |
| org | `org:read`, `org:update` | Built: seeded and enforced by `require()` | B02, B04 | 2026-11-12 |
| files | `files:read`, `files:write`, `files:delete` | Built: keys seeded (B02), enforced by the files routes (B05) | B02, B05 | 2026-11-19 |
| search | `search:use` | Built: seeded (B02), enforced by `/search` (B07) | B02, B07 | 2026-11-20 |
| export | `export:run` | Built: seeded (B02), enforced by `/exports` together with the list's read key (B07) | B02, B07 | 2026-11-20 |
| notifications | `notifications:read` | Built: seeded (B02), enforced by `/notifications` (B07) | B02, B07 | 2026-11-20 |
| platform | `platform:manage` (Platform_Admin only) | Built: granted to no tenant role; `/platform/*` guarded by `require_platform_admin` | B02, B04 | 2026-11-12 |
| template | `items:read`, `items:write`, `items:delete` (example) | Built: declared in `_template/permissions.py` with default roles; granted to existing tenants by `sync-permissions` | B06 | 2026-11-19 |

## D. Backend services and components

| ID | Component | Responsibility | Status | Batch | Completed |
|---|---|---|---|---|---|
| S01 | `core.tenancy` | `resolve_tenant`, membership check, schema binding | Built: resolver, membership check, schema binding, request wiring (`tenant_access`) | B02, B04 | 2026-11-12 |
| S02 | `core.db` | Engines, sessions, `search_path` reset | Built | B01 | 2026-11-11 |
| S03 | `core.security` | Argon2, JWT, cookie helpers | Built: Argon2id, tokens, JWT, cookies, current_user / current_verified_user | B02, B03 | 2026-11-12 |
| S04 | `core.permissions` | `require()` dependency, permission cache | Built: registry, `require()`, `tenant_access`, `tenant_db`, Redis cache 60 s + invalidation; B06: `PermissionDef.default_roles`, defaults granted on sync for new keys; B12: `required_permission` on each `require()`, public session released before tenant work (pool deadlock fix) | B02, B04, B06, B12 | 2026-11-20 |
| S05 | `core.audit` | JSON-lines writer | Built | B01 | 2026-11-11 |
| S06 | `core.mail` | SMTP send, template render | Built: Jinja templates verify/reset/invite, aiosmtplib, queue_email | B03 | 2026-11-12 |
| S07 | `core.storage` | RustFS, presigned URLs | Built: presign PUT (15 min, signed Content-Type) / GET (60 s, original name), HEAD, delete, bucket check | B05 | 2026-11-19 |
| S08 | `core.errors` | Error model and handlers | Built | B01 | 2026-11-11 |
| S09 | `core.pagination` | Pagination and filter parsing | Built: page/page_size (B04); `ListSpec`, `sort=`, `filter[...]` (eq, any-of, gte/lte), 422 on unknown fields; `/users`, `/files`, `/items` use it | B04, B06 | 2026-11-19 |
| S10 | module `auth` | Login, refresh, reset, verify | Built: 10 endpoints incl. invitation + accept-invite (B04) | B03, B04 | 2026-11-12 |
| S11 | module `users` | Profile, invites, user admin in org | Built: /me, /users, invitations | B04 | 2026-11-12 |
| S12 | module `organizations` | Org info, provisioning service (no switch: one org per user) | Built: provisioning, /orgs, /org | B02, B04 | 2026-11-12 |
| S13 | module `rbac` | Roles, permissions read, assignment | Built: seed, /roles, /permissions, PUT roles | B02, B04 | 2026-11-12 |
| S14 | module `notifications` | Queue email, list in-app | Built: `notify()` helper, list/read/read-all; fed by export done/failed | B07 | 2026-11-20 |
| S15 | module `files` | Presign, confirm, list, delete | Built: presign-upload, confirm, list (`q`, `mine`), get, download-url, soft delete; audit | B05 | 2026-11-19 |
| S16 | module `search` | Unified search | Built: pluggable `search.py` sources (files, items); full text + `word_similarity`; code-like queries exact | B07 | 2026-11-20 |
| S17 | module `exports` | Create/poll/download exports | Built: pluggable `exports.py` sources (files, items, users); own exports only; retention cleanup | B07 | 2026-11-20 |
| S18 | module `health` | Liveness and readiness | Built | B01 | 2026-11-11 |
| S20 | `app.openapi_dump` + route-name operationIds | Offline OpenAPI schema for the generated client; drift check | Built | B08 | 2026-11-13 |
| S19 | `cli` | Developer admin commands | Partial: create-tenant, migrate-*, list/suspend/activate-org, sync-permissions (grants defaults for new keys, B06), rotate-secret-check; create-user, set-user-status (B03); invite-user (B04); cleanup-files (B05); cleanup-exports (B07) | B02, B03, B04, B05, B06, B07 | 2026-11-20 |
| S21 | `app.modules.registry` | The one list of modules: loads routers, permissions, models | Built: replaces `main.MODULES` and `PERMISSION_MODULES` | B06 | 2026-11-19 |
| S22 | module `_template` | Copyable example business module (`/items`) + copy guide | Built: CRUD, list sort/filter/q, soft delete, audit, `README.md`; proven by `tests/test_module_copy.py` | B06 | 2026-11-19 |

## E. Background jobs (arq)

| ID | Job | Trigger | Status | Batch | Completed |
|---|---|---|---|---|---|
| J01 | `send_email` | Any email event, retried | Built: 4 tries (30 s / 2 min / 10 min), audit email.failed | B03 | 2026-11-12 |
| J02 | `build_export` | Export request | Built: CSV (UTF-8 BOM) / XLSX, server-side cursor, `EXPORT_MAX_ROWS`; cron `cleanup_exports` (03:45) | B07 | 2026-11-20 |
| J03 | `cleanup_expired_tokens` | Cron daily | Built: cron 03:00 UTC | B03 | 2026-11-12 |
| J04 | `cleanup_orphan_files` | Cron daily | Built: cron 03:30 UTC + CLI `cleanup-files`; per-tenant, batches of 500 | B05 | 2026-11-19 |

## F. Frontend pages

| ID | Route | Access | Status | Batch | Completed |
|---|---|---|---|---|---|
| P01 | `/login` | public | Built (RHF+Zod, silent refresh, forgot link) | B08, B09 | 2026-11-13 |
| P02 | `/forgot-password`, `/reset-password` | public | Built | B09 | 2026-11-13 |
| P03 | `/verify-email` | public | Built (+ unverified banner with resend) | B09 | 2026-11-13 |
| P04 | `/accept-invite` | public (token) | Built (new + existing account) | B09 | 2026-11-13 |
| P05 | `/post-login` | authenticated, redirects by role | Built (+ `/no-organization`) | B09 | 2026-11-13 |
| P06 | `/home/{owner,admin,manager,staff,user}` | per role | Built (wrong-role redirect; files/search/export cards are placeholders until B10 wires them; files API built in B05) | B09 | 2026-11-13 |
| P07 | `/platform` | Platform_Admin | Built (stats + organizations table) | B09 | 2026-11-13 |
| P08 | `/files` | `files:read` | Built: filters in URL, upload dialog (XHR progress), download, delete, export | B10 | 2026-11-20 |
| P09 | `/search` | `search:use` | Built: type chips, grouped results, client-side highlight | B10 | 2026-11-20 |
| P10 | `/users` | `users:read` | Built: members + invitations tabs, invite, roles, (de)activate; no role filter (user decision) | B10 | 2026-11-20 |
| P11 | `/settings/profile`, `/settings/organization` | authenticated / `org:read` | Built: name, change password; org read-only without `org:update` | B10 | 2026-11-20 |
| P12 | `/403`, `/404` | any | Built (+ error boundary, session-expired toast) | B08 | 2026-11-13 |
| P13 | `/no-organization` | authenticated, `landing_path = null` | Built | B09 | 2026-11-13 |

## F2. Frontend libraries and components

| ID | Object | Path (`frontend/src/`) | Status | Batch | Completed |
|---|---|---|---|---|---|
| F01 | Next.js app, tooling (TS, Tailwind 4, ESLint, Prettier, pnpm, Vitest) | `package.json`, configs | Built | B08 | 2026-11-13 |
| F02 | `/api/*` rewrite, `Cache-Control: no-store` on pages | `next.config.ts` | Built | B08, B09 | 2026-11-13 |
| F03 | Generated API client (orval) + schema snapshot + `make gen-client(-check)` | `api/generated/`, `openapi.json` | Built | B08 | 2026-11-13 |
| F04 | Fetch mutator: `X-Tenant`, cookies, single-flight refresh, `ApiError` | `lib/fetcher.ts`, `lib/api-error.ts` | Built | B08 | 2026-11-13 |
| F05 | Session + org state (`useSession`, `useSignOut`, `last_org`) | `lib/auth.ts`, `lib/org.ts`, `lib/tenant.ts` | Built | B08, B09 | 2026-11-13 |
| F06 | Permission helpers (`can`, `<Can>`, `<RequirePermission>`, `filterNav`) | `lib/permissions.tsx` | Built | B08 | 2026-11-13 |
| F07 | shadcn/ui components | `components/ui/` | Built (button, input, label, card, badge, dropdown, sheet, skeleton, separator, sonner, avatar, alert, table; B10: dialog, tabs on radix-ui, native select/checkbox/textarea/progress) | B08, B09, B10 | 2026-11-13 |
| F08 | App shell: top bar, sidebar/drawer, user menu, dev banner, verify banner, session-expired toast | `components/layout/` | Built | B08, B09 | 2026-11-13 |
| F09 | Navigation config | `config/navigation.ts` | Built; all core entries live since B10, Items (B11) | B08, B10, B11 | 2026-11-20 |
| F10 | Route guards | `proxy.ts`, `app/(app)/layout.tsx` | Built | B08, B09 | 2026-11-13 |
| F11 | Form helpers (Zod rules, server-error mapping) | `lib/forms.ts`, `components/forms/` | Built | B09 | 2026-11-13 |
| F12 | Landing logic + cards per role | `lib/landing.ts`, `config/landing.ts`, `components/dashboard/` | Built: every card live since B10 (files lists, search box, export links, shortcuts); only "Recent activity" waits for a business module | B09, B10 | 2026-11-20 |
| F13 | Frontend module template | `modules/_template/` | Built: config-driven list/detail/form, `/items`, README copy guide; no history panel (user decision) | B11 | 2026-11-20 |
| F14 | List building blocks: URL state, table, pager, row menu, search box, confirm, page frame | `lib/list-params.ts`, `components/data/`, `components/layout/page.tsx` | Built | B10 | 2026-11-20 |
| F15 | Export dialog + recent exports | `components/exports/` | Built | B10 | 2026-11-20 |
| F16 | Notifications bell | `components/layout/notifications-bell.tsx` | Built (30 s unread count, last 10, mark all read) | B10 | 2026-11-20 |
| F17 | Upload / download helpers | `lib/upload.ts`, `lib/files.ts` | Built (XHR progress, browser checks) | B10 | 2026-11-20 |

## G. Containers

| ID | Service | Port | Status | Batch | Completed |
|---|---|---|---|---|---|
| C01 | `frontend` | 3200 | Built: Next.js 16 dev server, `/api/*` proxied to backend (B08) | B00, B08 | 2026-11-13 |
| C02 | `backend` | 8200 | Built | B01 | 2026-11-11 |
| C03 | `worker` | none | Built: send_email + cron J03 (03:00) and J04 (03:30), own DB engine + audit writer | B01, B03, B05 | 2026-11-19 |
| C04 | `postgres` | 5200 on host → 5432 in container (published for DBeaver) | Built (host port 5200) | B00 | 2026-11-11 |
| C05 | `redis` | 6379 (internal) | Built | B00 | 2026-11-11 |
| C06 | `rustfs` (S3 storage, replaces RustFS) + `storage-init` | 9000 API, 9201 console on host (9001 in container, path `/rustfs/console/`) | Built (RustFS replaces MinIO; console host port 9201); S3 CORS from `CORS_ORIGINS` via `RUSTFS_CORS_ALLOWED_ORIGINS` (B05) | B00, B05 | 2026-11-19 |
| C07 | `mailpit` | 1025 SMTP, 8025 UI | Built | B00 | 2026-11-11 |
| C08 | `caddy` (prod only) | 80/443 | Not planned | — | dropped 2026-11-23 (B13: starter, not a production stack) |
| C09 | `init` (one-shot: migrate, sync, demo seed) | — | Built | B13 |  |

## H. Configuration keys (env)

`APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `COOKIE_SECURE`, `CORS_ORIGINS`, `REQUIRE_EMAIL_VERIFICATION`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `AUDIT_LOG_DIR`, `TENANT_HEADER`, `FRONTEND_URL`.

Configuration status: every key above is in `.env.example` and `app/config.py` (B00/B01, 2026-11-11), plus `MAX_UPLOAD_MB`, `EXPORT_MAX_ROWS`, `EXPORT_RETENTION_DAYS` / `EXPORT_CLEANUP_HOUR` / `EXPORT_CLEANUP_MINUTE` (B07), `AUDIT_FAIL_CLOSED`, `LOG_LEVEL` and the host-port keys. MinIO-specific keys were replaced by `S3_ACCESS_KEY` / `S3_SECRET_KEY` (RustFS). Dev `.env` sets `FRONTEND_URL=http://192.168.50.113:3200` (B09, 2026-11-13) so email links open on the LAN test PC. B05 (2026-11-19): `ALLOWED_MIME_TYPES` (empty = built-in list); dev `S3_PUBLIC_ENDPOINT=http://192.168.50.113:9000` and `CORS_ORIGINS` also lists `http://192.168.50.113:3200`. Frontend env: `NEXT_PUBLIC_APP_ENV`, `NEXT_PUBLIC_APP_NAME`, `NEXT_PUBLIC_MAILPIT_PORT`, `BACKEND_INTERNAL_URL`, `ALLOWED_DEV_ORIGINS` (B08), `NEXT_PUBLIC_MAX_UPLOAD_MB` / `NEXT_PUBLIC_ALLOWED_MIME_TYPES` (B10, from the backend values).

## I. Design artifacts

| ID | Artifact | Path | Status | Batch | Completed |
|---|---|---|---|---|---|
| X01 | Wireframe set: all screens (S01–S16, layouts, screen map), 21 pages A4 landscape | `01_design/wireframe.pdf`; source `01_design/wireframes/wireframe/wireframe.html`; build `01_design/wireframes/20261113_wireframe_build.sh` | Built: every screen drawn as built (B08–B11), updated 2026-11-20; automated test 26/26 | — | 2026-11-20 |
| X02 | Application flows drawn (F1–F13, system map), 14 pages A4 landscape | `01_design/process_flows/appFlows.pdf`; source `process_flows/source/appFlows.html`; build `process_flows/build_appFlows.sh` | Built (as built through B11) | — | 2026-11-20 |
| X03 | Application flows v2 (text, as built) | `01_design/app_flow_v2.md` (v1 `app_flows.md` kept) | Built | — | 2026-11-20 |

## J. System-wide test suites and CI

| ID | Suite | Path | Status | Batch | Completed |
|---|---|---|---|---|---|
| Q01 | Permission matrix generated from the routes (C3) + spec-pinned keys | `backend/tests/test_permission_matrix.py`, `tests/route_catalog.py` | Built: 158 tests | B12 | 2026-11-20 |
| Q02 | Tenant isolation incl. 50 parallel requests (C2) | `backend/tests/test_isolation.py` | Built: 30 tests | B12 | 2026-11-20 |
| Q03 | Audit line per mutation (C7) | `backend/tests/test_audit_coverage.py` | Built: 24 recipes + 3 reasoned exceptions | B12 | 2026-11-20 |
| Q04 | Provisioning from an empty database (C8) | `backend/tests/test_provisioning.py` | Built: 4 tests | B12 | 2026-11-20 |
| Q05 | Playwright critical flows C1 (6 roles), C4, C5, C6 + `e2e` tenant seed | `frontend/tests/e2e/` (`make e2e`) | Built: 9 tests | B12 | 2026-11-20 |
| Q06 | CI: `make ci` + `.github/workflows/ci.yml` (backend, frontend, e2e jobs) | `Makefile`, `.github/workflows/ci.yml` | Built; inactive until the project has a git remote (user choice) | B12 | 2026-11-20 |
