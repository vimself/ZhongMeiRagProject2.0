from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.services.llm.client import DashScopeClient
from app.services.rag.vector_utils import clean_display_text

DEFAULT_RERANK_INSTRUCT = (
    "Given an engineering question, retrieve passages that directly answer the query "
    "with precise factual details."
)
MAX_RERANK_DOCUMENT_CHARS = 3500


async def rerank_results(
    query: str,
    results: list[Any],
    *,
    top_n: int | None = None,
) -> list[Any]:
    settings = get_settings()
    if (
        not settings.rag_rerank_enabled
        or settings.app_env == "test"
        or settings.dashscope_api_key is None
        or len(results) < 2
        or not query.strip()
    ):
        return results[:top_n] if top_n is not None else list(results)

    documents = [_document_text(item) for item in results]
    if sum(bool(document) for document in documents) < 2:
        return results[:top_n] if top_n is not None else list(results)

    try:
        async with DashScopeClient() as client:
            rankings = await client.rerank_documents(
                query,
                documents,
                model=settings.dashscope_rerank_model,
                top_n=top_n,
                instruct=DEFAULT_RERANK_INSTRUCT,
            )
    except Exception:
        return results[:top_n] if top_n is not None else list(results)

    ranked_items: list[Any] = []
    used_indexes: set[int] = set()
    for index, _score in rankings:
        if index < 0 or index >= len(results) or index in used_indexes:
            continue
        ranked_items.append(results[index])
        used_indexes.add(index)

    if len(used_indexes) < len(results):
        leftovers = [results[index] for index in range(len(results)) if index not in used_indexes]
        ranked_items.extend(leftovers)

    return ranked_items[:top_n] if top_n is not None else ranked_items


def _document_text(item: Any) -> str:
    raw = getattr(item, "section_text", "") or getattr(item, "snippet", "")
    text = clean_display_text(str(raw))
    if len(text) <= MAX_RERANK_DOCUMENT_CHARS:
        return text
    return text[:MAX_RERANK_DOCUMENT_CHARS].rstrip() + "..."
