# File System Layout

Monorepo. `docker_compose.yml` from this folder is copied to the repo root as `docker-compose.yml`.

Updated 2026-11-23 to match the build through B13 (previous version: `20261120_file_system.md`).

```
daffy/
├── docker-compose.yml            dev stack (Postgres, Redis, RustFS, Mailpit, API, worker, frontend)
├── README.md                     setup, commands, adding a module
├── README_CLONING.md             what to update after cloning
├── .env.example                  every setting, with safe dev defaults
├── Makefile                      up, down, migrate, gen-client, test, create-tenant, cli, fe-*, e2e, ci
├── .github/workflows/ci.yml      backend, frontend, e2e jobs (inactive until the repo has a remote; B12)
├── .pre-commit-config.yaml
├── 00_plan/                      requirements (this planning folder)
├── 01_design/                    design docs
│   ├── wireframe.pdf             wireframes of every screen, as built
│   ├── wireframes/               wireframe source + build/test scripts (wireframe/wireframe.html)
│   ├── process_flows/            appFlows.pdf (F1–F13 drawn), source/appFlows.html, build_appFlows.sh
│   ├── app_flows.md              application flows v1 (spec, kept)
│   ├── app_flow_v2.md            application flows as built
│   ├── gant_sched.md             living schedule (dated copies = backups)
│   └── object_msterlist.md       living object list (dated copies = backups)
├── 03_summary/                   yyyymmdd_daily_summary.md
├── 04_todos/                     yyyymmdd_todo.md
├── 05_stage<NN>/                 per batch: dated design, plan, test script + results, manual test (.md, .ps1)
│
├── backend/                      FastAPI, port 8200
│   ├── Dockerfile
│   ├── pyproject.toml            uv-managed
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── public/               shared schema track (versions/)
│   │   └── tenant/               per-tenant track (versions/: 0001 initial, 0002 files, 0003 items,
│   │                             0004 exports + notifications)
│   ├── app/
│   │   ├── main.py               app factory, middleware; routers come from the module registry
│   │   ├── config.py             pydantic-settings
│   │   ├── openapi_dump.py       writes openapi.json for gen-client
│   │   ├── core/
│   │   │   ├── tenancy.py        resolve_tenant, tenant_session (schema_translate_map)
│   │   │   ├── db.py             engine, pool, session factory
│   │   │   ├── security.py       password hashing, JWT, cookies
│   │   │   ├── permissions.py    require(), permission registry, tenant_access (releases the public
│   │   │   │                     session before tenant work, B12)
│   │   │   ├── audit.py          JSON-lines audit writer
│   │   │   ├── mail.py           SMTP sender, Jinja templates, queue_email
│   │   │   ├── ratelimit.py      Redis fixed-window limiter (auth endpoints)
│   │   │   ├── storage.py        RustFS client: presigned PUT/GET, HEAD, put_file, delete
│   │   │   ├── errors.py         exception types, handlers, catch-all middleware
│   │   │   ├── logging.py        structlog JSON setup, request-id middleware
│   │   │   ├── pagination.py     page / sort / filter[...] helpers (ListSpec, ListQuery)
│   │   │   └── migrations.py     programmatic Alembic API (both tracks)
│   │   ├── modules/
│   │   │   ├── registry.py       THE module list: loads router, permissions, models, search, exports
│   │   │   ├── auth/             login, refresh, logout, verify, reset, invitation accept
│   │   │   ├── users/            /me, members, invitations; exports.py (users export)
│   │   │   ├── organizations/    /org, provisioning.py (create-tenant steps), demo_seed.py
│   │   │   ├── platform/         /platform/orgs, /platform/stats (Platform_Admin)
│   │   │   ├── rbac/             /roles, /permissions, role assignment; seed.py (roles + default grants)
│   │   │   ├── files/            presign, confirm, list, download, delete; cleanup.py (J04);
│   │   │   │                     search.py, exports.py (search / export sources)
│   │   │   ├── search/           /search; sources.py (SearchSource registry)
│   │   │   ├── exports/          /exports; models.py (export_jobs), sources.py (ExportSource registry),
│   │   │   │                     builder.py (J02 body), cleanup.py (retention)
│   │   │   ├── notifications/    /notifications; models.py; service.notify() for any module
│   │   │   ├── health/           /health/live, /health/ready
│   │   │   └── _template/        copy me to add a business module (/items): models, permissions,
│   │   │                         schemas, service, router, search.py, exports.py, README.md
│   │   ├── models/
│   │   │   ├── base.py           PublicBase / TenantBase (separate MetaData)
│   │   │   ├── public.py         User, Organization, OrgMembership, tokens, Invitation
│   │   │   └── tenant.py         Role, Permission, RolePermission, UserRole, Setting, File
│   │   ├── worker/
│   │   │   ├── settings.py       arq WorkerSettings, crons (J03 03:00, J04 03:30, exports 03:45)
│   │   │   └── jobs.py           send_email, build_export, cleanup_* jobs
│   │   ├── templates/email/      Jinja2 (verify, reset, invite)
│   │   └── cli.py                create-tenant, create-user, invite-user, migrate-all, sync-permissions,
│   │                             suspend/activate-org, cleanup-files, cleanup-exports, ...
│   └── tests/                    pytest + testcontainers; route_catalog.py drives the B12 suites:
│                                 test_permission_matrix (C3), test_isolation (C2),
│                                 test_audit_coverage (C7), test_provisioning (C8)
│
├── frontend/                     Next.js, port 3200
│   ├── Dockerfile
│   ├── package.json              pnpm (tooling runs in the container only)
│   ├── next.config.ts            rewrite /api/* to backend
│   ├── orval.config.ts           OpenAPI client generation
│   ├── openapi.json              schema snapshot (make gen-client; drift-checked)
│   ├── src/
│   │   ├── app/                  App Router routes
│   │   │   ├── (public)/         login, forgot-password, reset-password, verify-email, accept-invite
│   │   │   └── (app)/            authenticated shell
│   │   │       ├── post-login/   role-based redirect
│   │   │       ├── no-organization/
│   │   │       ├── home/[role]/  landing pages
│   │   │       ├── files/, search/, users/
│   │   │       ├── settings/     profile/, organization/
│   │   │       ├── items/        B11 template routes: list, new, [id], [id]/edit
│   │   │       └── platform/     Platform_Admin page
│   │   ├── api/generated/        orval output (do not edit)
│   │   ├── components/
│   │   │   ├── ui/               shadcn/ui + dialog, tabs (radix-ui), native.tsx (select, checkbox,
│   │   │   │                     textarea, progress)
│   │   │   ├── layout/           shell, sidebar, top bar, user menu, notifications bell, dev banner,
│   │   │   │                     page.tsx (GatedPage, PageHeader)
│   │   │   ├── data/             DataTable, Pager, RowMenu, SearchInput, ConfirmDialog
│   │   │   ├── dashboard/        landing cards
│   │   │   ├── exports/          Export dialog + recent exports
│   │   │   ├── files/            upload dialog
│   │   │   ├── users/            invite + roles dialogs
│   │   │   ├── search/           search types
│   │   │   └── forms/            labelled field, form alert
│   │   ├── lib/                  fetcher (X-Tenant), auth, permissions, list-params (URL state),
│   │   │                         upload, files (download), format, highlight, forms
│   │   ├── config/               navigation.ts (menu + permission), landing.ts (cards per role), site.ts
│   │   ├── modules/_template/    frontend module template: types.ts (ModuleConfig), config.ts (items),
│   │   │                         components/ (list, detail, form), README.md
│   │   ├── test/                 Vitest fixtures and helpers
│   │   └── proxy.ts              route guard (Next 16 name for middleware.ts, B08 D2)
│   └── tests/e2e/                Playwright, own package (C1, C4, C5, C6): specs, helpers.ts,
│                                 seed_e2e.py (e2e tenant), run_e2e.sh (make e2e)
│
├── deploy/
│   ├── postgres/init.sql         extensions: pg_trgm, citext
│   ├── check_ports.sh            make ports
│   ├── audit_ignore.txt          accepted pip-audit findings
│   └── README.md                 backup / restore, logrotate, before production
├── ops/sql/README.md             operator SQL (data_model.md §6)
│
└── logs/
    └── audit/                    bind-mounted host dir: audit.log (+ rotated)
```

