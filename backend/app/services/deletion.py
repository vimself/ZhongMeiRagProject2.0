from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.core.config import get_settings
from app.models.chat import ChatMessageCitation, ChatSession
from app.models.document import (
    Document,
    DocumentAsset,
    DocumentIngestJob,
    DocumentParseResult,
    IngestStepReceipt,
    KnowledgeChunkV2,
    KnowledgePageIndexV2,
)
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.services.ingest.idempotency import external_payload_path, load_stored_payload
from app.services.ocr.client import GlmOCRClient

T = TypeVar("T")
DOCUMENT_DELETING_STATUS = "deleting"
INGEST_CANCEL_REQUESTED_STATUS = "cancel_requested"
INGEST_CANCELLED_STATUS = "cancelled"
INGEST_TERMINAL_STATUSES = {"succeeded", "dead", "failed", INGEST_CANCELLED_STATUS}


@dataclass(frozen=True)
class DocumentDeletionResources:
    artifact_paths: list[str]
    job_ids: list[str]
    ocr_session_ids: list[str]


async def collect_document_deletion_resources(
    db: AsyncSession, document_ids: list[str]
) -> DocumentDeletionResources:
    compact_ids = list(dict.fromkeys(document_ids))
    if not compact_ids:
        return DocumentDeletionResources(artifact_paths=[], job_ids=[], ocr_session_ids=[])
    artifact_paths = await collect_document_artifact_paths(db, compact_ids)
    job_ids = await collect_document_ingest_job_ids(db, compact_ids)
    ocr_session_ids = await collect_document_ocr_session_ids(db, compact_ids)
    return DocumentDeletionResources(
        artifact_paths=artifact_paths,
        job_ids=job_ids,
        ocr_session_ids=ocr_session_ids,
    )


async def collect_document_artifact_paths(db: AsyncSession, document_ids: list[str]) -> list[str]:
    if not document_ids:
        return []

    paths: list[str] = []
    document_rows = await db.execute(
        select(Document.storage_path).where(Document.id.in_(document_ids))
    )
    paths.extend(str(path) for path in document_rows.scalars().all() if path)

    parse_rows = await db.execute(
        select(DocumentParseResult.markdown_path).where(
            DocumentParseResult.document_id.in_(document_ids)
        )
    )
    paths.extend(str(path) for path in parse_rows.scalars().all() if path)

    asset_rows = await db.execute(
        select(DocumentAsset.storage_path).where(DocumentAsset.document_id.in_(document_ids))
    )
    paths.extend(str(path) for path in asset_rows.scalars().all() if path)

    job_ids = list(
        await db.scalars(
            select(DocumentIngestJob.id).where(DocumentIngestJob.document_id.in_(document_ids))
        )
    )
    if job_ids:
        receipt_rows = await db.execute(
            select(IngestStepReceipt.payload_json).where(IngestStepReceipt.job_id.in_(job_ids))
        )
        paths.extend(_collect_receipt_payload_paths(receipt_rows.scalars().all()))
    return list(dict.fromkeys(paths))


async def collect_document_ingest_job_ids(
    db: AsyncSession, document_ids: list[str]
) -> list[str]:
    compact_ids = list(dict.fromkeys(document_ids))
    if not compact_ids:
        return []
    return list(
        dict.fromkeys(
            await db.scalars(
                select(DocumentIngestJob.id).where(
                    DocumentIngestJob.document_id.in_(compact_ids)
                )
            )
        )
    )


async def collect_document_ocr_session_ids(
    db: AsyncSession, document_ids: list[str]
) -> list[str]:
    compact_ids = list(dict.fromkeys(document_ids))
    if not compact_ids:
        return []

    session_ids: list[str] = []
    parse_rows = await db.scalars(
        select(DocumentParseResult.ocr_session_id).where(
            DocumentParseResult.document_id.in_(compact_ids)
        )
    )
    session_ids.extend(str(value) for value in parse_rows if value)

    receipt_rows = await db.execute(
        select(IngestStepReceipt.payload_json)
        .join(DocumentIngestJob, IngestStepReceipt.job_id == DocumentIngestJob.id)
        .where(
            DocumentIngestJob.document_id.in_(compact_ids),
            IngestStepReceipt.step == "upload_to_ocr",
            IngestStepReceipt.status == "succeeded",
        )
    )
    for stored_payload in receipt_rows.scalars().all():
        payload = load_stored_payload(stored_payload)
        if not isinstance(payload, dict):
            continue
        session_id = payload.get("ocr_session_id")
        if isinstance(session_id, str) and session_id:
            session_ids.append(session_id)

    return list(dict.fromkeys(session_ids))


