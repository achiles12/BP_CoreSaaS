"""Permission keys of the files module (object_msterlist.md §C).

Declared in B02 so every tenant is seeded with the full matrix from day one
(design B02 D8); the module's endpoints arrive in a later batch.
"""

from app.core.permissions import ALL_ROLES, OWNER_ADMIN_MANAGER, STAFF_UP, PermissionDef, register

register(
    [
        PermissionDef("files:read", "List and download files", ALL_ROLES),
        PermissionDef("files:write", "Upload files", STAFF_UP),
        PermissionDef("files:delete", "Delete files", OWNER_ADMIN_MANAGER),
    ]
)
