"""Permission keys of the search module (object_msterlist.md §C).

Declared in B02 so every tenant is seeded with the full matrix from day one
(design B02 D8); the module's endpoints arrive in a later batch.
"""

from app.core.permissions import ALL_ROLES, PermissionDef, register

register(
    [
        PermissionDef("search:use", "Use global search", ALL_ROLES),
    ]
)
