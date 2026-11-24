"""Business rules of the template module (design B06 §3.4, D10–D14).

The pattern every module follows:
- every query runs in the caller's tenant session, so another tenant's id is
  simply not found (404, C2)
- lists use core.pagination (ListSpec + ListQuery): only named fields can be
  sorted or filtered
- every change commits, then writes one audit line `<module>.<verb>`
- soft delete: `deleted_at` set, the row is never returned again
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import NotFound
from app.core.pagination import FilterField, ListQuery, ListSpec, paginate
from app.core.permissions import TenantAccess
from app.models.public import User
from app.modules._template.models import ITEM_STATUSES, TemplateItem
from app.modules._template.schemas import ItemCreate, ItemOut, ItemUpdate

log = structlog.get_logger("app.items")

AUDIT_ENTITY = "item"
# What GET /items may sort and filter by (D14).
ITEMS_LIST = ListSpec(
    sort={
        "title": TemplateItem.title,
        "status": TemplateItem.status,
        "created_at": TemplateItem.created_at,
        "updated_at": TemplateItem.updated_at,
    },
    default_sort="-created_at",
    filters={
        "status": FilterField(TemplateItem.status, "enum", choices=ITEM_STATUSES),
        "owner_id": FilterField(TemplateItem.owner_id, "uuid"),
        "created_at": FilterField(TemplateItem.created_at, "datetime", ranges=True),
    },
)


def _escape_like(q: str) -> str:
    """Literal substring search: user input must not act as LIKE wildcards."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _out(item: TemplateItem, owner_name: str | None) -> ItemOut:
    return ItemOut(
        id=item.id,
        title=item.title,
        description=item.description,
        status=item.status,
        owner_id=item.owner_id,
        owner_name=owner_name,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _with_owner() -> Select:
    return (
        select(TemplateItem, User.full_name)
        .outerjoin(User, User.id == TemplateItem.owner_id)
        .where(TemplateItem.deleted_at.is_(None))
    )


async def _live_or_404(ts: AsyncSession, item_id: uuid.UUID) -> TemplateItem:
    item = await ts.scalar(
        select(TemplateItem)
        .where(TemplateItem.id == item_id, TemplateItem.deleted_at.is_(None))
        .with_for_update()  # serialise concurrent edits of one item
    )
    if item is None:
        raise NotFound("Item not found")
    return item


async def _owner_name(ts: AsyncSession, user_id: uuid.UUID) -> str | None:
    return await ts.scalar(select(User.full_name).where(User.id == user_id))


def items_statement(q: str | None, lq: ListQuery) -> Select:
    """The ONE query behind GET /items and the items export (B07 D4): same rows."""
    stmt = lq.apply(_with_owner())
    if q and q.strip():
        stmt = stmt.where(TemplateItem.title.ilike(f"%{_escape_like(q.strip())}%", escape="\\"))
    return stmt


async def list_items(ts: AsyncSession, q: str | None, lq: ListQuery) -> tuple[list[ItemOut], int]:
    rows, total = await paginate(ts, items_statement(q, lq), lq.page)
    return [_out(i, n) for i, n in rows], total


async def get_item(ts: AsyncSession, item_id: uuid.UUID) -> ItemOut:
    row = (await ts.execute(_with_owner().where(TemplateItem.id == item_id))).first()
    if row is None:
        raise NotFound("Item not found")
    return _out(row[0], row[1])


async def create_item(ts: AsyncSession, access: TenantAccess, body: ItemCreate) -> ItemOut:
    item = TemplateItem(
        title=body.title,
        description=body.description,
        status=body.status,
        owner_id=access.user_id,
    )
    ts.add(item)
    await ts.commit()
    await ts.refresh(item)
    log.info(
        "items.created", org=access.tenant.slug, actor=str(access.user_id), item_id=str(item.id)
    )
    audit.record(
        "items.create",
        entity=AUDIT_ENTITY,
        entity_id=str(item.id),
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={"title": item.title, "status": item.status},
    )
    return _out(item, await _owner_name(ts, item.owner_id))


async def update_item(
    ts: AsyncSession, access: TenantAccess, item_id: uuid.UUID, body: ItemUpdate
) -> ItemOut:
    """Apply only the fields sent; the audit diff holds only real changes."""
    item = await _live_or_404(ts, item_id)
    diff: dict[str, list] = {}
    for name in body.model_fields_set:
        old, new = getattr(item, name), getattr(body, name)
        if old != new:
            diff[name] = [old, new]
            setattr(item, name, new)
    if diff:
        item.updated_at = datetime.now(UTC)
        await ts.commit()
        await ts.refresh(item)
        audit.record(
            "items.update",
            entity=AUDIT_ENTITY,
            entity_id=str(item.id),
            org=access.tenant.slug,
            actor=str(access.user_id),
            diff=diff,
        )
    else:
        await ts.rollback()  # release the row lock; nothing changed
    log.info("items.updated", org=access.tenant.slug, item_id=str(item_id), changed=sorted(diff))
    return await get_item(ts, item_id)


async def delete_item(ts: AsyncSession, access: TenantAccess, item_id: uuid.UUID) -> None:
    item = await _live_or_404(ts, item_id)
    deleted_at = datetime.now(UTC)
    item.deleted_at = deleted_at
    await ts.commit()
    log.info(
        "items.deleted", org=access.tenant.slug, actor=str(access.user_id), item_id=str(item_id)
    )
    audit.record(
        "items.delete",
        entity=AUDIT_ENTITY,
        entity_id=str(item_id),
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={"deleted_at": [None, deleted_at.isoformat()]},
    )
