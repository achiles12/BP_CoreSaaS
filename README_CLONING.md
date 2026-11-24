# What to update after cloning

Everything per-clone lives in `.env` (git-ignored). Create it with `make env` (or `cp .env.example .env`), edit, then start the stack. Each clone is a complete, separate stack: its own Postgres, Redis, file storage, mail inbox and audit log.

| Your situation | Read |
|---|---|
| First try, nothing else running on these ports | nothing to change: `docker compose up -d`, then log in (see `README.md`) |
| Another clone already runs on this machine | [1](#1-second-clone-on-the-same-machine) |
| You open the app from another PC | [2](#2-opening-it-from-another-pc) |
| You start your own product | [3](#3-making-it-your-product) and [4](#4-demo-data-and-the-items-example) |
| Real users will use it | [5](#5-before-real-users) |

## 1. Second clone on the same machine

Do this **before** the first `up`.

```bash
git clone <repo> beta && cd beta
make env          # creates .env
# edit .env (table below)
make ports        # every line must say "free" (stopped clones are not seen)
docker compose up -d --build
```

| File | Key | Example | If you skip it |
|---|---|---|---|
| `.env` | `COMPOSE_PROJECT_NAME` (remove the `#`) | `beta` | The folder name is used. Two clones with the same name **share containers and data** |
| `.env` | `FRONTEND_PORT` | `3300` | "port is already allocated", the stack does not start |
| `.env` | `BACKEND_PORT` | `8300` | same |
| `.env` | `POSTGRES_HOST_PORT` (DBeaver) | `5300` | same |
| `.env` | `S3_API_PORT` (uploads, downloads) | `9300` | same |
| `.env` | `S3_CONSOLE_PORT` | `9301` | same |
| `.env` | `MAILPIT_SMTP_PORT` | `1325` | same |
| `.env` | `MAILPIT_UI_PORT` | `8325` | same |
| `.env` | `COOKIE_PREFIX` | leave commented out | Default is `<project>_`. If two clones on one host have the **same** value, logging into one logs you out of the other |

- Project names: lower-case letters, digits, `-` and `_`.
- Do not write comments after a port value.
- Email links, upload URLs, CORS and the mail banner follow the ports. Leave `FRONTEND_URL`, `CORS_ORIGINS` and `S3_PUBLIC_ENDPOINT` commented out; if set, they keep their old port.
- If you copied a `.env` from another clone, change the project name **and** all seven ports.
- Memory: each clone runs 7 containers. Stop unused ones with `docker compose stop`.

## 2. Opening it from another PC

| File | Key | Example | If you skip it |
|---|---|---|---|
| `.env` | `PUBLIC_HOST` | the server's LAN IP, e.g. `10.0.0.5` | Email links and uploads point to `localhost`, so they fail on the other PC; the dev server blocks the page's scripts |

Then `docker compose up -d`.

## 3. Making it your product

| File | What | Example | If you skip it |
|---|---|---|---|
| `.env` | `APP_NAME` | `Acme Cloud` | Screens and emails say "Core SaaS" |
| `.env` | `SMTP_FROM` | `no-reply@acme.test` | Emails come from `no-reply@app.local` |
| `.env.example` | the same keys, as your team's defaults | | Team members start with the old values |
| `backend/pyproject.toml` | `name`, then `cd backend && uv lock` | `acme-backend` | Cosmetic. Without `uv lock` the next frozen install fails |
| `frontend/package.json`, `frontend/tests/e2e/package.json` | `name` | `acme-frontend` | Cosmetic |
| `README.md` | title and text | | Describes the starter |
| git | `git remote set-url origin <your repo>` | | You push to the starter repo |
| `00_plan/`, `01_design/` | design documents of the starter | keep, replace or delete | They describe the starter, not your product |

The API title is fixed in `backend/app/main.py` (`title="Core SaaS API"`). If you change it, run `make gen-client`.

## 4. Demo data and the `/items` example

| File | What | If you skip it |
|---|---|---|
| `.env` | `SEED_DEMO=false` stops creating the demo org | A public, documented password exists in this database (dev only) |
| `backend/app/modules/organizations/demo_seed.py` | other demo users | The org stays "Demo Org" |
| `backend/app/modules/_template/`, `frontend/src/modules/_template/` | keep as the pattern to copy, or replace | Your product shows an "Items" page |

`SEED_DEMO=false` does not remove users that already exist: disable them with `make cli args="set-user-status --help"`, or start with an empty volume.

Adding your own module: [`backend/app/modules/_template/README.md`](backend/app/modules/_template/README.md), then [`frontend/src/modules/_template/README.md`](frontend/src/modules/_template/README.md).

Your own first tenant:

```bash
make create-tenant slug=acme name="Acme Inc" owner=owner@acme.test password=1
```

## 5. Before real users

This stack is a **development** stack. Read [`deploy/README.md`](deploy/README.md) first.

| File | Key | If you skip it |
|---|---|---|
| `.env` | `APP_ENV=prod` | API docs stay public, the demo seed may run |
| database | demo users: use an empty volume, or deactivate all six | Anyone can log in with the password in `README.md`, also as platform admin. `init` refuses to start in prod |
| `.env` | `SECRET_KEY` (32+ characters) | Anyone can forge logins. Refused in prod |
| `.env` | `COOKIE_SECURE=true` (needs HTTPS) | Login cookies travel in clear text. Refused in prod |
| `.env` | `POSTGRES_PASSWORD` | Default password. Refused in prod |
| `.env` | `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Default credentials. Refused in prod |
| `.env` | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Emails stay in Mailpit |

## Do not change

| What | Why |
|---|---|
| Ports inside the containers (right side of `3200:3200`) | The services find each other by them. `SMTP_PORT=1025` is one of these |
| `TENANT_HEADER` | The frontend always sends `X-Tenant` |
| `frontend/src/api/generated/`, `frontend/openapi.json` | Generated: `make gen-client` |

## Changing it later

| Change | What happens | Do |
|---|---|---|
| A port, `PUBLIC_HOST`, `APP_NAME` | Data stays | `make ports`, then `docker compose up -d` |
| `COOKIE_PREFIX` | Everyone must log in again | `docker compose up -d` |
| `COMPOSE_PROJECT_NAME`, or the folder name if it is unset | **New, empty volumes.** The old data stays in the old volumes | Set the old name back, or back up and restore ([`deploy/README.md`](deploy/README.md)) |
| `POSTGRES_PASSWORD` | Applies only to an **empty** volume; otherwise the API cannot connect | Also run `ALTER USER app PASSWORD '...'` in the database |
| `SECRET_KEY` | Everyone must log in again | `docker compose up -d` |
