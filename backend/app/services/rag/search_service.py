from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.document import Document, KnowledgeChunkV2
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.services.rag.retriever import RetrievalResult, Retriever
from app.services.rag.vector_utils import text_term_weights


class SearchService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_accessible_kb_ids(self, user: User) -> list[str]:
        if user.role == "admin":
            result = await self.db.execute(
                select(KnowledgeBase.id).where(KnowledgeBase.is_active.is_(True))
            )
            return [row[0] for row in result.all()]
        result = await self.db.execute(
            select(KnowledgeBasePermission.knowledge_base_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeBasePermission.knowledge_base_id)
            .where(
                KnowledgeBasePermission.user_id == user.id,
                KnowledgeBase.is_active.is_(True),
            )
        )
        return [row[0] for row in result.all()]

    async def search(
        self,
        *,
        user: User,
        query: str,
        kb_id: str | None = None,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "relevance",
        query_vector: list[float] | None = None,
    ) -> tuple[list[RetrievalResult], int]:
        accessible_ids = await self.get_accessible_kb_ids(user)
        if not accessible_ids:
            return [], 0

        if kb_id:
            if kb_id not in accessible_ids:
                return [], 0
            target_kb_ids = [kb_id]
        else:
            target_kb_ids = accessible_ids

        retriever = Retriever(self.db)
        all_results: list[RetrievalResult] = []
        # AsyncSession is not concurrency-safe; keep these calls sequential within
        # the request session and cap each KB at the retriever's existing 5000 rows.
        for kb in target_kb_ids:
            results = await retriever.retrieve(
                kb_id=kb,
                query=query,
                k=5000,
                filters=filters,
                query_vector=query_vector,
            )
            all_results.extend(results)

        all_results = await self._filter_visible_documents(all_results, filters or {})

        if sort_by == "date":
            doc_meta = await self._load_doc_metadata({r.document_id for r in all_results})
            all_results.sort(
                key=lambda r: doc_meta.get(r.document_id, {}).get("created_at", ""),
                reverse=True,
            )
        else:
            all_results.sort(key=lambda r: r.score, reverse=True)

        total = len(all_results)
        offset = (page - 1) * page_size
        page_results = all_results[offset : offset + page_size]
        return page_results, total

    async def _filter_visible_documents(
        self,
        results: list[RetrievalResult],
        filters: dict[str, Any],
    ) -> list[RetrievalResult]:
        if not results:
            return []
        doc_meta = await self._load_doc_metadata({r.document_id for r in results})
        date_from = filters.get("date_from")
        date_to = filters.get("date_to")
        filtered: list[RetrievalResult] = []
        for result in results:
            meta = doc_meta.get(result.document_id)
            if not meta or meta.get("status") == "disabled":
                continue
            created = meta.get("created_at", "")
            if isinstance(date_from, str) and date_from and created < date_from:
                continue
            if isinstance(date_to, str) and date_to and created > f"{date_to}T23:59:59":
                continue
            filtered.append(result)
        return filtered

    async def _load_doc_metadata(self, doc_ids: set[str]) -> dict[str, dict[str, str]]:
        if not doc_ids:
            return {}
        result = await self.db.execute(
            select(Document.id, Document.created_at, Document.status).where(
                Document.id.in_(doc_ids)
            )
        )
        metadata: dict[str, dict[str, str]] = {}
        for row in result.all():
            dt = row[1]
            created_at = dt.isoformat() if isinstance(dt, datetime) else str(dt or "")
            metadata[row[0]] = {"created_at": created_at, "status": str(row[2] or "")}
        return metadata

    async def hot_keywords(self, user: User, limit: int = 20) -> list[tuple[str, int]]:
        accessible_ids = await self.get_accessible_kb_ids(user)
        if not accessible_ids:
            return []

        result = await self.db.execute(
            select(KnowledgeChunkV2.content)
            .where(KnowledgeChunkV2.knowledge_base_id.in_(accessible_ids))
            .limit(5000)
        )
        counter: Counter[str] = Counter()
        for row in result.all():
            weights = text_term_weights(row[0])
            for token, weight in weights.items():
                if len(token) >= 2:
                    counter[token] += int(weight)

        return counter.most_common(limit)

    async def doc_types(self, user: User) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        accessible_ids = await self.get_accessible_kb_ids(user)
        if not accessible_ids:
            return [], []

        kind_result = await self.db.execute(
            select(Document.doc_kind, func.count())
            .where(
                Document.knowledge_base_id.in_(accessible_ids),
                Document.status != "disabled",
            )
            .group_by(Document.doc_kind)
        )
        doc_kinds = [(row[0] or "other", row[1]) for row in kind_result.all()]

        scheme_result = await self.db.execute(
            select(Document.scheme_type, func.count())
            .where(
                Document.knowledge_base_id.in_(accessible_ids),
                Document.status != "disabled",
                Document.scheme_type.isnot(None),
                Document.scheme_type != "",
            )
            .group_by(Document.scheme_type)
        )
        scheme_types = [(row[0], row[1]) for row in scheme_result.all()]

        return doc_kinds, scheme_types
