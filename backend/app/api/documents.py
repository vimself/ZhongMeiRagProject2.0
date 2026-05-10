from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _record_audit
from app.api.deps import DbSession, current_user
from app.api.knowledge_base_deps import RequireEditor, RequireViewer, _get_user_kb_role
from app.celery_app import celery_app
from app.core.config import get_settings
from app.models.auth import User
from app.models.document import (
    Document,
    DocumentAsset,
    DocumentIngestJob,
    DocumentParseResult,
    IngestCallbackReceipt,
    IngestStepReceipt,
    KnowledgeChunkV2,
)
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentOut,
    DocumentUploadResponse,
    RetryDocumentResponse,
)
from app.schemas.ingest import (
    IngestJobProgress,
    IngestStepProgress,
    RetrievalDebugItem,
    RetrievalDebugRequest,
    RetrievalDebugResponse,
)

router = APIRouter(tags=["documents"])
CurrentUser = Annotated[User, Depends(current_user)]
UploadedPdf = Annotated[UploadFile, File()]
OptionalTitle = Annotated[str | None, Form()]
DocKindForm = Annotated[str, Form()]
OptionalSchemeType = Annotated[str | None, Form()]
StandardClauseForm = Annotated[bool, Form()]

INGEST_STEPS = [
    "upload_to_ocr",
    "poll_and_fetch_ocr",
    "parse_outline",
    "section_aware_chunk",
    "embed_batch",
    "track_a_write",
    "track_b_write",
    "asset_register",
    "finalize",
]


@router.post(
    "/api/v2/knowledge-bases/{kb_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    kb_id: str,
    request: Request,
    result: RequireEditor,
    user: CurrentUser,
    db: DbSession,
    file: UploadedPdf,
    title: OptionalTitle = None,
    doc_kind: DocKindForm = "other",
    scheme_type: OptionalSchemeType = None,
    is_standard_clause: StandardClauseForm = False,
) -> DocumentUploadResponse:
    kb, _role = result
    content = await file.read()
    _validate_upload(file, content)
    settings = get_settings()
    now = datetime.now(UTC)
    suffix = Path(file.filename or "document.pdf").suffix.lower() or ".pdf"
    document_id = str(uuid.uuid4())
    storage_path = (
        Path(settings.upload_dir)
        / f"{now:%Y}"
        / f"{now:%m}"
        / f"{now:%d}"
        / f"{document_id}{suffix}"
    )
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)
    document = Document(
        id=document_id,
        knowledge_base_id=kb.id,
        uploader_id=user.id,
        title=(title or Path(file.filename or "document.pdf").stem).strip(),
        filename=file.filename or f"{document_id}.pdf",
        mime=file.content_type or "application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_path=str(storage_path),
        doc_kind=_normalize_doc_kind(doc_kind),
        scheme_type=scheme_type.strip() if scheme_type else None,
        is_standard_clause=is_standard_clause,
        status="pending",
    )
    job = DocumentIngestJob(document_id=document.id, status="queued", trace_id=str(uuid.uuid4()))
    db.add(document)
    db.add(job)
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="document.upload",
        target_type="document",
        target_id=document.id,
        request=request,
        details={"knowledge_base_id": kb_id, "filename": document.filename},
    )
    await db.commit()
    await db.refresh(job)
    _send_ingest_task(job_id=job.id, document_id=document.id, actor_user_id=user.id)
    return DocumentUploadResponse(document_id=document.id, job_id=job.id, trace_id=job.trace_id)


