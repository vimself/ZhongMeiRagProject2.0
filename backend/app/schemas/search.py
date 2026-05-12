from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# --- Search ---


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1024)
    kb_id: str | None = None
    doc_kind: str | None = None
    content_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    sort_by: str = Field(default="relevance")


class SearchHitOut(BaseModel):
    id: str
    index: int
    chunk_id: str | None = None
    document_id: str
    document_title: str
    knowledge_base_id: str
    section_path: list[str] = Field(default_factory=list)
    section_text: str = ""
    page_start: int | None = None
    page_end: int | None = None
    bbox: dict[str, Any] | None = None
    snippet: str = ""
    score: float = 0.0
    preview_url: str
    download_url: str


class SearchResponse(BaseModel):
    items: list[SearchHitOut]
    total: int
    page: int
    page_size: int


# --- Hot Keywords ---


class HotKeywordItem(BaseModel):
    keyword: str
    count: int


class HotKeywordsResponse(BaseModel):
    items: list[HotKeywordItem]


# --- Doc Types ---


class DocTypeCount(BaseModel):
    doc_kind: str
    count: int


class DocTypesResponse(BaseModel):
    doc_kinds: list[DocTypeCount]


# --- Export ---


class ExportRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1024)
    kb_id: str | None = None
    doc_kind: str | None = None
    content_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    format: str = Field(default="json", pattern=r"^(json|csv)$")


class ExportJobOut(BaseModel):
    job_id: str
    status: str
    created_at: str


class ExportJobStatusOut(BaseModel):
    job_id: str
    status: str
    result_count: int
    file_size: int | None = None
    download_url: str | None = None
    error: str | None = None
    created_at: str


# --- Dashboard ---


class DashboardStats(BaseModel):
    user_count: int
    kb_count: int
    kb_active_count: int
    document_total: int
    document_by_status: dict[str, int]
    document_by_kind: dict[str, int]
    chunk_count: int
    asset_count: int
    chat_session_count: int
    chat_message_count: int
    ingest_by_status: dict[str, int]
    recent_activities: list[dict[str, Any]]
    trends_7d: dict[str, Any]
    trends_14d: dict[str, Any]


class SystemStatus(BaseModel):
    database: dict[str, Any]
    redis: dict[str, Any]
    dashscope: dict[str, Any]
    uptime_seconds: float
