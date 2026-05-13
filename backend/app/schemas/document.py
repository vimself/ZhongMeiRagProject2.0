from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: str
    knowledge_base_id: str
    uploader_id: str
    uploader_name: str = ""
    title: str
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    doc_kind: str
    scheme_type: str | None = None
    is_standard_clause: bool
    status: str
    page_count: int | None = None
    created_at: str
    updated_at: str


class DocumentListResponse(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class DocumentDeleteResponse(BaseModel):
    document_id: str
    deleted: bool = True


class DocumentBatchDeleteRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=100)


class DocumentBatchDeleteResponse(BaseModel):
    deleted_ids: list[str]
    deleted_count: int


class DocumentUploadItem(BaseModel):
    document_id: str
    job_id: str
    trace_id: str
    title: str
    filename: str


class DocumentUploadRejectedItem(BaseModel):
    filename: str
    reason: str


class DocumentUploadResponse(BaseModel):
    document_id: str | None = None
    job_id: str | None = None
    trace_id: str | None = None
    documents: list[DocumentUploadItem] = Field(default_factory=list)
    rejected: list[DocumentUploadRejectedItem] = Field(default_factory=list)
    accepted_count: int = 0
    rejected_count: int = 0
    max_count: int = 50


class AssetOut(BaseModel):
    id: str
    kind: str
    page_no: int | None = None
    bbox: dict[str, Any] | None = None
    storage_path: str
    url: str | None = None
    caption: str | None = None
    created_at: str


class DocumentDetailResponse(DocumentOut):
    latest_job: dict[str, Any] | None = None
    parse_result: dict[str, Any] | None = None
    assets: list[AssetOut] = Field(default_factory=list)


class RetryDocumentResponse(BaseModel):
    document_id: str
    job_id: str
    trace_id: str
    status: str
