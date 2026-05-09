from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    creator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    permissions: Mapped[list[KnowledgeBasePermission]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_knowledge_bases_creator_id", "creator_id"),
        Index("ix_knowledge_bases_is_active", "is_active"),
    )


class KnowledgeBasePermission(Base):
    __tablename__ = "knowledge_base_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="permissions")

    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "user_id", name="uq_kb_permission_user"),
        Index("ix_kb_permissions_user_id", "user_id"),
        Index("ix_kb_permissions_kb_id", "knowledge_base_id"),
    )
