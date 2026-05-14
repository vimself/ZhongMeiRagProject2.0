"""Stage 7 RAG graph 节点单测（SQLite fallback + mock DashScope）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models.auth import User
from app.models.document import Document, KnowledgeChunkV2
from app.models.knowledge_base import KnowledgeBase
from app.security.password import hash_password
from app.services.llm.client import (
    ChatStreamDelta,
    DashScopeClient,
    DashScopeRateLimitError,
    _extract_stream_delta,
    _extract_stream_deltas,
)
from app.services.rag import graph as rag_graph
from app.services.rag.citations import CitationMeta, build_reference_payload


@pytest.fixture(autouse=True)
def _reset_db() -> None:
    async def _reset() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_reset())


async def _seed() -> None:
    async with AsyncSessionLocal() as session:
        user = User(
            id="user-1",
            username="u",
            display_name="用户",
            role="admin",
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
        session.add_all([user, kb, doc])
        for idx, (content, section, page) in enumerate(
            [
                ("施工现场必须落实安全生产责任制。", "总则/安全", 3),
                ("施工方案应包含进度计划与人员配置。", "总则/进度", 5),
                ("原材料须经检验合格方可入场。", "材料", 7),
            ]
        ):
            session.add(
                KnowledgeChunkV2(
                    id=f"chunk-{idx}",
                    knowledge_base_id=kb.id,
                    document_id=doc.id,
                    chunk_index=idx,
                    content=content,
                    section_path=section.split("/"),
                    section_id=f"s-{idx}",
                    content_type="paragraph",
                    doc_kind="plan",
                    tokens=len(content),
                    sha256=f"sha-{idx}",
                    page_start=page,
                    page_end=page,
                    bbox_json={"x": 1, "y": 2, "width": 3, "height": 4},
                )
            )
        await session.commit()


def test_plan_query_trims_whitespace() -> None:
    state = rag_graph.RagState(kb_id="kb", raw_query="   施工安全   ", user_id="u")
    rag_graph.plan_query(state)
    assert state.planned_query == "施工安全"


def test_dashscope_stream_delta_parser_extracts_content() -> None:
    payload = '{"choices":[{"delta":{"content":"回答片段[cite:1]"}}]}'
    assert _extract_stream_delta(payload) == "回答片段[cite:1]"
    assert _extract_stream_delta('{"choices":[{"delta":{}}]}') == ""
    assert _extract_stream_delta('{"choices":[{"delta":{"reasoning_content":"thinking"}}]}') == ""
    events = _extract_stream_deltas('{"choices":[{"delta":{"reasoning_content":"thinking"}}]}')
    assert events == [ChatStreamDelta(kind="reasoning", delta="thinking")]


def test_dashscope_stream_chat_disables_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Limiter:
        async def acquire(self, *_args: object, **_kwargs: object) -> None:
            return None

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    settings = SimpleNamespace(
        dashscope_api_key=SecretStr("test-key"),
        dashscope_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dashscope_chat_model="qwen3.6-plus",
        dashscope_chat_enable_thinking=False,
    )
    monkeypatch.setattr("app.services.llm.client.get_settings", lambda: settings)

    async def _run() -> None:
        http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=settings.dashscope_base_url,
        )
        async with DashScopeClient(client=http_client, rate_limiter=_Limiter()) as client:  # type: ignore[arg-type]
            messages = [{"role": "user", "content": "q"}]
            chunks = [chunk async for chunk in client.stream_chat(messages)]
        assert chunks == ["ok"]

    asyncio.run(_run())
    assert captured["model"] == "qwen3.6-plus"
    assert captured["stream"] is True
    assert captured["enable_thinking"] is False


def test_rrf_fusion_merges_ranks() -> None:
    state = rag_graph.RagState(kb_id="kb", raw_query="q", user_id="u", k=2)
    state.track_a = [("a", 0.9), ("b", 0.5)]
    state.track_b = [("b", 0.8), ("c", 0.7)]
    rag_graph.rrf_fusion(state, rrf_k=60)
    ids = [cid for cid, _ in state.fused]
    assert "b" in ids and ids[0] == "b"


def test_dedupe_citations_keeps_unique_sections() -> None:
    state = rag_graph.RagState(kb_id="kb", raw_query="q", user_id="u", k=5)
    from app.services.rag.retriever import RetrievalResult

    state.candidates = [
        RetrievalResult(
            chunk_id="a",
            document_id="d1",
            document_title="t",
            knowledge_base_id="kb",
            section_path=["一"],
            section_text="x",
            page_start=1,
            page_end=1,
            bbox=None,
            snippet="s",
            score=0.9,
        ),
        RetrievalResult(
            chunk_id="b",
            document_id="d1",
            document_title="t",
            knowledge_base_id="kb",
            section_path=["一"],
            section_text="x",
            page_start=1,
            page_end=1,
            bbox=None,
            snippet="s2",
            score=0.5,
        ),
        RetrievalResult(
            chunk_id="c",
            document_id="d1",
            document_title="t",
            knowledge_base_id="kb",
            section_path=["二"],
            section_text="y",
            page_start=2,
            page_end=2,
            bbox=None,
            snippet="s3",
            score=0.7,
        ),
    ]
    rag_graph.dedupe_citations(state)
    assert [c.chunk_id for c in state.citations] == ["a", "c"]
    assert state.citations[0].index == 1 and state.citations[1].index == 2


def test_should_answer_below_threshold() -> None:
    state = rag_graph.RagState(kb_id="kb", raw_query="q", user_id="u")
    state.citations = [
        CitationMeta(
            index=1,
            chunk_id="c",
            document_id="d",
            document_title="t",
            knowledge_base_id="kb",
            section_path=[],
            section_text="",
            page_start=1,
            page_end=1,
            bbox=None,
            snippet="",
            score=0.001,
        )
    ]
    assert rag_graph.should_answer(state, min_score=0.5) is False
    assert state.has_hit is False


def test_rewrite_citations_discards_out_of_range() -> None:
    state = rag_graph.RagState(kb_id="kb", raw_query="q", user_id="u")
    state.citations = [
        CitationMeta(
            index=1,
            chunk_id=None,
            document_id="d",
            document_title="t",
            knowledge_base_id="kb",
            section_path=[],
            section_text="",
            page_start=None,
            page_end=None,
            bbox=None,
            snippet="",
            score=0.0,
        )
    ]
    text = "第一段[cite:1]。第二段[cite:9]。第三段^[1]。"
    assert rag_graph.rewrite_citations(text, state) == "第一段。第二段。第三段。"


def test_build_reference_payload_contains_urls() -> None:
    meta = CitationMeta(
        index=2,
        chunk_id="c",
        document_id="d-42",
        document_title="文档",
        knowledge_base_id="kb",
        section_path=["总则"],
        section_text="xxx",
        page_start=7,
        page_end=7,
        bbox={"x": 1, "y": 2, "width": 3, "height": 4},
        snippet="片段",
        score=0.5,
    )
    payload = build_reference_payload(meta, user_id="u-1")
    assert payload["document_id"] == "d-42"
    assert "/api/v2/pdf/preview" in payload["preview_url"]
    assert "token=" in payload["preview_url"]
    assert "#page=7" in payload["preview_url"]
    assert "bbox=1,2,3,4" in payload["preview_url"]
    assert "/api/v2/documents/d-42/download" in payload["download_url"]


def test_build_prompt_uses_full_section_text_not_snippet() -> None:
    state = rag_graph.RagState(kb_id="kb", raw_query="问题", user_id="u", k=1)
    state.citations = [
        CitationMeta(
            index=1,
            chunk_id="c",
            document_id="d",
            document_title="文档",
            knowledge_base_id="kb",
            section_path=["总则", "安全"],
            section_text="完整证据块，包含比 snippet 更多的约束条件与数值要求。",
            page_start=3,
            page_end=3,
            bbox=None,
            snippet="截断摘要",
            score=0.9,
        )
    ]
    prompt = rag_graph.build_prompt(state)
    assert "完整证据块" in prompt[1]["content"]
    assert "截断摘要" not in prompt[1]["content"]


def test_build_prompt_includes_recent_history() -> None:
    state = rag_graph.RagState(
        kb_id="kb",
        raw_query="那人员配置要求呢",
        user_id="u",
        history=[
            {"role": "user", "content": "先看施工组织总则"},
            {"role": "assistant", "content": "总则里提到了安全责任制。"},
        ],
        k=1,
    )
    state.citations = [
        CitationMeta(
            index=1,
            chunk_id="c",
            document_id="d",
            document_title="文档",
            knowledge_base_id="kb",
            section_path=["总则", "进度"],
            section_text="施工方案应包含进度计划与人员配置。",
            page_start=5,
            page_end=5,
            bbox=None,
            snippet="人员配置",
            score=0.8,
        )
    ]
    prompt = rag_graph.build_prompt(state)
    assert "## 最近对话" in prompt[1]["content"]
    assert "用户: 先看施工组织总则" in prompt[1]["content"]
    assert "助手: 总则里提到了安全责任制。" in prompt[1]["content"]


def test_contextualize_query_uses_recent_history(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_messages: list[dict[str, Any]] = []

    class FakeDashScopeClient:
        async def __aenter__(self) -> FakeDashScopeClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def complete_chat(
            self,
            messages: list[dict[str, Any]],
            *,
            model: str | None = None,
            enable_thinking: bool | None = None,
        ) -> str:
            captured_messages.extend(messages)
            assert model is None
            assert enable_thinking is False
            return "施工组织设计中关于人员配置的要求"

    monkeypatch.setattr(rag_graph, "DashScopeClient", FakeDashScopeClient)
    state = rag_graph.RagState(
        kb_id="kb",
        raw_query="那人员配置要求呢",
        user_id="u",
        history=[
            {"role": "user", "content": "先看施工组织总则"},
            {"role": "assistant", "content": "总则里提到了安全责任制。"},
        ],
    )
    rag_graph.plan_query(state)
    asyncio.run(rag_graph.contextualize_query(state))
    assert state.planned_query == "施工组织设计中关于人员配置的要求"
    assert any("最近对话" in message["content"] for message in captured_messages)
    assert any("那人员配置要求呢" in message["content"] for message in captured_messages)


def test_prepare_citations_sqlite_fallback_hits_chunks() -> None:
    async def _run() -> None:
        await _seed()
        async with AsyncSessionLocal() as db:
            state = await rag_graph.prepare_citations(
                db, kb_id="kb-1", user_id="user-1", query="施工 安全"
            )
        assert state.citations, "应至少命中一条 chunk"
        assert state.citations[0].document_title == "施工方案总则"
        assert state.citations[0].page_start == 3

    asyncio.run(_run())


def test_prepare_citations_can_search_multiple_kbs() -> None:
    async def _run() -> None:
        await _seed()
        async with AsyncSessionLocal() as db:
            kb2 = KnowledgeBase(id="kb-2", name="KB2", description="", creator_id="user-1")
            doc2 = Document(
                id="doc-2",
                knowledge_base_id=kb2.id,
                uploader_id="user-1",
                title="机电安装细则",
                filename="b.pdf",
                mime="application/pdf",
                size_bytes=10,
                sha256="sha-2",
                storage_path="b.pdf",
            )
            chunk2 = KnowledgeChunkV2(
                id="chunk-kb2",
                knowledge_base_id=kb2.id,
                document_id=doc2.id,
                chunk_index=0,
                content="机电安装必须完成接地连续性检查。",
                section_path=["机电", "接地"],
                section_id="s-kb2",
                content_type="paragraph",
                doc_kind="plan",
                tokens=10,
                sha256="sha-kb2",
                page_start=8,
                page_end=8,
            )
            db.add_all([kb2, doc2, chunk2])
            await db.commit()

            state = await rag_graph.prepare_citations(
                db,
                kb_id="__all__",
                kb_ids=["kb-1", "kb-2"],
                user_id="user-1",
                query="接地 连续性",
            )
        assert state.citations, "应能命中跨知识库 chunk"
        assert state.citations[0].knowledge_base_id == "kb-2"
        assert state.citations[0].document_title == "机电安装细则"

    asyncio.run(_run())


def test_generate_stream_falls_back_on_429() -> None:
    async def _run() -> None:
        state = rag_graph.RagState(kb_id="kb", raw_query="问题", user_id="u", k=1)
        state.citations = [
            CitationMeta(
                index=1,
                chunk_id="c",
                document_id="d",
                document_title="文档",
                knowledge_base_id="kb",
                section_path=["一"],
                section_text="文本",
                page_start=1,
                page_end=1,
                bbox=None,
                snippet="片段",
                score=0.9,
            )
        ]
        calls: list[str | None] = []

        async def _fake_stream(
            messages: list[dict[str, Any]], model: str | None
        ) -> AsyncIterator[str]:
            calls.append(model)
            if len(calls) == 1:
                raise DashScopeRateLimitError("429")
            yield "依据[cite:1]。"

        chunks: list[str] = []
        async for delta in rag_graph.generate_stream(state, stream_factory=_fake_stream):
            chunks.append(delta)
        assert chunks == ["依据[cite:1]。"]
        assert calls[0] and calls[1]
        assert calls[1] != calls[0]
        assert state.finish_reason == "stop"
        assert state.model_used == calls[1]

    asyncio.run(_run())


def test_fallback_no_hit_stream_uses_config_message() -> None:
    async def _run() -> None:
        out: list[str] = []
        async for chunk in rag_graph.fallback_no_hit_stream():
            out.append(chunk)
        assert out and "无法在知识库中找到依据" in out[0]

    asyncio.run(_run())
