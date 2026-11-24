"""Permission keys of the template module and who gets them by default (B06 D12).

`default_roles` are granted in new tenants, and in existing tenants when
`make cli args=sync-permissions` first adds the key (B06 D1).

COPYING: rename the "items:" prefix to your module's.
"""

from app.core.permissions import ALL_ROLES, OWNER_ADMIN, STAFF_UP, PermissionDef, register

register(
    [
        PermissionDef("items:read", "List and view items", ALL_ROLES),
        PermissionDef("items:write", "Create and edit items", STAFF_UP),
        PermissionDef("items:delete", "Delete items", OWNER_ADMIN),
    ]
)
