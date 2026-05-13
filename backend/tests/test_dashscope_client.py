from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.services.llm.client import DashScopeClient, DashScopeRequestError


class FakeRateLimiter:
    async def acquire(self, _model: str, *, tokens: int = 1) -> None:
        return None


@pytest.fixture(autouse=True)
def configure_dashscope(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "dashscope_api_key", SecretStr("sk-test"))
    monkeypatch.setattr(settings, "dashscope_embedding_model", "qwen3-vl-embedding")
    monkeypatch.setattr(settings, "dashscope_embedding_dimension", 1024)
    monkeypatch.setattr(settings, "dashscope_native_base_url", "https://dashscope.test/api/v1")


@pytest.mark.asyncio
async def test_multimodal_embedding_splits_official_content_limit() -> None:
    batch_sizes: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content.decode("utf-8"))
        contents = body["input"]["contents"]
        batch_sizes.append(len(contents))
        rows = []
        for item in contents:
            index = int(item["text"].removeprefix("text-"))
            rows.append({"embedding": [float(index)]})
        return httpx.Response(200, json={"output": {"embeddings": rows}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = DashScopeClient(client=http, rate_limiter=FakeRateLimiter())
        embeddings = await client.embed_batch([f"text-{index}" for index in range(45)])

    assert batch_sizes == [20, 20, 5]
    assert embeddings == [[float(index)] for index in range(45)]


@pytest.mark.asyncio
async def test_multimodal_embedding_400_preserves_response_body_without_retry() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={
                "code": "InvalidParameter",
                "message": "batch size is invalid",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = DashScopeClient(client=http, rate_limiter=FakeRateLimiter())
        with pytest.raises(DashScopeRequestError) as exc_info:
            await client.embed_batch(["text"])

    assert calls == 1
    assert "HTTP 400" in str(exc_info.value)
    assert "batch size is invalid" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rerank_documents_uses_compatible_api_and_parses_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "dashscope_base_url",
        "https://dashscope.test/compatible-mode/v1",
    )
    captured_path: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_path.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.73},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = DashScopeClient(client=http, rate_limiter=FakeRateLimiter())
        rankings = await client.rerank_documents(
            "施工安全要求",
            ["第一段", "第二段"],
            model="qwen3-rerank",
            top_n=2,
        )

    assert captured_path == ["/compatible-api/v1/reranks"]
    assert rankings == [(1, 0.91), (0, 0.73)]


@pytest.mark.asyncio
async def test_complete_chat_uses_non_stream_mode_and_returns_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "dashscope_base_url",
        "https://dashscope.test/compatible-mode/v1",
    )
    captured_body: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "改写后的独立检索问题",
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=settings.dashscope_base_url,
    ) as http:
        client = DashScopeClient(client=http, rate_limiter=FakeRateLimiter())
        content = await client.complete_chat(
            [{"role": "user", "content": "那这个标准适用于哪里？"}],
            enable_thinking=False,
        )

    assert captured_body["stream"] is False
    assert captured_body["enable_thinking"] is False
    assert content == "改写后的独立检索问题"
