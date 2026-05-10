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
from app.services.llm.client import DashScopeClient, DashScopeRateLimitError
from app.services.rag.citations import CitationMeta, build_reference_payload
from app.services.rag.retriever import RetrievalResult, Retriever

CITE_PATTERN = re.compile(r"\[cite:(\d+)\]")


@dataclass
class RagState:
    """RAG 节点间传递的不可变状态（dataclass 便于重放 / 序列化）。"""

    kb_id: str
    raw_query: str
    user_id: str
    filters: dict[str, Any] = field(default_factory=dict)
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


# ---------- Node: retrieve_track_a / retrieve_track_b ----------


async def retrieve_track_a(
    state: RagState,
    retriever: Retriever,
    *,
    query_vector: list[float] | None,
) -> RagState:
    """向量召回。直接复用 Retriever 的 fallback 实现，单测在 SQLite 下稳定。"""
    if query_vector and retriever._can_use_seekdb_native():  # noqa: SLF001
        try:
            state.track_a = await retriever._seekdb_vector_search(  # noqa: SLF001
                state.kb_id, query_vector, state.filters, k=state.k * 2
            )
            return state
        except Exception:
            state.track_a = []
    chunks = await retriever._load_chunks(state.kb_id, state.filters)  # noqa: SLF001
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
    if retriever._can_use_seekdb_native():  # noqa: SLF001
        try:
            state.track_b = await retriever._seekdb_lexical_search(  # noqa: SLF001
                state.kb_id,
                state.planned_query or state.raw_query,
                state.filters,
                k=state.k * 2,
            )
            return state
        except Exception:
            state.track_b = []
    chunks = await retriever._load_chunks(state.kb_id, state.filters)  # noqa: SLF001
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


async def _default_llm_stream(
    messages: list[dict[str, Any]],
    model: str | None,
) -> AsyncIterator[str]:
    async with DashScopeClient() as client:
        async for chunk in client.stream_chat(messages, model=model):
            yield chunk


def build_prompt(state: RagState) -> list[dict[str, Any]]:
    context_lines: list[str] = []
    for meta in state.citations:
        section = " > ".join(meta.section_path) if meta.section_path else "(无章节)"
        context_lines.append(
            f"[cite:{meta.index}] 文档《{meta.document_title or meta.document_id}》"
            f" | 章节: {section} | 页: {meta.page_start or '?'}\n{meta.snippet}"
        )
    context_block = "\n\n".join(context_lines) if context_lines else "(无检索结果)"
    system_prompt = (
        "你是一名严谨的工程文档助理。请仅依据提供的检索上下文回答用户问题，"
        "每一个来自上下文的结论都必须以形如 [cite:编号] 的占位符在句尾标出引用。"
        "编号严格对应上下文前缀的 [cite:N]。"
        "若上下文不足以回答，请明确回复“无法在知识库中找到依据”，不要编造。"
        "使用简洁中文，不要输出 Markdown 代码块之外的标题或列表符号。"
    )
    user_prompt = (
        f"## 检索上下文\n{context_block}\n\n"
        f"## 用户问题\n{state.raw_query}\n\n"
        "请基于上下文作答，每条结论都附 [cite:编号]。"
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

    输出原始文本（含 [cite:i] 占位），由 rewrite_citations 统一改写为 ^[n]。
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


async def fallback_no_hit_stream() -> AsyncIterator[str]:
    """无命中兜底：单一 delta。"""
    yield get_settings().chat_no_hit_message


# ---------- Node: rewrite_citations ----------


def rewrite_citations(text: str, state: RagState) -> str:
    """将 [cite:i] 替换为 ^[n]；丢弃越界角标。"""
    valid_indexes = {c.index for c in state.citations}

    def _replace(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if idx not in valid_indexes:
            return ""
        return f"^[{idx}]"

    rewritten = CITE_PATTERN.sub(_replace, text)
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
    user_id: str,
    query: str,
    filters: dict[str, Any] | None = None,
    k: int | None = None,
    query_vector: list[float] | None = None,
) -> RagState:
    """执行 plan → retrieve_a/b → rrf → materialize → dedupe → should_answer。"""
    settings = get_settings()
    state = RagState(
        kb_id=kb_id,
        raw_query=query,
        user_id=user_id,
        filters=filters or {},
        k=k or settings.chat_topk,
    )
    plan_query(state)
    retriever = Retriever(db)
    await retrieve_track_a(state, retriever, query_vector=query_vector)
    await retrieve_track_b(state, retriever)
    rrf_fusion(state)
    await materialize_candidates(state, retriever)
    dedupe_citations(state)
    should_answer(state, min_score=settings.chat_min_score_threshold)
    return state


def build_reference_payloads(state: RagState) -> list[dict[str, Any]]:
    return [build_reference_payload(meta, user_id=state.user_id) for meta in state.citations]
