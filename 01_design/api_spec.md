# API Specification

Base URL: `/api` (Next.js rewrites to FastAPI :8200, where paths have no `/api` prefix: backend serves `/auth/login`, browser calls `/api/auth/login`). Format: JSON. OpenAPI at `/docs` and `/openapi.json` (dev only in prod config).

## Conventions

| Item | Rule |
|---|---|
| Auth | httpOnly cookies `access_token`, `refresh_token`. No bearer tokens in the browser |
| Tenant | Header `X-Tenant: <org slug>` on every tenant-scoped call |
| Request id | `X-Request-ID` optional in, always returned |
| Pagination | `?page=1&page_size=25` (max 100) → `{items, total, page, page_size}` |
| Sorting | `?sort=-created_at,name` |
| Filtering | `?filter[status]=active` |
| Search | `?q=text` |
| Dates | ISO 8601 UTC |
| IDs | UUID |

Error body (all errors):
```json
{ "error": { "code": "permission_denied", "message": "Missing permission files:write", "request_id": "..." } }
```

| HTTP | code | Meaning |
|---|---|---|
| 400 | `bad_request` | Malformed request |
| 401 | `unauthenticated` | No/expired session |
| 403 | `permission_denied` | Missing permission, or not a member of the tenant |
| 404 | `not_found` | Unknown resource or tenant |
| 405 | `method_not_allowed` | HTTP method not supported by the route |
| 409 | `conflict` | Duplicate, state conflict |
| 422 | `validation_error` | Pydantic details in `error.fields` |
| 429 | `rate_limited` | Too many requests |
| 500 | `internal_error` | Unexpected |

Legend for the tables: **T** = needs `X-Tenant`; **Perm** = required permission; "auth" = any logged-in user.

## 1. Health (no auth)

| Method | Path | Notes |
|---|---|---|
| GET | `/health/live` | 200 if process is up |
| GET | `/health/ready` | checks Postgres, Redis, RustFS |

## 2. Auth

| Method | Path | T | Perm | Description |
|---|---|---|---|---|
| POST | `/auth/login` | | none | `{email,password}` → sets cookies, returns `{user, memberships}`. Generic 401 on failure |
| POST | `/auth/logout` | | auth | Revokes refresh token family, clears cookies |
| POST | `/auth/refresh` | | refresh cookie | Rotates tokens |
| POST | `/auth/invitation` | | none | `{token}` → `{email, org_name, role_key, existing_account}` for the accept page (B04) |
| POST | `/auth/accept-invite` | | none | `{token,password,full_name}` creates the user + membership + role. An existing account with no org sends its **current** password. Returns `{status, email}`; does not log in |
| POST | `/auth/verify-email` | | none | `{token}` |
| POST | `/auth/resend-verification` | | auth | |
| POST | `/auth/forgot-password` | | none | `{email}`. Always 202 |
| POST | `/auth/reset-password` | | none | `{token,new_password}` |
| POST | `/auth/change-password` | | auth | `{current_password,new_password}` |

## 3. Me and organizations

