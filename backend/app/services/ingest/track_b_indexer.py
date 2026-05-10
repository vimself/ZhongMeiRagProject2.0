from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import KnowledgePageIndexV2
from app.services.ingest.chunker import ChunkCandidate


async def write_page_index(
    db: AsyncSession,
    *,
    document_id: str,
    chunks: Sequence[ChunkCandidate],
) -> int:
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
                text="\n\n".join(chunk.content for chunk in page_chunks),
            )
        )
    await db.flush()
    return len(pages)
