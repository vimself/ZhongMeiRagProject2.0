from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import KnowledgePageIndexV2
from app.services.ingest.chunker import ChunkCandidate

TRUNCATION_MARKER = "\n\n[page_index_text_truncated]"


async def write_page_index(
    db: AsyncSession,
    *,
    document_id: str,
    chunks: Sequence[ChunkCandidate],
) -> int:
    settings = get_settings()
    await db.execute(
        delete(KnowledgePageIndexV2).where(KnowledgePageIndexV2.document_id == document_id)
    )
    pages: dict[int, list[ChunkCandidate]] = {}
    for chunk in chunks:
        page = chunk.page_start or 1
        pages.setdefault(page, []).append(chunk)
    for page_no, page_chunks in sorted(pages.items()):
        db.add(
            KnowledgePageIndexV2(
                document_id=document_id,
                page_no=page_no,
                section_map_json={
                    "sections": [
                        {
                            "section_id": chunk.section_id,
                            "section_path": chunk.section_path,
                            "chunk_index": chunk.chunk_index,
                        }
                        for chunk in page_chunks
                    ]
                },
                block_count=len(page_chunks),
                text=build_page_index_text(
                    page_chunks,
                    max_bytes=settings.ingest_page_index_text_max_bytes,
                ),
            )
        )
    await db.flush()
    return len(pages)


def build_page_index_text(chunks: Sequence[ChunkCandidate], *, max_bytes: int) -> str:
    """Page index text is auxiliary; cap it so large OCR tables cannot break ingest."""
    seen: set[str] = set()
    parts: list[str] = []
    for chunk in chunks:
        if chunk.sha256 in seen:
            continue
        seen.add(chunk.sha256)
        parts.append(chunk.content)
    return truncate_utf8("\n\n".join(parts), max_bytes=max_bytes)


def truncate_utf8(text: str, *, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    marker = TRUNCATION_MARKER.encode("utf-8")
    if max_bytes <= len(marker):
        return marker[:max_bytes].decode("utf-8", errors="ignore")
    budget = max_bytes - len(marker)
    prefix = raw[:budget].decode("utf-8", errors="ignore").rstrip()
    return prefix + TRUNCATION_MARKER
