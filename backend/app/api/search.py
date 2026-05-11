from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from app.api.auth import _record_audit
from app.api.deps import BearerCredentials, DbSession, current_user
from app.celery_app import celery_app
from app.models.auth import User
from app.models.search_export import SearchExportJob
from app.schemas.search import (
    DocTypeCount,
    DocTypesResponse,
    ExportJobOut,
    ExportJobStatusOut,
    ExportRequest,
    HotKeywordItem,
    HotKeywordsResponse,
    SchemeTypeCount,
    SearchHitOut,
    SearchRequest,
    SearchResponse,
)
from app.security.jwt import decode_token, issue_search_export_token
from app.services.rag.citations import CitationMeta, build_reference_payload
from app.services.rag.search_service import SearchService

router = APIRouter(prefix="/api/v2/search", tags=["search"])
CurrentUser = Annotated[User, Depends(current_user)]


@router.post("/documents", response_model=SearchResponse)
async def search_documents(
    request: Request,
    body: SearchRequest,
    user: CurrentUser,
    db: DbSession,
) -> SearchResponse:
    svc = SearchService(db)
    filters: dict[str, object] = {}
    if body.doc_kind:
        filters["doc_kind"] = body.doc_kind
    if body.scheme_type:
        filters["scheme_type"] = body.scheme_type
    if body.content_type:
        filters["content_type"] = body.content_type
    if body.date_from:
        filters["date_from"] = body.date_from
    if body.date_to:
        filters["date_to"] = body.date_to

    results, total = await svc.search(
        user=user,
        query=body.query,
        kb_id=body.kb_id,
        filters=filters,
        page=body.page,
        page_size=body.page_size,
        sort_by=body.sort_by,
    )

    items: list[SearchHitOut] = []
    for idx, r in enumerate(results, start=(body.page - 1) * body.page_size + 1):
        meta = CitationMeta(
            index=idx,
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            document_title=r.document_title,
            knowledge_base_id=r.knowledge_base_id,
            section_path=r.section_path,
            section_text=r.section_text,
            page_start=r.page_start,
            page_end=r.page_end,
            bbox=r.bbox,
            snippet=r.snippet,
            score=r.score,
        )
        payload = build_reference_payload(meta, user_id=user.id)
        items.append(SearchHitOut(**payload))

    await _record_audit(
        db,
        actor_user_id=user.id,
        action="search.documents",
        target_type="search",
        target_id=None,
        request=request,
        details={"query": body.query, "total": total},
    )
    await db.commit()
    return SearchResponse(items=items, total=total, page=body.page, page_size=body.page_size)


@router.get("/hot-keywords", response_model=HotKeywordsResponse)
async def hot_keywords(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> HotKeywordsResponse:
    svc = SearchService(db)
    raw = await svc.hot_keywords(user, limit=limit)
    return HotKeywordsResponse(items=[HotKeywordItem(keyword=kw, count=c) for kw, c in raw])


@router.get("/doc-types", response_model=DocTypesResponse)
async def doc_types(
    user: CurrentUser,
    db: DbSession,
) -> DocTypesResponse:
    svc = SearchService(db)
    doc_kinds, scheme_types = await svc.doc_types(user)
    return DocTypesResponse(
        doc_kinds=[DocTypeCount(doc_kind=k, count=c) for k, c in doc_kinds],
        scheme_types=[SchemeTypeCount(scheme_type=s, count=c) for s, c in scheme_types],
    )


@router.post("/export", response_model=ExportJobOut)
async def create_export(
    request: Request,
    body: ExportRequest,
    user: CurrentUser,
    db: DbSession,
) -> ExportJobOut:
    job = SearchExportJob(
        user_id=user.id,
        status="pending",
        format=body.format,
        filters_json={
            "query": body.query,
            "kb_id": body.kb_id,
            "doc_kind": body.doc_kind,
            "scheme_type": body.scheme_type,
            "content_type": body.content_type,
            "date_from": body.date_from,
            "date_to": body.date_to,
        },
    )
    job.set_defaults()
    db.add(job)
    await db.flush()

    celery_app.send_task("search.export_generate", kwargs={"job_id": job.id, "user_id": user.id})

    await _record_audit(
        db,
        actor_user_id=user.id,
        action="search.export",
        target_type="search_export",
        target_id=job.id,
        request=request,
    )
    await db.commit()
    return ExportJobOut(
        job_id=job.id,
        status=job.status,
        created_at=job.created_at.isoformat(),
    )


@router.get("/export/{job_id}", response_model=ExportJobStatusOut)
async def get_export_status(
    job_id: str,
    user: CurrentUser,
    db: DbSession,
) -> ExportJobStatusOut:
    job = await db.get(SearchExportJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    download_url = None
    if job.status == "succeeded" and job.file_path:
        token = issue_search_export_token(subject=user.id, job_id=job.id).token
        download_url = f"/api/v2/search/export/{job_id}/download?token={token}"
    return ExportJobStatusOut(
        job_id=job.id,
        status=job.status,
        result_count=job.result_count,
        file_size=job.file_size,
        download_url=download_url,
        error=job.error,
        created_at=job.created_at.isoformat(),
    )


@router.get("/export/{job_id}/download")
async def download_export(
    job_id: str,
    db: DbSession,
    credentials: BearerCredentials,
    token: str | None = Query(default=None),
) -> FileResponse:
    subject = await _resolve_export_subject(
        job_id=job_id,
        db=db,
        credentials=credentials,
        token=token,
    )
    job = await db.get(SearchExportJob, job_id)
    if job is None or job.user_id != subject:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    if job.status != "succeeded" or not job.file_path:
        raise HTTPException(status_code=400, detail="导出尚未完成")
    import os

    abs_path = os.path.abspath(job.file_path)
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="导出文件不存在")
    return FileResponse(
        abs_path,
        media_type="application/zip",
        filename=f"search_export_{job_id}.zip",
    )


async def _resolve_export_subject(
    *,
    job_id: str,
    db: DbSession,
    credentials: BearerCredentials,
    token: str | None,
) -> str:
    if token:
        token_data = decode_token(token, expected_type="search_export")
        if token_data.claims.get("job") != job_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="导出 token 范围错误",
            )
        user = await db.get(User, token_data.subject)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在或已停用",
            )
        return user.id

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_data = decode_token(credentials.credentials, expected_type="access")
    user = await db.get(User, token_data.subject)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")
    return user.id