| Method | Path | T | Perm | Description |
|---|---|---|---|---|
| GET | `/me` | optional | auth | User, org, `roles`, `permissions`, `landing_path` (uses the user's one org; `X-Tenant` selects another org for Platform_Admin) |
| PATCH | `/me` | | auth | Update `full_name` |
| GET | `/orgs` | | auth | The user's org (one at most; Platform_Admin: all) |
| GET | `/org` | T | `org:read` | Current org info |
| PATCH | `/org` | T | `org:update` | Update name, settings |

`/me` example (with tenant):
```json
{ "user": {"id":"…","email":"a@b.c","full_name":"A"},
  "org": {"slug":"acme","name":"Acme"},
  "roles": ["manager"],
  "permissions": ["users:read","files:read","files:write","search:use"],
  "landing_path": "/home/manager",
  "is_platform_admin": false }
```

## 4. Users (tenant)

| Method | Path | T | Perm | Description |
|---|---|---|---|---|
| GET | `/users` | T | `users:read` | Members of the org, with roles. Supports `q`, filters, pagination |
| GET | `/users/{id}` | T | `users:read` | |
| POST | `/users/invite` | T | `users:invite` | `{email, role_key}` → sends invite email |
| PATCH | `/users/{id}` | T | `users:update` | Update name/status |
| POST | `/users/{id}/deactivate` | T | `users:deactivate` | Sets membership inactive |
| POST | `/users/{id}/activate` | T | `users:deactivate` | |
| GET | `/invitations` | T | `users:invite` | Pending invites |
| DELETE | `/invitations/{id}` | T | `users:invite` | |

## 5. RBAC (read plus assignment; grants are edited in SQL)

| Method | Path | T | Perm | Description |
|---|---|---|---|---|
| GET | `/roles` | T | `roles:read` | Roles with permission keys |
| GET | `/permissions` | T | `roles:read` | All permission keys |
| PUT | `/users/{id}/roles` | T | `roles:assign` | `{role_keys:[…]}`. Admin cannot grant owner; Owner cannot remove the last owner |

## 6. Files

| Method | Path | T | Perm | Description |
|---|---|---|---|---|
| POST | `/files/presign-upload` | T | `files:write` | `{name, mime_type, size_bytes}` → `{file_id, upload_url, headers}` |
| POST | `/files/{id}/confirm` | T | `files:write` | Verifies object, marks active |
| GET | `/files` | T | `files:read` | List with `q`, filters, pagination |
| GET | `/files/{id}` | T | `files:read` | Metadata |
| GET | `/files/{id}/download-url` | T | `files:read` | `{url, expires_in:60}` |
| DELETE | `/files/{id}` | T | `files:delete` | Soft delete; worker removes the object later |

Limits: max size `MAX_UPLOAD_MB` (default 50); allowed mime list in config.

## 7. Search

| Method | Path | T | Perm | Description |
|---|---|---|---|---|
| GET | `/search` | T | `search:use` | `q`, `types=files,items`, pagination. Returns `[{type,id,title,snippet,score}]`; only types the user may read |

## 8. Exports

| Method | Path | T | Perm | Description |
|---|---|---|---|---|
| POST | `/exports` | T | `export:run` | `{resource:"files"\|"items"\|"users", format:"csv"\|"xlsx", filters:{}}` → 202 `{id}` |
| GET | `/exports/{id}` | T | `export:run` | Status; when done includes `download_url` |
| GET | `/exports` | T | `export:run` | Recent exports |

## 9. Notifications

| Method | Path | T | Perm | Description |
|---|---|---|---|---|
| GET | `/notifications` | T | `notifications:read` | List; `?unread=true` |
| POST | `/notifications/{id}/read` | T | `notifications:read` | |
| POST | `/notifications/read-all` | T | `notifications:read` | |

Email sending has no public endpoint; it is triggered by events (invite, verify, reset).

## 10. Platform (Platform_Admin only, no tenant header)

Kept deliberately small; heavy lifting is CLI/SQL.

| Method | Path | Perm | Description |
|---|---|---|---|
| GET | `/platform/orgs` | `platform:manage` | All orgs with status |
| GET | `/platform/stats` | `platform:manage` | Counts (placeholder for dashboards) |

## 11. Template module (example)

| Method | Path | T | Perm |
|---|---|---|---|
| GET | `/items` | T | `items:read` |
| POST | `/items` | T | `items:write` |
| GET | `/items/{id}` | T | `items:read` |
| PATCH | `/items/{id}` | T | `items:write` |
| DELETE | `/items/{id}` | T | `items:delete` |

Every mutating call writes an audit line.

## 12. Frontend client

`orval` reads `/openapi.json` and generates typed TanStack Query hooks in `frontend/src/api/generated`. A custom fetch mutator adds `X-Tenant` from app state, `credentials: "include"`, and performs one silent `/auth/refresh` on 401 before failing.
