from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Body,
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
from app.api.knowledge_base_deps import (
    RequireEditor,
    RequireViewer,
    require_document_role,
)
from app.celery_app import celery_app
from app.core.config import get_settings
from app.core.timezone import beijing_now, isoformat_beijing
from app.models.auth import User
from app.models.document import (
    Document,
    DocumentAsset,
    DocumentIngestJob,
    DocumentParseResult,
    IngestCallbackReceipt,
    IngestStepReceipt,
)
from app.schemas.document import (
    AssetOut,
    DocumentBatchDeleteRequest,
    DocumentBatchDeleteResponse,
    DocumentDeleteResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentOut,
    DocumentUploadItem,
    DocumentUploadRejectedItem,
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
from app.security.jwt import issue_asset_token, issue_pdf_token
from app.services.deletion import (
    DOCUMENT_DELETING_STATUS,
    collect_document_deletion_resources,
    delete_artifact_files,
    hard_delete_documents,
    release_document_ingest_resources,
    request_document_deletion,
)
from app.services.llm.client import DashScopeClient
from app.services.rag.retriever import Retriever

router = APIRouter(tags=["documents"])
CurrentUser = Annotated[User, Depends(current_user)]
OptionalUploadedPdf = Annotated[UploadFile | None, File()]
OptionalUploadedPdfs = Annotated[list[UploadFile] | None, File()]
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

INGEST_STEP_PROGRESS = {
    "upload_to_ocr": 15,
    "poll_and_fetch_ocr": 35,
    "parse_outline": 45,
    "section_aware_chunk": 55,
    "embed_batch": 70,
    "track_a_write": 82,
    "track_b_write": 90,
    "asset_register": 96,
    "finalize": 100,
}

INGEST_STEP_PHASES = {
    "upload_to_ocr": "ocr",
    "poll_and_fetch_ocr": "ocr",
    "parse_outline": "embedding",
    "section_aware_chunk": "embedding",
    "embed_batch": "embedding",
    "track_a_write": "vector_indexing",
    "track_b_write": "vector_indexing",
    "asset_register": "vector_indexing",
    "finalize": "ready",
}

DOCUMENT_STATUS_COMPAT = {
    "parsing": "embedding",
    "indexing": "vector_indexing",
}

INGEST_PHASE_RANK = {
    "pending": 0,
    "ocr": 1,
    "embedding": 2,
    "vector_indexing": 3,
    "ready": 4,
}


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
    file: OptionalUploadedPdf = None,
    files: OptionalUploadedPdfs = None,
    title: OptionalTitle = None,
    doc_kind: DocKindForm = "other",
    scheme_type: OptionalSchemeType = None,
    is_standard_clause: StandardClauseForm = False,
) -> DocumentUploadResponse:
    kb, _role = result
    settings = get_settings()
    upload_files = _collect_upload_files(
        file=file,
        files=files,
        max_count=settings.upload_max_files,
    )
    single_upload = len(upload_files) == 1
    accepted: list[DocumentUploadItem] = []
    rejected: list[DocumentUploadRejectedItem] = []
    tasks_to_send: list[tuple[str, str]] = []
    upload_files = await _filter_duplicate_upload_files(
        db=db,
        kb_id=kb.id,
        upload_files=upload_files,
        rejected=rejected,
    )

    for upload_file in upload_files:
        try:
            item, document_id, job_id = await _stage_document_upload(
                kb_id=kb.id,
                user_id=user.id,
                request=request,
                db=db,
                file=upload_file,
                title=title if single_upload else None,
                doc_kind=doc_kind,
                scheme_type=scheme_type,
                is_standard_clause=is_standard_clause,
            )
        except HTTPException as exc:
            if single_upload:
                raise
            rejected.append(
                DocumentUploadRejectedItem(
                    filename=upload_file.filename or "未命名文件",
                    reason=str(exc.detail),
                )
            )
            continue
        accepted.append(item)
        tasks_to_send.append((job_id, document_id))

    if not accepted:
        if rejected and all(item.reason == "文件名已存在" for item in rejected):
            return DocumentUploadResponse(
                documents=[],
                rejected=rejected,
                accepted_count=0,
                rejected_count=len(rejected),
                max_count=settings.upload_max_files,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="没有可上传的有效 PDF 文件",
        )

    await db.commit()
    for job_id, document_id in tasks_to_send:
        _send_ingest_task(job_id=job_id, document_id=document_id, actor_user_id=user.id)
    first = accepted[0]
    return DocumentUploadResponse(
        document_id=first.document_id,
        job_id=first.job_id,
        trace_id=first.trace_id,
        documents=accepted,
        rejected=rejected,
        accepted_count=len(accepted),
        rejected_count=len(rejected),
        max_count=settings.upload_max_files,
    )


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
        Document.knowledge_base_id == kb.id,
        Document.status.notin_(("disabled", DOCUMENT_DELETING_STATUS)),
    )
    count_query = (
        select(func.count())
        .select_from(Document)
        .where(
            Document.knowledge_base_id == kb.id,
            Document.status.notin_(("disabled", DOCUMENT_DELETING_STATUS)),
        )
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


@router.delete(
    "/api/v2/knowledge-bases/{kb_id}/documents",
    response_model=DocumentBatchDeleteResponse,
)
async def delete_documents_batch(
    kb_id: str,
    request: Request,
    body: Annotated[DocumentBatchDeleteRequest, Body()],
    result: RequireEditor,
    user: CurrentUser,
    db: DbSession,
) -> DocumentBatchDeleteResponse:
    kb, role = result
    if role not in {"admin", "owner"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有删除文档的权限")
    document_ids = list(dict.fromkeys(body.document_ids))
    rows = list(
        (
            await db.execute(
                select(Document).where(
                    Document.id.in_(document_ids),
                    Document.knowledge_base_id == kb.id,
                )
            )
        )
        .scalars()
        .all()
    )
    if len(rows) != len(document_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    resources = await collect_document_deletion_resources(db, document_ids)
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="document.delete.batch",
        target_type="knowledge_base",
        target_id=kb.id,
        request=request,
        details={"knowledge_base_id": kb_id, "document_ids": document_ids, "count": len(rows)},
    )
    await request_document_deletion(db, document_ids)
    await db.commit()
    await release_document_ingest_resources(resources)
    await hard_delete_documents(db, document_ids, delete_files=False)
    await db.commit()
    delete_artifact_files(resources.artifact_paths)
    return DocumentBatchDeleteResponse(deleted_ids=document_ids, deleted_count=len(document_ids))


@router.get("/api/v2/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: str,
    user: CurrentUser,
    db: DbSession,
) -> DocumentDetailResponse:
    document, _role = await require_document_role(
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
        assets=[
            _asset_payload(asset, user_id=user.id, kb_id=document.knowledge_base_id)
            for asset in assets
        ],
    )


@router.get("/api/v2/documents/{document_id}/progress", response_model=IngestJobProgress)
async def get_ingest_progress(
    document_id: str,
    user: CurrentUser,
    db: DbSession,
) -> IngestJobProgress:
    document, _role = await require_document_role(
        db, user, document_id, {"viewer", "editor", "owner"}
    )
    job = await _latest_job(db, document.id)
    if job is None:
        return IngestJobProgress(
            document_id=document.id,
            document_status=_normalize_document_status(document.status),
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
            created_at=isoformat_beijing(receipt.created_at),
        )
        for receipt in receipts
    ]
    done = {receipt.step for receipt in receipts if receipt.status == "succeeded"}
    document_status = _progress_status(document.status, job.status, done)
    progress = _progress_percent(document_status, job.status, done)
    return IngestJobProgress(
        document_id=document.id,
        job_id=job.id,
        job_status=job.status,
        document_status=document_status,
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
    document, _role = await require_document_role(db, user, document_id, {"owner"})
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


@router.delete("/api/v2/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> DocumentDeleteResponse:
    document, _role = await require_document_role(db, user, document_id, {"owner"})
    resources = await collect_document_deletion_resources(db, [document.id])
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="document.delete",
        target_type="document",
        target_id=document.id,
        request=request,
        details={"knowledge_base_id": document.knowledge_base_id},
    )
    await request_document_deletion(db, [document.id])
    await db.commit()
    await release_document_ingest_resources(resources)
    await hard_delete_documents(db, [document.id], delete_files=False)
    await db.commit()
    delete_artifact_files(resources.artifact_paths)
    return DocumentDeleteResponse(document_id=document_id)


@router.post("/api/v2/retrieval/debug", response_model=RetrievalDebugResponse)
async def retrieval_debug(
    body: RetrievalDebugRequest,
    user: CurrentUser,
    db: DbSession,
) -> RetrievalDebugResponse:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    retriever = Retriever(db)
    query_vector = await _query_embedding(body.query)
    results = await retriever.retrieve(
        kb_id=body.kb_id,
        query=body.query,
        k=body.k,
        filters=body.filters,
        query_vector=query_vector,
    )
    items = [_retrieval_item(r, user_id=user.id) for r in results]
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
                    details={
                        "job_id": job_id,
                        "session_id": session_id,
                        "status": status_value,
                    },
                )
        await db.commit()
    return {"status": "ok"}


def _collect_upload_files(
    *,
    file: UploadFile | None,
    files: list[UploadFile] | None,
    max_count: int,
) -> list[UploadFile]:
    upload_files: list[UploadFile] = []
    if file is not None:
        upload_files.append(file)
    if files:
        upload_files.extend(files)
    if not upload_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请选择要上传的 PDF 文件",
        )
    if len(upload_files) > max_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"一次最多上传 {max_count} 份文档",
        )
    return upload_files


