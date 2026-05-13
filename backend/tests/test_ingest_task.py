from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models.auth import AuditLog, User
from app.models.document import (
    Document,
    DocumentIngestJob,
    DocumentParseResult,
    IngestStepReceipt,
    KnowledgeChunkV2,
    KnowledgePageIndexV2,
)
from app.models.knowledge_base import KnowledgeBase
from app.security.password import hash_password
from app.services.deletion import hard_delete_documents
from app.services.ingest.dead_letter import mark_dead_letter
from app.services.ingest.idempotency import run_idempotent_step
from app.services.ocr.exceptions import OCRFailed
from app.tasks.ingest import process_ingest_job


@pytest.fixture(autouse=True)
def reset_database() -> None:
    async def _reset() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_reset())


class FakeOCR:
    def __init__(self) -> None:
        self.session_id = "sid-1"
        self.callback_url: str | None = None

    async def __aenter__(self) -> FakeOCR:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def upload(self, _path: Path, *, callback_url: str | None = None) -> str:
        self.callback_url = callback_url
        return self.session_id

    async def poll_until_done(self, _session_id: str) -> dict[str, Any]:
        return {"status": "completed"}

    async def fetch_markdown(self, _session_id: str, include_meta: bool = False) -> dict[str, Any]:
        assert include_meta is True
        return {"markdown": "# 总则\n施工方案内容"}

    async def fetch_images_b64(self, _session_id: str) -> dict[str, Any]:
        return {"images": [{"name": "a.jpg", "base64": "AA==", "page_no": 1}]}

    async def delete_session(self, _session_id: str) -> bool:
        return True


class FailingOCR(FakeOCR):
    async def poll_until_done(self, _session_id: str) -> dict[str, Any]:
        raise OCRFailed("ocr failed")


class FakeTrackAIndexer:
    async def embed_chunks(self, chunks: list[Any]) -> list[list[float]]:
        return [[0.1, 0.2] for _chunk in chunks]

    async def write_chunks(
        self,
        db: AsyncSession,
        *,
        knowledge_base_id: str,
        document_id: str,
        doc_kind: str,
        scheme_type: str | None,
        chunks: list[Any],
        vectors: list[list[float]],
    ) -> int:
        await db.execute(
            delete(KnowledgeChunkV2).where(KnowledgeChunkV2.document_id == document_id)
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            db.add(
                KnowledgeChunkV2(
                    knowledge_base_id=knowledge_base_id,
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    section_path=chunk.section_path,
                    section_id=chunk.section_id,
                    content_type=chunk.content_type,
                    doc_kind=doc_kind,
                    scheme_type=scheme_type,
                    tokens=chunk.tokens,
                    sha256=chunk.sha256,
                    vector=vector,
                )
            )
        await db.flush()
        return len(chunks)


async def _seed(tmp_path: Path) -> None:
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
    async with AsyncSessionLocal() as session:
        user = User(
            id="user-id",
            username="u",
            display_name="用户",
            role="admin",
            password_hash=hash_password("pass"),
        )
        kb = KnowledgeBase(id="kb-id", name="KB", description="", creator_id=user.id)
        doc = Document(
            id="doc-id",
            knowledge_base_id=kb.id,
            uploader_id=user.id,
            title="文档",
            filename="a.pdf",
            mime="application/pdf",
            size_bytes=10,
            sha256="doc-sha",
            storage_path=str(pdf_path),
        )
        job = DocumentIngestJob(id="job-id", document_id=doc.id, status="queued")
        session.add_all([user, kb, doc, job])
        await session.commit()


def _patch_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr("app.tasks.ingest.DeepSeekOCRClient", FakeOCR)
    monkeypatch.setattr("app.tasks.ingest.TrackAIndexer", FakeTrackAIndexer)


@pytest.mark.asyncio
async def test_process_ingest_job_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    await _seed(tmp_path)
    _patch_success(monkeypatch, tmp_path)
    result = await process_ingest_job("job-id", "doc-id", "user-id")
    assert result["status"] == "ready"


@pytest.mark.asyncio
async def test_process_marks_document_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await _seed(tmp_path)
    _patch_success(monkeypatch, tmp_path)
    await process_ingest_job("job-id", "doc-id", "user-id")
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, "doc-id")
    assert doc is not None
    assert doc.status == "ready"


@pytest.mark.asyncio
async def test_process_writes_receipts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    await _seed(tmp_path)
    _patch_success(monkeypatch, tmp_path)
    await process_ingest_job("job-id", "doc-id", "user-id")
    async with AsyncSessionLocal() as session:
        receipts = (await session.execute(select(IngestStepReceipt))).scalars().all()
    assert {receipt.step for receipt in receipts} >= {"upload_to_ocr", "finalize"}


