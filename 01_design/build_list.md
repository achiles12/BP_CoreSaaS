# Build List: Core SaaS Scaffold (Phase 1)

Every object to build, grouped into batches in build order. When a batch is finished, it can be run and tested on its own.

Sources: `file_system.md` (paths), `object_msterlist.md` (IDs E/T/R/S/J/P/C), `deliverables.md` (scope and acceptance), `gant_sched.md` (work packages W0–W15), `api_spec.md`, `data_model.md`, `backend_processes.md`, `ui_screens.md`.

Paths are relative to the repo root `daffy/`. Each batch has its own stage folder for its dated design, test and manual-test notes: `05_stage<NN>/` (`NN` = batch number).

## Overview

| Batch | Name | Work pkg | Depends on | Milestone | Est. days |
|---|---|---|---|---|---|
| B00 | Repo and dev stack — **built 2026-11-11, 13/13 automated tests pass** | W0 | — | — | 2 |
| B01 | Backend core and audit — **built 2026-11-11, 56 pytest + 12/12 live checks pass** | W1, W5 | B00 | — | 4 |
| B02 | Data model and tenancy — **built 2026-11-11, 122 pytest + 26/26 live checks pass; M1 reached** | W2 | B01 | **M1** | 4 |
| B03 | Auth and email — **built 2026-11-12, 184 pytest + 25/25 live checks pass** | W3, W6 (mail part) | B02 | — | 5 |
| B04 | RBAC, me, orgs, users, invites — **built 2026-11-12, 285 pytest; M3 (backend) reached** | W4, W6 (invite part) | B03 | **M3** (backend) | 5 |
| B05 | Files — **built 2026-11-19, 332 pytest + 17/17 live checks pass** (presigned upload/download via RustFS on the LAN IP, J04 cleanup) | W7 | B04 | — | 4 |
| B06 | Pagination and template module (backend) — **built 2026-11-19, 393 pytest + 16/16 live checks pass** (sort/filter helper, `/items` template, one module registry, default grants on sync) | W8 (helpers), W13 (backend) | B05 | — | 3 |
| B07 | Search, exports, notifications — **built 2026-11-20, 446 pytest + 18/18 live checks pass** (search over files + items, CSV/XLSX exports via the worker, retention cleanup, notifications) | W8, W9 | B06 | — | 4 |
| B08 | Frontend base — **built 2026-11-13, 53 vitest + 19/19 live checks pass** (+ placeholder login and one `/home` landing page) | W10 | B03 | — | 4 |
| B09 | Frontend auth and landing pages — **built 2026-11-13, 97 vitest + 27/27 live checks (42-step browser walk) pass; M2 reached**. B05–B07 cards are placeholders | W11 | B08, B04 | **M2** | 4 |
| B10 | Frontend features — **built 2026-11-20; M4 reached** (Files, Search, Users, Profile, Organization, Export dialog, bell; landing cards live) | W12 | B09, B05, B07 | **M4** | 6 |
| B11 | Frontend template module — **built 2026-11-20** (config-driven `src/modules/_template`, `/items`) | W13 (frontend) | B10, B06 | — | 2 |
| B12 | Cross-cutting test suites — **built 2026-11-20** (generated permission matrix, isolation incl. 50 parallel, audit per mutation, provisioning, Playwright C1/C4/C5/C6, `make ci` + ci.yml e2e job) | W14 | B11 | — | 4 |
| B13 | Clone-and-run starter | W15 | all | **M5** | 3 |

The backend (B00–B07) and frontend (B08–B11) can overlap once B03 has an OpenAPI schema.

---

## B00 — Repo and dev stack (W0)

