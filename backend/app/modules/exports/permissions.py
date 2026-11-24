"""Permission keys of the exports module (object_msterlist.md §C).

Declared in B02 so every tenant is seeded with the full matrix from day one
(design B02 D8); the module's endpoints arrive in a later batch.
"""

from app.core.permissions import OWNER_ADMIN_MANAGER, PermissionDef, register

register(
    [
        PermissionDef("export:run", "Run data exports", OWNER_ADMIN_MANAGER),
    ]
)
