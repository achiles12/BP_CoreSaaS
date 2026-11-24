# Setting up from a fresh clone

Part A gets the stack running, B lists the settings to change, C adds business logic, D lists other extension points. See also [`README.md`](README.md) and [`README_CLONING.md`](README_CLONING.md).

## A. Get it running

**1. Install:** Docker with a recent Compose v2, `make` and `git`, on Linux, macOS or WSL 2. You also need [`uv`](https://docs.astral.sh/uv/) for `make gen-client`, `lint` and `test`. You don't need Node or pnpm, because frontend tools run in the container.

**2. Clone and create your settings**

```bash
git clone <repo> acme && cd acme
make env          # .env.example -> .env
```

**3. Edit `.env`** (part B), **before the first start**.

**4. Check ports, then start**

```bash
make ports                     # every line must say "free"
docker compose up -d --build
docker compose logs init       # must end with "[init] ready"
make check                     # every line OK
```

`init` migrates, syncs permissions and adds demo data on every `up`.

**5. Log in** at <http://localhost:3200> as `owner@demo.test` / `Demo-pass-2026-ok`. The other demo users are `admin@`, `manager@`, `staff@`, `user@` and `platform@`.

API docs are at `:8200/docs` and emails at `:8025`.

**6. Create your own tenant**

```bash
make create-tenant slug=acme name="Acme Inc" owner=owner@acme.test password=1
```

**If it fails**

- **"port is already allocated":** change that port in `.env`.
- **Permission denied** (your UID is not 1000): `chmod -R a+rwX logs frontend backend`, then `docker compose up -d`.

## B. Settings to change in `.env`

| When | Key | Set to |
|---|---|---|
| Always | `COMPOSE_PROJECT_NAME` (uncomment) | `acme`. Pick it once: a new name means new, **empty** volumes |
| Always | `APP_NAME`, `SMTP_FROM` | `Acme Cloud`, `no-reply@acme.test` |
| Always | `SECRET_KEY` | output of `openssl rand -hex 32` |
| Before first start | `POSTGRES_PASSWORD` | `openssl rand -hex 16`. Use hex: it goes into a URL. Later changes also need `ALTER USER` |
| Recommended | `S3_ACCESS_KEY`, `S3_SECRET_KEY` | your own values |
| Second clone on the machine | all 7 ports | `3300, 8300, 5300, 9300, 9301, 1325, 8325`, in file order |
| Opened from another PC | `PUBLIC_HOST` | the server's LAN IP |
| No demo data | `SEED_DEMO` | `false` before first start. It does not remove existing demo users |
| Optional | `MAX_UPLOAD_MB`, `ALLOWED_MIME_TYPES`, `EXPORT_*` | your limits |
| Real email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | your relay (port 587) |

- **Leave commented out:** `FRONTEND_URL`, `CORS_ORIGINS`, `S3_PUBLIC_ENDPOINT` and `COOKIE_PREFIX` are derived.
- **No effect in `.env`:** `ACCESS_TOKEN_MINUTES` and `REFRESH_TOKEN_DAYS` are hard-coded in `docker-compose.yml`, so edit them there.
- **Apply changes:** `docker compose up -d`.

**Other branding**

| What | Where |
|---|---|
| Colors | `frontend/src/app/globals.css` |
| Icon | `frontend/src/app/icon.svg` |
| Emails | `backend/app/templates/email/` |
| API title | `backend/app/main.py`, then `make gen-client` |
| Git remote | `git remote set-url origin <your repo>` |

This is a development stack. Before real users, read `README_CLONING.md` section 5 and [`deploy/README.md`](deploy/README.md).

## C. Add business logic (example: `projects`)

Copy `_template`, the working `/items` example. Run everything from the repo root.

### Backend

**1. Copy and rename** (GNU sed; on macOS use `gsed`)

```bash
M=backend/app/modules/projects
cp -r backend/app/modules/_template $M && rm -rf $M/__pycache__
sed -i \
 -e 's/app\.modules\._template/app.modules.projects/g; s/_template_items/projects/g; s/TemplateItem/Project/g' \
 -e 's/ITEM_STATUSES/PROJECT_STATUSES/g; s/ITEMS_LIST/PROJECTS_LIST/g; s/items_statement/projects_statement/g' \
 -e 's/\bItem\(Create\|Update\|Out\|Status\)/Project\1/g' \
 -e 's/\b\(list\|get\|create\|update\|delete\)_items\b/\1_projects/g; s/\b\(get\|create\|update\|delete\)_item\b/\1_project/g' \
 -e 's/item_id/project_id/g; s/"items"/"projects"/g; s/items:/projects:/g; s#/items#/projects#g' \
 -e 's/items\.\(create\|update\|delete\)/projects.\1/g; s/"item"/"project"/g; s/app\.items/app.projects/g; s/Item not found/Project not found/g' \
 $M/*.py
```

This also covers what the template README's rename table omits: the `Item*` schema names, and `type` / `resource` in `search.py` / `exports.py`. Keeping the old search or export name fails with "registered twice".

**2. Write your logic in `backend/app/modules/projects/`**

| File | What goes here |
|---|---|
| `models.py` | table and columns |
| `schemas.py` | input/output fields, validation |
| **`service.py`** | **business rules:** calculations, status changes, limits |
| `router.py` | endpoints only; each needs `require("projects:…")` |
| `permissions.py` | keys and the roles that get them |
| `search.py`, `exports.py` | optional; delete if unused |

In `service.py`, keep this order: load the row, check the rule, change, commit, `audit.record(...)`.

**3. Migration:** the starter's tenant head is `0004_exports_notifications`, so your first one is **0005** (the template README's `0004_projects.py` example is out of date). Later modules follow your own newest revision.

