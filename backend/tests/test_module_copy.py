"""B06 "done when": copy `_template`, register it, sync permissions -> it works.

Exactly what a developer does (modules/_template/README.md), done to a temp
package so nothing is written into app/modules or the migration chain:

1. copy the template's sources, renaming items -> widgets (keys, table, paths,
   route names, model class)
2. add the package to registry.MODULES (the ONE list)
3. create its table in an existing tenant (stands in for a tenant revision)
4. run sync_permissions on that tenant (stands in for `make cli args=sync-permissions`)
5. start the app: staff can create a widget, user can only read it

No core file is touched in between: that is the claim under test.
"""

import asyncio
import re
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.config import Settings
from app.core import db, permissions
from app.core.tenancy import tenant_session
from app.main import create_app
from app.models.base import TENANT_SCHEMA_PLACEHOLDER, TenantBase
from app.modules import registry
from app.modules.rbac.seed import sync_permissions
from tests.b04_helpers import call, login
from tests.conftest import B04World

pytestmark = pytest.mark.integration

TEMPLATE_DIR = Path(registry.__file__).parent / "_template"
PKG = "b06copy.widgets"
SCHEMA = "tenant_acme4"


def _rename(src: str) -> str:
    """The renames the README tells a developer to make."""
    src = src.replace("app.modules._template", PKG)
    src = src.replace("_template_items", "b06copy_widgets")
    src = src.replace('"items:', '"widgets:').replace("items:", "widgets:")
    src = src.replace('prefix="/items"', 'prefix="/widgets"').replace(
        'tags=["items"]', 'tags=["widgets"]'
    )
    src = re.sub(r"\b(list|get|create|update|delete)_items\b", r"\1_widgets", src)
    src = re.sub(r"\b(get|create|update|delete)_item\b", r"\1_widget", src)
    return src.replace("TemplateItem", "Widget")


@pytest.fixture
def widgets_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    pkg_dir = tmp_path / "b06copy" / "widgets"
    pkg_dir.mkdir(parents=True)
    (tmp_path / "b06copy" / "__init__.py").write_text("")
    for f in TEMPLATE_DIR.glob("*.py"):
        (pkg_dir / f.name).write_text(_rename(f.read_text()))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(registry, "MODULES", [*registry.MODULES, PKG])  # step 2
    try:
        yield
    finally:
        # Undo the process-wide side effects so later tests see the real registry.
        for key in [k for k in permissions._registry if k.startswith("widgets:")]:  # noqa: SLF001
            del permissions._registry[key]  # noqa: SLF001
        table = TenantBase.metadata.tables.get(f"{TENANT_SCHEMA_PLACEHOLDER}.b06copy_widgets")
        if table is not None:  # keep the drift test blind to the copy
            TenantBase.metadata.remove(table)
        for name in [m for m in sys.modules if m == "b06copy" or m.startswith("b06copy.")]:
            del sys.modules[name]
        shutil.rmtree(tmp_path / "b06copy", ignore_errors=True)


async def _create_table_and_sync(db_url: str) -> int:
    db.init_engine(db_url)
    try:
        registry.load_models()
        from b06copy.widgets.models import Widget  # type: ignore[import-not-found]

        bound = db.get_engine().execution_options(
            schema_translate_map={TENANT_SCHEMA_PLACEHOLDER: SCHEMA}
        )
        async with bound.begin() as c:  # step 3
            await c.run_sync(lambda sc: Widget.__table__.create(sc, checkfirst=True))
        async with tenant_session(SCHEMA) as ts:  # step 4
            return await sync_permissions(ts)
    finally:
        await db.dispose_engine()


async def _cleanup(db_url: str) -> None:
    db.init_engine(db_url)
    try:
        async with db.get_engine().begin() as c:
            await c.execute(text("drop table if exists tenant_acme4.b06copy_widgets"))
            await c.execute(text("delete from tenant_acme4.permissions where key like 'widgets:%'"))
    finally:
        await db.dispose_engine()


def test_copied_template_works_after_register_and_sync(
    widgets_module: None, b04_settings: Settings, b04_world: B04World, audit_log: Path
) -> None:
    try:
        assert asyncio.run(_create_table_and_sync(b04_world.db_url)) == 3
        # Permission sets are cached for 60 s per user; drop them so the new
        # grants show now (as invalidate_access does after a role change).
        r = Redis.from_url(b04_settings.redis_url)
        for key in r.scan_iter("perm:*"):
            r.delete(key)

        with TestClient(create_app(b04_settings)) as c:  # step 5
            paths = c.get("/openapi.json").json()["paths"]
            assert "/widgets" in paths and "/items" in paths
            staff = login(c, b04_world.users["staff"])
            user = login(c, b04_world.users["user"])
            made = call(c, "POST", "/widgets", staff, "acme4", json={"title": "Copied"})
            assert made.status_code == 201, made.text
            assert (
                call(c, "POST", "/widgets", user, "acme4", json={"title": "x"}).status_code == 403
            )
            listed = call(c, "GET", "/widgets", user, "acme4").json()
            assert [w["title"] for w in listed["items"]] == ["Copied"]
            wid = made.json()["id"]
            assert call(c, "DELETE", f"/widgets/{wid}", staff, "acme4").status_code == 403
            admin = login(c, b04_world.users["admin"])
            assert call(c, "DELETE", f"/widgets/{wid}", admin, "acme4").status_code == 204
    finally:
        asyncio.run(_cleanup(b04_world.db_url))
        r = Redis.from_url(b04_settings.redis_url)
        for key in r.scan_iter("perm:*"):
            r.delete(key)