async def hard_delete_documents(
    db: AsyncSession,
    document_ids: list[str],
    *,
    remove_chat_citations: bool = True,
    delete_files: bool = True,
) -> int:
    compact_ids = list(dict.fromkeys(document_ids))
    if not compact_ids:
        return 0

    artifact_paths = await collect_document_artifact_paths(db, compact_ids) if delete_files else []
    await request_document_deletion(db, compact_ids)
    job_ids = list(
        await db.scalars(
            select(DocumentIngestJob.id).where(DocumentIngestJob.document_id.in_(compact_ids))
        )
    )
    if remove_chat_citations:
        await db.execute(
            delete(ChatMessageCitation).where(ChatMessageCitation.document_id.in_(compact_ids))
        )
    if job_ids:
        await db.execute(delete(IngestStepReceipt).where(IngestStepReceipt.job_id.in_(job_ids)))
    await db.execute(
        delete(KnowledgePageIndexV2).where(KnowledgePageIndexV2.document_id.in_(compact_ids))
    )
    await db.execute(delete(KnowledgeChunkV2).where(KnowledgeChunkV2.document_id.in_(compact_ids)))
    await db.execute(delete(DocumentAsset).where(DocumentAsset.document_id.in_(compact_ids)))
    await db.execute(
        delete(DocumentParseResult).where(DocumentParseResult.document_id.in_(compact_ids))
    )
    await db.execute(
        delete(DocumentIngestJob).where(DocumentIngestJob.document_id.in_(compact_ids))
    )
    result = await _without_mysql_foreign_key_checks(
        db,
        lambda: db.execute(delete(Document).where(Document.id.in_(compact_ids))),
    )
    if delete_files:
        delete_artifact_files(artifact_paths)
    return int(result.rowcount or 0)


async def request_document_deletion(db: AsyncSession, document_ids: list[str]) -> None:
    compact_ids = list(dict.fromkeys(document_ids))
    if not compact_ids:
        return
    await db.execute(
        update(Document).where(Document.id.in_(compact_ids)).values(status=DOCUMENT_DELETING_STATUS)
    )
    await db.execute(
        update(DocumentIngestJob)
        .where(
            DocumentIngestJob.document_id.in_(compact_ids),
            DocumentIngestJob.status.notin_(INGEST_TERMINAL_STATUSES),
        )
        .values(status=INGEST_CANCEL_REQUESTED_STATUS)
    )


async def release_document_ingest_resources(resources: DocumentDeletionResources) -> None:
    revoke_ingest_tasks(resources.job_ids)
    await delete_ocr_sessions(resources.ocr_session_ids)


def revoke_ingest_tasks(job_ids: list[str]) -> None:
    compact_ids = list(dict.fromkeys(job_ids))
    if not compact_ids or get_settings().app_env == "test":
        return
    for job_id in compact_ids:
        try:
            celery_app.control.revoke(job_id, terminate=False)
        except Exception:
            continue


async def delete_ocr_sessions(session_ids: list[str]) -> None:
    compact_ids = list(dict.fromkeys(session_ids))
    if not compact_ids or get_settings().app_env == "test":
        return
    async with GlmOCRClient() as ocr:
        for session_id in compact_ids:
            try:
                await ocr.delete_session(session_id)
            except Exception:
                continue


async def hard_delete_knowledge_base(db: AsyncSession, kb_id: str) -> dict[str, int]:
    document_ids = list(
        await db.scalars(select(Document.id).where(Document.knowledge_base_id == kb_id))
    )

    await db.execute(
        update(ChatSession)
        .where(ChatSession.knowledge_base_id == kb_id)
        .values(knowledge_base_id=None)
    )
    await db.execute(
        delete(ChatMessageCitation).where(ChatMessageCitation.knowledge_base_id == kb_id)
    )
    await hard_delete_documents(db, document_ids, remove_chat_citations=False, delete_files=False)
    await db.execute(delete(KnowledgeChunkV2).where(KnowledgeChunkV2.knowledge_base_id == kb_id))
    permission_result = await db.execute(
        delete(KnowledgeBasePermission).where(KnowledgeBasePermission.knowledge_base_id == kb_id)
    )
    kb_result = await _without_mysql_foreign_key_checks(
        db,
        lambda: db.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb_id)),
    )
    return {
        "document_count": len(document_ids),
        "permission_count": int(permission_result.rowcount or 0),
        "knowledge_base_count": int(kb_result.rowcount or 0),
    }


def delete_artifact_files(paths: list[str]) -> int:
    deleted = 0
    for raw_path in paths:
        file_path = _resolve_safe_upload_file(raw_path)
        if file_path is None:
            continue
        try:
            file_path.unlink(missing_ok=True)
            deleted += 1
        except OSError:
            continue
    return deleted


async def _without_mysql_foreign_key_checks(
    db: AsyncSession,
    operation: Callable[[], Awaitable[T]],
) -> T:
    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""
    if dialect_name not in {"mysql", "mariadb"}:
        return await operation()

    await db.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    try:
        return await operation()
    finally:
        await db.execute(text("SET FOREIGN_KEY_CHECKS=1"))


def _resolve_safe_upload_file(raw_path: str) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return None
    if not resolved.is_file():
        return None

    settings = get_settings()
    allowed_roots = [Path(settings.upload_dir)]
    for root in allowed_roots:
        root_path = root if root.is_absolute() else Path.cwd() / root
        try:
            resolved.relative_to(root_path.resolve(strict=False))
            return resolved
        except ValueError:
            continue
    return None


def _collect_receipt_payload_paths(payloads: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for payload in payloads:
        path = external_payload_path(payload)
        if path:
            paths.append(path)
    return paths