| # | Object | Type | Path |
|---|---|---|---|
| 1 | Dev compose (C01–C07, `storage-init`) | config | `docker-compose.yml` (copied from `01_design/docker_compose.yml`) |
| 2 | Env template, every key in master list §H plus `MAX_UPLOAD_MB`, `EXPORT_MAX_ROWS` | config | `.env.example` |
| 3 | Make targets (`up`, `down`, `logs`, `migrate`, `create-tenant`, `gen-client`, `test`, `e2e`, `lint`) | script | `Makefile` |
| 4 | Postgres init: `pg_trgm`, `citext` | sql | `deploy/postgres/init.sql` |
| 5 | Audit log host dir | dir | `logs/audit/.gitkeep` |
| 6 | Backend image + project | config | `backend/Dockerfile`, `backend/pyproject.toml` (uv) |
| 7 | Frontend image placeholder (just enough for the container to start) | config | `frontend/Dockerfile` |
| 8 | Lint/format hooks | config | `.pre-commit-config.yaml` |
| 9 | CI skeleton (lint, type check, test) | config | `.github/workflows/ci.yml` (or Gitea equivalent) |
| 10 | Ignore files | config | `.gitignore`, `.dockerignore` |

**Done when:** `docker compose up` brings up postgres, redis, rustfs, mailpit; the bucket exists.

## B01 — Backend core and audit (W1, W5)

| # | Object | ID | Type | Path |
|---|---|---|---|---|
| 1 | Settings (pydantic-settings) | — | config | `backend/app/config.py` |
| 2 | Error types, error body, handlers | S08 | core | `backend/app/core/errors.py` |
| 3 | Engines, sessions, `search_path` reset | S02 | core | `backend/app/core/db.py` |
| 4 | JSON-lines audit writer `record()` | S05 | core | `backend/app/core/audit.py` |
| 5 | Structlog setup + request-id middleware | — | core | `backend/app/core/logging.py` *(new file, not in `file_system.md`; my call)* |
| 6 | Health module: `/health/live`, `/health/ready` | S18 | module | `backend/app/modules/health/` |
| 7 | App factory, router registry, middleware, startup checks | — | app | `backend/app/main.py` |
| 8 | Test harness (pytest config, fixtures, testcontainers) | — | test | `backend/tests/conftest.py` |

**Done when:** `/api/health/ready` is green; an audit test line lands in `logs/audit/audit.log`; errors return the standard body.

## B02 — Data model and tenancy (W2)

| # | Object | ID | Type | Path |
|---|---|---|---|---|
| 1 | Public models: users, organizations, org_memberships, refresh_tokens, invitations, verification/reset tokens | E01–E06 | model | `backend/app/models/public.py` |
| 2 | Tenant models: roles, permissions, role_permissions, user_roles, settings | T01–T04, T07 | model | `backend/app/models/tenant.py` |
| 3 | Alembic config, two tracks | E07, T10 | config | `backend/alembic.ini`, `backend/migrations/{public,tenant}/env.py` |
| 4 | Initial public migration | — | migration | `backend/migrations/public/versions/0001_*.py` |
| 5 | Initial tenant migration (incl. cross-schema FKs) | — | migration | `backend/migrations/tenant/versions/0001_*.py` |
| 6 | Tenant resolver, membership check, schema binding | S01 | core | `backend/app/core/tenancy.py` |
| 7 | Permission registry + module `permissions.py` collection (seed side only) | S04 (part) | core | `backend/app/core/permissions.py` |
| 8 | Seed data: roles R02–R06, grant matrix, default settings | — | seed | `backend/app/modules/rbac/seed.py` |
| 9 | Provisioning service (8 idempotent steps) | S12 (part) | service | `backend/app/modules/organizations/provisioning.py` |
| 10 | CLI: `create-tenant`, `migrate-public`, `migrate-all`, `list-orgs`, `suspend-org`, `activate-org`, `rotate-secret-check` | S19 (part) | cli | `backend/app/cli.py` |

**Done when (M1):** `make create-tenant slug=acme ...` creates `tenant_acme` with seeded roles; re-running it is safe; a bad slug is rejected.

## B03 — Auth and email (W3, W6 mail part)

Mail is pulled forward from W6 so that forgot-password and verify-email work end to end inside this batch *(my call; the Gantt chart puts it after RBAC)*.

