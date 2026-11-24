"""Permission keys of the users module (object_msterlist.md §C).

Declared in B02 so every tenant is seeded with the full matrix from day one
(design B02 D8); the module's endpoints arrive in a later batch.
"""

from app.core.permissions import OWNER_ADMIN, OWNER_ADMIN_MANAGER, PermissionDef, register

register(
    [
        PermissionDef("users:read", "List and view organization members", OWNER_ADMIN_MANAGER),
        PermissionDef("users:invite", "Invite users to the organization", OWNER_ADMIN),
        PermissionDef("users:update", "Edit member details", OWNER_ADMIN),
        PermissionDef("users:deactivate", "Deactivate and reactivate members", OWNER_ADMIN),
    ]
)
