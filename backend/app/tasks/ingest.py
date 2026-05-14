from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from celery import Task
from sqlalchemy import select

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentIngestJob, DocumentParseResult
from app.services.deletion import (
    DOCUMENT_DELETING_STATUS,
    INGEST_CANCEL_REQUESTED_STATUS,
    collect_document_artifact_paths,
    delete_artifact_files,
    hard_delete_documents,
)
from app.services.ingest.asset_registry import register_assets
from app.services.ingest.chunker import chunk_outline
from app.services.ingest.dead_letter import mark_dead_letter
from app.services.ingest.idempotency import (
    get_receipt_payload,
    idempotency_key,
    run_idempotent_step,
)
from app.services.ingest.outline_parser import parse_outline
from app.services.ingest.track_a_indexer import TrackAIndexer
from app.services.ingest.track_b_indexer import write_page_index
from app.services.ocr.client import GlmOCRClient
from app.services.ocr.exceptions import OCRTransient
from app.tasks.async_runner import run_async_task


class IngestCancelled(Exception):
    pass


@celery_app.task(
    name="ingest.process",
    bind=True,
    acks_late=True,
    autoretry_for=(OCRTransient,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
)
def process(self: Task, *, job_id: str, document_id: str, actor_user_id: str) -> dict[str, Any]:
    return run_async_task(
        process_ingest_job(
            job_id,
            document_id,
            actor_user_id,
            retry_index=int(getattr(self.request, "retries", 0) or 0),
            max_retries=int(self.max_retries or 0),
            dispatch_postprocess=True,
        )
    )


@celery_app.task(name="ingest.retry")
def retry(job_id: str, document_id: str, actor_user_id: str) -> dict[str, Any]:
    return run_async_task(
        process_ingest_job(job_id, document_id, actor_user_id, dispatch_postprocess=True)
    )


@celery_app.task(name="ingest.postprocess", acks_late=True)
def postprocess(*, job_id: str, document_id: str, actor_user_id: str) -> dict[str, Any]:
    return run_async_task(postprocess_ingest_job(job_id, document_id, actor_user_id))


@celery_app.task(name="ingest.dead_letter_handler")
def dead_letter_handler(job_id: str) -> dict[str, str]:
    return {"job_id": job_id, "status": "observed"}


async def process_ingest_job(
    job_id: str,
    document_id: str,
    actor_user_id: str,
    *,
    retry_index: int = 0,
    max_retries: int = 5,
    dispatch_postprocess: bool = False,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        job = await db.scalar(
            select(DocumentIngestJob)
            .where(DocumentIngestJob.id == job_id)
            .with_for_update(skip_locked=True)
        )
        document = await db.get(Document, document_id)
        if document is None:
            return await _finish_cancelled_ingest(db, document_id=document_id, job_id=job_id)
        if job is None:
            raise ValueError("入库任务或文档不存在")
        active_job = job
        active_document = document
        ocr_session_id: str | None = None
        try:
            await _raise_if_cancelled(db, job_id=active_job.id, document_id=active_document.id)
            active_job.status = "running"
            active_job.attempt += 1
            active_document.status = "ocr"
            await db.commit()

            async with GlmOCRClient() as ocr:
                upload_payload = await run_idempotent_step(
                    db,
                    job_id=active_job.id,
                    step="upload_to_ocr",
                    input_payload={
                        "document_id": active_document.id,
                        "sha256": active_document.sha256,
                        "attempt": active_job.attempt,
                    },
                    runner=lambda: _upload_to_ocr(
                        ocr,
                        Path(active_document.storage_path),
                        job_id=active_job.id,
                        document_id=active_document.id,
                    ),
                )
                await db.commit()
                await _raise_if_cancelled(db, job_id=active_job.id, document_id=active_document.id)
                session_id = str(upload_payload["ocr_session_id"])
                ocr_session_id = session_id

                ocr_payload = await run_idempotent_step(
                    db,
                    job_id=active_job.id,
                    step="poll_and_fetch_ocr",
                    input_payload={"ocr_session_id": session_id},
                    runner=lambda: _poll_and_fetch(
                        ocr,
                        session_id,
                        cancel_checker=lambda: _raise_if_cancelled(
                            db,
                            job_id=active_job.id,
                            document_id=active_document.id,
                        ),
                    ),
                )
                await db.commit()
                await _raise_if_cancelled(db, job_id=active_job.id, document_id=active_document.id)
                await ocr.delete_session(session_id)
                ocr_session_id = None

            active_document.status = "embedding"
            await db.commit()
            await _raise_if_cancelled(db, job_id=active_job.id, document_id=active_document.id)
            if dispatch_postprocess:
                _dispatch_postprocess_task(
                    job_id=active_job.id,
                    document_id=active_document.id,
                    actor_user_id=actor_user_id,
                )
                return {
                    "document_id": active_document.id,
                    "job_id": active_job.id,
                    "status": "ocr_completed",
                    "next": "ingest.postprocess",
                }
            return await _postprocess_ocr_payload(
                db,
                job=active_job,
                document=active_document,
                actor_user_id=actor_user_id,
                ocr_session_id=session_id,
                ocr_payload=ocr_payload,
            )
        except IngestCancelled:
            await db.rollback()
            await _delete_ocr_session(ocr_session_id)
            return await _finish_cancelled_ingest(db, document_id=document_id, job_id=job_id)
        except OCRTransient as exc:
            await db.rollback()
            await _delete_ocr_session(ocr_session_id)
            job = await db.get(DocumentIngestJob, job_id)
            document = await db.get(Document, document_id)
            if job is not None and document is not None:
                if retry_index >= max_retries:
                    await mark_dead_letter(db, document=document, job=job, error=str(exc))
                else:
                    job.status = "queued"
                    job.last_error = str(exc)
                    document.status = "pending"
                await db.commit()
            raise
        except Exception as exc:
            await db.rollback()
            if await _is_cancelled_or_deleted(db, job_id=job_id, document_id=document_id):
                await _delete_ocr_session(ocr_session_id)
                return await _finish_cancelled_ingest(db, document_id=document_id, job_id=job_id)
            job = await db.get(DocumentIngestJob, job_id)
            document = await db.get(Document, document_id)
            if job is not None and document is not None:
                await mark_dead_letter(db, document=document, job=job, error=str(exc))
                await db.commit()
            raise


async def postprocess_ingest_job(
    job_id: str,
    document_id: str,
    actor_user_id: str,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        job = await db.scalar(
            select(DocumentIngestJob)
            .where(DocumentIngestJob.id == job_id)
            .with_for_update(skip_locked=True)
        )
        document = await db.get(Document, document_id)
        if document is None:
            return await _finish_cancelled_ingest(db, document_id=document_id, job_id=job_id)
        if job is None:
            raise ValueError("入库任务或文档不存在")
        try:
            await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)
            upload_payload = await _load_upload_payload(db, job=job, document=document)
            session_id = str(upload_payload["ocr_session_id"])
            ocr_payload = await _load_ocr_payload(db, job_id=job.id, session_id=session_id)
            if ocr_payload is None:
                raise ValueError("OCR 结果回执不存在，无法执行后处理")
            return await _postprocess_ocr_payload(
                db,
                job=job,
                document=document,
                actor_user_id=actor_user_id,
                ocr_session_id=session_id,
                ocr_payload=ocr_payload,
            )
        except IngestCancelled:
            await db.rollback()
            return await _finish_cancelled_ingest(db, document_id=document_id, job_id=job_id)
        except Exception as exc:
            await db.rollback()
            if await _is_cancelled_or_deleted(db, job_id=job_id, document_id=document_id):
                return await _finish_cancelled_ingest(db, document_id=document_id, job_id=job_id)
            job = await db.get(DocumentIngestJob, job_id)
            document = await db.get(Document, document_id)
            if job is not None and document is not None:
                await mark_dead_letter(db, document=document, job=job, error=str(exc))
                await db.commit()
            raise


async def _postprocess_ocr_payload(
    db: Any,
    *,
    job: DocumentIngestJob,
    document: Document,
    actor_user_id: str,
    ocr_session_id: str,
    ocr_payload: dict[str, Any],
) -> dict[str, Any]:
    del actor_user_id
    settings = get_settings()
    markdown = str(ocr_payload.get("markdown", ""))
    document.status = "embedding"
    await db.commit()
    await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)
    parsed_payload = await run_idempotent_step(
        db,
        job_id=job.id,
        step="parse_outline",
        input_payload={"markdown_sha256": _sha256(markdown)},
        runner=lambda: _parse(markdown),
    )
    await db.commit()
    await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)
    parsed = parse_outline(markdown)
    chunks = chunk_outline(parsed)
    await run_idempotent_step(
        db,
        job_id=job.id,
        step="section_aware_chunk",
        input_payload=parsed_payload,
        runner=lambda: _chunks_payload(chunks),
    )
    await db.commit()
    await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)

    indexer = TrackAIndexer()
    vectors_payload = await run_idempotent_step(
        db,
        job_id=job.id,
        step="embed_batch",
        input_payload={"chunk_sha256": [chunk.sha256 for chunk in chunks]},
        runner=lambda: _embed(indexer, chunks),
    )
    await db.commit()
    await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)
    vectors = [
        [float(value) for value in vector]
        for vector in vectors_payload.get("vectors", [])
        if isinstance(vector, list)
    ]

    document.status = "vector_indexing"
    await db.commit()
    await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)
    count_a = await indexer.write_chunks(
        db,
        knowledge_base_id=document.knowledge_base_id,
        document_id=document.id,
        doc_kind=document.doc_kind,
        scheme_type=document.scheme_type,
        chunks=chunks,
        vectors=vectors,
    )
    await run_idempotent_step(
        db,
        job_id=job.id,
        step="track_a_write",
        input_payload={"document_id": document.id, "count": count_a},
        runner=lambda: _static_payload({"count": count_a}),
    )
    await db.commit()
    await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)

    count_b = await write_page_index(db, document_id=document.id, chunks=chunks)
    await run_idempotent_step(
        db,
        job_id=job.id,
        step="track_b_write",
        input_payload={"document_id": document.id, "count": count_b},
        runner=lambda: _static_payload({"count": count_b}),
    )
    await db.commit()
    await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)

    assets_count = await register_assets(
        db,
        document_id=document.id,
        assets_payload=dict(ocr_payload.get("assets", {})),
        output_dir=Path(settings.upload_dir),
    )
    await run_idempotent_step(
        db,
        job_id=job.id,
        step="asset_register",
        input_payload={"document_id": document.id, "count": assets_count},
        runner=lambda: _static_payload({"count": assets_count}),
    )
    await db.commit()
    await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)

    markdown_path = Path(settings.upload_dir) / "markdown" / f"{document.id}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    layout = ocr_payload.get("layout", [])
    layout_path: Path | None = None
    if isinstance(layout, list) and layout:
        layout_path = markdown_path.with_suffix(".layout.json")
        layout_path.write_text(
            json.dumps(layout, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    await _upsert_parse_result(
        db,
        document=document,
        ocr_session_id=ocr_session_id,
        markdown_path=markdown_path,
        markdown=markdown,
        outline_json=parsed.to_dict(),
        stats={
            "chunk_count": len(chunks),
            "asset_count": assets_count,
            "layout_page_count": len(layout) if isinstance(layout, list) else 0,
            "layout_path": str(layout_path) if layout_path is not None else None,
        },
    )

    document.page_count = parsed.page_count
    document.status = "ready"
    job.status = "succeeded"
    job.last_error = None
    await _raise_if_cancelled(db, job_id=job.id, document_id=document.id)
    await run_idempotent_step(
        db,
        job_id=job.id,
        step="finalize",
        input_payload={"document_id": document.id, "status": "ready"},
        runner=lambda: _static_payload({"document_id": document.id, "status": "ready"}),
    )
    await db.commit()
    return {
        "document_id": document.id,
        "job_id": job.id,
        "status": "ready",
    }


async def _raise_if_cancelled(db: Any, *, job_id: str, document_id: str) -> None:
    if await _is_cancelled_or_deleted(db, job_id=job_id, document_id=document_id):
        raise IngestCancelled


async def _is_cancelled_or_deleted(db: Any, *, job_id: str, document_id: str) -> bool:
    document = await db.scalar(
        select(Document)
        .where(Document.id == document_id)
        .execution_options(populate_existing=True)
    )
    job = await db.scalar(
        select(DocumentIngestJob)
        .where(DocumentIngestJob.id == job_id)
        .execution_options(populate_existing=True)
    )
    if document is None or job is None:
        return True
    return (
        document.status == DOCUMENT_DELETING_STATUS or job.status == INGEST_CANCEL_REQUESTED_STATUS
    )


async def _finish_cancelled_ingest(db: Any, *, document_id: str, job_id: str) -> dict[str, Any]:
    artifact_paths = await collect_document_artifact_paths(db, [document_id])
    await hard_delete_documents(db, [document_id])
    await db.commit()
    delete_artifact_files(artifact_paths)
    return {"document_id": document_id, "job_id": job_id, "status": "cancelled"}


async def _delete_ocr_session(session_id: str | None) -> None:
    if not session_id:
        return
    try:
        async with GlmOCRClient() as ocr:
            await ocr.delete_session(session_id)
    except Exception:
        return


def _dispatch_postprocess_task(*, job_id: str, document_id: str, actor_user_id: str) -> None:
    celery_app.send_task(
        "ingest.postprocess",
        queue="ingest",
        task_id=job_id,
        kwargs={
            "job_id": job_id,
            "document_id": document_id,
            "actor_user_id": actor_user_id,
        },
    )


async def _load_upload_payload(
    db: Any,
    *,
    job: DocumentIngestJob,
    document: Document,
) -> dict[str, Any]:
    key = idempotency_key(
        job.id,
        "upload_to_ocr",
        {
            "document_id": document.id,
            "sha256": document.sha256,
            "attempt": job.attempt,
        },
    )
    payload = await get_receipt_payload(db, key=key)
    if payload is None:
        raise ValueError("OCR 上传回执不存在，无法执行后处理")
    return payload


async def _load_ocr_payload(db: Any, *, job_id: str, session_id: str) -> dict[str, Any] | None:
    key = idempotency_key(job_id, "poll_and_fetch_ocr", {"ocr_session_id": session_id})
    return await get_receipt_payload(db, key=key)


async def _upload_to_ocr(
    ocr: GlmOCRClient,
    path: Path,
    *,
    job_id: str,
    document_id: str,
) -> dict[str, Any]:
    callback_url = _ocr_callback_url(job_id=job_id, document_id=document_id)
    session_id = await ocr.upload(path, callback_url=callback_url)
    return {"ocr_session_id": session_id}


async def _poll_and_fetch(
    ocr: GlmOCRClient,
    session_id: str,
    *,
    cancel_checker: Any = None,
) -> dict[str, Any]:
    status_payload = await ocr.poll_until_done(session_id, cancel_checker=cancel_checker)
    markdown_payload = await ocr.fetch_markdown(session_id, include_meta=True)
    assets_payload = await ocr.fetch_images_b64(session_id)
    try:
        layout_payload = await ocr.fetch_layout(session_id)
    except Exception:
        layout_payload = {"session_id": session_id, "layout": []}
    return {
        "status": status_payload,
        "markdown": markdown_payload.get("markdown", ""),
        "assets": assets_payload,
        "layout": layout_payload.get("layout", []),
    }


async def _parse(markdown: str) -> dict[str, Any]:
    return parse_outline(markdown).to_dict()


async def _chunks_payload(chunks: list[Any]) -> dict[str, Any]:
    return {"chunks": [chunk.to_dict() for chunk in chunks], "count": len(chunks)}


async def _embed(indexer: TrackAIndexer, chunks: list[Any]) -> dict[str, Any]:
    vectors = await indexer.embed_chunks(chunks)
    return {"vectors": vectors, "count": len(vectors)}


async def _static_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


async def _upsert_parse_result(
    db: Any,
    *,
    document: Document,
    ocr_session_id: str,
    markdown_path: Path,
    markdown: str,
    outline_json: dict[str, Any],
    stats: dict[str, Any],
) -> None:
    result = await db.scalar(
        select(DocumentParseResult).where(DocumentParseResult.document_id == document.id)
    )
    if result is None:
        result = DocumentParseResult(
            document_id=document.id,
            ocr_session_id=ocr_session_id,
            markdown_path=str(markdown_path),
            markdown_sha256=_sha256(markdown),
            outline_json=outline_json,
            stats_json=stats,
        )
        db.add(result)
    else:
        result.ocr_session_id = ocr_session_id
        result.markdown_path = str(markdown_path)
        result.markdown_sha256 = _sha256(markdown)
        result.outline_json = outline_json
        result.stats_json = stats
    await db.flush()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ocr_callback_url(*, job_id: str, document_id: str) -> str | None:
    settings = get_settings()
    base_url = settings.ocr_callback_base_url.strip().rstrip("/")
    if not base_url:
        return None
    query = urlencode({"job_id": job_id, "document_id": document_id})
    return f"{base_url}/api/v2/ocr/callback?{query}"
