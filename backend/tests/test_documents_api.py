from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.main import create_app
from app.models.auth import AuditLog, User
from app.models.document import (
    Document,
    DocumentIngestJob,
    IngestCallbackReceipt,
    IngestStepReceipt,
    KnowledgeChunkV2,
)
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.security.login_limiter import login_failure_limiter
from app.security.password import hash_password
from app.services.rag.retriever import Retriever


@pytest.fixture(autouse=True)
def reset_database() -> None:
    async def _reset() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        login_failure_limiter.clear_memory()

    asyncio.run(_reset())


def _seed() -> None:
    async def _inner() -> None:
        async with AsyncSessionLocal() as session:
            admin = User(
                id="admin-id",
                username="admin",
                display_name="管理员",
                role="admin",
                password_hash=hash_password("admin-pass"),
            )
            viewer = User(
                id="viewer-id",
                username="viewer",
                display_name="查看者",
                role="user",
                password_hash=hash_password("user-pass"),
            )
            other = User(
                id="other-id",
                username="other",
                display_name="其他用户",
                role="user",
                password_hash=hash_password("user-pass"),
            )
            kb = KnowledgeBase(id="kb-id", name="KB", description="", creator_id=admin.id)
            perm = KnowledgeBasePermission(
                knowledge_base_id=kb.id,
                user_id=viewer.id,
                role="viewer",
            )
            session.add_all([admin, viewer, other, kb, perm])
            await session.commit()

    asyncio.run(_inner())


def _seed_document(status: str = "pending") -> None:
    async def _inner() -> None:
        async with AsyncSessionLocal() as session:
            doc = Document(
                id="doc-id",
                knowledge_base_id="kb-id",
                uploader_id="admin-id",
                title="测试文档",
                filename="test.pdf",
                mime="application/pdf",
                size_bytes=20,
                sha256="sha",
                storage_path="uploads/documents/test.pdf",
                status=status,
            )
            job = DocumentIngestJob(id="job-id", document_id=doc.id, status="queued")
            session.add_all([doc, job])
            await session.commit()

    asyncio.run(_inner())


def _client_and_token(
    username: str = "admin", password: str = "admin-pass"
) -> tuple[TestClient, str]:
    client = TestClient(create_app())
    resp = client.post("/api/v2/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return client, str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _pdf_file(
    name: str = "test.pdf", content: bytes = b"%PDF-1.4\n%%EOF"
) -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, content, "application/pdf")}


def test_upload_document_success() -> None:
    _seed()
    client, token = _client_and_token()
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_file(),
        data={"doc_kind": "plan"},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["document_id"]


def test_upload_document_writes_audit_log() -> None:
    _seed()
    client, token = _client_and_token()
    client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_file(),
    )

    async def _actions() -> list[str]:
        async with AsyncSessionLocal() as session:
            return list(await session.scalars(select(AuditLog.action)))

    assert "document.upload" in asyncio.run(_actions())


def test_upload_rejects_invalid_extension() -> None:
    _seed()
    client, token = _client_and_token()
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_file(name="test.txt"),
    )
    assert resp.status_code == 400


def test_upload_rejects_invalid_magic() -> None:
    _seed()
    client, token = _client_and_token()
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_file(content=b"not pdf"),
    )
    assert resp.status_code == 400


def test_upload_rejects_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed()
    settings = get_settings()
    original = settings.upload_max_mb
    monkeypatch.setattr(settings, "upload_max_mb", 0)
    client, token = _client_and_token()
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_file(),
    )
    monkeypatch.setattr(settings, "upload_max_mb", original)
    assert resp.status_code == 400


def test_upload_requires_editor_permission() -> None:
    _seed()
    client, token = _client_and_token("viewer", "user-pass")
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_file(),
    )
    assert resp.status_code == 403


def test_upload_requires_auth() -> None:
    _seed()
    client = TestClient(create_app())
    resp = client.post("/api/v2/knowledge-bases/kb-id/documents", files=_pdf_file())
    assert resp.status_code in {401, 403}


