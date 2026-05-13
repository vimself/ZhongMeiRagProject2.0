from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, KnowledgeChunkV2
from app.services.deletion import DOCUMENT_DELETING_STATUS
from app.services.rag.vector_utils import (
    clean_display_text,
    dense_vector_literal,
    sparse_vector_literal,
    text_term_weights,
)


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: str
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
    preview_url: str | None = None
    download_url: str | None = None


class Retriever:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def retrieve(
        self,
        *,
        kb_id: str,
        query: str,
        k: int = 10,
        filters: dict[str, Any] | None = None,
        query_vector: list[float] | None = None,
    ) -> list[RetrievalResult]:
        filters = filters or {}
        cleaned_query = clean_display_text(query)
        loaded_chunks: list[KnowledgeChunkV2] | None = None
        chunks: list[KnowledgeChunkV2]
        if self._can_use_seekdb_native():
            try:
                vector_results = (
                    await self._seekdb_vector_search(kb_id, query_vector, filters, k=k * 2)
                    if query_vector
                    else []
                )
                bm25_results = await self._seekdb_lexical_search(
                    kb_id,
                    cleaned_query,
                    filters,
                    k=k * 2,
                )
                needs_vector_fallback = query_vector is not None and not vector_results
                needs_bm25_fallback = bool(cleaned_query) and not bm25_results
                if needs_vector_fallback or needs_bm25_fallback:
                    loaded_chunks = await self._load_chunks(kb_id, filters)
                if needs_vector_fallback and loaded_chunks is not None:
                    vector_results = self._vector_search_with_query_vector(
                        loaded_chunks,
                        query_vector,
                        k=k * 2,
                    )
                if needs_bm25_fallback and loaded_chunks is not None:
                    bm25_results = self._bm25_search(loaded_chunks, cleaned_query, k=k * 2)
                candidate_ids = [chunk_id for chunk_id, _ in vector_results + bm25_results]
                if candidate_ids:
                    chunks = (
                        self._loaded_chunks_by_ids(loaded_chunks, candidate_ids)
                        if loaded_chunks is not None
                        else await self._load_chunks_by_ids(candidate_ids)
                    )
                else:
                    chunks = []
                if not chunks:
                    chunks = loaded_chunks or await self._load_chunks(kb_id, filters)
                    vector_results, bm25_results = self._fallback_search_tracks(
                        chunks,
                        query=cleaned_query,
                        k=k * 2,
                        query_vector=query_vector,
                    )
            except SQLAlchemyError:
                chunks = await self._load_chunks(kb_id, filters)
                vector_results, bm25_results = self._fallback_search_tracks(
                    chunks,
                    query=cleaned_query,
                    k=k * 2,
                    query_vector=query_vector,
                )
        else:
            chunks = await self._load_chunks(kb_id, filters)
            vector_results, bm25_results = self._fallback_search_tracks(
                chunks,
                query=cleaned_query,
                k=k * 2,
                query_vector=query_vector,
            )
        if not chunks:
            return []
        # RRF fusion
        fused = self._rrf_fuse(vector_results, bm25_results, k=k)
        # Load document titles
        doc_ids = {chunk.document_id for chunk in chunks}
        doc_titles = await self._load_doc_titles(doc_ids)
        # Build results
        chunk_map = {chunk.id: chunk for chunk in chunks}
        results: list[RetrievalResult] = []
        for chunk_id, score in fused:
            chunk = chunk_map.get(chunk_id)
            if chunk is None:
                continue
            content = chunk.content
            snippet_source = clean_display_text(content)
            snippet = snippet_source[:200] if len(snippet_source) > 200 else snippet_source
            bbox = chunk.bbox_json
            results.append(
                RetrievalResult(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_title=doc_titles.get(chunk.document_id, ""),
                    knowledge_base_id=chunk.knowledge_base_id,
                    section_path=chunk.section_path,
                    section_text=content,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    bbox=bbox,
                    snippet=snippet,
                    score=score,
                )
            )
        return results

    async def _load_chunks(self, kb_id: str, filters: dict[str, Any]) -> list[KnowledgeChunkV2]:
        query = (
            select(KnowledgeChunkV2)
            .join(Document, Document.id == KnowledgeChunkV2.document_id)
            .where(
                KnowledgeChunkV2.knowledge_base_id == kb_id,
                Document.status.notin_(("disabled", DOCUMENT_DELETING_STATUS)),
            )
        )
        doc_kind = filters.get("doc_kind")
        scheme_type = filters.get("scheme_type")
        if isinstance(doc_kind, str) and doc_kind:
            query = query.where(KnowledgeChunkV2.doc_kind == doc_kind)
        if isinstance(scheme_type, str) and scheme_type:
            query = query.where(KnowledgeChunkV2.scheme_type == scheme_type)
        content_type = filters.get("content_type")
        if isinstance(content_type, str) and content_type:
            query = query.where(KnowledgeChunkV2.content_type == content_type)
        query = query.limit(5000)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _load_chunks_by_ids(self, chunk_ids: list[str]) -> list[KnowledgeChunkV2]:
        unique_ids = list(dict.fromkeys(chunk_ids))
        if not unique_ids:
            return []
        result = await self.db.execute(
            select(KnowledgeChunkV2)
            .join(Document, Document.id == KnowledgeChunkV2.document_id)
            .where(
                KnowledgeChunkV2.id.in_(unique_ids),
                Document.status.notin_(("disabled", DOCUMENT_DELETING_STATUS)),
            )
        )
        rows = list(result.scalars().all())
        row_map = {row.id: row for row in rows}
        return [row_map[chunk_id] for chunk_id in unique_ids if chunk_id in row_map]

    @staticmethod
    def _loaded_chunks_by_ids(
        chunks: list[KnowledgeChunkV2] | None,
        chunk_ids: list[str],
    ) -> list[KnowledgeChunkV2]:
        if not chunks:
            return []
        unique_ids = list(dict.fromkeys(chunk_ids))
        chunk_map = {chunk.id: chunk for chunk in chunks}
        return [chunk_map[chunk_id] for chunk_id in unique_ids if chunk_id in chunk_map]

    async def _load_doc_titles(self, doc_ids: set[str]) -> dict[str, str]:
        if not doc_ids:
            return {}
        result = await self.db.execute(
            select(Document.id, Document.title).where(Document.id.in_(doc_ids))
        )
        return {row[0]: row[1] for row in result.all()}

    def _can_use_seekdb_native(self) -> bool:
        bind = self.db.get_bind()
        return bind.dialect.name not in {"sqlite"}

    async def _seekdb_vector_search(
        self,
        kb_id: str,
        query_vector: list[float] | None,
        filters: dict[str, Any],
        k: int,
    ) -> list[tuple[str, float]]:
        if not query_vector:
            return []
        where_sql, params = self._seekdb_filters(kb_id, filters)
        params["query_vector"] = self._vector_literal(query_vector)
        params["limit"] = k
        result = await self.db.execute(
            text(
                f"""
                SELECT c.id AS id, cosine_similarity(c.vector_native, :query_vector) AS score
                FROM knowledge_chunks_v2 c
                JOIN documents d ON d.id = c.document_id
                WHERE {where_sql} AND c.vector_native IS NOT NULL
                ORDER BY cosine_distance(c.vector_native, :query_vector) APPROXIMATE
                LIMIT :limit
                """
            ),
            params,
        )
        return [(str(row.id), float(row.score)) for row in result if row.score is not None]

    async def _seekdb_lexical_search(
        self,
        kb_id: str,
        query: str,
        filters: dict[str, Any],
        k: int,
    ) -> list[tuple[str, float]]:
        if not query.strip():
            return []
        try:
            bm25_results = await self._seekdb_bm25_search(kb_id, query, filters, k=k)
        except SQLAlchemyError:
            bm25_results = []
        try:
            sparse_results = await self._seekdb_sparse_search(kb_id, query, filters, k=k)
        except SQLAlchemyError:
            sparse_results = []
        if bm25_results and sparse_results:
            return self._rrf_fuse(bm25_results, sparse_results, k=k)
        return bm25_results or sparse_results

    async def _seekdb_bm25_search(
        self,
        kb_id: str,
        query: str,
        filters: dict[str, Any],
        k: int,
    ) -> list[tuple[str, float]]:
        where_sql, params = self._seekdb_filters(kb_id, filters)
        params["query_text"] = query
        params["limit"] = k
        result = await self.db.execute(
            text(
                f"""
                SELECT c.id AS id,
                       MATCH(c.content) AGAINST(:query_text IN NATURAL LANGUAGE MODE) AS score
                FROM knowledge_chunks_v2 c
                JOIN documents d ON d.id = c.document_id
                WHERE {where_sql}
                  AND MATCH(c.content) AGAINST(:query_text IN NATURAL LANGUAGE MODE)
                ORDER BY score DESC
                LIMIT :limit
                """
            ),
            params,
        )
        return [(str(row.id), float(row.score)) for row in result if row.score is not None]

    async def _seekdb_sparse_search(
        self,
        kb_id: str,
        query: str,
        filters: dict[str, Any],
        k: int,
    ) -> list[tuple[str, float]]:
        query_sparse = sparse_vector_literal(text_term_weights(query))
        if not query_sparse:
            return []
        where_sql, params = self._seekdb_filters(kb_id, filters)
        params["query_sparse"] = query_sparse
        params["limit"] = k
        result = await self.db.execute(
            text(
                f"""
                SELECT c.id AS id,
                       -negative_inner_product(c.sparse_native, :query_sparse) AS score
                FROM knowledge_chunks_v2 c
                JOIN documents d ON d.id = c.document_id
                WHERE {where_sql} AND c.sparse_native IS NOT NULL
                ORDER BY negative_inner_product(c.sparse_native, :query_sparse) APPROXIMATE
                LIMIT :limit
                """
            ),
            params,
        )
        return [(str(row.id), float(row.score)) for row in result if row.score is not None]

    @staticmethod
    def _seekdb_filters(kb_id: str, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        clauses = [
            "c.knowledge_base_id = :kb_id",
            "d.status NOT IN ('disabled', 'deleting')",
        ]
        params: dict[str, Any] = {"kb_id": kb_id}
        doc_kind = filters.get("doc_kind")
        scheme_type = filters.get("scheme_type")
        if isinstance(doc_kind, str) and doc_kind:
            clauses.append("c.doc_kind = :doc_kind")
            params["doc_kind"] = doc_kind
        if isinstance(scheme_type, str) and scheme_type:
            clauses.append("c.scheme_type = :scheme_type")
            params["scheme_type"] = scheme_type
        content_type = filters.get("content_type")
        if isinstance(content_type, str) and content_type:
            clauses.append("c.content_type = :content_type")
            params["content_type"] = content_type
        return " AND ".join(clauses), params

    @staticmethod
    def _vector_literal(values: list[float]) -> str:
        return dense_vector_literal(values)

    def _vector_search(
        self,
        chunks: list[KnowledgeChunkV2],
        query: str,
        k: int,
    ) -> list[tuple[str, float]]:
        """SQLite fallback: compute cosine similarity in Python."""
        query_vec = self._text_to_simple_vector(query)
        if not query_vec:
            return []
        scored: list[tuple[str, float]] = []
        for chunk in chunks:
            chunk_vec = chunk.vector
            if not chunk_vec or not isinstance(chunk_vec, list):
                continue
            if len(chunk_vec) != len(query_vec):
                continue
            sim = self._cosine_similarity(query_vec, chunk_vec)
            if sim > 0:
                scored.append((chunk.id, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def _fallback_search_tracks(
        self,
        chunks: list[KnowledgeChunkV2],
        *,
        query: str,
        k: int,
        query_vector: list[float] | None,
    ) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
        if query_vector:
            vector_results = self._vector_search_with_query_vector(chunks, query_vector, k=k)
        else:
            vector_results = self._vector_search(chunks, query, k=k)
        return vector_results, self._bm25_search(chunks, query, k=k)

    def _vector_search_with_query_vector(
        self,
        chunks: list[KnowledgeChunkV2],
        query_vector: list[float],
        k: int,
    ) -> list[tuple[str, float]]:
        scored: list[tuple[str, float]] = []
        for chunk in chunks:
            chunk_vec = chunk.vector
            if not chunk_vec or not isinstance(chunk_vec, list):
                continue
            if len(chunk_vec) != len(query_vector):
                continue
            sim = self._cosine_similarity(query_vector, chunk_vec)
            if sim > 0:
                scored.append((chunk.id, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def _bm25_search(
        self,
        chunks: list[KnowledgeChunkV2],
        query: str,
        k: int,
    ) -> list[tuple[str, float]]:
        """SQLite fallback: term frequency + phrase matching."""
        query_lower = clean_display_text(query).lower()
        if not query_lower:
            return []
        query_terms = list(text_term_weights(query_lower))
        scored: list[tuple[str, float]] = []
        for chunk in chunks:
            content_lower = clean_display_text(chunk.content).lower()
            lexical = sum(content_lower.count(term) for term in query_terms)
            phrase = 3 if query_lower in content_lower else 0
            score = float(lexical + phrase)
            if score > 0:
                scored.append((chunk.id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    @staticmethod
    def _rrf_fuse(
        vector_results: list[tuple[str, float]],
        bm25_results: list[tuple[str, float]],
        k: int,
        rrf_k: int = 60,
    ) -> list[tuple[str, float]]:
        if vector_results and not bm25_results:
            return vector_results[:k]
        if bm25_results and not vector_results:
            return bm25_results[:k]
        scores: dict[str, float] = {}
        active_tracks = int(bool(vector_results)) + int(bool(bm25_results))
        for rank, (chunk_id, _) in enumerate(vector_results):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
        for rank, (chunk_id, _) in enumerate(bm25_results):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
        normalizer = active_tracks * (1.0 / (rrf_k + 1)) if active_tracks else 1.0
        ranked = sorted(
            ((chunk_id, score / normalizer) for chunk_id, score in scores.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:k]

    @staticmethod
    def _text_to_simple_vector(text: str) -> list[float]:
        """Very simple bag-of-characters vector for testing fallback."""
        import math

        vec = [0.0] * 256
        for ch in text.lower():
            idx = ord(ch) % 256
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        import math

        if len(a) != len(b):
            min_len = min(len(a), len(b))
            a = a[:min_len]
            b = b[:min_len]
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