| # | Object | ID | Type | Path |
|---|---|---|---|---|
| 1 | Argon2, JWT, cookie helpers | S03 | core | `backend/app/core/security.py` |
| 2 | SMTP sender + template render | S06 | core | `backend/app/core/mail.py` |
| 3 | Email templates (html + txt): verify, reset, invite | — | template | `backend/app/templates/email/` |
| 4 | Worker settings | C03 | worker | `backend/app/worker/settings.py` |
| 5 | Job `send_email` (retry 30 s / 2 min / 10 min) | J01 | job | `backend/app/worker/jobs.py` |
| 6 | Job `cleanup_expired_tokens` (cron 03:00) | J03 | job | `backend/app/worker/jobs.py` |
| 7 | Auth module: login, logout, refresh (rotation + reuse detection), verify-email, resend, forgot/reset, change-password | S10 | module | `backend/app/modules/auth/{router,service,schemas}.py` |
| 8 | Rate limit (Redis fixed window, 5/min per IP+email; login counts failures only. slowapi replaced, B03 D7) | — | core | `backend/app/core/ratelimit.py`, used in `auth/router.py` |
| 9 | Current-user dependency | — | core | `backend/app/core/security.py` |
| 10 | CLI: `create-user --platform-admin`, `set-user-status` | S19 (part) | cli | `backend/app/cli.py` |

**Done when:** login sets cookies; refresh rotates; reusing an old refresh token revokes the family; a reset email shows up in Mailpit (C5).

## B04 — RBAC, me, orgs, users, invites (W4, W6 invite part)

| # | Object | ID | Type | Path |
|---|---|---|---|---|
| 1 | `require("<key>")` dependency + per-request permission cache | S04 | core | `backend/app/core/permissions.py` |
| 2 | RBAC module: `/roles`, `/permissions`, `PUT /users/{id}/roles` (owner rules) | S13 | module | `backend/app/modules/rbac/` |
| 3 | Organizations module: `/orgs`, `GET/PATCH /org` | S12 | module | `backend/app/modules/organizations/` |
| 4 | Users module: `/me` (+ landing_path), `PATCH /me`, `/users` CRUD, activate/deactivate | S11 | module | `backend/app/modules/users/` |
| 5 | Invitations: `POST /users/invite`, `GET/DELETE /invitations`, `POST /auth/accept-invite` | S11, S10 | module | `backend/app/modules/users/`, `auth/` |
| 6 | Platform endpoints `/platform/orgs`, `/platform/stats` (stub) | — | module | `backend/app/modules/organizations/platform_router.py` *(placement is my call)* |
| 7 | CLI: `invite-user`, `sync-permissions` | S19 (part) | cli | `backend/app/cli.py` |

**Done when (M3 backend):** invite → accept → login works (C4); `/me` returns the right `landing_path` for all six roles; a missing permission returns 403; a forged `X-Tenant` is rejected (C2, C3).

## B05 — Files (W7)

| # | Object | ID | Type | Path |
|---|---|---|---|---|
| 1 | S3 client (RustFS, path-style), presigned PUT/GET, HEAD | S07 | core | `backend/app/core/storage.py` |
| 2 | `files` model + tenant migration (GIN, trigram, btree indexes) | T05 | model, migration | `models/tenant.py`, `migrations/tenant/versions/0002_files.py` |
| 3 | Files module: presign-upload, confirm, list, get, download-url, delete | S15 | module | `backend/app/modules/files/` |
| 4 | Job `cleanup_orphan_files` (cron 03:30, per-tenant) | J04 | job | `backend/app/worker/jobs.py` |

**Done when:** upload → confirm → download through a presigned URL (C6); a delete is soft, and J04 removes the object.

**Built 2026-11-19** (`05_stage05/20261119_b05_design.md`): RustFS CORS via `RUSTFS_CORS_ALLOWED_ORIGINS` (= `CORS_ORIGINS`), dev `S3_PUBLIC_ENDPOINT` on the LAN IP, new setting `ALLOWED_MIME_TYPES`, CLI `cleanup-files [--org]`. `GET /files` has `q` + `mine=true` only; sort/`filter[...]` come with B06.