@router.get("/api/v2/knowledge-bases/{kb_id}/documents", response_model=DocumentListResponse)
async def list_documents(
    result: RequireViewer,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=256),
    status_filter: str | None = Query(default=None, alias="status"),
) -> DocumentListResponse:
    kb, _role = result
    query = select(Document).where(
        Document.knowledge_base_id == kb.id, Document.status != "disabled"
    )
    count_query = (
        select(func.count())
        .select_from(Document)
        .where(Document.knowledge_base_id == kb.id, Document.status != "disabled")
    )
    if search:
        pattern = f"%{search}%"
        condition = or_(Document.title.ilike(pattern), Document.filename.ilike(pattern))
        query = query.where(condition)
        count_query = count_query.where(condition)
    if status_filter:
        query = query.where(Document.status == status_filter)
        count_query = count_query.where(Document.status == status_filter)
    total = (await db.execute(count_query)).scalar_one()
    rows = (
        (
            await db.execute(
                query.order_by(Document.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    users_map = await _users_map(db, [row.uploader_id for row in rows])
    return DocumentListResponse(
        items=[_document_out(row, users_map.get(row.uploader_id, "")) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/api/v2/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: str,
    user: CurrentUser,
    db: DbSession,
) -> DocumentDetailResponse:
    document, _role = await _require_document_role(
        db, user, document_id, {"viewer", "editor", "owner"}
    )
    users_map = await _users_map(db, [document.uploader_id])
    latest_job = await _latest_job(db, document.id)
    parse_result = await db.scalar(
        select(DocumentParseResult).where(DocumentParseResult.document_id == document.id)
    )
    assets = (
        (await db.execute(select(DocumentAsset).where(DocumentAsset.document_id == document.id)))
        .scalars()
        .all()
    )
    base = _document_out(document, users_map.get(document.uploader_id, ""))
    return DocumentDetailResponse(
        **base.model_dump(),
        latest_job=_job_payload(latest_job) if latest_job else None,
        parse_result=_parse_payload(parse_result) if parse_result else None,
        assets=[_asset_payload(asset) for asset in assets],
    )


@router.get("/api/v2/documents/{document_id}/progress", response_model=IngestJobProgress)
async def get_ingest_progress(
    document_id: str,
    user: CurrentUser,
    db: DbSession,
) -> IngestJobProgress:
    document, _role = await _require_document_role(
        db, user, document_id, {"viewer", "editor", "owner"}
    )
    job = await _latest_job(db, document.id)
    if job is None:
        return IngestJobProgress(
            document_id=document.id,
            document_status=document.status,
            progress=0,
            steps=[],
        )
    receipts = (
        (await db.execute(select(IngestStepReceipt).where(IngestStepReceipt.job_id == job.id)))
        .scalars()
        .all()
    )
    steps = [
        IngestStepProgress(
            step=receipt.step,
            status=receipt.status,
            created_at=receipt.created_at.isoformat(),
        )
        for receipt in receipts
    ]
    done = {receipt.step for receipt in receipts if receipt.status == "succeeded"}
    progress = 100 if job.status == "succeeded" else int(len(done) / len(INGEST_STEPS) * 100)
    return IngestJobProgress(
        document_id=document.id,
        job_id=job.id,
        job_status=job.status,
        document_status=document.status,
        progress=progress,
        steps=steps,
        last_error=job.last_error,
    )


@router.post("/api/v2/documents/{document_id}/retry", response_model=RetryDocumentResponse)
async def retry_document(
    document_id: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> RetryDocumentResponse:
    document, _role = await _require_document_role(db, user, document_id, {"owner"})
    job = DocumentIngestJob(document_id=document.id, status="queued", trace_id=str(uuid.uuid4()))
    document.status = "pending"
    db.add(job)
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="document.retry",
        target_type="document",
        target_id=document.id,
        request=request,
        details={"knowledge_base_id": document.knowledge_base_id},
    )
    await db.commit()
    await db.refresh(job)
    _send_ingest_task(job_id=job.id, document_id=document.id, actor_user_id=user.id)
    return RetryDocumentResponse(
        document_id=document.id,
        job_id=job.id,
        trace_id=job.trace_id,
        status=job.status,
    )


@router.delete("/api/v2/documents/{document_id}", response_model=DocumentOut)
async def disable_document(
    document_id: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> DocumentOut:
    document, _role = await _require_document_role(db, user, document_id, {"owner"})
    document.status = "disabled"
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="document.disable",
        target_type="document",
        target_id=document.id,
        request=request,
        details={"knowledge_base_id": document.knowledge_base_id},
    )
    await db.commit()
    await db.refresh(document)
    users_map = await _users_map(db, [document.uploader_id])
    return _document_out(document, users_map.get(document.uploader_id, ""))


@router.post("/api/v2/retrieval/debug", response_model=RetrievalDebugResponse)
async def retrieval_debug(
    body: RetrievalDebugRequest,
    user: CurrentUser,
    db: DbSession,
) -> RetrievalDebugResponse:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    query = select(KnowledgeChunkV2).where(KnowledgeChunkV2.knowledge_base_id == body.kb_id)
    doc_kind = body.filters.get("doc_kind")
    scheme_type = body.filters.get("scheme_type")
    if isinstance(doc_kind, str) and doc_kind:
        query = query.where(KnowledgeChunkV2.doc_kind == doc_kind)
    if isinstance(scheme_type, str) and scheme_type:
        query = query.where(KnowledgeChunkV2.scheme_type == scheme_type)
    chunks = (await db.execute(query.limit(1000))).scalars().all()
    ranked = sorted(
        ((_debug_score(body.query, chunk.content), chunk) for chunk in chunks),
        key=lambda item: item[0],
        reverse=True,
    )[: body.k]
    items = [
        RetrievalDebugItem(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            score=score,
            content=chunk.content,
            section_path=chunk.section_path,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
        )
        for score, chunk in ranked
        if score > 0
    ]
    return RetrievalDebugResponse(items=items, total=len(items))


@router.post("/api/v2/ocr/callback")
async def receive_ocr_callback(
    request: Request,
    db: DbSession,
    job_id: str | None = Query(default=None),
    document_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    settings = get_settings()
    callback_token = (
        settings.ocr_callback_token.get_secret_value() if settings.ocr_callback_token else ""
    )
    if callback_token:
        expected = f"Bearer {callback_token}"
        if authorization != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OCR 回调鉴权失败")
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OCR 回调 payload 无效")
    session_id = str(payload.get("session_id") or "")
    status_value = str(payload.get("status") or "unknown")
    idempotency_key = str(
        payload.get("idempotency_key")
        or (
            f"ocr-callback:{job_id or 'no-job'}:"
            f"{document_id or 'no-doc'}:{session_id}:{status_value}"
        )
    )
    existing = await db.scalar(
        select(IngestCallbackReceipt).where(
            IngestCallbackReceipt.idempotency_key == idempotency_key
        )
    )
    if existing is None:
        enriched_payload = {
            "job_id": job_id,
            "document_id": document_id,
            "payload": payload,
        }
        db.add(
            IngestCallbackReceipt(
                idempotency_key=idempotency_key,
                payload_json=enriched_payload,
            )
        )
        if document_id:
            document = await db.get(Document, document_id)
            if document is not None:
                await _record_audit(
                    db,
                    actor_user_id=document.uploader_id,
                    action="ingest.callback.received",
                    target_type="document",
                    target_id=document.id,
                    request=request,
                    details={"job_id": job_id, "session_id": session_id, "status": status_value},
                )
        await db.commit()
    return {"status": "ok"}


def _validate_upload(file: UploadFile, content: bytes) -> None:
    settings = get_settings()
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 PDF 文件")
    if len(content) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件超过大小限制")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件魔数不是 PDF")
    if file.content_type not in {None, "", "application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件 MIME 类型不正确")


def _normalize_doc_kind(doc_kind: str) -> str:
    allowed = {"plan", "spec", "drawing", "quantity", "other"}
    return doc_kind if doc_kind in allowed else "other"


async def _require_document_role(
    db: AsyncSession,
    user: User,
    document_id: str,
    allowed: set[str],
) -> tuple[Document, str]:
    document = await db.get(Document, document_id)
    if document is None or document.status == "disabled":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    if user.role == "admin":
        return document, "admin"
    role = await _get_user_kb_role(db, user.id, document.knowledge_base_id)
    if role is None or role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有访问此文档的权限")
    return document, role


async def _users_map(db: AsyncSession, user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    users = (await db.execute(select(User).where(User.id.in_(set(user_ids))))).scalars().all()
    return {user.id: user.display_name for user in users}


async def _latest_job(db: AsyncSession, document_id: str) -> DocumentIngestJob | None:
    job: DocumentIngestJob | None = await db.scalar(
        select(DocumentIngestJob)
        .where(DocumentIngestJob.document_id == document_id)
        .order_by(DocumentIngestJob.created_at.desc())
        .limit(1)
    )
    return job


def _document_out(document: Document, uploader_name: str = "") -> DocumentOut:
    return DocumentOut(
        id=document.id,
        knowledge_base_id=document.knowledge_base_id,
        uploader_id=document.uploader_id,
        uploader_name=uploader_name,
        title=document.title,
        filename=document.filename,
        mime=document.mime,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        doc_kind=document.doc_kind,
        scheme_type=document.scheme_type,
        is_standard_clause=document.is_standard_clause,
        status=document.status,
        page_count=document.page_count,
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat(),
    )


def _job_payload(job: DocumentIngestJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "attempt": job.attempt,
        "available_at": job.available_at.isoformat(),
        "last_error": job.last_error,
        "trace_id": job.trace_id,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _parse_payload(result: DocumentParseResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "ocr_session_id": result.ocr_session_id,
        "markdown_path": result.markdown_path,
        "markdown_sha256": result.markdown_sha256,
        "outline": result.outline_json,
        "stats": result.stats_json,
        "created_at": result.created_at.isoformat(),
    }


def _asset_payload(asset: DocumentAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "kind": asset.kind,
        "page_no": asset.page_no,
        "bbox": asset.bbox_json,
        "storage_path": asset.storage_path,
        "caption": asset.caption,
        "created_at": asset.created_at.isoformat(),
    }


def _send_ingest_task(*, job_id: str, document_id: str, actor_user_id: str) -> None:
    settings = get_settings()
    if settings.app_env == "test":
        return
    celery_app.send_task(
        "ingest.process",
        queue="ingest",
        kwargs={"job_id": job_id, "document_id": document_id, "actor_user_id": actor_user_id},
    )


def _debug_score(query: str, content: str) -> float:
    query_terms = [term for term in query.lower().split() if term]
    lowered = content.lower()
    lexical = sum(lowered.count(term) for term in query_terms)
    phrase = 3 if query.lower() in lowered else 0
    return float(lexical + phrase)
