# Backend Processes

## 1. Worker (arq)

One worker container running `arq app.worker.settings.WorkerSettings`. Redis is the queue. Jobs are idempotent; defaults: `max_tries=3`, exponential backoff, `job_timeout=300`.

| ID | Job | Trigger | Steps | Failure handling |
|---|---|---|---|---|
| J01 | `send_email(template, to, context, org_slug?)` | verify, reset, invite | render Jinja2 (html + text) → SMTP send with `SMTP_*` settings | retry 30 s / 2 min / 10 min, then log error and audit `email.failed` |
| J02 | `build_export(export_id, org_slug)` | `POST /exports` | bind tenant schema → stream rows (server-side cursor) → write CSV/XLSX to temp → upload to RustFS → update `export_jobs` | status `failed` with error text |
| J03 | `cleanup_expired_tokens` | cron daily 03:00 | delete expired/used reset, verify and refresh tokens, expired invitations | log counts |
| J04 | `cleanup_orphan_files` | cron daily 03:30 | per tenant: `pending` files older than 24 h and `deleted` rows → delete RustFS object, remove or mark row | per-tenant try/except |

Per-tenant jobs get `org_slug` and open their own tenant session; they never rely on request state.

## 2. Tenant provisioning (CLI)

`python -m app.cli create-tenant --slug acme --name "Acme" --owner-email owner@acme.test`

1. Validate slug pattern and uniqueness; reserved words rejected (`public`, `admin`, `platform`, ...).
2. Insert `organizations` row, status `provisioning`, `schema_name = tenant_<slug>`.
3. `CREATE SCHEMA tenant_acme`.
4. Run tenant Alembic track targeting the schema.
5. Seed roles, permissions, grants, settings.
6. Create or find the owner user; create membership and `user_roles` owner; if the user is new, send an invite email.
7. Set status `active`; write audit line `org.created`.
8. On any failure: mark `provisioning` row `failed`, drop the half-created schema (only if it was created in this run), exit non-zero.

Each step is idempotent so a re-run with the same slug resumes.

## 3. Other CLI commands

| Command | Purpose |
|---|---|
| `migrate-public` | Run public migrations |
| `migrate-all` | Run tenant migrations for every active org; report per tenant |
| `sync-permissions` | Upsert permission keys from modules into every tenant; does not alter grants |
| `create-user --email --platform-admin` | Create a Platform_Admin |
| `invite-user --org --email --role` | Create invitation + email |
| `set-user-status --email --active/--inactive` | |
| `suspend-org / activate-org --slug` | |
| `list-orgs` | |
| `rotate-secret-check` | Sanity check of config |

All CLI actions write audit lines with `actor="cli:<os-user>"`.

## 4. Audit writer

`core.audit.record(action, entity, entity_id, org, actor, diff, result)`.

- Builds the JSON line (see `system_design.md` §7), strips sensitive keys (`password`, `token`, `secret`, `authorization`).
- Appends through a dedicated `logging.Logger("audit")` with `WatchedFileHandler(AUDIT_LOG_DIR/audit.log)`; propagation off; formatter emits the raw JSON.
- Logrotate (host): weekly, keep 12, compress, `copytruncate` not needed with `WatchedFileHandler`.
- Auth events recorded: login success/failure, logout, refresh reuse detected, password change/reset, invite accepted.
- Mutation events: `<module>.<verb>` e.g. `files.delete`, `users.invite`, `roles.assign`.

Example line:
```json
{"ts":"2026-11-11T10:15:02Z","org":"acme","actor":"7f3c…","action":"files.delete","entity":"file","entity_id":"a1b2…","diff":{"status":["active","deleted"]},"ip":"172.18.0.1","request_id":"c9d1…","result":"ok"}
```

## 5. Email

- Templates: `verify_email`, `reset_password`, `invite_user` (html + txt) in `app/templates/email`.
- Links use `FRONTEND_URL` (e.g. `http://localhost:3200/reset-password?token=...`).
- Tokens: 32 random bytes URL-safe; only the SHA-256 hash stored; expiry reset 1 h, verify 24 h, invite 7 days; single use.
- Dev: SMTP `mailpit:1025`, no auth, no TLS.

## 6. Files lifecycle

1. `presign-upload`: validate, insert `files(status=pending)`, return presigned PUT (15 min).
2. Browser PUTs to RustFS.
3. `confirm`: HEAD the object, compare size, set `active`, audit `files.upload`.
4. Delete: set `deleted`, audit; J04 removes the object later.
5. Pending rows never confirmed are removed by J04.

## 7. Search and export implementation notes

- Search queries `plainto_tsquery('simple', q)` ranked with `ts_rank`, plus `similarity(name, q) > 0.3` for typos; union per resource type; only types the caller has permission for.
- Export reads with the same filter parser as list endpoints to guarantee the same rows; row limit `EXPORT_MAX_ROWS` (default 100 000).

## 8. Auth maintenance

- Refresh reuse detection: presenting a revoked token revokes the whole `family_id` and audits `auth.refresh_reuse`.
- Failed-login counter in Redis (5/min per IP+email); no account lockout in Phase 1.

## 9. Startup and health

- Backend start: load config, check DB connectivity, ensure audit directory is writable (fail fast), mount routers.
- `/health/ready` checks Postgres, Redis, RustFS bucket.
- `storage-init` one-shot container (aws-cli) creates the bucket.

## 10. Backups (ops)

- `pg_dump` per run (all schemas) daily; retain 14 days.
- RustFS volume and `logs/audit` folder copied nightly.
- Restore procedure documented in `README` of `deploy/`.
