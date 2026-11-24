# Application Flows (v2, as built)

Version 2 of `app_flows.md`, updated 2026-11-20 to match the system as built through B11. The original `app_flows.md` is kept unchanged as the first spec. The same flows are drawn in `process_flows/appFlows.pdf` (source `process_flows/source/appFlows.html`); step numbers here match the diagrams.

Notation: **FE** frontend (Next.js :3200), **BE** backend API (FastAPI :8200), **W** worker (arq), **S3** RustFS (:9000, LAN IP).

Each flow ends with **Changed from v1**: what differs from `app_flows.md` and why.

| ID | Flow | Status |
|---|---|---|
| F1 | Login and role-based landing | built |
| F2 | Session refresh | built |
| F3 | Invite and accept | built |
| F4 | Forgot / reset password | built |
| F5 | Switch organization | **dropped** |
| F6 | Upload a file | built |
| F7 | Download (and delete) a file | built |
| F8 | Search and filter | built |
| F9 | Export | built |
| F10 | Manage roles | built |
| F11 | Platform admin tasks | built |
| F12 | Audit read | built |
| F13 | Add a business module (developer flow) | built |

## F1. Login and role-based landing

1. User opens `/login` (or any app page while signed out, which redirects to `/login?next=<page>`) and enters email + password.
2. FE checks the form (Zod: email format, password present).
3. FE `POST /auth/login`.
4. BE counts the attempt in Redis (5 per minute per IP + email; over that: 429).
5. BE loads the user by email, verifies the Argon2 hash and checks `is_active`.
   - Wrong password, unknown email or inactive account: the same **401 "Invalid email or password"**; audit `auth.login` with result `denied`.
6. BE starts a new refresh-token family and sets `last_login_at`.
7. BE answers 200 with cookies `access_token` (15 min) and `refresh_token` (14 days, path `/api/auth`); audit `auth.login`.
8. FE goes to `/post-login` (keeps `?next=`).
9. FE `GET /me` (no `X-Tenant` needed).
10. BE reads the user's membership (one org), roles and permissions.
11. BE returns user, org, roles, permissions and `landing_path`.
12. FE picks the target: `next=` if allowed, else `landing_path`; no org → `/no-organization`; platform admin → `/platform`.
13. FE shows `/home/<role>`: sidebar and cards filtered by permission. A user on another role's landing page is sent to their own.

Unverified email: login works, but tenant data answers 403 `email_not_verified`; the app shows a banner with **Resend**.

**Changed from v1:** no org picker and no `localStorage.last_org` (v1 steps 4–5). One organization per user (decision 2026-11-12, B04 D1): `/me` returns the org without an `X-Tenant` header. Users without an org land on `/no-organization`. Unverified users are not refused at login (v1 "unverified" branch); they are limited by the 403 above.

## F2. Session refresh

1. FE calls any endpoint; BE answers 401 (access token expired after 15 min).
2. FE starts ONE shared refresh; any other 401 at the same moment waits for it (single-flight).
3. FE `POST /auth/refresh` with the `refresh_token` cookie.
4. BE checks the token, revokes it and issues the next one in the same family.
5. Success: new cookies; FE retries the original call once.
6. Token already revoked (replayed / stolen): BE revokes the **whole family** and audits `auth.refresh_reuse`; 401.
7. Refresh fails: FE clears the session, shows a "session expired" toast and redirects to `/login?next=<current page>`.

`/auth/login`, `/auth/refresh` and `/auth/logout` never trigger a refresh.

**Changed from v1:** adds refresh-token rotation with reuse detection (B03 D10) and the session-expired toast. The single-flight rule is why concurrent 401s must share one refresh: a second use of a rotated token would look like theft.

## F3. Invite and accept

