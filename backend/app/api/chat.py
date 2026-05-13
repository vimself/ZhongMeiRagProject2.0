"""Stage 7 RAG 聊天 API。"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.api.auth import _record_audit
from app.api.deps import DbSession, current_user
from app.api.knowledge_base_deps import _get_user_kb_role
from app.core.config import get_settings
from app.core.timezone import beijing_now, isoformat_beijing
from app.models.auth import User
from app.models.chat import ChatMessage, ChatMessageCitation, ChatSession
from app.models.knowledge_base import KnowledgeBase
from app.schemas.chat import (
    ChatCitationOut,
    ChatMessageOut,
    ChatSessionDetail,
    ChatSessionListResponse,
    ChatSessionSummary,
    ChatStreamRequest,
)
from app.services.llm.client import DashScopeClient
from app.services.rag.citations import CitationMeta, build_reference_payload
from app.services.rag.graph import (
    build_reference_payloads,
    fallback_no_hit_stream,
    generate_stream_events,
    prepare_citations,
    rewrite_citations,
)

router = APIRouter(prefix="/api/v2/chat", tags=["chat"])

CurrentUser = Annotated[User, Depends(current_user)]


async def _ensure_kb_viewer(db: Any, user: User, kb_id: str) -> KnowledgeBase:
    kb: KnowledgeBase | None = await db.get(KnowledgeBase, kb_id)
    if kb is None or not kb.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    if user.role != "admin":
        role = await _get_user_kb_role(db, user.id, kb.id)
        if role not in {"viewer", "editor", "owner"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="没有访问此知识库的权限",
            )
    return kb


def _iso(value: datetime | None) -> str:
    return isoformat_beijing(value)


def _is_no_evidence_answer(answer: str) -> bool:
    normalized = re.sub(r"\s+", "", answer or "")
    return any(
        phrase in normalized
        for phrase in (
            "无法在知识库中找到依据",
            "未在知识库中找到依据",
            "没有在知识库中找到依据",
        )
    )


def _summary(session: ChatSession, message_count: int) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=session.id,
        title=session.title,
        knowledge_base_id=session.knowledge_base_id,
        is_active=session.is_active,
        message_count=message_count,
        created_at=_iso(session.created_at),
        updated_at=_iso(session.updated_at),
    )


def _citation_meta_from_row(row: ChatMessageCitation) -> CitationMeta:
    return CitationMeta(
        index=row.index,
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_title=row.document_title,
        knowledge_base_id=row.knowledge_base_id,
        section_path=list(row.section_path_json or []),
        section_text=row.section_text,
        page_start=row.page_start,
        page_end=row.page_end,
        bbox=row.bbox_json,
        snippet=row.snippet,
        score=row.score,
    )


def _citation_out(row: ChatMessageCitation, user_id: str) -> ChatCitationOut:
    meta = _citation_meta_from_row(row)
    payload = build_reference_payload(meta, user_id=user_id)
    return ChatCitationOut(**payload)


def _message_out(message: ChatMessage, user_id: str) -> ChatMessageOut:
    return ChatMessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        finish_reason=message.finish_reason,
        model=message.model,
        created_at=_iso(message.created_at),
        citations=[_citation_out(row, user_id) for row in (message.citations or [])],
    )


async def _load_recent_history(
    db: DbSession,
    *,
    session_id: str,
    limit: int,
) -> list[dict[str, str]]:
    if limit <= 0:
        return []
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(
            ChatMessage.created_at.desc(),
            case((ChatMessage.role == "assistant", 0), (ChatMessage.role == "user", 1), else_=2),
            ChatMessage.id.desc(),
        )
        .limit(limit)
    )
    messages = list((await db.execute(stmt)).scalars().all())
    messages.reverse()
    history: list[dict[str, str]] = []
    for message in messages:
        content = (message.content or "").strip()
        if message.role not in {"user", "assistant"} or not content:
            continue
        history.append({"role": message.role, "content": content})
    return history


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    user: CurrentUser,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    include_inactive: bool = Query(default=False),
) -> ChatSessionListResponse:
    base = select(ChatSession).where(ChatSession.user_id == user.id)
    if not include_inactive:
        base = base.where(ChatSession.is_active.is_(True))
    total_scalar = await db.scalar(select(func.count()).select_from(base.subquery()))
    total = int(total_scalar or 0)
    offset = (page - 1) * page_size
    rows = (
        (
            await db.execute(
                base.order_by(ChatSession.updated_at.desc()).limit(page_size).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    counts: dict[str, int] = {}
    if rows:
        count_rows = await db.execute(
            select(ChatMessage.session_id, func.count(ChatMessage.id))
            .where(ChatMessage.session_id.in_([row.id for row in rows]))
            .group_by(ChatMessage.session_id)
        )
        counts = {sid: int(cnt) for sid, cnt in count_rows.all()}
    return ChatSessionListResponse(
        items=[_summary(row, counts.get(row.id, 0)) for row in rows],
        total=total,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(session_id: str, user: CurrentUser, db: DbSession) -> ChatSessionDetail:
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    msgs_stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .options(selectinload(ChatMessage.citations))
        .order_by(
            ChatMessage.created_at.asc(),
            case((ChatMessage.role == "user", 0), (ChatMessage.role == "assistant", 1), else_=2),
            ChatMessage.id.asc(),
        )
    )
    messages = (await db.execute(msgs_stmt)).scalars().all()
    return ChatSessionDetail(
        id=session.id,
        title=session.title,
        knowledge_base_id=session.knowledge_base_id,
        is_active=session.is_active,
        created_at=_iso(session.created_at),
        updated_at=_iso(session.updated_at),
        messages=[_message_out(m, user.id) for m in messages],
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, str]:
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    session.is_active = False
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="chat.session.disable",
        target_type="chat_session",
        target_id=session.id,
        request=request,
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/stream")
async def chat_stream(
    body: ChatStreamRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> EventSourceResponse:
    kb = await _ensure_kb_viewer(db, user, body.kb_id)
    # Session handling
    session: ChatSession | None = None
    if body.session_id:
        session = await db.get(ChatSession, body.session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
        if session.knowledge_base_id is None:
            session.knowledge_base_id = kb.id
        elif session.knowledge_base_id != kb.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="会话所属知识库与当前请求不一致",
            )
    if session is None:
        title = body.question.strip()[:40] or "新会话"
        session = ChatSession(user_id=user.id, knowledge_base_id=kb.id, title=title)
        db.add(session)
        await db.flush()
    session_id = session.id
    await db.commit()

    question = body.question
    settings = get_settings()
    history = (
        await _load_recent_history(
            db,
            session_id=session.id,
            limit=settings.chat_history_limit,
        )
        if body.session_id
        else []
    )

    async def event_gen() -> AsyncIterator[dict[str, Any]]:
        yield {
            "event": "status",
            "data": json.dumps(
                {"stage": "retrieving", "message": "正在检索证据"},
                ensure_ascii=False,
            ),
        }
        state = await prepare_citations(
            db,
            kb_id=kb.id,
            user_id=user.id,
            query=body.question,
            filters=body.filters,
            history=history,
            k=body.k,
            query_vector=await _query_embedding(body.question),
        )
        references = build_reference_payloads(state)
        await _record_audit(
            db,
            actor_user_id=user.id,
            action="chat.stream.start",
            target_type="chat_session",
            target_id=session_id,
            request=request,
            details={"kb_id": kb.id, "citations": len(references)},
        )
        await db.commit()
        # 1) 先下发 references
        yield {
            "event": "references",
            "data": json.dumps(
                {"session_id": session_id, "references": references},
                ensure_ascii=False,
            ),
        }
        raw_chunks: list[str] = []
        try:
            if not state.has_hit:
                async for delta in fallback_no_hit_stream():
                    raw_chunks.append(delta)
                    yield {
                        "event": "content",
                        "data": json.dumps({"delta": delta}, ensure_ascii=False),
                    }
                state.finish_reason = "no_hit"
                state.model_used = "fallback"
            else:
                yield {
                    "event": "status",
                    "data": json.dumps(
                        {"stage": "generating", "message": "正在组织答案"},
                        ensure_ascii=False,
                    ),
                }
                try:
                    async for event in generate_stream_events(state):
                        if event.kind == "reasoning":
                            yield {
                                "event": "reasoning",
                                "data": json.dumps({"delta": event.delta}, ensure_ascii=False),
                            }
                            continue
                        raw_chunks.append(event.delta)
                        rewritten_delta = rewrite_citations(event.delta, state)
                        yield {
                            "event": "content",
                            "data": json.dumps({"delta": rewritten_delta}, ensure_ascii=False),
                        }
                except Exception as exc:  # pragma: no cover - exercised in tests via mock
                    yield {
                        "event": "error",
                        "data": json.dumps(
                            {"code": "LLM_ERROR", "message": str(exc)},
                            ensure_ascii=False,
                        ),
                    }
                    state.finish_reason = "error"
        finally:
            state.answer_raw = "".join(raw_chunks)
            state.answer_rewritten = (
                rewrite_citations(state.answer_raw, state) if state.has_hit else state.answer_raw
            )
            visible_citations = state.citations
            if state.finish_reason != "error" and _is_no_evidence_answer(state.answer_rewritten):
                state.finish_reason = "no_hit"
                visible_citations = []
            # 2) 持久化（尽力）
            try:
                await _persist_turn(
                    session_id=session_id,
                    user_message=question,
                    answer=state.answer_rewritten,
                    citations=visible_citations,
                    finish_reason=state.finish_reason,
                    model=state.model_used,
                )
            except SQLAlchemyError:
                # 持久化失败不影响 SSE 主流程
                pass
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "session_id": session_id,
                        "finish_reason": state.finish_reason or "stop",
                        "model": state.model_used,
                        "citations": len(visible_citations),
                        "min_score_threshold": settings.chat_min_score_threshold,
                    },
                    ensure_ascii=False,
                ),
            }

    return EventSourceResponse(event_gen())


async def _query_embedding(query: str) -> list[float] | None:
    settings = get_settings()
    if settings.app_env == "test":
        return None
    try:
        async with DashScopeClient() as client:
            embeddings = await client.embed_batch([query])
    except Exception:
        return None
    return embeddings[0] if embeddings else None


async def _persist_turn(
    *,
    session_id: str,
    user_message: str,
    answer: str,
    citations: list[CitationMeta],
    finish_reason: str | None,
    model: str,
) -> None:
    """在独立 DB 会话内持久化一轮对话。"""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        turn_started_at = beijing_now()
        user_msg = ChatMessage(
            session_id=session_id,
            role="user",
            content=user_message,
            created_at=turn_started_at,
        )
        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=answer,
            finish_reason=finish_reason,
            model=model or None,
            created_at=turn_started_at + timedelta(microseconds=1),
        )
        db.add(user_msg)
        db.add(assistant_msg)
        await db.flush()
        for meta in citations:
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
        await db.commit()


# Export for main.py
__all__ = ["router"]
