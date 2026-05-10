from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.services.llm.rate_limiter import RedisTokenBucket


class DashScopeClient:
    """DashScope OpenAI 兼容接口客户端。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        rate_limiter: RedisTokenBucket | None = None,
    ) -> None:
        settings = get_settings()
        if settings.dashscope_api_key is None:
            raise RuntimeError("DASHSCOPE_API_KEY 未配置")
        self.settings = settings
        self._owns_client = client is None
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        self._client = client or httpx.AsyncClient(
            base_url=settings.dashscope_base_url.rstrip("/"),
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0),
            headers=headers,
        )
        self._rate_limiter = rate_limiter or RedisTokenBucket()

    async def __aenter__(self) -> DashScopeClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def embed_batch(self, inputs: Sequence[str]) -> list[list[float]]:
        await self._rate_limiter.acquire(self.settings.dashscope_embedding_model, tokens=1)
        response = await self._client.post(
            "/embeddings",
            json={"model": self.settings.dashscope_embedding_model, "input": list(inputs)},
        )
        response.raise_for_status()
        body = response.json()
        rows = body.get("data")
        if not isinstance(rows, list):
            raise ValueError("DashScope embedding 响应缺少 data")
        embeddings: list[list[float]] = []
        for row in rows:
            embedding = row.get("embedding") if isinstance(row, dict) else None
            if not isinstance(embedding, list):
                raise ValueError("DashScope embedding 响应格式不正确")
            embeddings.append([float(value) for value in embedding])
        return embeddings

    async def stream_chat(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        await self._rate_limiter.acquire(self.settings.dashscope_chat_model, tokens=1)
        async with self._client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": self.settings.dashscope_chat_model,
                "messages": messages,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    yield payload