def test_list_documents_search_and_status() -> None:
    _seed()
    _seed_document(status="ready")
    client, token = _client_and_token()
    resp = client.get(
        "/api/v2/knowledge-bases/kb-id/documents?search=测试&status=ready",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_get_document_detail() -> None:
    _seed()
    _seed_document()
    client, token = _client_and_token()
    resp = client.get("/api/v2/documents/doc-id", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["latest_job"]["id"] == "job-id"


def test_get_progress_with_receipts() -> None:
    _seed()
    _seed_document()

    async def _receipt() -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                IngestStepReceipt(
                    job_id="job-id",
                    step="upload_to_ocr",
                    idempotency_key="k",
                    status="succeeded",
                    payload_json={},
                )
            )
            await session.commit()

    asyncio.run(_receipt())
    client, token = _client_and_token()
    resp = client.get("/api/v2/documents/doc-id/progress", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["progress"] > 0


def test_retry_document_requeues() -> None:
    _seed()
    _seed_document(status="failed")
    client, token = _client_and_token()
    resp = client.post("/api/v2/documents/doc-id/retry", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_disable_document_soft_deletes() -> None:
    _seed()
    _seed_document()
    client, token = _client_and_token()
    resp = client.delete("/api/v2/documents/doc-id", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"


def test_disabled_document_is_not_retrieved() -> None:
    _seed()
    _seed_document(status="disabled")

    async def _retrieve() -> int:
        async with AsyncSessionLocal() as session:
            session.add(
                KnowledgeChunkV2(
                    knowledge_base_id="kb-id",
                    document_id="doc-id",
                    chunk_index=0,
                    content="塔吊基础专项施工方案",
                    section_path=["1"],
                    section_id="1",
                    doc_kind="plan",
                    tokens=8,
                    sha256="chunk-sha",
                )
            )
            await session.commit()
            results = await Retriever(session).retrieve(kb_id="kb-id", query="塔吊基础")
            return len(results)

    assert asyncio.run(_retrieve()) == 0


def test_document_in_deleted_kb_is_not_accessible() -> None:
    _seed()
    _seed_document(status="ready")

    async def _disable_kb() -> None:
        async with AsyncSessionLocal() as session:
            kb = await session.get(KnowledgeBase, "kb-id")
            assert kb is not None
            kb.is_active = False
            await session.commit()

    asyncio.run(_disable_kb())

    client, token = _client_and_token()
    resp = client.get("/api/v2/documents/doc-id", headers=_auth(token))
    assert resp.status_code == 404


def test_other_user_cannot_access_document() -> None:
    _seed()
    _seed_document()
    client, token = _client_and_token("other", "user-pass")
    resp = client.get("/api/v2/documents/doc-id", headers=_auth(token))
    assert resp.status_code == 403


def test_ocr_callback_records_receipt_and_audit() -> None:
    _seed()
    _seed_document()
    client = TestClient(create_app())
    resp = client.post(
        "/api/v2/ocr/callback?job_id=job-id&document_id=doc-id",
        json={"session_id": "sid-1", "status": "completed", "idempotency_key": "cb-1"},
    )
    assert resp.status_code == 200

    async def _check() -> tuple[bool, bool]:
        async with AsyncSessionLocal() as session:
            receipt = await session.scalar(
                select(IngestCallbackReceipt).where(IngestCallbackReceipt.idempotency_key == "cb-1")
            )
            audit = await session.scalar(
                select(AuditLog).where(AuditLog.action == "ingest.callback.received")
            )
            return receipt is not None, audit is not None

    assert asyncio.run(_check()) == (True, True)


def test_ocr_callback_is_idempotent() -> None:
    _seed()
    _seed_document()
    client = TestClient(create_app())
    for _ in range(2):
        resp = client.post(
            "/api/v2/ocr/callback?job_id=job-id&document_id=doc-id",
            json={"session_id": "sid-1", "status": "completed", "idempotency_key": "cb-1"},
        )
        assert resp.status_code == 200

    async def _count() -> int:
        async with AsyncSessionLocal() as session:
            rows = await session.scalars(select(IngestCallbackReceipt))
            return len(list(rows))

    assert asyncio.run(_count()) == 1
