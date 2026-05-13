from __future__ import annotations

from app.core.config import get_settings
from app.services.llm.client import DashScopeClient


async def get_query_embedding(query: str) -> list[float] | None:
    settings = get_settings()
    if settings.app_env == "test":
        return None
    try:
        async with DashScopeClient() as client:
            embeddings = await client.embed_batch([query])
    except Exception:
        return None
    return embeddings[0] if embeddings else None
