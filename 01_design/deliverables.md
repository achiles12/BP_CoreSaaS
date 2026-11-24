# Deliverables: Core SaaS Scaffold

Goal: a **reusable core SaaS scaffold** with the functions in `00_plan/saas_functionality.md` available, business rules/logic left ready to implement, and a **post-login landing page that depends on the user's role (RBAC)**.

Stack (from `00_plan/suggested_tech_stack.md`, "Idea 2" architecture): Next.js :3200, FastAPI :8200, Postgres (schema per tenant), Redis + arq, RustFS (S3-compatible; replaces MinIO, whose images are no longer published — decision 2026-11-11), Mailpit. No production stack (decision 2026-11-23).

## Design documents (this folder)

| File | Contents |
|---|---|
| `deliverables.md` | This file: scope, phase 1 deliverables, acceptance criteria |
| `file_system.md` | Repository layout and what lives where |
| `arch_overview.pdf` | Architecture diagram and request flow |
| `object_msterlist.md` | Master list of every object (entities, services, modules, pages, jobs) |
| `system_design.md` | Components, multi-tenancy, auth, RBAC, errors, config, security |
| `ui_screens.md` | Screens, navigation, role-based landing pages |
| `data_model.md` | Tables for `public` and tenant schemas, DDL-level detail |
| `api_spec.md` | REST endpoints, headers, error format |
| `backend_processes.md` | Background jobs, provisioning, audit writer, email, exports |
| `app_flows.md` | Flow descriptions for the main features |
| `critical_user_flow.md` | The end-to-end flows that must never break |
| `gant_sched.md` | Phase 1 schedule |
| `dev_tools.md` | Tooling, conventions, commands |
| `docker_compose.yml` | Dev stack (named `docker_compose.ym` in the brief; spelled with the `l` here) |

## Phase 1 scope (build now)

| # | Function | Included |
|---|---|---|
| 1 | Authentication and account management | register (by invite), login, logout, refresh, verify email, forgot/reset password, profile, change password |
| 2 | Organization / tenant management | schema-per-tenant provisioning, org settings, tenant resolved by `X-Tenant` header. One organization per user (2026-11-12), so there is no org switching |
| 3 | RBAC | roles Platform_Admin, Owner, Admin, Manager, Staff, User; permission checks as FastAPI dependencies; role-based landing page |
| 4 | Notifications and communication | email through SMTP (Mailpit in dev) via background jobs with retry; in-app notification list is optional, tables are in the model |
| 5 | Audit logs | JSON-lines flat file in a host log directory |
| 6 | File and document management | upload/download through RustFS presigned URLs, metadata in tenant schema |
| 7 | Search, filtering, data export | Postgres full-text + trigram search, filters, pagination, CSV/XLSX export |
| 8 | Platform administration | developer CLI + DBeaver/SQL. **No admin UI.** |

## Prepared but not built

| Function | Preparation only |
|---|---|
| Billing (Phase 3) | `organizations.plan`, `organizations.limits` JSONB |
| Dashboard/analytics (Phase 2-3) | role landing page shows a placeholder card area; stats endpoint stub |
| Production email relay (Phase 2) | SMTP env vars only |
| Tenant resolution beyond header, in-app audit reader | **not planned** |

## Reusability requirements

1. **Module template.** Adding a business feature = copy `backend/app/modules/_template` and `frontend/src/modules/_template`, register it in one list. No core file edits besides the registry.
2. **Permissions are data.** A module declares its permission keys; provisioning seeds them. Checks use `Depends(require("<key>"))`.
3. **Everything configurable by environment variables.** No tenant names or domains in code.
4. **One resolver per cross-cutting concern**: tenant (`resolve_tenant`), current user, permission check, audit writer, mail sender, storage client.
5. **Generated API client.** Frontend never hand-writes API calls; it regenerates from the OpenAPI schema.

## Acceptance criteria

- A fresh clone starts with `docker compose up` alone, migrated and with demo logins; two clones with different `.env` ports run side by side. `/api/health` is green.
- CLI creates a tenant and an Owner; the Owner logs in and lands on `/home/owner`.
- Each of the six roles logs in and lands on its own landing page (see `ui_screens.md`).
- A user without a permission gets **403** on the API and does not see the menu item.
- A tenant A user cannot read tenant B data, even with a forged `X-Tenant` (membership check).
- A password-reset email appears in Mailpit.
- Uploaded file downloads through a presigned URL; metadata is searchable.
- Search and CSV export work on the sample module.
- Every write action appends one line to `audit.log`.
- Backend tests (pytest) and one Playwright login-and-land test pass in CI.

## Out of scope

Billing logic, dashboards content, admin UI, subdomain tenancy, real email delivery, SSO/SAML, in-app audit reader, mobile apps.

## Open items to confirm

1. Registration model: **invite-only** (assumed; there is no admin UI so Owner/Admin invite users). Open signup would need a signup-creates-tenant flow.
2. Email verification: enabled (read from Mailpit). Can be switched off with `REQUIRE_EMAIL_VERIFICATION=false`.
3. Platform_Admin is a platform-level flag, not a per-tenant role (see `data_model.md`).
