"""引用元数据 -> 前端协议 payload 工具。

抽象自 backend/app/api/documents.py::_retrieval_item，供 chat stream 与历史详情复用。
token 不持久化，每次组装 payload 时重新签发（5 min 过期）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from app.security.jwt import issue_pdf_token


@dataclass(frozen=True)
class CitationMeta:
    """RAG 引用稳定元数据（用于持久化 + 生成前端协议）。"""

    index: int
    chunk_id: str | None
    document_id: str
    document_title: str
    knowledge_base_id: str
    section_path: list[str]
    section_text: str
    page_start: int | None
    page_end: int | None
    bbox: dict[str, Any] | None
    snippet: str
    score: float


def build_reference_payload(
    meta: CitationMeta,
    *,
    user_id: str,
) -> dict[str, Any]:
    """将稳定引用元数据 + 新签发 token 组装为前端 JSON 协议。"""
    issued = issue_pdf_token(
        subject=user_id,
        document_id=meta.document_id,
        knowledge_base_id=meta.knowledge_base_id,
    )
    token = quote(issued.token)
    page = meta.page_start or 1
    preview_url = f"/api/v2/pdf/preview?document_id={meta.document_id}&page={page}&token={token}"
    bbox_fragment = _bbox_fragment(meta.bbox)
    if bbox_fragment:
        preview_url = f"{preview_url}#bbox={bbox_fragment}"
    download_url = f"/api/v2/documents/{meta.document_id}/download?token={token}"
    return {
        "id": f"ref-{meta.index}",
        "index": meta.index,
        "chunk_id": meta.chunk_id,
        "document_id": meta.document_id,
        "document_title": meta.document_title,
        "knowledge_base_id": meta.knowledge_base_id,
        "section_path": meta.section_path,
        "section_text": meta.section_text,
        "page_start": meta.page_start,
        "page_end": meta.page_end,
        "bbox": meta.bbox,
        "snippet": meta.snippet,
        "score": meta.score,
        "preview_url": preview_url,
        "download_url": download_url,
    }


def _bbox_fragment(bbox: dict[str, Any] | None) -> str:
    if not bbox:
        return ""
    x = bbox.get("x", bbox.get("left"))
    y = bbox.get("y", bbox.get("top"))
    width = bbox.get("width", bbox.get("w"))
    height = bbox.get("height", bbox.get("h"))
    values = [x, y, width, height]
    if not all(isinstance(value, int | float) for value in values):
        return ""
    return ",".join(str(value) for value in values)
