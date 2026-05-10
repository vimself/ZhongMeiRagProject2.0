from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import KnowledgeChunkV2
from app.services.ingest.chunker import ChunkCandidate
from app.services.llm.client import DashScopeClient
from app.services.rag.vector_utils import (
    dense_vector_literal,
    sparse_vector_literal,
    text_term_weights,
)


class TrackAIndexer:
    def __init__(
        self,
        embedding_client: Any | None = None,
        cache: Any | None = None,
        *,
        batch_size: int | None = None,
    ) -> None:
        settings = get_settings()
        self.embedding_client = embedding_client
        self.cache = cache
        self.batch_size = batch_size or settings.embed_batch_size
        self._memory_cache: dict[str, list[float]] = {}

    async def embed_chunks(self, chunks: Sequence[ChunkCandidate]) -> list[list[float]]:
        vectors: list[list[float] | None] = []
        pending_texts: list[str] = []
        pending_positions: list[int] = []
        for index, chunk in enumerate(chunks):
            cached = await self._cache_get(chunk.sha256)
            vectors.append(cached)
            if cached is None:
                pending_positions.append(index)
                pending_texts.append(chunk.content)
        for offset in range(0, len(pending_texts), self.batch_size):
            batch = pending_texts[offset : offset + self.batch_size]
            batch_positions = pending_positions[offset : offset + self.batch_size]
            embeddings = await self._embed_batch(batch)
            for position, embedding in zip(batch_positions, embeddings, strict=True):
                vectors[position] = embedding
                await self._cache_set(chunks[position].sha256, embedding)
        return [vector or [] for vector in vectors]

    async def write_chunks(
        self,
        db: AsyncSession,
        *,
        knowledge_base_id: str,
        document_id: str,
        doc_kind: str,
        scheme_type: str | None,
        chunks: Sequence[ChunkCandidate],
        vectors: Sequence[list[float]],
    ) -> int:
        await db.execute(
            delete(KnowledgeChunkV2).where(KnowledgeChunkV2.document_id == document_id)
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            sparse = _simple_sparse(chunk.content)
            db.add(
                KnowledgeChunkV2(
                    knowledge_base_id=knowledge_base_id,
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    section_path=chunk.section_path,
                    section_id=chunk.section_id,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    bbox_json=None,
                    content_type=chunk.content_type,
                    doc_kind=doc_kind,
                    scheme_type=scheme_type,
                    tokens=chunk.tokens,
                    sha256=chunk.sha256,
                    vector=vector,
                    sparse=sparse,
                    vector_native=dense_vector_literal(vector) if vector else None,
                    sparse_native=sparse_vector_literal(sparse),
                )
            )
        await db.flush()
        return len(chunks)

    async def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if self.embedding_client is not None:
            return list(await self.embedding_client.embed_batch(texts))
        async with DashScopeClient() as client:
            return await client.embed_batch(texts)

    async def _cache_get(self, sha256: str) -> list[float] | None:
        if sha256 in self._memory_cache:
            return self._memory_cache[sha256]
        if self.cache is None:
            return None
        value = await self.cache.get(f"embedding:{sha256}")
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        vector = [float(item) for item in json.loads(str(value))]
        self._memory_cache[sha256] = vector
        return vector

    async def _cache_set(self, sha256: str, vector: list[float]) -> None:
        self._memory_cache[sha256] = vector
        if self.cache is not None:
            await self.cache.setex(f"embedding:{sha256}", 7 * 24 * 3600, json.dumps(vector))


def _simple_sparse(text: str) -> dict[str, float]:
    return text_term_weights(text)
