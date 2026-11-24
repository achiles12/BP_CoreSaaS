# Core SaaS scaffold

> **Cloned this to start a project, or running a second copy? Read [`README_CLONING.md`](README_CLONING.md).**

A starter for multi-tenant SaaS products: login, organizations (one Postgres schema per tenant), roles and permissions, invitations, files, search, exports, notifications, audit log, and a module template for your own features.

Next.js :3200 · FastAPI :8200 · Postgres 16 · Redis + arq · RustFS (S3) · Mailpit

## Quick start

Needs Docker with a recent Compose v2, and Linux, macOS or WSL 2.

```bash
git clone <repo> && cd <repo>
docker compose up -d --build
docker compose logs init      # migrations + demo data; ends with "[init] ready"
```

Open <http://localhost:3200>. The first page load compiles and takes a few seconds.

| Demo login | Lands on |
|---|---|
| `owner@demo.test` | `/home/owner` |
| `admin@demo.test` | `/home/admin` |
| `manager@demo.test` | `/home/manager` |
| `staff@demo.test` | `/home/staff` |
| `user@demo.test` | `/home/user` |
| `platform@demo.test` | `/platform` |

Password for all: `Demo-pass-2026-ok` (development only; `SEED_DEMO=false` turns the demo off).

| Service | Address |
|---|---|
| App | <http://localhost:3200> |
| API docs | <http://localhost:8200/docs> |
| Emails (Mailpit) | <http://localhost:8025> |
| File storage console | <http://localhost:9201/rustfs/console/> |
| Postgres (DBeaver) | `localhost:5200`, database, user and password `app` |

All ports can be changed in `.env`: [`README_CLONING.md`](README_CLONING.md).

## Daily commands

| Command | Does |
|---|---|
| `make up`, `make down`, `make logs`, `make check` | start, stop (data stays), follow logs, smoke check |
| `make ports` | are this clone's host ports free? |
| `make create-tenant slug=acme name="Acme" owner=o@acme.test password=1` | new tenant |
| `make cli args=--help` | all admin commands |
| `make migrate` | apply new migrations (also runs on every `up`) |
| `make gen-client` | regenerate the typed API client |
| `make lint`, `make test`, `make fe-lint`, `make fe-test` | checks |
| `make e2e`, `make audit`, `make perf` | browser tests, known vulnerabilities, p95 gate |
| `make ci` | everything CI runs |
| `make clean` | **deletes this clone's data** (asks first) |

`make lint`, `make test` and `make audit` also need [`uv`](https://docs.astral.sh/uv/) on the host. Frontend tools run in the container.

## Adding a module

1. Backend: copy `_template`, see [`backend/app/modules/_template/README.md`](backend/app/modules/_template/README.md).
2. Frontend: see [`frontend/src/modules/_template/README.md`](frontend/src/modules/_template/README.md).

How the flows work: [`01_design/app_flow_v2.md`](01_design/app_flow_v2.md). Where things live: [`01_design/file_system.md`](01_design/file_system.md).

## If something fails

| Symptom | Cause |
|---|---|
| "port is already allocated" | `make ports`, change the port in `.env` |
| `init` exited with 1 | `docker compose logs init`; fix, then `docker compose up -d` |
| `init` says "audit directory ... is not writable", or the frontend "permission denied" | The images run as UID 1000 and your Linux user has another UID: `chmod -R a+rwX logs frontend backend`, then `docker compose up -d` |
| Logged out when opening another clone | Same `COOKIE_PREFIX` in both |
| Data gone | Project or folder name changed: see "Changing it later" in `README_CLONING.md` |

Backups and going to production: [`deploy/README.md`](deploy/README.md). Operator SQL: [`ops/sql/README.md`](ops/sql/README.md).