## B06 — Pagination and template module, backend (W8 helpers, W13 backend)

The backend template module comes before search/export because both use `items` as a resource type.

| # | Object | ID | Type | Path |
|---|---|---|---|---|
| 1 | Page/sort/`filter[...]` parser, shared by lists and exports | S09 | core | `backend/app/core/pagination.py` |
| 2 | Retrofit `/users` and `/files` lists onto the helper | — | refactor | — |
| 3 | `_template_items` model + migration | T09 | model, migration | `models/tenant.py`, `migrations/tenant/versions/0003_items.py` |
| 4 | Template module: `/items` CRUD, `items:*` permissions, audit | — | module | `backend/app/modules/_template/` |
| 5 | Module registry (one list in `main.py`) and copy guide | — | app, doc | `backend/app/main.py`, `modules/_template/README.md` |

**Done when:** after copying `_template`, registering it and running `sync-permissions`, a new module works with no other core edits.

**Built 2026-11-19** (`05_stage06/20261119_b06_design.md`): the registry is `app/modules/registry.py` (not `main.py`); modules keep their tables in their own `models.py`; `PermissionDef.default_roles` replaces the matrix in `rbac/seed.py`, and `sync-permissions` grants defaults for newly added keys only. Proven by `tests/test_module_copy.py`. Copy guide: `backend/app/modules/_template/README.md`.

## B07 — Search, exports, notifications (W8, W9)

| # | Object | ID | Type | Path |
|---|---|---|---|---|
| 1 | Search module: FTS + trigram, union by type, permission-filtered | S16 | module | `backend/app/modules/search/` |
| 2 | `export_jobs` + `notifications` models + migration | T08, T06 | model, migration | `models/tenant.py`, `migrations/tenant/versions/0004_*.py` |
| 3 | Exports module: create, status, list | S17 | module | `backend/app/modules/exports/` |
| 4 | Job `build_export` (CSV/XLSX, server-side cursor, `EXPORT_MAX_ROWS`) | J02 | job | `backend/app/worker/jobs.py` |
| 5 | Notifications module: list, read, read-all | S14 | module | `backend/app/modules/notifications/` |

**Done when:** search returns files + items for allowed types only; a CSV export of items downloads with the same rows as the filtered list.

**Built 2026-11-20** (`05_stage07/20261120_b07_design.md`): tables live in the modules' own `models.py` (as B06), migration `0004_exports_notifications`. Modules plug in through optional `search.py` / `exports.py` (registry `load_parts`), so a copied module is searchable/exportable with no core edit. Fuzzy match uses `word_similarity` (> 0.5) instead of `similarity` (> 0.3). Export completion creates an in-app notification. New settings `EXPORT_RETENTION_DAYS` (7, 0 = keep), `EXPORT_CLEANUP_HOUR`/`MINUTE` (03:45 UTC); CLI `cleanup-exports [--org]`; new dependency `openpyxl` (rebuild the backend image).

## B08 — Frontend base (W10)

| # | Object | Type | Path |
|---|---|---|---|
| 1 | Next.js app, TS, Tailwind, ESLint/Prettier, pnpm | config | `frontend/package.json`, `tsconfig.json`, etc. |
| 2 | `/api/*` rewrite to backend | config | `frontend/next.config.ts` |
| 3 | orval config + generated client | config, generated | `frontend/orval.config.ts`, `src/api/generated/` |
| 4 | Fetch mutator: `X-Tenant`, credentials, single refresh on 401 | lib | `frontend/src/lib/fetcher.ts` |
| 5 | Auth/session + org state (`last_org`) | lib | `frontend/src/lib/auth.ts` |
| 6 | Permission helpers (`can()`, `<Can>`) | lib | `frontend/src/lib/permissions.ts` |
| 7 | shadcn/ui components | ui | `frontend/src/components/ui/` |
| 8 | App shell, sidebar, top bar (org name; no switcher, one org per user), user menu, dev banner | ui | `frontend/src/components/layout/` |
| 9 | Navigation config `{label, href, icon, permission}` | config | `frontend/src/config/navigation.ts` |
| 10 | Route guards (proxy + layout guard) | lib | `frontend/src/proxy.ts` (Next 16 rename of middleware.ts), `(app)/layout.tsx` |
| 11 | Error pages and boundary: `/403`, `/404`, global error, session-expired toast | page | P12 |
| 12 | Vitest + RTL setup | test | `frontend/vitest.config.ts` |
| 13 | `make gen-client` drift check in CI | script | `Makefile`, CI |

