from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from celery import Task
from sqlalchemy import select

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentIngestJob, DocumentParseResult
from app.services.ingest.asset_registry import register_assets
from app.services.ingest.chunker import chunk_outline
from app.services.ingest.dead_letter import mark_dead_letter
from app.services.ingest.idempotency import run_idempotent_step
from app.services.ingest.outline_parser import parse_outline
from app.services.ingest.track_a_indexer import TrackAIndexer
from app.services.ingest.track_b_indexer import write_page_index
from app.services.ocr.client import DeepSeekOCRClient
from app.services.ocr.exceptions import OCRTransient


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
    return asyncio.run(process_ingest_job(job_id, document_id, actor_user_id))


@celery_app.task(name="ingest.retry")
def retry(job_id: str, document_id: str, actor_user_id: str) -> dict[str, Any]:
    return asyncio.run(process_ingest_job(job_id, document_id, actor_user_id))


@celery_app.task(name="ingest.dead_letter_handler")
def dead_letter_handler(job_id: str) -> dict[str, str]:
    return {"job_id": job_id, "status": "observed"}


async def process_ingest_job(job_id: str, document_id: str, actor_user_id: str) -> dict[str, Any]:
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        job = await db.scalar(
            select(DocumentIngestJob)
            .where(DocumentIngestJob.id == job_id)
            .with_for_update(skip_locked=True)
        )
        document = await db.get(Document, document_id)
        if job is None or document is None:
            raise ValueError("入库任务或文档不存在")
        active_job = job
        active_document = document
        try:
            active_job.status = "running"
            active_job.attempt += 1
            active_document.status = "ocr"
            await db.commit()

            async with DeepSeekOCRClient() as ocr:
                upload_payload = await run_idempotent_step(
                    db,
                    job_id=active_job.id,
                    step="upload_to_ocr",
                    input_payload={
                        "document_id": active_document.id,
                        "sha256": active_document.sha256,
                    },
                    runner=lambda: _upload_to_ocr(
                        ocr,
                        Path(active_document.storage_path),
                        job_id=active_job.id,
                        document_id=active_document.id,
                    ),
                )
                session_id = str(upload_payload["ocr_session_id"])

                ocr_payload = await run_idempotent_step(
                    db,
                    job_id=active_job.id,
                    step="poll_and_fetch_ocr",
                    input_payload={"ocr_session_id": session_id},
                    runner=lambda: _poll_and_fetch(ocr, session_id),
                )
                await ocr.delete_session(session_id)

            markdown = str(ocr_payload.get("markdown", ""))
            active_document.status = "parsing"
            parsed_payload = await run_idempotent_step(
                db,
                job_id=active_job.id,
                step="parse_outline",
                input_payload={"markdown_sha256": _sha256(markdown)},
                runner=lambda: _parse(markdown),
            )
            parsed = parse_outline(markdown)
            chunks = chunk_outline(parsed)
            active_document.status = "indexing"
            await run_idempotent_step(
                db,
                job_id=active_job.id,
                step="section_aware_chunk",
                input_payload=parsed_payload,
                runner=lambda: _chunks_payload(chunks),
            )

            indexer = TrackAIndexer()
            vectors_payload = await run_idempotent_step(
                db,
                job_id=active_job.id,
                step="embed_batch",
                input_payload={"chunk_sha256": [chunk.sha256 for chunk in chunks]},
                runner=lambda: _embed(indexer, chunks),
            )
            vectors = [
                [float(value) for value in vector]
                for vector in vectors_payload.get("vectors", [])
                if isinstance(vector, list)
            ]

            count_a = await indexer.write_chunks(
                db,
                knowledge_base_id=active_document.knowledge_base_id,
                document_id=active_document.id,
                doc_kind=active_document.doc_kind,
                scheme_type=active_document.scheme_type,
                chunks=chunks,
                vectors=vectors,
            )
            await run_idempotent_step(
                db,
                job_id=active_job.id,
                step="track_a_write",
                input_payload={"document_id": active_document.id, "count": count_a},
                runner=lambda: _static_payload({"count": count_a}),
            )

            count_b = await write_page_index(db, document_id=active_document.id, chunks=chunks)
            await run_idempotent_step(
                db,
                job_id=active_job.id,
                step="track_b_write",
                input_payload={"document_id": active_document.id, "count": count_b},
                runner=lambda: _static_payload({"count": count_b}),
            )

            assets_count = await register_assets(
                db,
                document_id=active_document.id,
                assets_payload=dict(ocr_payload.get("assets", {})),
                output_dir=Path(settings.upload_dir),
            )
            await run_idempotent_step(
                db,
                job_id=active_job.id,
                step="asset_register",
                input_payload={"document_id": active_document.id, "count": assets_count},
                runner=lambda: _static_payload({"count": assets_count}),
            )

            markdown_path = Path(settings.upload_dir) / "markdown" / f"{active_document.id}.md"
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(markdown, encoding="utf-8")
            await _upsert_parse_result(
                db,
                document=active_document,
                ocr_session_id=session_id,
                markdown_path=markdown_path,
                markdown=markdown,
                outline_json=parsed.to_dict(),
                stats={"chunk_count": len(chunks), "asset_count": assets_count},
            )

            active_document.page_count = parsed.page_count
            active_document.status = "ready"
            active_job.status = "succeeded"
            active_job.last_error = None
            await run_idempotent_step(
                db,
                job_id=active_job.id,
                step="finalize",
                input_payload={"document_id": active_document.id, "status": "ready"},
                runner=lambda: _static_payload(
                    {"document_id": active_document.id, "status": "ready"}
                ),
            )
            await db.commit()
            return {
                "document_id": active_document.id,
                "job_id": active_job.id,
                "status": "ready",
            }
        except Exception as exc:
            await db.rollback()
            job = await db.get(DocumentIngestJob, job_id)
            document = await db.get(Document, document_id)
            if job is not None and document is not None:
                await mark_dead_letter(db, document=document, job=job, error=str(exc))
                await db.commit()
            raise


async def _upload_to_ocr(
    ocr: DeepSeekOCRClient,
    path: Path,
    *,
    job_id: str,
    document_id: str,
) -> dict[str, Any]:
    callback_url = _ocr_callback_url(job_id=job_id, document_id=document_id)
    session_id = await ocr.upload(path, callback_url=callback_url)
    return {"ocr_session_id": session_id}


async def _poll_and_fetch(ocr: DeepSeekOCRClient, session_id: str) -> dict[str, Any]:
    status_payload = await ocr.poll_until_done(session_id)
    markdown_payload = await ocr.fetch_markdown(session_id, include_meta=True)
    assets_payload = await ocr.fetch_images_b64(session_id)
    return {
        "status": status_payload,
        "markdown": markdown_payload.get("markdown", ""),
        "assets": assets_payload,
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