1. Owner/Admin: **Users → Invite**, email + one role.
2. FE `POST /users/invite {email, role_key}`.
3. BE checks `users:invite` and the rank rule (cannot invite above your own role). Already a member or already invited → 409, shown in the dialog.
4. BE stores the invitation (token as a hash, valid 7 days).
5. BE enqueues `send_email(invite)` via Redis; audit `users.invite`.
6. BE answers 201; FE shows a toast and the **Pending invitations (n)** tab updates.
7. W renders the email and sends it over SMTP (Mailpit in dev); retries after 30 s, 2 min, 10 min, then audit `email.failed`.
8. Invitee opens `/accept-invite?token=…`.
9. FE `POST /auth/invitation {token}` → org, role, and whether the account exists.
10. Invitee enters name + password (new account) or the current password (existing account with no org).
11. FE `POST /auth/accept-invite`.
12. BE creates the user (or attaches the existing one), the membership and `user_roles`; marks the invitation accepted and the email verified; audit `auth.invite_accepted`. An account that already belongs to an org → 409.
13. FE redirects to `/login`.

Optional: before acceptance the owner/admin can **Revoke** on the Pending invitations tab (`DELETE /invitations/{id}`, audit `users.invitation_revoked`); the link stops working.

**Changed from v1:** adds Revoke (B10) and the email retry schedule. The audit action for acceptance is `auth.invite_accepted`.

## F4. Forgot / reset password

1. User opens `/forgot-password`, enters the email.
2. FE `POST /auth/forgot-password`.
3. If the email belongs to an account: BE stores a reset token (hash, short life) and enqueues `send_email(reset)`; W sends it.
4. BE always answers **202**, whether or not the account exists (no account discovery). Rate limited like login.
5. User opens `/reset-password?token=` and enters the new password twice.
6. FE checks the rules (12+ characters, a letter and a digit, both fields match).
7. FE `POST /auth/reset-password {token, new_password}`.
8. BE validates the token (single use), sets the new Argon2 hash, revokes **all** refresh tokens of the user; audit `auth.password_reset`.
9. BE answers 204; FE goes to `/login`. Expired or used token → 400 ("request a new link").

**Changed from v1:** none in substance; the rate limit and password rule are spelled out.

## F5. Switch organization: dropped

One organization per user (decision 2026-11-12, B04 D1): there is nothing to switch. Platform admins (no membership) reach organizations through `/platform` and by sending `X-Tenant`, which is always audited (`tenancy.platform_admin_access`).

**Changed from v1:** unchanged (already dropped in v1).

## F6. Upload a file

1. **Files → Upload**: drag and drop or browse; several files, one progress bar each, uploaded one after another.
2. FE checks each file first: empty, larger than `MAX_UPLOAD_MB` (50), or a type not allowed (e.g. `.md`, which has no browser MIME type). A refused file shows its reason and nothing is sent.
3. FE `POST /files/presign-upload {name, mime_type, size_bytes}`.
4. BE checks `files:write`, size (413) and type (415); stores a `files` row with status `pending`.
5. BE returns `file_id`, `upload_url` (valid 15 min) and the signed headers.
6. FE PUTs the bytes **straight to RustFS** with XMLHttpRequest (upload progress), sending the signed `Content-Type`.
7. FE `POST /files/{id}/confirm`.
8. BE HEADs the object (exists, size matches), sets status `active`; audit `files.upload`.
9. FE shows "Done", refreshes the list and toasts.

A failed or cancelled PUT leaves a `pending` row; the daily cleanup J04 (03:30) deletes it after 24 h.

**Changed from v1:** the browser checks size and type before presigning; uploads use XHR for progress; the server answers 413/415 (v1 said 422) for size/type.

## F7. Download (and delete) a file

1. User picks **⋯ → Download** on /files (or a file hit in Search, or a file on a landing card).
2. FE `GET /files/{id}/download-url`.
3. BE checks `files:read` and that the file is active in this tenant (else 404).
4. BE returns a presigned URL valid 60 s.
5. The browser opens it; RustFS sends the file with its original name (`Content-Disposition`).

Delete (`files:delete`: owner, admin, manager): **⋯ → Delete** → confirm → `DELETE /files/{id}` → status `deleted` (soft), audit `files.delete`, row disappears; J04 removes the object later.

