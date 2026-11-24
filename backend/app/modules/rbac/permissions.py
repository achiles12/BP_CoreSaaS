"""Permission keys of the rbac module (object_msterlist.md §C).

Declared in B02 so every tenant is seeded with the full matrix from day one
(design B02 D8); the module's endpoints arrive in a later batch.
"""

from app.core.permissions import OWNER_ADMIN, OWNER_ADMIN_MANAGER, PermissionDef, register

register(
    [
        PermissionDef("roles:read", "View roles and permissions", OWNER_ADMIN_MANAGER),
        PermissionDef("roles:assign", "Assign roles to members", OWNER_ADMIN),
    ]
)
