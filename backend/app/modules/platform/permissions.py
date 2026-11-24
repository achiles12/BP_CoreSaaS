"""Permission keys of the platform module (object_msterlist.md §C).

Declared in B02 so every tenant is seeded with the full matrix from day one
(design B02 D8); the module's endpoints arrive in a later batch.
"""

from app.core.permissions import PermissionDef, register

register(
    [
        PermissionDef(
            "platform:manage",
            "Platform administration (implied by is_platform_admin; never a tenant role)",
        ),
    ]
)