**Changed from v1:** no `files.download` audit (the optional `AUDIT_READS` switch was not built). Delete added to the flow.

## F8. Search and filter

Global search:

1. User types in **Search** (or the landing-page search box); after 300 ms the text is written to the URL (`?q=`).
2. Fewer than 2 characters: a hint, no request.
3. FE `GET /search?q=&types=&page=`.
4. BE drops types the user cannot read (`files:read`, `items:read`); an unknown type → 422.
5. BE searches each type: full text (`plainto_tsquery('simple')`) OR typo match (`word_similarity(q, title) > 0.5`); results are UNIONed and ranked by score.
   - **Code-like queries** (at least half of the letters and digits are digits, e.g. `INV-2026-0412`): typo match is off; exact full text or substring only, so neighbouring codes are not returned.
6. BE returns `{type, id, title, snippet, score}` (snippet is plain text).
7. FE groups hits by type and highlights the words. A file hit downloads (F7); an item hit opens `/items/{id}`.

List filters (Files, Users, Items):

8. User sets search, Type, Status, "Mine only", dates, sort or page; each change is written to the URL (shareable, survives reload; quick successive changes keep each other).
9. FE `GET /files?q=…&filter[mime_type]=…&filter[created_at][gte]=…&sort=…&page=…`.
10. BE allows only the fields named in the list's `ListSpec`; anything else → 422 naming what is allowed.
11. BE returns `{items, total, page, page_size}`.

**Changed from v1:** typo match uses `word_similarity > 0.5` instead of `similarity > 0.3` (B07 build ruling); code-like queries match exactly (user decision 2026-11-20); snippets are plain text and highlighted in the browser; Files uses "Mine only" instead of an uploader filter; Users has no role filter (user decision, B10 D2).

## F9. Export

1. On a list, **Export** → CSV or Excel (XLSX) → **Export**. The button shows only with `export:run` (owner, admin, manager) AND the list's read key.
2. FE `POST /exports {resource, format, filters}`; `filters` are the list's current query as strings (all pages).
3. BE re-checks the permissions and parses the filters now (bad filter → 422, no job).
4. BE stores `export_jobs` (`queued`); audit `exports.create`.
5. BE enqueues `build_export`; if the queue is down → 503 and the job is marked failed.
6. BE answers 202.
7. FE polls `GET /exports/{id}` every 2 s until done or failed; closing the dialog stops polling.
8. W marks the job `running`, re-checks the requester's permissions, counts the rows (more than `EXPORT_MAX_ROWS` (100 000) → failed "narrow the filters"; never a cut-short file), streams the rows with a server-side cursor using **the same query as the list**.
9. W writes CSV (UTF-8 with BOM; cells starting `= + - @` get a leading `'`) or XLSX and uploads it to RustFS.
10. W marks the job `done` (row count, object key), creates a notification `export.done` for the requester; audit `exports.finish`. On failure: `failed` + error, notification `export.failed`.
11. FE shows "Ready: N rows" and **Download**; each click fetches a fresh 60 s link.

The dialog also lists the user's last 5 exports. Users only see their own exports. The bell shows the notification (F-bell below). The daily `cleanup_exports` (03:45) deletes files older than `EXPORT_RETENTION_DAYS` (7; 0 = keep) and marks those jobs `expired`; jobs stuck in queued/running for over an hour are marked failed.

**Changed from v1:** adds own-exports-only, the requester notification, retention cleanup and stuck-job handling (B07 decisions); the "small exports may stream directly" option was not built (always a job).

### Notifications bell (part of F9)

The bell in the top bar polls `GET /notifications?unread=true&page_size=1` every 30 s (and on window focus) for the unread count (badge hidden at 0, "99+" above 99). Opening it loads the last 10. Clicking an entry marks it read (`POST /notifications/{id}/read`); an `export.done` entry also downloads the file. **Mark all read** → `POST /notifications/read-all`. Today only exports create notifications; any module can call `notify()`.

## F10. Manage roles

