from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.services.llm.rate_limiter import RedisTokenBucket


class DashScopeRateLimitError(RuntimeError):
    """DashScope 返回 429/限流时抛出。"""


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
        if self._uses_multimodal_embedding_endpoint():
            return await self._embed_multimodal_batch(inputs)
        response = await self._client.post(
            "/embeddings",
            json={
                "model": self.settings.dashscope_embedding_model,
                "input": list(inputs),
                "dimensions": self.settings.dashscope_embedding_dimension,
            },
        )
        if response.status_code == 429:
            model = self.settings.dashscope_embedding_model
            raise DashScopeRateLimitError(f"DashScope embedding rate limited (model={model})")
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

    async def _embed_multimodal_batch(self, inputs: Sequence[str]) -> list[list[float]]:
        url = (
            self.settings.dashscope_native_base_url.rstrip("/")
            + "/services/embeddings/multimodal-embedding/multimodal-embedding"
        )
        response = await self._client.post(
            url,
            json={
                "model": self.settings.dashscope_embedding_model,
                "input": {"contents": [{"text": text} for text in inputs]},
                "parameters": {"dimension": self.settings.dashscope_embedding_dimension},
            },
        )
        if response.status_code == 429:
            model = self.settings.dashscope_embedding_model
            raise DashScopeRateLimitError(f"DashScope embedding rate limited (model={model})")
        response.raise_for_status()
        body = response.json()
        output = body.get("output")
        rows = output.get("embeddings") if isinstance(output, dict) else None
        if not isinstance(rows, list):
            raise ValueError("DashScope multimodal embedding 响应缺少 output.embeddings")
        embeddings: list[list[float]] = []
        for row in rows:
            embedding = row.get("embedding") if isinstance(row, dict) else None
            if not isinstance(embedding, list):
                raise ValueError("DashScope multimodal embedding 响应格式不正确")
            embeddings.append([float(value) for value in embedding])
        return embeddings

    def _uses_multimodal_embedding_endpoint(self) -> bool:
        model = self.settings.dashscope_embedding_model.lower()
        return "vl-embedding" in model or model.startswith("multimodal-embedding")

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        chosen = model or self.settings.dashscope_chat_model
        await self._rate_limiter.acquire(chosen, tokens=1)
        try:
            async with self._client.stream(
                "POST",
                "/chat/completions",
                json={
                    "model": chosen,
                    "messages": messages,
                    "stream": True,
                },
            ) as response:
                if response.status_code == 429:
                    raise DashScopeRateLimitError(f"DashScope rate limited (model={chosen})")
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            break
                        delta = _extract_stream_delta(payload)
                        if delta:
                            yield delta
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise DashScopeRateLimitError(str(exc)) from exc
            raise


def _extract_stream_delta(payload: str) -> str:
    try:
        body = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""
