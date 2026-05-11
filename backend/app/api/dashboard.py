from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _record_audit
from app.api.deps import DbSession, require_admin
from app.core.config import get_settings
from app.models.auth import AuditLog, User
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document, DocumentAsset, DocumentIngestJob, KnowledgeChunkV2
from app.models.knowledge_base import KnowledgeBase
from app.schemas.search import DashboardStats, SystemStatus

router = APIRouter(prefix="/api/v2/dashboard", tags=["dashboard"])
AdminUser = Annotated[User, Depends(require_admin)]

_app_start_time = time.monotonic()


@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(
    request: Request,
    admin: AdminUser,
    db: DbSession,
) -> DashboardStats:
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0

    kb_count = (await db.execute(select(func.count()).select_from(KnowledgeBase))).scalar() or 0
    kb_active = (
        await db.execute(
            select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.is_active.is_(True))
        )
    ).scalar() or 0

    doc_total = (await db.execute(select(func.count()).select_from(Document))).scalar() or 0

    status_rows = (
        await db.execute(select(Document.status, func.count()).group_by(Document.status))
    ).all()
    doc_by_status = {row[0]: row[1] for row in status_rows}

    kind_rows = (
        await db.execute(select(Document.doc_kind, func.count()).group_by(Document.doc_kind))
    ).all()
    doc_by_kind = {row[0] or "other": row[1] for row in kind_rows}

    chunk_count = (
        await db.execute(select(func.count()).select_from(KnowledgeChunkV2))
    ).scalar() or 0
    asset_count = (await db.execute(select(func.count()).select_from(DocumentAsset))).scalar() or 0
    session_count = (await db.execute(select(func.count()).select_from(ChatSession))).scalar() or 0
    message_count = (await db.execute(select(func.count()).select_from(ChatMessage))).scalar() or 0

    ingest_rows = (
        await db.execute(
            select(DocumentIngestJob.status, func.count()).group_by(DocumentIngestJob.status)
        )
    ).all()
    ingest_by_status = {row[0]: row[1] for row in ingest_rows}

    recent_rows = (
        (await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(20)))
        .scalars()
        .all()
    )
    recent_activities = [
        {
            "action": a.action,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "ip_address": a.ip_address,
            "created_at": a.created_at.isoformat() if a.created_at else "",
        }
        for a in recent_rows
    ]

    now = datetime.now(UTC)
    trends_7d = await _build_trends(db, now, 7)
    trends_14d = await _build_trends(db, now, 14)

    await _record_audit(
        db,
        actor_user_id=admin.id,
        action="dashboard.view",
        target_type="dashboard",
        target_id=None,
        request=request,
    )
    await db.commit()

    return DashboardStats(
        user_count=user_count,
        kb_count=kb_count,
        kb_active_count=kb_active,
        document_total=doc_total,
        document_by_status=doc_by_status,
        document_by_kind=doc_by_kind,
        chunk_count=chunk_count,
        asset_count=asset_count,
        chat_session_count=session_count,
        chat_message_count=message_count,
        ingest_by_status=ingest_by_status,
        recent_activities=recent_activities,
        trends_7d=trends_7d,
        trends_14d=trends_14d,
    )


async def _build_trends(db: AsyncSession, now: datetime, days: int) -> dict[str, Any]:
    dates: list[str] = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        dates.append(d)

    doc_counts = {d: 0 for d in dates}
    chat_counts = {d: 0 for d in dates}

    start_date = now - timedelta(days=days - 1)

    doc_rows = (
        await db.execute(select(Document.created_at).where(Document.created_at >= start_date))
    ).all()
    for row in doc_rows:
        created_at = row[0]
        if not isinstance(created_at, datetime):
            continue
        day = created_at.strftime("%Y-%m-%d")
        if day in doc_counts:
            doc_counts[day] += 1

    chat_rows = (
        await db.execute(select(ChatSession.created_at).where(ChatSession.created_at >= start_date))
    ).all()
    for row in chat_rows:
        created_at = row[0]
        if not isinstance(created_at, datetime):
            continue
        day = created_at.strftime("%Y-%m-%d")
        if day in chat_counts:
            chat_counts[day] += 1

    return {
        "dates": dates,
        "documents": [doc_counts[d] for d in dates],
        "chat_sessions": [chat_counts[d] for d in dates],
    }


@router.get("/system-status", response_model=SystemStatus)
async def system_status(
    request: Request,
    admin: AdminUser,
    db: DbSession,
) -> SystemStatus:
    settings = get_settings()

    db_status = "ok"
    db_latency = 0.0
    try:
        t0 = time.monotonic()
        await db.execute(text("SELECT 1"))
        db_latency = round((time.monotonic() - t0) * 1000, 2)
    except Exception:
        db_status = "down"
        db_latency = 0.0

    redis_status = "down"
    redis_latency = 0.0
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        t0 = time.monotonic()
        await r.ping()
        redis_latency = round((time.monotonic() - t0) * 1000, 2)
        redis_status = "ok"
        await r.aclose()
    except Exception:
        redis_status = "down"
        redis_latency = 0.0

    dashscope = await _check_dashscope()

    uptime = time.monotonic() - _app_start_time

    await _record_audit(
        db,
        actor_user_id=admin.id,
        action="dashboard.system_status",
        target_type="dashboard",
        target_id=None,
        request=request,
    )
    await db.commit()

    return SystemStatus(
        database={"status": db_status, "latency_ms": db_latency},
        redis={"status": redis_status, "latency_ms": redis_latency},
        dashscope=dashscope,
        uptime_seconds=round(uptime, 1),
    )


async def _check_dashscope() -> dict[str, object]:
    settings = get_settings()
    if not settings.dashscope_api_key or not settings.dashscope_api_key.get_secret_value():
        return {"status": "not_configured"}

    url = f"{settings.dashscope_base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {settings.dashscope_api_key.get_secret_value()}"}
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url, headers=headers)
        latency = round((time.monotonic() - t0) * 1000, 2)
        if 200 <= resp.status_code < 300:
            return {"status": "ok", "latency_ms": latency}
        if resp.status_code in {401, 403}:
            return {"status": "down", "latency_ms": latency, "code": resp.status_code}
        return {"status": "degraded", "latency_ms": latency, "code": resp.status_code}
    except Exception:
        return {"status": "down", "latency_ms": 0.0}
