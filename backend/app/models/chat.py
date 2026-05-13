from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timezone import beijing_now
from app.db.base import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_base_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新会话")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=beijing_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=beijing_now, onupdate=beijing_now
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )

    __table_args__ = (
        Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),
        Index("ix_chat_sessions_kb", "knowledge_base_id"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=beijing_now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
    citations: Mapped[list[ChatMessageCitation]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="ChatMessageCitation.index",
    )

    __table_args__ = (Index("ix_chat_messages_session_created", "session_id", "created_at"),)


class ChatMessageCitation(Base):
    __tablename__ = "chat_message_citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    document_title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    section_path_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    section_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=beijing_now)

    message: Mapped[ChatMessage] = relationship(back_populates="citations")

    __table_args__ = (
        Index("ix_chat_citations_message", "message_id"),
        Index("ix_chat_citations_document", "document_id"),
    )


class RagEvalRun(Base):
    __tablename__ = "rag_eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False)
    golden_file: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=beijing_now)

    __table_args__ = (Index("ix_rag_eval_runs_run_key_created", "run_key", "created_at"),)