**Done when:** the shell renders, guards redirect to `/login`, and the generated client compiles.

**Scope added 2026-11-13 (user):** a placeholder `/login` that really logs in and one `/home` landing page for every role; B09 replaces both.

## B09 — Frontend auth and landing pages (W11)

| # | Object | ID | Path |
|---|---|---|---|
| 1 | Public layout | — | `src/app/(public)/layout.tsx` |
| 2 | Login | P01 / S01 | `(public)/login` |
| 3 | Forgot / reset password | P02 / S02 | `(public)/forgot-password`, `reset-password` |
| 4 | Verify email | P03 / S03 | `(public)/verify-email` |
| 5 | Accept invite | P04 / S04 | `(public)/accept-invite` |
| 6 | Post-login redirect (no org picker: one org per user, B04 D1) | P05 / S05 | `(app)/post-login` |
| 7 | Landing pages owner/admin/manager/staff/user (placeholder cards, wrong-role redirect) | P06 / S07 | `(app)/home/[role]` |
| 8 | Platform page (orgs table, stats placeholder) | P07 | `(app)/platform` |

**Done when (M2):** each of the six roles logs in and lands on its own page (C1).

**Built 2026-11-13:** B05–B07 not built yet, so the landing cards for files, search and exports are labelled placeholders (user decision). Also added: `/no-organization`, the unverified-email banner, and `FRONTEND_URL` on the LAN IP. The manual test is combined with B08 (`05_stage09`).

## B10 — Frontend features (W12)

| # | Object | ID | Path |
|---|---|---|---|
| 1 | Users page: table, invite dialog, roles, activate/deactivate, invitations tab | P10 / S10 | `(app)/users` |
| 2 | Files page: table, filters, upload dialog with progress, download, delete | P08 / S08 | `(app)/files` |
| 3 | Search page | P09 / S09 | `(app)/search` |
| 4 | Profile settings + change password | P11 / S11 | `(app)/settings/profile` |
| 5 | Organization settings | P11 / S12 | `(app)/settings/organization` |
| 6 | Export dialog + recent exports (shared component) | S13 | `src/components/exports/` |
| 7 | Notifications bell (optional) | S14 | `src/components/layout/` |

**Done when (M4):** files, search and export work in the UI.

**Built 2026-11-20** with B11 (`05_stage10/20261120_b10_design.md`): no item History panel (D1) and no Users role filter (D2) (user decisions); filters in the URL; uploads by XHR for progress; shadcn dialog/tabs hand-written on `radix-ui`, native select/checkbox/textarea (no shadcn CLI). The browser walk found and fixed two bugs (search title gaps; quick filter changes overwriting each other).

## B11 — Frontend template module (W13 frontend)

| # | Object | ID | Path |
|---|---|---|---|
| 1 | Module template: list/detail/create, search, filter, export | S15 (UI) | `frontend/src/modules/_template/` |
| 2 | `/items` route using the template | — | `(app)/items` |
| 3 | Copy guide | doc | `frontend/src/modules/_template/README.md` |

**Built 2026-11-20** (design shared with B10, `05_stage10/`): one `ModuleConfig` (`types.ts`) drives generic `ModuleList` / `ModuleDetail` / `ModuleForm`; route files are ~10 lines; a new module = config + routes + one nav line.