@pytest.mark.asyncio
async def test_process_writes_parse_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    await _seed(tmp_path)
    _patch_success(monkeypatch, tmp_path)
    await process_ingest_job("job-id", "doc-id", "user-id")
    async with AsyncSessionLocal() as session:
        result = await session.scalar(select(DocumentParseResult))
    assert result is not None
    assert result.ocr_session_id == "sid-1"


@pytest.mark.asyncio
async def test_process_writes_chunk_and_page_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await _seed(tmp_path)
    _patch_success(monkeypatch, tmp_path)
    await process_ingest_job("job-id", "doc-id", "user-id")
    async with AsyncSessionLocal() as session:
        chunks = (await session.execute(select(KnowledgeChunkV2))).scalars().all()
        pages = (await session.execute(select(KnowledgePageIndexV2))).scalars().all()
    assert chunks
    assert pages


@pytest.mark.asyncio
async def test_process_is_idempotent_on_same_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await _seed(tmp_path)
    _patch_success(monkeypatch, tmp_path)
    await process_ingest_job("job-id", "doc-id", "user-id")
    await process_ingest_job("job-id", "doc-id", "user-id")
    async with AsyncSessionLocal() as session:
        receipts = (await session.execute(select(IngestStepReceipt))).scalars().all()
    assert len(receipts) == len({receipt.idempotency_key for receipt in receipts})


@pytest.mark.asyncio
async def test_process_failure_marks_dead(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    await _seed(tmp_path)
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr("app.tasks.ingest.DeepSeekOCRClient", FailingOCR)
    with pytest.raises(OCRFailed):
        await process_ingest_job("job-id", "doc-id", "user-id")
    async with AsyncSessionLocal() as session:
        job = await session.get(DocumentIngestJob, "job-id")
        doc = await session.get(Document, "doc-id")
    assert job is not None and job.status == "dead"
    assert doc is not None and doc.status == "failed"


@pytest.mark.asyncio
async def test_process_cancel_requested_hard_deletes_document(tmp_path: Path) -> None:
    await _seed(tmp_path)
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, "doc-id")
        job = await session.get(DocumentIngestJob, "job-id")
        assert doc is not None and job is not None
        doc.status = "deleting"
        job.status = "cancel_requested"
        await session.commit()

    result = await process_ingest_job("job-id", "doc-id", "user-id")
    assert result["status"] == "cancelled"

    async with AsyncSessionLocal() as session:
        doc_count = len(list(await session.scalars(select(Document))))
        job_count = len(list(await session.scalars(select(DocumentIngestJob))))
        audit_count = len(
            list(
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == "ingest.step_failed")
                )
            )
        )
    assert (doc_count, job_count, audit_count) == (0, 0, 0)


@pytest.mark.asyncio
async def test_process_stale_deleted_document_returns_cancelled(tmp_path: Path) -> None:
    await _seed(tmp_path)
    async with AsyncSessionLocal() as session:
        await hard_delete_documents(session, ["doc-id"])
        await session.commit()

    result = await process_ingest_job("job-id", "doc-id", "user-id")
    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_process_missing_job_raises(tmp_path: Path) -> None:
    await _seed(tmp_path)
    with pytest.raises(ValueError):
        await process_ingest_job("missing", "doc-id", "user-id")


@pytest.mark.asyncio
async def test_dead_letter_writes_audit(tmp_path: Path) -> None:
    await _seed(tmp_path)
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, "doc-id")
        job = await session.get(DocumentIngestJob, "job-id")
        assert doc is not None and job is not None
        await mark_dead_letter(session, document=doc, job=job, error="boom")
        await session.commit()
    async with AsyncSessionLocal() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "ingest.step_failed")
        )
    assert audit is not None
    assert audit.actor_user_id == "user-id"


@pytest.mark.asyncio
async def test_idempotent_step_reuses_payload(tmp_path: Path) -> None:
    await _seed(tmp_path)
    calls = 0

    async def runner() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    async with AsyncSessionLocal() as session:
        first = await run_idempotent_step(
            session,
            job_id="job-id",
            step="upload_to_ocr",
            input_payload={"a": 1},
            runner=runner,
        )
        second = await run_idempotent_step(
            session,
            job_id="job-id",
            step="upload_to_ocr",
            input_payload={"a": 1},
            runner=runner,
        )
    assert first == second
    assert calls == 1
