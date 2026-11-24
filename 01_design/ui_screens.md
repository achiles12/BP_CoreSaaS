# UI Screens

Next.js (App Router), shadcn/ui, Tailwind, React Hook Form + Zod, TanStack Query. Responsive; sidebar collapses to a drawer on mobile. Light and dark themes (shadcn tokens).

## 1. Layout

**Public layout:** centered card on plain background, product name on top.

**App shell (authenticated):**
```
┌──────────────────────────────────────────────────────────┐
│ Logo   Org name                    🔔   [User menu ▾]     │ top bar
├───────────┬──────────────────────────────────────────────┤
│ Sidebar   │  Page title                    [primary action]│
│ (filtered │  ───────────────────────────────────────────  │
│  by       │  Content                                       │
│  permis-  │                                                │
│  sions)   │                                                │
└───────────┴──────────────────────────────────────────────┘
```
Navigation entries come from `config/navigation.ts`: `{label, href, icon, permission}`. An entry shows only if the user has the permission.

## 2. Screens

### S01 Login `/login`
Email, password, "Forgot password?". Errors are generic ("Invalid email or password"). On success go to `/post-login`.
States: loading, error, rate limited (429 message).

### S02 Forgot / reset password `/forgot-password`, `/reset-password?token=`
Email form (always shows "If the account exists, an email was sent"); reset form with new password and confirmation, strength hint.

### S03 Verify email `/verify-email?token=`
Shows success/failure; link to login.

### S04 Accept invite `/accept-invite?token=`
Shows org name and role; fields: full name, password, confirm.

### S05 Post-login `/post-login`
No UI except a spinner. Fetches `/me` and redirects to `landing_path`. `landing_path = null` (no organization) shows a "You are not a member of an organization" page.

### S06 Org picker: dropped
**One organization per user** (decision 2026-11-12, B04 D1). The top bar shows the org name instead of a switcher.

### S07 Landing pages `/home/<role>`

Same shell, a role-specific set of cards (placeholders in the scaffold, filled by business modules):

| Role | Path | Cards in the scaffold |
|---|---|---|
| Platform_Admin | `/platform` | Organizations table, platform stats placeholder |
| Owner | `/home/owner` | Welcome, members count, pending invites, recent files, recent activity placeholder, link to org settings |
| Admin | `/home/admin` | Welcome, pending invites, recent files, manage users shortcut |
| Manager | `/home/manager` | Welcome, team members, recent files, export shortcut |
| Staff | `/home/staff` | Welcome, my recent files, search box |
| User | `/home/user` | Welcome, search box, files |

Each card checks permissions before rendering. A user visiting a landing path of another role gets redirected to their own.

### S08 Files `/files`
Table: name, size, type, uploaded by, date. Search box, filters (type, uploader, date), pagination, "Upload" button (drag-and-drop dialog with progress), row actions: download, delete (confirm dialog). Empty state with upload prompt.

### S09 Search `/search`
Large search input, result groups by type, highlight snippet, filter by type.

### S10 Users `/users` (`users:read`)
Table: name, email, roles, status. Actions: Invite (dialog: email, role), change roles, deactivate/activate. Tab for pending invitations with revoke.

### S11 Profile `/settings/profile`
Name, email (read-only), change password form, sessions note.

### S12 Organization settings `/settings/organization` (`org:read`, edit needs `org:update`)
Name, display name. Read-only slug.

### S13 Exports (drawer from tables)
"Export" button on lists opens a dialog: format CSV/XLSX → progress → download link. Recent exports list.

### S14 Notifications (bell dropdown)
Unread count, last 10, "mark all read". Optional in Phase 1.

### S15 Template items `/items`
Example business list/detail/create form demonstrating list + search + filter + export + audit.

### S16 Errors
`/403` "You do not have access", `/404`, global error boundary, offline/session-expired toast that redirects to `/login`.

## 3. Route guards

| Rule | Behavior |
|---|---|
| Not authenticated | redirect to `/login?next=<path>` |
| Authenticated, missing permission | `/403` |
| Authenticated on `/login` | redirect to `/post-login` |
| Unknown org slug in storage | clear it and show the picker |

## 4. Forms (RHF + Zod)

Schemas live next to forms; email format, password min 12 chars with letters and numbers, file name length. Server errors (`422 error.fields`) are mapped onto fields.

## 5. Dev-mode banner

When `NEXT_PUBLIC_APP_ENV=dev`: a small banner "Dev: emails go to Mailpit (localhost:8025)".

## 6. Accessibility and quality

Keyboard navigable dialogs, labelled inputs, visible focus, color contrast via shadcn tokens; loading skeletons for tables; toasts for mutations.
