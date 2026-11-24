"""THE module registry (design B06 D3): the one list a new module is added to.

Each entry is a package under app/modules (or, for tests, a full dotted path).
A module may provide any of:
    router.py       `router: APIRouter`   included by main.create_app()
    permissions.py  calls core.permissions.register([...])
    models.py       tenant tables on TenantBase (B06 D4)
    search.py       calls modules.search.sources.register(SearchSource(...)) (B07 D14)
    exports.py      calls modules.exports.sources.register(ExportSource(...)) (B07 D14)
Missing files are simply skipped.

Kept out of main.py so the CLI and the worker can load permissions and models
without importing the web app.
"""

import importlib
from types import ModuleType

import structlog
from fastapi import APIRouter

log = structlog.get_logger("app.modules.registry")

MODULES: list[str] = [
    "health",
    "auth",
    "users",
    "rbac",
    "organizations",
    "platform",
    "files",
    "search",
    "exports",
    "notifications",
    "_template",  # example business module (/items); copy it, then add yours below
]


def _package(name: str) -> str:
    return name if "." in name else f"app.modules.{name}"


def _import_optional(name: str, part: str) -> ModuleType | None:
    """Import <module>.<part>; None if that file does not exist.

    A ModuleNotFoundError raised from INSIDE an existing file (a broken import)
    is re-raised, so a typo never silently drops a module.
    """
    dotted = f"{_package(name)}.{part}"
    try:
        return importlib.import_module(dotted)
    except ModuleNotFoundError as exc:
        if exc.name == dotted:
            return None
        raise


def load_routers() -> list[tuple[str, APIRouter]]:
    """(module name, router) for every registered module that has a router."""
    out = []
    for name in MODULES:
        mod = _import_optional(name, "router")
        if mod is not None:
            out.append((name, mod.router))
    return out


def load_permissions() -> None:
    """Import every permissions.py (each registers its keys; idempotent)."""
    for name in MODULES:
        _import_optional(name, "permissions")


def load_models() -> None:
    """Import every models.py so TenantBase.metadata holds all tenant tables."""
    for name in MODULES:
        _import_optional(name, "models")


def load_parts(part: str) -> list[ModuleType]:
    """Import <module>.<part> for every registered module that has it (B07 D14).

    E.g. load_parts("search") registers every module's search source. Importing
    is idempotent, so callers may call this on every lookup.
    """
    out = []
    for name in MODULES:
        mod = _import_optional(name, part)
        if mod is not None:
            out.append(mod)
    return out
