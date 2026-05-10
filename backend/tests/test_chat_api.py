"""Stage 7 Chat SSE + sessions API 测试（mock DashScope + SQLite fallback）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.main import create_app
from app.models.auth import User
from app.models.document import Document, KnowledgeChunkV2
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.security.login_limiter import login_failure_limiter
from app.security.password import hash_password
from app.services.llm.client import DashScopeRateLimitError


@pytest.fixture(autouse=True)
def _reset() -> None:
    async def _inner() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        login_failure_limiter.clear_memory()

    asyncio.run(_inner())
    # 重置 sse_starlette 的 AppStatus 跨事件循环事件
    try:
        from sse_starlette.sse import AppStatus

        AppStatus.should_exit_event = None
    except Exception:  # pragma: no cover - 兼容不同版本
        pass


def _seed(*, with_permission: bool = True, with_chunk: bool = True) -> None:
    async def _inner() -> None:
        async with AsyncSessionLocal() as session:
            user = User(
                id="user-1",
                username="u",
                display_name="U",
                role="user",
                password_hash=hash_password("pass"),
            )
            other = User(
                id="user-2",
                username="u2",
                display_name="U2",
                role="user",
                password_hash=hash_password("pass"),
            )
            kb = KnowledgeBase(id="kb-1", name="KB", description="", creator_id=user.id)
            doc = Document(
                id="doc-1",
                knowledge_base_id=kb.id,
                uploader_id=user.id,
                title="施工方案总则",
                filename="a.pdf",
                mime="application/pdf",
                size_bytes=10,
                sha256="sha",
                storage_path="a.pdf",
            )
            rows: list[Any] = [user, other, kb, doc]
            if with_permission:
                rows.append(
                    KnowledgeBasePermission(knowledge_base_id=kb.id, user_id=user.id, role="viewer")
                )
            if with_chunk:
                rows.append(
                    KnowledgeChunkV2(
                        id="chunk-1",
                        knowledge_base_id=kb.id,
                        document_id=doc.id,
                        chunk_index=0,
                        content="施工现场必须落实安全生产责任制，监督员佩戴标识。",
                        section_path=["总则", "安全"],
                        section_id="s-1",
                        content_type="paragraph",
                        doc_kind="plan",
                        tokens=10,
                        sha256="sha-chunk",
                        page_start=3,
                        page_end=3,
                        bbox_json={"x": 1, "y": 2, "width": 3, "height": 4},
                    )
                )
            session.add_all(rows)
            await session.commit()

    asyncio.run(_inner())


def _login(client: TestClient, username: str = "u") -> str:
    resp = client.post("/api/v2/auth/login", json={"username": username, "password": "pass"})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _fake_llm_stream(messages: list[dict[str, Any]], model: str | None) -> AsyncIterator[str]:
    # Emit two deltas with [cite:1] placeholder
    yield "根据上下文，"
    yield "必须落实安全生产责任制[cite:1]。"


async def _fake_429_then_ok_factory_builder() -> Any:
    calls: list[str | None] = []

    async def factory(messages: list[dict[str, Any]], model: str | None) -> AsyncIterator[str]:
        calls.append(model)
        if len(calls) == 1:
            raise DashScopeRateLimitError("429")
        yield "fallback 返回[cite:1]。"

    return factory, calls


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    current_event = ""
    current_data: list[str] = []
    for line in text.splitlines():
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current_data.append(line.split(":", 1)[1].strip())
        elif line == "":
            if current_event and current_data:
                payload = "\n".join(current_data)
                try:
                    events.append((current_event, json.loads(payload)))
                except json.JSONDecodeError:
                    events.append((current_event, {"raw": payload}))
            current_event = ""
            current_data = []
    return events


def test_chat_stream_events_order_and_rewrite() -> None:
    _seed()

    async def _factory(messages: list[dict[str, Any]], model: str | None) -> AsyncIterator[str]:
        async for chunk in _fake_llm_stream(messages, model):
            yield chunk

    from app.core.config import get_settings

    get_settings().chat_min_score_threshold = 0.0
    with patch(
        "app.services.rag.graph._default_llm_stream",
        side_effect=lambda m, mo: _factory(m, mo),
    ):
        client = TestClient(create_app())
        token = _login(client)
        resp = client.post(
            "/api/v2/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"kb_id": "kb-1", "question": "施工 安全"},
        )
        assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)
    names = [e[0] for e in events]
    assert names[0] == "references"
    assert "content" in names
    assert names[-1] == "done"
    # 引用 payload 校验
    refs_payload = events[0][1]
    assert "session_id" in refs_payload
    assert refs_payload["references"], "应包含 references"
    ref0 = refs_payload["references"][0]
    for key in [
        "document_id",
        "document_title",
        "knowledge_base_id",
        "section_path",
        "section_text",
        "page_start",
        "page_end",
        "bbox",
        "snippet",
        "chunk_id",
        "score",
        "preview_url",
        "download_url",
    ]:
        assert key in ref0, f"引用 payload 缺少字段 {key}"
    # content 必须把 [cite:1] 改写成 ^[1]
    content_deltas = [e[1]["delta"] for e in events if e[0] == "content"]
    joined = "".join(content_deltas)
    assert "[cite:" not in joined
    assert "^[1]" in joined


def test_chat_stream_permission_denied() -> None:
    _seed(with_permission=False)
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/chat/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"kb_id": "kb-1", "question": "施工 安全"},
    )
    assert resp.status_code == 403


def test_chat_stream_no_hit_returns_fallback_message() -> None:
    _seed(with_chunk=False)
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/chat/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"kb_id": "kb-1", "question": "施工 安全"},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    content = "".join(e[1]["delta"] for e in events if e[0] == "content")
    assert "无法在知识库中找到依据" in content
    done = [e for e in events if e[0] == "done"][-1][1]
    assert done["finish_reason"] == "no_hit"


def test_chat_sessions_list_and_detail_resigns_tokens() -> None:
    _seed()

    async def _factory(messages: list[dict[str, Any]], model: str | None) -> AsyncIterator[str]:
        yield "回答[cite:1]。"

    from app.core.config import get_settings

    get_settings().chat_min_score_threshold = 0.0
    with patch(
        "app.services.rag.graph._default_llm_stream",
        side_effect=lambda m, mo: _factory(m, mo),
    ):
        client = TestClient(create_app())
        token = _login(client)
        stream_resp = client.post(
            "/api/v2/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"kb_id": "kb-1", "question": "施工 安全"},
        )
        assert stream_resp.status_code == 200
        events = _parse_sse(stream_resp.text)
        session_id = events[0][1]["session_id"]

    # 列表
    list_resp = client.get("/api/v2/chat/sessions", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert any(item["id"] == session_id for item in items)

    # 详情（历史引用需重新签发 token）
    detail = client.get(
        f"/api/v2/chat/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    msgs = detail["messages"]
    assistant = [m for m in msgs if m["role"] == "assistant"]
    assert assistant and assistant[0]["citations"], "应持久化 assistant 引用"
    cit = assistant[0]["citations"][0]
    assert "token=" in cit["preview_url"]
    assert "token=" in cit["download_url"]


def test_chat_session_detail_404_for_other_user() -> None:
    _seed()

    # 先让 user-1 建立会话
    async def _factory(messages: list[dict[str, Any]], model: str | None) -> AsyncIterator[str]:
        yield "answer[cite:1]."

    with patch(
        "app.services.rag.graph._default_llm_stream",
        side_effect=lambda m, mo: _factory(m, mo),
    ):
        client = TestClient(create_app())
        token1 = _login(client, "u")
        stream_resp = client.post(
            "/api/v2/chat/stream",
            headers={"Authorization": f"Bearer {token1}"},
            json={"kb_id": "kb-1", "question": "施工 安全"},
        )
        events = _parse_sse(stream_resp.text)
        session_id = events[0][1]["session_id"]

    token2 = _login(client, "u2")
    resp = client.get(
        f"/api/v2/chat/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert resp.status_code == 404