```bash
V=backend/migrations/tenant/versions
sed 's/0003_items/0005_projects/g; s/0002_files/0004_exports_notifications/g; s/_template_items/projects/g' \
  $V/0003_items.py > $V/0005_projects.py
```

Make its columns match `models.py`.

**4. Register:** add `"projects",` to `MODULES` in `backend/app/modules/registry.py`.

**5. Apply**

```bash
make migrate
make cli args=sync-permissions
make gen-client
```

### Frontend

**6.** Copy the config and pages. Keep `_template`: your pages reuse its components.

```bash
mkdir -p frontend/src/modules/projects
cp frontend/src/modules/_template/config.ts frontend/src/modules/projects/
cp -r "frontend/src/app/(app)/items" "frontend/src/app/(app)/projects"
```

**7.** In `projects/config.ts`:

- Rename `itemsConfig` to `projectsConfig`.
- Change `./types` to `@/modules/_template/types`.
- Set `resource`, labels, `basePath`, permissions, columns, filters, fields, the Zod schema and the `api` hooks.

**8.** In the 4 copied pages, change the config import and its uses.

**9.** Connect it in `frontend/src/`:

- Sidebar: `config/navigation.ts`
- Dashboard cards: `config/landing.ts`
- Search: `components/search/search-types.ts`

### Tests

**10.** These fail until updated:

- `backend/tests/test_migrations.py`: set `TENANT_HEAD` to `"0005_projects"` and add `"projects"` to `TENANT_TABLES`.
- `backend/tests/test_audit_coverage.py`: add POST, PATCH and DELETE to `RECIPES` (or `NO_AUDIT` with a reason).

Copy `backend/tests/test_items_api.py` for your own rules, then:

```bash
(cd backend && uv run ruff check --fix . && uv run ruff format .)   # fix remaining long lines by hand
make fe-format && make ci
```

## D. Other extension points

| Need | Where |
|---|---|
| Notify a user | `notifications.service.notify(ts, user_id, type, title)`, before your commit |
| Send an email | 3 template files, add the name to `TEMPLATES` in `core/mail.py`, call `queue_email` |
| Background or scheduled job | logic in your module, wrapper in `worker/jobs.py`, register in `worker/settings.py` |
| New setting | `config.py`, `x-backend-env` in `docker-compose.yml`, `.env.example` |
| New Python package | `cd backend && uv add <pkg>`, then `docker compose up -d --build` |
| New frontend package | edit `package.json`, `make fe-install`, then `make fe-rebuild` |
| Hide Items | remove its line in `navigation.ts`. Unregistering it also breaks tests that use it |

Don't edit `frontend/src/api/generated/`, `frontend/openapi.json` or `TENANT_HEADER`.
