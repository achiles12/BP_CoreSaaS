# Application Flows

Notation: **FE** frontend, **BE** backend, **W** worker.

## F1. Login and role-based landing

1. User opens `/login`, submits email + password.
2. FE `POST /auth/login`. BE rate-limit check → verify Argon2 hash → check `is_active` (and `is_verified` if required) → issue cookies → audit `auth.login` → return user + memberships.
3. FE navigates to `/post-login`.
4. FE `GET /me` (no tenant) → memberships. If one membership: select it. If several: use `localStorage.last_org` if valid, else show picker. Platform_Admin with no memberships goes to `/platform`.
5. FE stores org slug; subsequent calls send `X-Tenant`.
6. FE `GET /me` with tenant → roles, permissions, `landing_path`.
7. FE redirects to `landing_path`. Guard on that page confirms the role.

Failure branches: wrong credentials (generic 401), unverified (message with "resend"), inactive (generic 401), no memberships (message "No organization access, contact your administrator").

## F2. Session refresh

FE gets 401 on any call → one `POST /auth/refresh` → success: retry original call; failure: clear state, redirect `/login?next=`. Concurrent 401s share one refresh promise.

## F3. Invite and accept

1. Owner/Admin: Users → Invite (email, role). `POST /users/invite`.
2. BE: check permission (and that Admin cannot invite Owner), create invitation (hash token), enqueue `send_email(invite_user)`, audit `users.invite`.
3. Invitee opens the link `/accept-invite?token=…` in the Mailpit message.
4. FE `POST /auth/invitation` `{token}` shows org/role and whether the account exists; then `POST /auth/accept-invite`. BE validates token, creates user (or attaches an existing account **with no org**, which needs its current password; an account already in an org gets 409), creates membership + `user_roles`, marks invitation accepted, marks email verified, audit.
5. Redirect to `/login`.

## F4. Forgot / reset password

1. `/forgot-password` → `POST /auth/forgot-password` (always 202).
2. If the user exists: token created, email queued.
3. Link → `/reset-password?token=` → `POST /auth/reset-password`.
4. BE validates token, sets new hash, revokes all refresh tokens of the user, audit `auth.password_reset`.

## F5. Switch organization: dropped

**One organization per user** (decision 2026-11-12, B04 D1): a user has one org, so there is nothing to switch. `/me` returns that org without an `X-Tenant` header. Platform admins (no membership) reach other orgs via `/platform` and by sending `X-Tenant`.

## F6. Upload a file

1. Files → Upload → pick file(s).
2. FE `POST /files/presign-upload` per file (validates type/size).
3. FE `PUT` to the presigned URL with progress.
4. FE `POST /files/{id}/confirm`; list refreshes.
5. Errors: size/type rejected (422), upload failed (row stays pending, cleaned by J04).

## F7. Download a file

FE `GET /files/{id}/download-url` → opens the URL (60 s). Audit `files.download` optional by setting `AUDIT_READS=true`.

## F8. Search and filter

Typing in the search box (debounced 300 ms) calls `GET /search?q=` (global) or the list endpoint with `q` and `filter[...]` (page-local). Pagination and sort state live in the URL query string so views are shareable and restorable.

## F9. Export

1. On a list, Export → choose format; `POST /exports` with the current filters.
2. BE inserts `export_jobs(queued)`, enqueues J02, returns 202.
3. FE polls `GET /exports/{id}` every 2 s (stops at done/failed).
4. On done, FE offers the presigned download URL.

## F10. Manage roles (no UI for grants)

- Assign/remove user roles: Users screen → `PUT /users/{id}/roles` (needs `roles:assign`). Rules: cannot assign a role above your own; cannot remove the last owner.
- Change what a role can do: developer edits seeds/migration and runs `sync`, or runs SQL in DBeaver (see `data_model.md` §6). Permission cache expires in 60 s.

## F11. Platform admin tasks

Developer uses CLI: create tenant, create Platform_Admin, suspend org, migrate all. Platform_Admin in the UI sees only the org list and stats stub.

## F12. Audit read

Operator connects with PuTTY/SFTP to the host and reads `logs/audit/audit.log` (`grep`, `jq`). No in-app view.

## F13. Add a business module (developer flow)

Copy template, define model + migration, service rules, router, permissions, navigation entry; run `migrate-all`, `sync-permissions`, regenerate client; add the permission to role grants.
