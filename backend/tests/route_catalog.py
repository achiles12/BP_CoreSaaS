"""Route catalog for the system-wide suites (B12 D2, D5).

Introspects the FastAPI app instead of keeping hand-written endpoint lists, so
a new module's routes are covered by the permission matrix and the audit
coverage test without editing them.
"""

import re
import uuid
from dataclasses import dataclass

from fastapi.routing import APIRoute

from app.core.permissions import tenant_access
from app.modules import registry

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_PARAM = re.compile(r"\{[^}]+\}")


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str  # template, e.g. /files/{file_id}
    name: str  # route function name (= operationId)
    key: str | None  # permission from require(), None when the route has none
    tenant: bool  # depends on tenant_access (X-Tenant + membership)

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


def _walk(dep, seen: list) -> None:  # noqa: ANN001  (fastapi Dependant)
    for d in dep.dependencies:
        seen.append(d.call)
        _walk(d, seen)


def _api_routes() -> list[APIRoute]:
    """Every route main.create_app() mounts: the registry's routers.

    Read from the routers, not app.routes: FastAPI 0.16x keeps included
    routers as lazy wrappers whose internals are private.
    """
    return [
        r
        for _name, router in registry.load_routers()
        for r in router.routes
        if isinstance(r, APIRoute)
    ]


def catalog() -> list[RouteInfo]:
    out = []
    for r in _api_routes():
        if not isinstance(r, APIRoute):
            continue
        calls: list = []
        _walk(r.dependant, calls)
        keys = {getattr(c, "required_permission", None) for c in calls} - {None}
        if len(keys) > 1:
            raise AssertionError(f"{r.path}: more than one require(): {keys}")
        for m in sorted((r.methods or set()) - {"HEAD", "OPTIONS"}):
            out.append(
                RouteInfo(
                    method=m,
                    path=r.path,
                    name=r.name,
                    key=next(iter(keys), None),
                    tenant=tenant_access in calls,
                )
            )
    return out


def tenant_routes() -> list[RouteInfo]:
    return [r for r in catalog() if r.tenant]


def mutation_routes() -> list[RouteInfo]:
    return [r for r in catalog() if r.method in MUTATING]


def fill_path(path: str) -> str:
    """/files/{file_id} -> /files/<random uuid> (an id that exists nowhere)."""
    return _PARAM.sub(lambda _m: str(uuid.uuid4()), path)
