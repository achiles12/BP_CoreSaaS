# `_template`: copy me to add a business module

`/items` is a small, complete example: a tenant table, permissions with default
grants, a list with search, sort and filter, create/read/update/delete, soft
delete and audit lines. A new module starts as a copy of this folder.

Adding a module touches **no core file**: you copy this folder, add one line
to `app/modules/registry.py`, and add one tenant migration (design B06 D3–D5).
`tests/test_module_copy.py` proves this by doing it automatically.

## Steps (example: a `projects` module)

1. **Copy the folder**

   ```bash
   cp -r backend/app/modules/_template backend/app/modules/projects
   ```

2. **Rename inside the copy**

   | In | Change | To |
   |---|---|---|
   | all files | `app.modules._template` | `app.modules.projects` |
   | `permissions.py` | `items:read/write/delete` (and their `default_roles` if needed) | `projects:read/write/delete` |
   | `router.py`, `service.py` | `"items:…"` in `require(...)` | `"projects:…"` |
   | `router.py` | `prefix="/items"`, `tags=["items"]` | `"/projects"`, `["projects"]` |
   | `router.py` | `list_items`, `get_item`, `create_item`, `update_item`, `delete_item` | `list_projects`, … (they become OpenAPI operationIds and frontend hook names, and must be unique across the app) |
   | `models.py` | class `TemplateItem`, `__tablename__ = "_template_items"`, index names | `Project`, `"projects"`, `ix_projects_…` |
   | `models.py`, `schemas.py`, `service.py` | the fields | your fields |
   | `service.py` | `AUDIT_ENTITY = "item"`, `"items.create"` etc. | `"project"`, `"projects.create"` … |

   Default grants: `default_roles` in `permissions.py` decides which roles get
   each key in new tenants, and in existing tenants when step 5 first adds the key.
   Use the sets from `app/core/permissions.py` (`ALL_ROLES`, `STAFF_UP`,
   `OWNER_ADMIN_MANAGER`, `OWNER_ADMIN`, `OWNER`).

3. **Write a tenant migration**: copy
   `backend/migrations/tenant/versions/0003_items.py` to the next number
   (e.g. `0004_projects.py`), set `revision` and `down_revision` = the
   current head, and create your table. Keep it identical to `models.py`;
   `tests/test_migrations.py::test_tenant_schema_matches_models` fails on any drift.

4. **Register the module**: add `"projects"` to `MODULES` in
   `backend/app/modules/registry.py`. That one line loads its router,
   permissions and models.

5. **Apply**

   ```bash
   make migrate                         # every tenant gets the new table
   make cli args=sync-permissions       # adds the keys + their default grants
   make gen-client                      # typed frontend hooks (useListProjects, …)
   ```

   `sync-permissions` grants defaults only for keys it adds in that run. If you
   later remove a grant in DBeaver, it stays removed.

6. **Test**: copy `backend/tests/test_items_api.py` and adapt it.

## What the template shows

| Concern | Where |
|---|---|
| Permission check (403) | `router.py`: `Depends(require("items:write"))` |
| Tenant isolation (404 for another tenant's id) | every query runs in `tenant_db` |
| List: paging, `sort=-created_at,title`, `filter[status]=open,done`, `filter[created_at][gte]=2026-11-01` | `service.ITEMS_LIST` + `core/pagination.py` |
| Search box | `q` (title contains, case-insensitive, trigram index) |
| Audit line per change (`items.create/update/delete`, diff of changed fields) | `service.py` |
| Soft delete | `deleted_at`; deleted rows are never returned |
| Validation (422) | `schemas.py`: limits, allowed statuses, unknown fields refused |

Leave `_template` itself registered: it is the reference example (`/items`).
Remove it from the registry only when the product no longer wants it.
