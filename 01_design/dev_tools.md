# Developer Tools

## Runtime versions

| Tool | Version |
|---|---|
| Python | 3.12 |
| Node.js | 22 LTS |
| PostgreSQL | 16 |
| Redis | 7 |
| Docker / Compose | current (Compose v2 syntax) |

## Backend

| Purpose | Tool |
|---|---|
| Package/env | **uv** 0.13.7 (`pyproject.toml`, `uv.lock`); same version on host (`~/.local/bin`), in the Dockerfile and in CI |
| Web | FastAPI, Uvicorn, Pydantic v2, pydantic-settings |
| DB | SQLAlchemy 2.0 async, asyncpg, Alembic |
| Auth | FastAPI-Users (flows), argon2-cffi, PyJWT |
| Jobs | arq, Redis |
| Mail | aiosmtplib, Jinja2 |
| Files | aioboto3 (RustFS, S3-compatible; `addressing_style="path"`) |
| Export | openpyxl / xlsxwriter, `csv` |
| Rate limit | slowapi |
| Logging | structlog |
| Lint/format | ruff |
| Types | pyright |
| Tests | pytest, pytest-asyncio, httpx, testcontainers. **Run on the host** with uv (`make test`); containers only run the app (decision 2026-11-11, B01 D1) |
| Audit/security | pip-audit |

## Frontend

| Purpose | Tool |
|---|---|
| Package manager | **pnpm** |
| Framework | Next.js (App Router) + React + TypeScript |
| UI | shadcn/ui, Tailwind CSS, lucide-react |
| Server state | TanStack Query; TanStack Table for lists |
| API client | **orval** from FastAPI OpenAPI |
| Forms | React Hook Form + Zod |
| Lint/format | ESLint, Prettier |
| Tests | Vitest + React Testing Library, **Playwright** (e2e) |

## Infrastructure and ops tools

| Tool | Use |
|---|---|
| Docker Compose | Dev stack (`docker_compose.yml`) |
| Mailpit | Read dev emails, http://localhost:8025 |
| RustFS Console | Browse buckets/objects, http://localhost:9201/rustfs/console/ |
| **DBeaver** | SQL and role/permission maintenance (Postgres on localhost:5200) |
| PuTTY / SFTP | Read `logs/audit/audit.log` on the host |
| pip-audit, pnpm audit | Known vulnerabilities (`make audit`) |
| logrotate | Audit log rotation (host) |
| pre-commit | ruff, eslint, prettier, schema-drift check |
| CI | GitHub Actions or Gitea/Woodpecker: lint, type check, tests, build images, audit |

## Ports (dev)

| Service | Port |
|---|---|
| Next.js | 3200 |
| FastAPI | 8200 |
| Postgres | 5200 |
| RustFS S3 API / console | 9000 / 9201 (host; console is 9001 inside the container) |
| Mailpit SMTP / UI | 1025 / 8025 |
| Redis | internal only |

## Make targets

```
make up            docker compose up -d
make down          docker compose down
make logs          follow logs
make migrate       public migrations + migrate-all
make create-tenant slug=acme name=Acme owner=owner@acme.test
make gen-client    regenerate frontend API client from /openapi.json
make test          backend + frontend unit tests
make e2e           Playwright
make lint          ruff, pyright, eslint
```

## Conventions

- **Git:** trunk-based, short branches, Conventional Commits.
- **Code:** type hints everywhere in the backend; no business logic in routers; one module per feature; services take a session and a context (`user`, `org`, `request_id`).
- **Migrations:** every schema change is an Alembic revision on the right track; never edit applied revisions.
- **Config:** every setting appears in `.env.example`; no secrets committed.
- **API changes:** regenerate client in the same commit; CI fails on drift.
- **Tests:** each module ships with permission tests; isolation tests are mandatory (`critical_user_flow.md`).
- **Naming:** DB `snake_case`, API JSON `snake_case`, TS `camelCase` mapped in the generated client, permission keys `module:action`.

## Local setup (target)

```
cp .env.example .env
docker compose up -d
make migrate
make create-tenant slug=acme name=Acme owner=owner@acme.test
# open Mailpit, accept invite, log in at http://localhost:3200
```
