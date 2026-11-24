"""In-app notifications (design B07 §3.7, D1, D12, D13; system_design.md §6).

`notify()` is the one way to create a notification. It only adds the row to
the caller's tenant session, so the notification commits (or rolls back)
together with the change that caused it. Any module or job may call it.

Users only ever see and change their OWN rows: another user's id is a 404,
exactly like an id from another tenant (C2).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import NotFound
from app.core.pagination import PageParams, paginate
from app.core.permissions import TenantAccess
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import NotificationOut

log = structlog.get_logger("app.notifications")

AUDIT_ENTITY = "notification"


def notify(
    ts: AsyncSession,
    user_id: uuid.UUID,
    type: str,  # noqa: A002  (the column is called type)
    title: str,
    body: str | None = None,
    data: dict[str, Any] | None = None,
) -> Notification:
    """Queue a notification row in `ts`. The CALLER commits."""
    n = Notification(user_id=user_id, type=type, title=title, body=body, data=data or {})
    ts.add(n)
    log.info("notifications.created", user_id=str(user_id), type=type)
    return n


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        type=n.type,
        title=n.title,
        body=n.body,
        data=n.data or {},
        read_at=n.read_at,
        created_at=n.created_at,
    )


async def list_notifications(
    ts: AsyncSession, access: TenantAccess, unread: bool, page: PageParams
) -> tuple[list[NotificationOut], int]:
    stmt = select(Notification).where(Notification.user_id == access.user_id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
    rows, total = await paginate(ts, stmt, page)
    return [_out(r[0]) for r in rows], total


async def mark_read(
    ts: AsyncSession, access: TenantAccess, notification_id: uuid.UUID
) -> NotificationOut:
    """Set read_at once (D12): a second call keeps the first time and is not audited."""
    n = await ts.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == access.user_id
        )
    )
    if n is None:
        raise NotFound("Notification not found")
    if n.read_at is None:
        read_at = datetime.now(UTC)
        n.read_at = read_at
        await ts.commit()
        audit.record(
            "notifications.read",
            entity=AUDIT_ENTITY,
            entity_id=str(n.id),
            org=access.tenant.slug,
            actor=str(access.user_id),
            diff={"read_at": [None, read_at.isoformat()]},
        )
    return _out(n)


async def mark_all_read(ts: AsyncSession, access: TenantAccess) -> int:
    """Mark every unread notification of the caller read; returns how many."""
    res = await ts.execute(
        update(Notification)
        .where(Notification.user_id == access.user_id, Notification.read_at.is_(None))
        .values(read_at=func.now())
    )
    count = int(res.rowcount or 0)  # type: ignore[attr-defined]  # CursorResult
    await ts.commit()
    log.info("notifications.read_all", org=access.tenant.slug, count=count)
    audit.record(
        "notifications.read_all",
        entity=AUDIT_ENTITY,
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={"count": count},
    )
    return count
