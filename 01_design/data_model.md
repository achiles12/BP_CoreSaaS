# Data Model

Postgres 16. Extensions (in `deploy/postgres/init.sql`): `pgcrypto`, `pg_trgm`, `citext`.
IDs are UUID v4 (`gen_random_uuid()`). Timestamps are `timestamptz` default `now()`. Soft delete uses `deleted_at` where noted.

## 1. Schema `public` (shared)

### users (E01)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| email | citext unique not null | |
| password_hash | text not null | Argon2id |
| full_name | text | |
| is_active | bool default true | |
| is_verified | bool default false | |
| is_platform_admin | bool default false | Platform_Admin flag |
| last_login_at | timestamptz | |
| created_at, updated_at | timestamptz | |

### organizations (E02)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text not null | |
| slug | citext unique not null | `^[a-z][a-z0-9_]{2,30}$`, value of `X-Tenant` |
| schema_name | text unique not null | `tenant_<slug>`, generated only by provisioning |
| status | text | `active`, `suspended`, `provisioning`, `failed` (aborted provisioning; B02 D7) |
| plan | text default 'free' | billing hook (Phase 3) |
| limits | jsonb default '{}' | billing hook |
| created_at, updated_at | timestamptz | |

### org_memberships (E03)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK users | |
| org_id | uuid FK organizations | |
| status | text | `active`, `inactive` |
| created_at | timestamptz | |
| unique (user_id, org_id) | | |

### refresh_tokens (E04)
`id`, `user_id` FK, `family_id uuid`, `token_hash text unique`, `expires_at`, `revoked_at`, `replaced_by uuid`, `created_at`, `ip inet`, `user_agent text`. Index on `family_id`, `user_id`.

### invitations (E05)
`id`, `org_id` FK, `email citext`, `role_key text`, `token_hash text unique`, `invited_by uuid FK users`, `expires_at`, `accepted_at`, `created_at`. Partial unique `(org_id, email)` where `accepted_at is null`.

### one-time tokens (E06)
`email_verification_tokens` and `password_reset_tokens`: `id`, `user_id` FK, `token_hash text unique`, `expires_at`, `used_at`, `created_at`.

## 2. Tenant schema `tenant_<slug>`

### roles (T01)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| key | text unique | `owner`, `admin`, `manager`, `staff`, `user` |
| name | text | display name |
| priority | int | lower wins for landing page (owner=10 ... user=50) |
| landing_path | text | e.g. `/home/owner` |
| is_system | bool | system roles are not deleted |

### permissions (T02)
`id`, `key text unique` (e.g. `files:write`), `module text`, `description text`.

### role_permissions (T03)
`role_id` FK, `permission_id` FK, primary key `(role_id, permission_id)`.

### user_roles (T04)
`user_id uuid` (references `public.users.id`; cross-schema FK created in the tenant migration), `role_id` FK, `assigned_by uuid`, `assigned_at`. PK `(user_id, role_id)`.

### files (T05)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text | original file name |
| mime_type | text | |
| size_bytes | bigint | |
| object_key | text unique | RustFS key |
| status | text | `pending`, `active`, `deleted` |
| uploaded_by | uuid | user id |
| search_vector | tsvector generated | `to_tsvector('simple', name)` |
| created_at, updated_at, deleted_at | timestamptz | |

Indexes: GIN on `search_vector`; GIN trigram on `name`; btree on `(status, created_at desc)`.

### notifications (T06)
`id`, `user_id`, `type`, `title`, `body`, `data jsonb`, `read_at`, `created_at`. Index `(user_id, read_at, created_at desc)`.

### settings (T07)
`key text PK`, `value jsonb`, `updated_at`, `updated_by`.

### export_jobs (T08)
`id`, `requested_by`, `resource text`, `format text` (`csv`/`xlsx`), `filters jsonb`, `status` (`queued`, `running`, `done`, `failed`), `object_key`, `row_count`, `error`, `created_at`, `finished_at`.

### _template_items (T09)
Sample business entity so search, filter, export and audit are demonstrated: `id`, `title text`, `description text`, `status text`, `owner_id uuid`, `search_vector tsvector`, `created_at`, `updated_at`, `deleted_at`. Removed or renamed by the real product.

## 3. Relationships

```
users 1──0..1 org_memberships *──1 organizations   (one org per user: unique user_id, B04 migration 0002)
users 1──* user_roles(tenant) *──1 roles(tenant) 1──* role_permissions *──1 permissions
users 1──* files.uploaded_by (logical)
organizations 1──1 schema tenant_<slug>
```

Cross-schema references (`user_id` columns in tenant tables) are enforced as FKs to `public.users(id)` with `ON DELETE RESTRICT`. Users are deactivated, never hard-deleted.

## 4. Migrations

| Track | Location | Applied |
|---|---|---|
| public | `migrations/public` | once, at deploy |
| tenant | `migrations/tenant` | for every row in `organizations`, via `migrate-all`; also on provisioning |

Tenant migrations run with `search_path` set to the tenant schema and a version table inside the tenant schema (`alembic_version_tenant`). `migrate-all` prints one line per tenant and exits non-zero if any failed; it is safe to re-run.

## 5. Seed data (at provisioning)

- Roles with priorities and landing paths from `object_msterlist.md`.
- Permissions from every module's `permissions.py`.
- Default role-permission grants from the matrix in `system_design.md`.
- Default `settings` rows (e.g. `app.display_name`).

## 6. Maintenance with DBeaver / SQL

Because there is no admin UI, roles and permissions are edited directly. Rules:

- Change defaults in seed files/migrations first so new tenants get them.
- For one tenant, use SQL inside a transaction and keep the statement in `ops/sql/` for the record.
- Never edit `schema_name` or `slug` of an existing organization.