async def _filter_duplicate_upload_files(
    *,
    db: AsyncSession,
    kb_id: str,
    upload_files: list[UploadFile],
    rejected: list[DocumentUploadRejectedItem],
) -> list[UploadFile]:
    candidate_names = [_upload_basename(upload_file) for upload_file in upload_files]
    candidate_name_keys = [_filename_key(filename) for filename in candidate_names]
    existing_names = await db.scalars(
        select(Document.filename).where(
            Document.knowledge_base_id == kb_id,
            Document.status.notin_(("disabled", DOCUMENT_DELETING_STATUS)),
            func.lower(Document.filename).in_(candidate_name_keys),
        )
    )
    existing_name_keys = {_filename_key(filename) for filename in existing_names}
    seen_name_keys: set[str] = set()
    unique_files: list[UploadFile] = []

    for upload_file, filename in zip(upload_files, candidate_names, strict=True):
        filename_key = _filename_key(filename)
        if filename_key in existing_name_keys or filename_key in seen_name_keys:
            rejected.append(DocumentUploadRejectedItem(filename=filename, reason="文件名已存在"))
            continue
        seen_name_keys.add(filename_key)
        unique_files.append(upload_file)

    return unique_files


async def _stage_document_upload(
    *,
    kb_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession,
    file: UploadFile,
    title: str | None,
    doc_kind: str,
    scheme_type: str | None,
    is_standard_clause: bool,
) -> tuple[DocumentUploadItem, str, str]:
    content = await file.read()
    _validate_upload(file, content)
    settings = get_settings()
    now = beijing_now()
    original_filename = Path(file.filename or "document.pdf").name
    suffix = Path(original_filename).suffix.lower() or ".pdf"
    document_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    storage_path = (
        Path(settings.upload_dir)
        / f"{now:%Y}"
        / f"{now:%m}"
        / f"{now:%d}"
        / f"{document_id}{suffix}"
    )
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)
    filename_stem = Path(original_filename).stem or "未命名文档"
    document_title = (title or filename_stem).strip() or filename_stem
    document = Document(
        id=document_id,
        knowledge_base_id=kb_id,
        uploader_id=user_id,
        title=document_title,
        filename=original_filename or f"{document_id}.pdf",
        mime=file.content_type or "application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_path=str(storage_path),
        doc_kind=_normalize_doc_kind(doc_kind),
        scheme_type=scheme_type.strip() if scheme_type else None,
        is_standard_clause=is_standard_clause,
        status="pending",
    )
    job = DocumentIngestJob(
        id=job_id,
        document_id=document.id,
        status="queued",
        trace_id=trace_id,
    )
    db.add(document)
    db.add(job)
    await _record_audit(
        db,
        actor_user_id=user_id,
        action="document.upload",
        target_type="document",
        target_id=document.id,
        request=request,
        details={"knowledge_base_id": kb_id, "filename": document.filename},
    )
    return (
        DocumentUploadItem(
            document_id=document.id,
            job_id=job.id,
            trace_id=job.trace_id,
            title=document.title,
            filename=document.filename,
        ),
        document.id,
        job.id,
    )