## B12 — Cross-cutting test suites (W14)

Each batch ships its own unit and permission tests. This batch adds the suites that cover the whole system.

| # | Object | Covers | Path |
|---|---|---|---|
| 1 | Tenant isolation suite, incl. 50-parallel pooled test | C2 | `backend/tests/test_isolation.py` |
| 2 | Generated permission matrix (every endpoint × role) | C3 | `backend/tests/test_permission_matrix.py` |
| 3 | Audit-per-mutation test | C7 | `backend/tests/test_audit_coverage.py` |
| 4 | Provisioning end-to-end | C8 | `backend/tests/test_provisioning.py` |
| 5 | Playwright: login-and-land per role, invite flow, reset flow, upload/download | C1, C4, C5, C6 | `frontend/tests/e2e/` |
| 6 | CI wiring for all of the above | — | CI workflow |

**Built 2026-11-20** (`05_stage12/20261120_b12_design.md`): CI option A (user): `ci.yml` complete with an e2e job (compose stack) and the same steps locally as `make ci`; no git remote yet. The matrix and audit suites are generated from a route catalog, so copied modules are covered without test edits; a pinned table checks route permissions against `api_spec.md`. E2E has its own package and tenant `e2e` (seeded by `seed_e2e.py`). **Bug found and fixed:** each tenant request held two pooled DB connections; >15 concurrent requests deadlocked until the 30 s pool timeout (fix in `core/permissions.tenant_access`).

## B13 — Clone-and-run starter (W15)

Changed 2026-11-23 (user): not a production stack; the repo is cloned as the base of new projects. Caddy, the prod compose, TLS and an SMTP relay were dropped. Design: `05_stage13/20261123_b13_design.md`.

| # | Object | Path |
|---|---|---|
| 1 | Per-clone project name, ports, cookie prefix, derived URLs | `docker-compose.yml`, `.env.example` |
| 2 | `init` service and CLI `init`, `seed-demo` | `backend/app/cli.py` |
| 3 | Demo org and users | `backend/app/modules/organizations/demo_seed.py` |
| 4 | Port check, audits, p95 gate | `deploy/check_ports.sh`, `deploy/audit_ignore.txt`, `backend/tests/perf/list_p95.py` |
| 5 | What to update after cloning | `README_CLONING.md` |
| 6 | Setup, operations, operator SQL | `README.md`, `deploy/README.md`, `ops/sql/README.md` |
| 7 | Prod guards for database and storage credentials | `backend/app/config.py` |

**Done when (M5):** the template module works, all suites pass, and two fresh clones run side by side on one machine.

---

## Discrepancies found while compiling this list

1. **Postgres host port:** resolved 2026-11-11: host port **5200** mapped to container 5432. Updated `docker_compose.yml`, `object_msterlist.md`, `dev_tools.md`.
2. **Email ordering:** the Gantt chart puts W6 (email) after RBAC; this list moves the mail core into B03 so the reset flow can be tested there. The invite part stays in B04.
3. **Files not listed in `file_system.md`:** `core/logging.py`, `organizations/platform_router.py`, `rbac/seed.py`, `deploy/logrotate/`, `ops/sql/`. Add them to `file_system.md` or fold them into existing files.
6. **B04 (2026-11-12):** one organization per user (user decision; public migration `0002`); new endpoint `POST /auth/invitation`; `sync-permissions` already existed (B02); platform endpoints in `modules/platform/router.py`; `core/pagination.py` started (minimal) for `/users`.
5. **B03 (2026-11-12):** FastAPI-Users dropped in favour of own code (user decision, B03 D2); slowapi replaced by `core/ratelimit.py` (B03 D7); new settings `REFRESH_COOKIE_PATH`, `AUTH_RATE_LIMIT_PER_MINUTE`, `APP_NAME`. `system_design.md` §3 still names both libraries.
4. **Stage folders:** the build_object skill expects `05_stage*` folders defined in `deliverables.md`, but none are defined there. This list assumes `05_stage<NN>/` per batch.
