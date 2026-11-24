"""Tenant table of the exports module: `export_jobs` (T08, design B07 §3.1).

Lifecycle: queued (POST /exports) -> running (worker) -> done | failed;
done -> expired when the retention cleanup removes the file (D2).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantBase, created_at, uuid_pk
from app.models.public import User

EXPORT_STATUSES = ("queued", "running", "done", "failed", "expired")
EXPORT_FORMATS = ("csv", "xlsx")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(repr(v) for v in values)


class ExportJob(TenantBase):
    __tablename__ = "export_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in(EXPORT_STATUSES)})", name="status"),
        CheckConstraint(f"format IN ({_in(EXPORT_FORMATS)})", name="format"),
        Index("ix_export_jobs_requested_by_created_at", "requested_by", text("created_at DESC")),
        # retention cleanup: done jobs by finish time; stuck queued/running jobs
        Index("ix_export_jobs_status_finished_at", "status", "finished_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requested_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    # A registered export source name (files, items, users); checked by the API.
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    # The list query as sent ({"q": ..., "filter[status]": ...}), replayed by the job.
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    object_key: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
