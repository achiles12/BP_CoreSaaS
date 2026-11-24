# File System Layout

Monorepo. `docker_compose.yml` from this folder is copied to the repo root as `docker-compose.yml`.

```
daffy/
├── docker-compose.yml            dev stack
├── docker-compose.prod.yml       adds Caddy, removes Mailpit (later)
├── .env.example                  every setting, with safe dev defaults
├── Makefile                      up, down, migrate, gen-client, test, create-tenant
├── 00_plan/                      requirements (this planning folder)
├── 01_design/                    design docs
│   └── wireframe.pdf             wireframes of every screen (built from 05_stage10/wireframe/)
│
├── backend/                      FastAPI, port 8200
│   ├── Dockerfile
│   ├── pyproject.toml            uv-managed
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── public/               shared schema track (versions/)
│   │   └── tenant/               per-tenant track (versions/)
│   ├── app/
│   │   ├── main.py               app factory, router registry, middleware
│   │   ├── config.py             pydantic-settings
│   │   ├── core/
│   │   │   ├── tenancy.py        resolve_tenant, schema binding
│   │   │   ├── db.py             engine, session factory, tenant session
│   │   │   ├── security.py       password hashing, JWT, cookies
│   │   │   ├── permissions.py    require(), permission registry
│   │   │   ├── audit.py          JSON-lines audit writer
│   │   │   ├── mail.py           SMTP sender, Jinja templates
│   │   │   ├── ratelimit.py      Redis fixed-window limiter (auth endpoints)
│   │   │   ├── storage.py        RustFS client, presigned URLs
│   │   │   ├── errors.py         exception types, handlers, catch-all middleware
│   │   │   ├── logging.py        structlog JSON setup, request-id middleware
│   │   │   ├── pagination.py     page/filter/sort helpers
│   │   │   └── migrations.py     programmatic Alembic API (both tracks)
│   │   ├── modules/
│   │   │   ├── auth/             router, service, schemas
│   │   │   ├── users/
│   │   │   ├── organizations/
│   │   │   ├── rbac/
│   │   │   ├── notifications/
│   │   │   ├── files/
│   │   │   ├── search/
│   │   │   ├── exports/
│   │   │   ├── health/
│   │   │   └── _template/        copy me to add a business module
│   │   ├── models/
│   │   │   ├── base.py           PublicBase / TenantBase (separate MetaData)
│   │   │   ├── public.py         User, Organization, OrgMembership, ...
│   │   │   └── tenant.py         Role, Permission, File, ...
│   │   ├── worker/
│   │   │   ├── settings.py       arq WorkerSettings
│   │   │   └── jobs.py           send_email, build_export, ...
│   │   ├── templates/email/      Jinja2 (verify, reset, invite)
│   │   └── cli.py                create-tenant, create-user, migrate-all, ...
│   └── tests/
│
├── frontend/                     Next.js, port 3200
│   ├── Dockerfile
│   ├── package.json              pnpm
│   ├── next.config.ts            rewrite /api/* to backend
│   ├── orval.config.ts           OpenAPI client generation
│   ├── openapi.json              schema snapshot (make gen-client; drift-checked)
│   ├── src/
│   │   ├── app/                  App Router routes
│   │   │   ├── (public)/login, forgot-password, reset-password, verify
│   │   │   └── (app)/            authenticated shell
│   │   │       ├── post-login/   role-based redirect
│   │   │       ├── home/[role]/  landing pages
│   │   │       ├── files/, search/, settings/, users/
│   │   │       └── platform/     Platform_Admin pages
│   │   ├── api/generated/        orval output (do not edit)
│   │   ├── components/ui/        shadcn/ui
│   │   ├── components/layout/    shell, sidebar, top bar, user menu, dev banner (no org switcher: one org per user)
│   │   ├── lib/                  fetcher with X-Tenant, auth, permissions
│   │   ├── proxy.ts              route guard (Next 16 name for middleware.ts, B08 D2)
│   │   ├── modules/_template/    frontend module template
│   │   └── config/navigation.ts  menu items with required permissions
│   └── tests/e2e/                Playwright
│
├── deploy/
│   ├── caddy/Caddyfile           prod only
│   └── postgres/init.sql         extensions: pg_trgm, citext
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

- Module = `router.py`, `service.py`, `schemas.py`, `permissions.py`, optional `models` in `app/models`.
- Tenant provisioning lives in `modules/organizations/provisioning.py`; default roles/grants in `modules/rbac/seed.py`.
- Tenant migrations are written WITHOUT a schema (run with `SET LOCAL search_path`); public ones name `public` explicitly.
- Routers only parse requests and call services. Services hold business rules. Models hold no logic.
- Generated code lives under `api/generated` and is never hand edited. CI fails if it drifts from the schema.
