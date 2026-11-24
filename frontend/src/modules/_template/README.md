# Frontend module template (`_template` → `/items`)

The frontend half of a business module (B11, design `05_stage10/20261120_b10_design.md` D13).
The backend half is `backend/app/modules/_template/` (its README covers the API, permissions and migration).

A module here is **one config file**. The generic pages read it:

| File                           | What it is                                                                                       |
| ------------------------------ | ------------------------------------------------------------------------------------------------ |
| `types.ts`                     | `ModuleConfig`: the contract (columns, filters, detail rows, form fields, Zod schema, API hooks) |
| `config.ts`                    | `itemsConfig`: the example; **this is the file you rewrite**                                     |
| `components/module-list.tsx`   | search + filters in the URL, table, paging, New, Export                                          |
| `components/module-detail.tsx` | fields, Edit, Delete (confirm)                                                                   |
| `components/module-form.tsx`   | create/edit with RHF + Zod; server 422s mapped onto fields; edit sends only changed fields       |

Pages are thin: `src/app/(app)/items/{page, new/page, [id]/page, [id]/edit/page}.tsx`.

## Copy it (example: `widgets`)

1. **Backend first.** Copy the backend module, register it and migrate, then sync permissions (backend README). Check `GET /widgets` works.
2. **Regenerate the client:** `make gen-client`. You get `useListWidgets`, `useGetWidget`, `createWidget`, `updateWidget`, `deleteWidget` in `src/api/generated/endpoints/widgets/`.
3. **Config:** copy `config.ts` to `src/modules/widgets/config.ts` (keep importing `types.ts` and the generic components from `_template`). Rename `itemsConfig` → `widgetsConfig` and set:
   - `resource: "widgets"` (the export resource, if the backend added `exports.py`), labels, `basePath: "/widgets"`
   - `permissions` → `widgets:read|write|delete`
   - `columns`, `filters` (params must be filters the backend `ListSpec` allows), `detail`, `fields`, `schema`, `emptyValues`, `toValues`, `toCreate`, `toUpdate` (only changed fields)
   - `api` → the generated widget hooks. Keep `useGet` idle for an empty id.
4. **Routes:** copy `src/app/(app)/items/` to `src/app/(app)/widgets/` and change the config import (4 files, ~10 lines each).
5. **Navigation:** add one line to `src/config/navigation.ts`: `{ label: "Widgets", href: "/widgets", icon: …, permission: "widgets:read" }`.
6. **Search** (optional): if the backend added `search.py`, add the type to `src/components/search/search-types.ts` (`SEARCH_TYPES` and `HIT_HREF`).
7. **Test:** copy `module.test.tsx`, point it at the new config and mock the generated widget endpoints; `make fe-test`, `make fe-lint`.

No other core file changes.

## Rules the template keeps

- Filters, search and page live in the URL (shareable, survive reload).
- Every button is gated by the config's permissions; the API enforces them anyway.
- No in-app history/audit panel (audit is read with the shell or DBeaver; design D1).
