from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    session_id: str | None = None
    kb_id: str = Field(..., description="目标知识库 ID；传 __all__ 表示当前用户可访问的全部知识库")
    question: str = Field(..., min_length=1, max_length=4000)
    filters: dict[str, Any] | None = None
    k: int | None = Field(default=None, ge=1, le=20)


class ChatCitationOut(BaseModel):
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


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    finish_reason: str | None = None
    model: str | None = None
    created_at: str
    citations: list[ChatCitationOut] = Field(default_factory=list)


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    knowledge_base_id: str | None = None
    is_active: bool = True
    message_count: int = 0
    created_at: str
    updated_at: str


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionSummary]
    total: int


class ChatSessionDetail(BaseModel):
    id: str
    title: str
    knowledge_base_id: str | None = None
    is_active: bool = True
    created_at: str
    updated_at: str
    messages: list[ChatMessageOut]