1. Owner/Admin: **Users → ⋯ → Change roles** (checkboxes, roles from `GET /roles`).
2. FE `PUT /users/{id}/roles {role_keys}`.
3. BE checks `roles:assign`, the rank rule (cannot assign a role above your own) and the last-owner rule. A refusal (403/409) is shown in the dialog, which stays open.
4. BE replaces `user_roles`; audit `roles.assign`; drops that user's cached permission set in Redis.
5. FE toasts; the role badges update.

Deactivate / Activate (`users:deactivate`) is in the same menu, with a confirmation; deactivation signs the member out (sessions revoked); audit `users.deactivate` / `users.activate`. The last owner cannot be deactivated.

Changing what a role can do (no UI): the developer edits the module's `permissions.py` (`default_roles`) and runs `make cli args=sync-permissions` (grants defaults only for NEW keys, so a removal made by an operator sticks), or changes `role_permissions` with SQL in DBeaver. Cached permission sets expire within 60 s.

**Changed from v1:** module-declared default grants (`default_roles`, B06 D1) replace the central seed matrix; the cache is dropped immediately on a role change.

## F11. Platform admin tasks

Create a tenant: `make create-tenant slug=acme name="Acme" owner=owner@acme.test`:

1. Validate the slug (pattern, reserved words).
2. `organizations` row with status `provisioning`.
3. `CREATE SCHEMA tenant_acme`.
4. Tenant migrations (0001 … 0004).
5. Seed roles and the default grants of every module.
6. Owner: existing user, new user, or an invitation email.
7. Status `active`; audit `org.created`.

Every step is idempotent: re-running resumes after a failure; a failed run drops only a schema it created itself.

Keep tenants running: `make migrate` (public, then every tenant), `make cli args=sync-permissions`, `suspend-org` / `activate-org` (audit `org.suspended` / `org.activated`), `cleanup-files`, `cleanup-exports`, `list-orgs`.

Platform admin in the UI: logs in (no org) → `/platform` (organizations table + stats stub). Entering a tenant by sending `X-Tenant` is always audited. No admin screens: everything else via the CLI or DBeaver.

**Changed from v1:** adds `sync-permissions`, `activate-org` and the cleanup commands; provisioning is resumable.

## F12. Audit read

Written by the app: every write action commits, then appends exactly one JSON line to `logs/audit/audit.log` (e.g. `items.update`, `files.upload`, `users.invite`). Sensitive actions fail closed: if the line cannot be written, the request fails. Secrets and tokens are redacted.

Read by an operator: PuTTY/SFTP to the host, `cd logs/audit`, then `grep '"action": "items.update"' audit.log` or `jq 'select(.org=="b04live")' audit.log`. No in-app view.

**Changed from v1:** none. The item "History" panel drawn in the wireframe was dropped (user decision, B10 D1): audit stays a file.

## F13. Add a business module (developer flow)

Backend:
1. Copy `backend/app/modules/_template` → `widgets`; rename the table, permission keys and `/widgets`.
2. `models.py` + the next tenant migration.
3. `permissions.py` with `default_roles`.
4. Optional: `search.py` (searchable) and `exports.py` (exportable).
5. Add `"widgets"` to `registry.MODULES`.
6. `make migrate` and `make cli args=sync-permissions`.

Frontend:
7. `make gen-client` (generates `useListWidgets`, `createWidget`, …).
8. Copy `frontend/src/modules/_template/config.ts`: columns, filters, fields, schema, API hooks.
9. Route files under `src/app/(app)/widgets/` (4 files, about 10 lines each).
10. One line in `src/config/navigation.ts`; optional search type in `search-types.ts`.

Verify: copy the module tests (`make test`, `make fe-test`, `make fe-lint`), `make gen-client-check`, then sign in per role and check that the buttons follow the permissions.

Only the registry line and the navigation line touch shared files. Guides: `backend/app/modules/_template/README.md`, `frontend/src/modules/_template/README.md`.

**Changed from v1:** the frontend half is config-driven (B11): one `config.ts` drives the generic list, detail and form; search and export are opt-in per module; default grants live in the module's `permissions.py`.
