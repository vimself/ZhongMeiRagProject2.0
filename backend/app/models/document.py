from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    uploader_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    doc_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    scheme_type: Mapped[str | None] = mapped_column(String(64))
    is_standard_clause: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    page_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    ingest_jobs: Mapped[list[DocumentIngestJob]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    parse_result: Mapped[DocumentParseResult | None] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    assets: Mapped[list[DocumentAsset]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_kb_status_created", "knowledge_base_id", "status", "created_at"),
        Index("ix_documents_sha256", "sha256"),
    )


class DocumentParseResult(Base):
    __tablename__ = "document_parse_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    ocr_session_id: Mapped[str | None] = mapped_column(String(128))
    markdown_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    markdown_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    outline_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="parse_result")


class DocumentAsset(Base):
    __tablename__ = "document_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="assets")

    __table_args__ = (Index("ix_document_assets_document_id", "document_id"),)


class DocumentIngestJob(Base):
    __tablename__ = "document_ingest_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, default=new_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    document: Mapped[Document] = relationship(back_populates="ingest_jobs")
    receipts: Mapped[list[IngestStepReceipt]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_document_ingest_jobs_available_status", "available_at", "status"),
        Index("ix_document_ingest_jobs_document_id", "document_id"),
    )


class IngestStepReceipt(Base):
    __tablename__ = "ingest_step_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_ingest_jobs.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[DocumentIngestJob] = relationship(back_populates="receipts")

    __table_args__ = (
        Index("ix_ingest_step_receipts_job_step", "job_id", "step"),
        Index("ix_ingest_step_receipts_key", "idempotency_key"),
    )


class IngestCallbackReceipt(Base):
    __tablename__ = "ingest_callback_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class KnowledgeChunkV2(Base):
    __tablename__ = "knowledge_chunks_v2"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    section_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="paragraph")
    doc_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    scheme_type: Mapped[str | None] = mapped_column(String(64))
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[list[float] | None] = mapped_column(JSON)
    sparse: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_kchunks_v2_kb_kind_scheme", "knowledge_base_id", "doc_kind", "scheme_type"),
        Index("ix_kchunks_v2_doc_section", "document_id", "section_id"),
        Index("ix_kchunks_v2_document_id", "document_id"),
    )


class KnowledgePageIndexV2(Base):
    __tablename__ = "knowledge_page_index_v2"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    section_map_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    block_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_kpage_index_v2_doc_page", "document_id", "page_no"),
        Index("ix_kpage_index_v2_document_id", "document_id"),
    )
