"""Stage 7 RAG 问答链路：节点化 pipeline。

本文件用手写 async 节点替代 LangGraph 运行时，保证：
- 每个节点是纯函数或仅依赖注入的 collaborator，便于单测 / 重放；
- 预留 LangGraph 适配点（各节点函数可直接挂到 StateGraph 的 add_node）；
- 运行时不引入 langgraph 依赖（按用户决策，Stage 10 可平滑切换）。

节点：plan_query / retrieve_track_a / retrieve_track_b / rrf_fusion /
dedupe_citations / should_answer / generate_stream / rewrite_citations / persist
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.chat import ChatMessage, ChatMessageCitation, ChatSession
from app.services.llm.client import ChatStreamDelta, DashScopeClient, DashScopeRateLimitError
from app.services.rag.citations import CitationMeta, build_reference_payload
from app.services.rag.reranker import rerank_results
from app.services.rag.retriever import RetrievalResult, Retriever
from app.services.rag.vector_utils import clean_display_text

CITE_PATTERN = re.compile(r"\[cite:(\d+)\]")
HISTORY_REWRITE_MAX_MESSAGES = 6
HISTORY_REWRITE_MAX_CHARS = 400
GENERATION_HISTORY_MAX_MESSAGES = 6
GENERATION_HISTORY_MAX_CHARS = 240


@dataclass
class RagState:
    """RAG 节点间传递的不可变状态（dataclass 便于重放 / 序列化）。"""

    kb_id: str
    raw_query: str
    user_id: str
    kb_ids: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    k: int = 6
    planned_query: str = ""
    track_a: list[tuple[str, float]] = field(default_factory=list)  # (chunk_id, score)
    track_b: list[tuple[str, float]] = field(default_factory=list)
    fused: list[tuple[str, float]] = field(default_factory=list)
    candidates: list[RetrievalResult] = field(default_factory=list)
    citations: list[CitationMeta] = field(default_factory=list)
    has_hit: bool = False
    answer_raw: str = ""
    answer_rewritten: str = ""
    model_used: str = ""
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


# ---------- Node: plan_query ----------


def plan_query(state: RagState) -> RagState:
    """Light-weight planner: 去除首尾空白并做简单归一化。

    预留对 LLM 改写 / 意图识别的扩展点。当前保持 LLM-free，单测稳定。
    """
    cleaned = (state.raw_query or "").strip()
    state.planned_query = cleaned
    return state


def _format_history_messages(
    history: list[dict[str, str]],
    *,
    limit: int,
    max_chars: int,
) -> str:
    rows: list[str] = []
    for item in history[-limit:]:
        role = str(item.get("role", "")).strip().lower()
        content = clean_display_text(str(item.get("content", "")))
        if not content:
            continue
        if len(content) > max_chars:
            content = content[:max_chars].rstrip() + "..."
        if role == "user":
            rows.append(f"用户: {content}")
        elif role == "assistant":
            rows.append(f"助手: {content}")
    return "\n".join(rows)


async def contextualize_query(state: RagState) -> RagState:
    if not state.history or not state.planned_query:
        return state
    history_block = _format_history_messages(
        state.history,
        limit=HISTORY_REWRITE_MAX_MESSAGES,
        max_chars=HISTORY_REWRITE_MAX_CHARS,
    )
    if not history_block:
        return state
    messages = [
        {
            "role": "system",
            "content": (
                "你是 RAG 检索查询改写器。请结合最近对话，把最后一个用户问题改写为可直接"
                "检索的独立问题。必须保留人名、文档名、设备名、标准号、章节号、时间、数字、"
                "单位和否定约束。若原问题已经完整独立，则原样返回。只输出一行改写后的问题，"
                "不要解释。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"## 最近对话\n{history_block}\n\n"
                f"## 最后一个用户问题\n{state.planned_query}\n\n"
                "请输出独立检索问题。"
            ),
        },
    ]
    try:
        async with DashScopeClient() as client:
            rewritten = await client.complete_chat(messages, enable_thinking=False)
    except Exception:
        return state
    rewritten = clean_display_text(rewritten)
    if rewritten:
        state.planned_query = rewritten[:4000]
    return state


# ---------- Node: retrieve_track_a / retrieve_track_b ----------


async def retrieve_track_a(
    state: RagState,
    retriever: Retriever,
    *,
    query_vector: list[float] | None,
) -> RagState:
    """向量召回。直接复用 Retriever 的 fallback 实现，单测在 SQLite 下稳定。"""
    kb_scope = state.kb_ids or [state.kb_id]
    if query_vector and retriever._can_use_seekdb_native():  # noqa: SLF001
        try:
            state.track_a = await retriever._seekdb_vector_search(  # noqa: SLF001
                kb_scope, query_vector, state.filters, k=state.k * 2
            )
            return state
        except Exception:
            state.track_a = []
    chunks = await retriever._load_chunks(kb_scope, state.filters)  # noqa: SLF001
    if not chunks:
        state.track_a = []
        return state
    # 若上游提供真实向量（SeekDB 原生 path 可用），优先使用；否则 fallback 到字符向量。
    if query_vector:
        # Python 侧点积；仅用于真实 DashScope 出现的场景
        scored: list[tuple[str, float]] = []
        import math

        for chunk in chunks:
            vec = chunk.vector
            if not isinstance(vec, list) or not vec:
                continue
            dot = sum(x * y for x, y in zip(query_vector, vec, strict=False))
            norm_q = math.sqrt(sum(x * x for x in query_vector)) or 1.0
            norm_v = math.sqrt(sum(x * x for x in vec)) or 1.0
            sim = dot / (norm_q * norm_v)
            if sim > 0:
                scored.append((chunk.id, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        state.track_a = scored[: state.k * 2]
        return state
    state.track_a = retriever._vector_search(  # noqa: SLF001
        chunks, state.planned_query or state.raw_query, k=state.k * 2
    )
    return state


async def retrieve_track_b(state: RagState, retriever: Retriever) -> RagState:
    """页级 BM25 / 词频召回。"""
    kb_scope = state.kb_ids or [state.kb_id]
    if retriever._can_use_seekdb_native():  # noqa: SLF001
        try:
            state.track_b = await retriever._seekdb_lexical_search(  # noqa: SLF001
                kb_scope,
                state.planned_query or state.raw_query,
                state.filters,
                k=state.k * 2,
            )
            return state
        except Exception:
            state.track_b = []
    chunks = await retriever._load_chunks(kb_scope, state.filters)  # noqa: SLF001
    state.track_b = retriever._bm25_search(  # noqa: SLF001
        chunks, state.planned_query or state.raw_query, k=state.k * 2
    )
    return state


# ---------- Node: rrf_fusion ----------


def rrf_fusion(state: RagState, *, rrf_k: int = 60) -> RagState:
    scores: dict[str, float] = {}
    active_tracks = int(bool(state.track_a)) + int(bool(state.track_b))
    for rank, (chunk_id, _) in enumerate(state.track_a):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
    for rank, (chunk_id, _) in enumerate(state.track_b):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
    normalizer = active_tracks * (1.0 / (rrf_k + 1)) if active_tracks else 1.0
    ranked = sorted(
        ((chunk_id, score / normalizer) for chunk_id, score in scores.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    state.fused = ranked[: state.k * 2]
    return state


# ---------- Node: materialize candidates via retriever ----------


async def materialize_candidates(state: RagState, retriever: Retriever) -> RagState:
    """将 fused 的 chunk_id 转换为 RetrievalResult（用于 dedupe + citation 构建）。"""
    if not state.fused:
        state.candidates = []
        return state
    chunk_ids = [cid for cid, _ in state.fused]
    score_map = dict(state.fused)
    chunks = await retriever._load_chunks_by_ids(chunk_ids)  # noqa: SLF001
    doc_titles = await retriever._load_doc_titles({c.document_id for c in chunks})  # noqa: SLF001
    results: list[RetrievalResult] = []
    for chunk in chunks:
        content = chunk.content or ""
        snippet = content[:200] if len(content) > 200 else content
        results.append(
            RetrievalResult(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=doc_titles.get(chunk.document_id, ""),
                knowledge_base_id=chunk.knowledge_base_id,
                section_path=list(chunk.section_path or []),
                section_text=content,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                bbox=chunk.bbox_json,
                snippet=snippet,
                score=float(score_map.get(chunk.id, 0.0)),
            )
        )
    results.sort(key=lambda r: r.score, reverse=True)
    state.candidates = results
    return state


async def rerank_candidates(state: RagState) -> RagState:
    settings = get_settings()
    state.candidates = await rerank_results(
        state.planned_query or state.raw_query,
        state.candidates,
        top_n=max(state.k * 2, settings.rag_rerank_max_candidates),
    )
    return state


# ---------- Node: dedupe_citations ----------


def dedupe_citations(state: RagState) -> RagState:
    """按 (document_id, section_path, page_start) 去重并保留最高分。"""
    seen: dict[tuple[str, str, int | None], RetrievalResult] = {}
    for r in state.candidates:
        key = (r.document_id, "/".join(r.section_path or []), r.page_start)
        kept = seen.get(key)
        if kept is None or r.score > kept.score:
            seen[key] = r
    unique = sorted(seen.values(), key=lambda r: r.score, reverse=True)[: state.k]
    metas: list[CitationMeta] = []
    for idx, r in enumerate(unique, start=1):
        metas.append(
            CitationMeta(
                index=idx,
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_title=r.document_title,
                knowledge_base_id=r.knowledge_base_id,
                section_path=list(r.section_path or []),
                section_text=r.section_text,
                page_start=r.page_start,
                page_end=r.page_end,
                bbox=r.bbox,
                snippet=r.snippet,
                score=r.score,
            )
        )
    state.citations = metas
    return state


# ---------- Node: should_answer ----------


def should_answer(state: RagState, *, min_score: float = 0.0) -> bool:
    if not state.citations:
        state.has_hit = False
        return False
    top = max(c.score for c in state.citations)
    state.has_hit = top >= min_score
    return state.has_hit


# ---------- Node: generate_stream ----------


LlmStreamFactory = Callable[[list[dict[str, Any]], str | None], AsyncIterator[str]]
LlmEventStreamFactory = Callable[[list[dict[str, Any]], str | None], AsyncIterator[ChatStreamDelta]]


async def _default_llm_stream(
    messages: list[dict[str, Any]],
    model: str | None,
) -> AsyncIterator[str]:
    async with DashScopeClient() as client:
        async for chunk in client.stream_chat(messages, model=model):
            yield chunk


async def _default_llm_event_stream(
    messages: list[dict[str, Any]],
    model: str | None,
) -> AsyncIterator[ChatStreamDelta]:
    async with DashScopeClient() as client:
        async for event in client.stream_chat_events(messages, model=model):
            yield event


def build_prompt(state: RagState) -> list[dict[str, Any]]:
    context_lines: list[str] = []
    for meta in state.citations:
        section = " > ".join(meta.section_path) if meta.section_path else "(无章节)"
        context_text = clean_display_text(meta.section_text or meta.snippet)
        if not context_text:
            context_text = meta.snippet
        context_lines.append(
            f"[cite:{meta.index}] 文档《{meta.document_title or meta.document_id}》"
            f" | 章节: {section} | 页: {meta.page_start or '?'}\n{context_text}"
        )
    context_block = "\n\n".join(context_lines) if context_lines else "(无检索结果)"
    history_block = _format_history_messages(
        state.history,
        limit=GENERATION_HISTORY_MAX_MESSAGES,
        max_chars=GENERATION_HISTORY_MAX_CHARS,
    )
    history_section = f"## 最近对话\n{history_block}\n\n" if history_block else ""
    system_prompt = (
        "You are a careful engineering document assistant. Answer in concise Chinese. "
        "Use only the retrieved context; do not invent facts. "
        "Use clean Markdown only when it improves readability: short paragraphs, bullets, "
        "or compact tables are allowed. "
        "Do not output citation markers, footnotes, [cite:N], ^[N], reference lists, "
        "or a section named '引用依据'/'引用内容'; the application shows sources separately. "
        "Rewrite OCR or LaTeX-like fragments into plain user-facing Chinese. For example, "
        "write '$5^{\\circ}C \\sim 35^{\\circ}C$' as '5°C 至 35°C'. "
        "If the context is insufficient, say '无法在知识库中找到依据'. "
        "Do not output code blocks unless the user explicitly asks for code."
    )
    user_prompt = (
        f"## 检索上下文\n{context_block}\n\n"
        f"{history_section}"
        f"## 用户问题\n{state.raw_query}\n\n"
        "请基于上下文作答。先直接回答结论，再补充必要的要点或表格。"
        "不要把检索上下文原样复制给用户，不要输出引用编号或参考文档清单。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def generate_stream(
    state: RagState,
    *,
    stream_factory: LlmStreamFactory | None = None,
) -> AsyncIterator[str]:
    """按 state.citations 生成答案流；429 自动降级到 fallback 模型；两次都失败时抛出。

    输出原始文本，调用方会通过 rewrite_citations 移除模型误出的引用角标。
    调用方负责在生成结束后累积到 state.answer_raw。
    """
    settings = get_settings()
    factory: LlmStreamFactory = stream_factory or _default_llm_stream
    messages = build_prompt(state)
    chosen = settings.dashscope_chat_model
    try:
        async for chunk in factory(messages, chosen):
            state.model_used = chosen
            yield chunk
        state.finish_reason = "stop"
        return
    except DashScopeRateLimitError:
        pass
    fallback = settings.dashscope_chat_model_fallback
    async for chunk in factory(messages, fallback):
        state.model_used = fallback
        yield chunk
    state.finish_reason = "stop"


async def generate_stream_events(
    state: RagState,
    *,
    stream_factory: LlmEventStreamFactory | None = None,
) -> AsyncIterator[ChatStreamDelta]:
    settings = get_settings()
    factory: LlmEventStreamFactory = stream_factory or _default_llm_event_stream
    messages = build_prompt(state)
    chosen = settings.dashscope_chat_model
    try:
        async for event in factory(messages, chosen):
            state.model_used = chosen
            if isinstance(event, str):
                yield ChatStreamDelta(kind="content", delta=event)
                continue
            yield event
        state.finish_reason = "stop"
        return
    except DashScopeRateLimitError:
        pass
    fallback = settings.dashscope_chat_model_fallback
    async for event in factory(messages, fallback):
        state.model_used = fallback
        if isinstance(event, str):
            yield ChatStreamDelta(kind="content", delta=event)
            continue
        yield event
    state.finish_reason = "stop"


async def fallback_no_hit_stream() -> AsyncIterator[str]:
    """无命中兜底：单一 delta。"""
    yield get_settings().chat_no_hit_message


# ---------- Node: rewrite_citations ----------


def rewrite_citations(text: str, state: RagState) -> str:
    """移除模型输出中的引用角标；引用由前端证据面板和参考文档区展示。"""
    rewritten = CITE_PATTERN.sub("", text)
    rewritten = re.sub(r"\^\[\d+\]|\[\^\d+\]", "", rewritten)
    return rewritten


# ---------- Node: persist ----------


async def persist(
    db: AsyncSession,
    *,
    session: ChatSession,
    user_message: str,
    state: RagState,
) -> tuple[ChatMessage, ChatMessage]:
    """落库 user 消息 + assistant 消息 + 引用稳定元数据。"""
    user_msg = ChatMessage(session_id=session.id, role="user", content=user_message)
    assistant_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=state.answer_rewritten or state.answer_raw,
        finish_reason=state.finish_reason,
        model=state.model_used or None,
        usage_json=state.usage or None,
    )
    db.add(user_msg)
    db.add(assistant_msg)
    await db.flush()
    for meta in state.citations:
        db.add(
            ChatMessageCitation(
                message_id=assistant_msg.id,
                index=meta.index,
                document_id=meta.document_id,
                knowledge_base_id=meta.knowledge_base_id,
                chunk_id=meta.chunk_id,
                document_title=meta.document_title,
                section_path_json=list(meta.section_path),
                section_text=meta.section_text,
                page_start=meta.page_start,
                page_end=meta.page_end,
                bbox_json=meta.bbox,
                snippet=meta.snippet,
                score=meta.score,
            )
        )
    await db.flush()
    return user_msg, assistant_msg


# ---------- Facade: 组合各节点的一次检索 + 构建引用 ----------


async def prepare_citations(
    db: AsyncSession,
    *,
    kb_id: str,
    kb_ids: list[str] | None = None,
    user_id: str,
    query: str,
    filters: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
    k: int | None = None,
    query_vector: list[float] | None = None,
) -> RagState:
    """执行 plan → retrieve_a/b → rrf → materialize → dedupe → should_answer。"""
    settings = get_settings()
    state = RagState(
        kb_id=kb_id,
        raw_query=query,
        user_id=user_id,
        kb_ids=kb_ids or [kb_id],
        filters=filters or {},
        history=history or [],
        k=k or settings.chat_topk,
    )
    plan_query(state)
    await contextualize_query(state)
    retriever = Retriever(db)
    await retrieve_track_a(state, retriever, query_vector=query_vector)
    await retrieve_track_b(state, retriever)
    rrf_fusion(state)
    await materialize_candidates(state, retriever)
    await rerank_candidates(state)
    dedupe_citations(state)
    should_answer(state, min_score=settings.chat_min_score_threshold)
    return state


def build_reference_payloads(state: RagState) -> list[dict[str, Any]]:
    return [build_reference_payload(meta, user_id=state.user_id) for meta in state.citations]
