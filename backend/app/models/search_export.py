from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timezone import beijing_now
from app.db.base import Base
from app.models.document import new_uuid


class SearchExportJob(Base):
    __tablename__ = "search_export_jobs"
    __table_args__ = (
        Index("ix_sej_user_created", "user_id", "created_at"),
        Index("ix_sej_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    format: Mapped[str] = mapped_column(String(16), default="json", nullable=False)
    filters_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=beijing_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=beijing_now, onupdate=beijing_now
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def set_defaults(self) -> None:
        now = beijing_now()
        if self.created_at is None:
            self.created_at = now
        if self.expires_at is None:
            self.expires_at = now + timedelta(hours=24)
