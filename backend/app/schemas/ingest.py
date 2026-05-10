from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestStepProgress(BaseModel):
    step: str
    status: str
    created_at: str | None = None


class IngestJobProgress(BaseModel):
    document_id: str
    job_id: str | None = None
    job_status: str | None = None
    document_status: str
    progress: int
    steps: list[IngestStepProgress]
    last_error: str | None = None


class RetrievalDebugRequest(BaseModel):
    kb_id: str
    query: str = Field(min_length=1, max_length=1024)
    k: int = Field(default=10, ge=1, le=50)
    filters: dict[str, Any] = Field(default_factory=dict)


class RetrievalDebugItem(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str = ""
    knowledge_base_id: str = ""
    chunk_index: int = 0
    score: float
    content: str = ""
    section_path: list[str]
    section_text: str = ""
    page_start: int | None = None
    page_end: int | None = None
    bbox: dict[str, Any] | None = None
    snippet: str = ""
    preview_url: str | None = None
    download_url: str | None = None


class RetrievalDebugResponse(BaseModel):
    items: list[RetrievalDebugItem]
    total: int