## Runtime locations (containers)

| What | Path in container | Host mapping |
|---|---|---|
| Audit log | `/var/log/app/audit/audit.log` | `./logs/audit` |
| Postgres data | `/var/lib/postgresql/data` | named volume `pgdata` |
| RustFS (S3) data | `/data` | named volume `s3data` |

## Conventions

- **A backend module** is a folder under `app/modules/` with `router.py`, `service.py`, `schemas.py`, `permissions.py` (keys + `default_roles`), and optionally:
  - `models.py`: its tenant tables;
  - `search.py`: makes it searchable;
  - `exports.py`: makes it exportable.

  Add its name to `modules/registry.py`; nothing else in core changes (B06, B07).
- **A frontend module** is a `ModuleConfig` (copy `src/modules/_template/config.ts`), thin route files under `src/app/(app)/<name>/`, and one line in `config/navigation.ts` (B11).
- Tenant provisioning lives in `modules/organizations/provisioning.py`. Roles live in `modules/rbac/seed.py`; default grants are declared by each module's `permissions.py`.
- Tenant migrations are written WITHOUT a schema (run with `SET LOCAL search_path`); public ones name `public` explicitly. A module's migration is the next revision in the one tenant track.
- Routers only parse requests and call services. Services hold business rules. Models hold no logic.
- Generated code lives under `api/generated` and is never hand edited. CI fails if it drifts from the schema.
- **Tests:**
  - A new mutation route must be added to `RECIPES` or `NO_AUDIT` in `tests/test_audit_coverage.py`.
  - The permission matrix and isolation suites pick new routes up automatically from `tests/route_catalog.py`.
- **Documents** in `03_summary/`, `04_todos/` and `05_stage<NN>/` carry a `yyyymmdd_` prefix (`_<n>` when one already exists that day).
