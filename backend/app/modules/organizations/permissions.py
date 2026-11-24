"""Permission keys of the organizations module (object_msterlist.md §C).

Declared in B02 so every tenant is seeded with the full matrix from day one
(design B02 D8); the module's endpoints arrive in a later batch.
"""

from app.core.permissions import ALL_ROLES, OWNER, PermissionDef, register

register(
    [
        PermissionDef("org:read", "View organization settings", ALL_ROLES),
        PermissionDef("org:update", "Edit organization settings", OWNER),
    ]
)
