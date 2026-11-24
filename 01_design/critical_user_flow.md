# Critical User Flows

These must work and have automated tests before any release. Each is a "stop the line" flow.

| # | Flow | Why critical |
|---|---|---|
| C1 | Login → role landing page | Entry to the whole product; proves auth, tenancy, RBAC together |
| C2 | Tenant isolation | A leak between tenants is the worst failure |
| C3 | Permission enforcement | Hidden menu is not security; API must deny |
| C4 | Invite → accept → login | Only way users are created |
| C5 | Password reset | Account recovery, security sensitive |
| C6 | File upload → download | Core data function, presigned URLs |
| C7 | Audit line for every mutation | Accountability |
| C8 | Tenant provisioning (CLI) | Creates a usable tenant from nothing |

## C1. Login and landing

Given a tenant with six users (one per role), when each logs in:
- lands on its path: platform_admin `/platform`, owner `/home/owner`, admin `/home/admin`, manager `/home/manager`, staff `/home/staff`, user `/home/user`
- sidebar shows only permitted entries
- visiting another role's landing page redirects back
- logout clears cookies; back button does not show data

Tests: Playwright (one per role), pytest for `/me` payload.

## C2. Tenant isolation

Setup: tenants `acme` and `beta`, user A in acme only.
- A calls tenant-scoped endpoints with `X-Tenant: beta` → **403/404**, same body as unknown tenant.
- A calls with no header on a tenant route → 400.
- A lists files in acme → only acme rows. Data created in beta never appears.
- Forged `X-Tenant: acme; DROP SCHEMA` or `x" or "1"="1` → 404, nothing executed (slug is looked up, never interpolated).
- Concurrent requests for acme and beta on pooled connections never see each other's rows (load test with 50 parallel requests, asserts per-response tenant marker).
- Presigned URL generated for acme file is rejected by backend for a beta user.

## C3. Permission enforcement

For every endpoint in `api_spec.md` and each role: expected status per the matrix (generated parametrized test from the permission matrix). Specifically:
- `user` role: `POST /files/presign-upload` → 403.
- `admin` cannot assign `owner`; last owner cannot be removed.
- A deactivated membership returns 403 immediately (permission cache invalidated on status change).

## C4. Invite to login

1. Admin invites `new@x.test` as `staff`.
2. Mail appears in Mailpit with a valid link.
3. Accept with password; token cannot be reused; expired token rejected.
4. Login lands on `/home/staff`.
5. Audit lines: `users.invite`, `auth.invite_accepted`, `auth.login`.

## C5. Password reset

1. Request for existing and non-existing email: identical response.
2. Mail in Mailpit (only for existing).
3. Reset sets new password; old password fails; old sessions are revoked; token cannot be reused.
4. Rate limit returns 429 after repeated attempts.

## C6. File upload and download

1. Staff uploads a 5 MB PDF; row `pending` → `active`.
2. Appears in list and in search by name.
3. Download URL works for 60 s and then returns an expired response.
4. `user` role can download but not upload or delete.
5. Upload over the limit or disallowed type is rejected before any object is stored.
6. Delete removes it from lists; worker removes the object.

## C7. Audit

For each mutation endpoint, a test asserts one new JSON line in the audit file with correct `org`, `actor`, `action`, and no sensitive data. Test that a non-writable audit directory stops the app on startup.

## C8. Provisioning

`create-tenant` on an empty database creates schema, roles, permissions, grants; second run is a no-op; failed run leaves no half tenant; `migrate-all` brings an old tenant to current version.

## Non-functional gates

- API p95 < 300 ms for list endpoints with 10 000 rows (local).
- No high/critical findings in `pip-audit` / `pnpm audit`.
- `docker compose up` from a clean checkout works in under 5 minutes.