def _upload_basename(file: UploadFile) -> str:
    return Path(file.filename or "未命名文件").name or "未命名文件"


def _filename_key(filename: str) -> str:
    return filename.casefold()


def _validate_upload(file: UploadFile, content: bytes) -> None:
    settings = get_settings()
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 PDF 文件")
    if len(content) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件超过大小限制")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件魔数不是 PDF")
    if file.content_type not in {
        None,
        "",
        "application/pdf",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件 MIME 类型不正确")


def _normalize_doc_kind(doc_kind: str) -> str:
    allowed = {"plan", "spec", "drawing", "quantity", "other"}
    return doc_kind if doc_kind in allowed else "other"


async def _users_map(db: AsyncSession, user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    users = (await db.execute(select(User).where(User.id.in_(set(user_ids))))).scalars().all()
    return {user.id: user.username for user in users}


async def _latest_job(db: AsyncSession, document_id: str) -> DocumentIngestJob | None:
    job: DocumentIngestJob | None = await db.scalar(
        select(DocumentIngestJob)
        .where(DocumentIngestJob.document_id == document_id)
        .order_by(DocumentIngestJob.created_at.desc())
        .limit(1)
    )
    return job


def _normalize_document_status(status_value: str) -> str:
    return DOCUMENT_STATUS_COMPAT.get(status_value, status_value)


def _progress_status(document_status: str, job_status: str | None, done: set[str]) -> str:
    normalized = _normalize_document_status(document_status)
    if normalized in {"ready", "failed", "disabled", DOCUMENT_DELETING_STATUS}:
        return normalized
    if job_status == "succeeded" or "finalize" in done:
        return "ready"
    if job_status in {"dead", "failed"}:
        return "failed"
    phase = normalized if normalized in INGEST_PHASE_RANK else "pending"
    for step in reversed(INGEST_STEPS):
        if step in done:
            receipt_phase = INGEST_STEP_PHASES[step]
            if INGEST_PHASE_RANK[receipt_phase] > INGEST_PHASE_RANK[phase]:
                return receipt_phase
            return phase
    return phase


def _progress_percent(document_status: str, job_status: str | None, done: set[str]) -> int:
    if document_status == "ready" or job_status == "succeeded":
        return 100
    if document_status == "pending":
        return 0
    if not done:
        return {"ocr": 8, "embedding": 40, "vector_indexing": 75}.get(document_status, 0)
    progress = max(INGEST_STEP_PROGRESS.get(step, 0) for step in done)
    floor = {"ocr": 8, "embedding": 40, "vector_indexing": 75, "failed": 0}.get(
        document_status,
        0,
    )
    if document_status == "failed":
        return min(max(progress, floor), 99)
    return min(max(progress, floor), 99)


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
        status=_normalize_document_status(document.status),
        page_count=document.page_count,
        created_at=isoformat_beijing(document.created_at),
        updated_at=isoformat_beijing(document.updated_at),
    )


def _job_payload(job: DocumentIngestJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "attempt": job.attempt,
        "available_at": isoformat_beijing(job.available_at),
        "last_error": job.last_error,
        "trace_id": job.trace_id,
        "created_at": isoformat_beijing(job.created_at),
        "updated_at": isoformat_beijing(job.updated_at),
    }


def _parse_payload(result: DocumentParseResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "ocr_session_id": result.ocr_session_id,
        "markdown_path": result.markdown_path,
        "markdown_sha256": result.markdown_sha256,
        "outline": result.outline_json,
        "stats": result.stats_json,
        "created_at": isoformat_beijing(result.created_at),
    }


def _asset_payload(asset: DocumentAsset, *, user_id: str, kb_id: str) -> AssetOut:
    issued = issue_asset_token(
        subject=user_id,
        document_id=asset.document_id,
        asset_id=asset.id,
        knowledge_base_id=kb_id,
    )
    url = f"/api/v2/assets/preview?asset_id={asset.id}&token={quote(issued.token)}"
    return AssetOut(
        id=asset.id,
        kind=asset.kind,
        page_no=asset.page_no,
        bbox=asset.bbox_json,
        storage_path=asset.storage_path,
        url=url,
        caption=asset.caption,
        created_at=isoformat_beijing(asset.created_at),
    )


def _retrieval_item(r: Any, *, user_id: str) -> RetrievalDebugItem:
    issued = issue_pdf_token(
        subject=user_id,
        document_id=r.document_id,
        knowledge_base_id=r.knowledge_base_id,
    )
    token = quote(issued.token)
    preview_url = (
        f"/api/v2/pdf/preview?document_id={r.document_id}"
        f"&page={r.page_start or 1}&token={token}"
    )
    bbox = _bbox_fragment(r.bbox)
    if bbox:
        preview_url = f"{preview_url}#bbox={bbox}"
    return RetrievalDebugItem(
        chunk_id=r.chunk_id,
        document_id=r.document_id,
        document_title=r.document_title,
        knowledge_base_id=r.knowledge_base_id,
        chunk_index=0,
        score=r.score,
        content=r.section_text,
        section_path=r.section_path,
        section_text=r.section_text,
        page_start=r.page_start,
        page_end=r.page_end,
        bbox=r.bbox,
        snippet=r.snippet,
        preview_url=preview_url,
        download_url=f"/api/v2/documents/{r.document_id}/download?token={token}",
    )


def _bbox_fragment(bbox: dict[str, Any] | None) -> str:
    if not bbox:
        return ""
    x = bbox.get("x", bbox.get("left"))
    y = bbox.get("y", bbox.get("top"))
    width = bbox.get("width", bbox.get("w"))
    height = bbox.get("height", bbox.get("h"))
    values = [x, y, width, height]
    if not all(isinstance(value, int | float) for value in values):
        return ""
    return ",".join(str(value) for value in values)


def _send_ingest_task(*, job_id: str, document_id: str, actor_user_id: str) -> None:
    settings = get_settings()
    if settings.app_env == "test":
        return
    celery_app.send_task(
        "ingest.process",
        queue="ingest-ocr",
        task_id=job_id,
        kwargs={
            "job_id": job_id,
            "document_id": document_id,
            "actor_user_id": actor_user_id,
        },
    )


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
