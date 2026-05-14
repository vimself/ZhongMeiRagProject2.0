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
    DocumentAsset,
    DocumentIngestJob,
    DocumentParseResult,
    IngestCallbackReceipt,
    IngestStepReceipt,
    KnowledgeChunkV2,
    KnowledgePageIndexV2,
)
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.security.login_limiter import login_failure_limiter
from app.security.password import hash_password
from app.services.deletion import DocumentDeletionResources
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


def _seed_document(
    status: str = "pending", filename: str = "test.pdf", title: str = "测试文档"
) -> None:
    async def _inner() -> None:
        async with AsyncSessionLocal() as session:
            doc = Document(
                id="doc-id",
                knowledge_base_id="kb-id",
                uploader_id="admin-id",
                title=title,
                filename=filename,
                mime="application/pdf",
                size_bytes=20,
                sha256="sha",
                storage_path=f"uploads/documents/{filename}",
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


def _pdf_files(count: int) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("files", (f"test-{index}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf"))
        for index in range(count)
    ]


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
    assert resp.json()["accepted_count"] == 1


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


def test_batch_upload_documents_success() -> None:
    _seed()
    client, token = _client_and_token()
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_files(2),
        data={"doc_kind": "spec"},
    )
    assert resp.status_code == 202, resp.text
    payload = resp.json()
    assert payload["accepted_count"] == 2
    assert len(payload["documents"]) == 2

    async def _count_documents() -> int:
        async with AsyncSessionLocal() as session:
            rows = await session.scalars(select(Document))
            return len(list(rows))

    assert asyncio.run(_count_documents()) == 2


def test_batch_upload_rejects_existing_duplicate_filename_and_accepts_unique() -> None:
    _seed()
    _seed_document(status="ready", filename="test-0.pdf")
    client, token = _client_and_token()
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_files(2),
        data={"doc_kind": "spec"},
    )
    assert resp.status_code == 202, resp.text
    payload = resp.json()
    assert payload["accepted_count"] == 1
    assert payload["documents"][0]["filename"] == "test-1.pdf"
    assert payload["rejected_count"] == 1
    assert payload["rejected"] == [{"filename": "test-0.pdf", "reason": "文件名已存在"}]

    async def _filenames() -> list[str]:
        async with AsyncSessionLocal() as session:
            rows = await session.scalars(
                select(Document.filename).order_by(Document.filename.asc())
            )
            return list(rows)

    assert asyncio.run(_filenames()) == ["test-0.pdf", "test-1.pdf"]


def test_batch_upload_rejects_duplicate_filename_in_same_request() -> None:
    _seed()
    client, token = _client_and_token()
    files = [
        ("files", ("same.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
        ("files", ("same.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
        ("files", ("unique.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
    ]
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=files,
    )
    assert resp.status_code == 202, resp.text
    payload = resp.json()
    assert payload["accepted_count"] == 2
    assert [item["filename"] for item in payload["documents"]] == ["same.pdf", "unique.pdf"]
    assert payload["rejected"] == [{"filename": "same.pdf", "reason": "文件名已存在"}]


def test_single_upload_duplicate_filename_returns_rejected_payload() -> None:
    _seed()
    _seed_document(status="ready", filename="test.pdf")
    client, token = _client_and_token()
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_file(),
    )
    assert resp.status_code == 202, resp.text
    payload = resp.json()
    assert payload["accepted_count"] == 0
    assert payload["documents"] == []
    assert payload["rejected"] == [{"filename": "test.pdf", "reason": "文件名已存在"}]


def test_batch_upload_rejects_more_than_50_files() -> None:
    _seed()
    client, token = _client_and_token()
    resp = client.post(
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        files=_pdf_files(51),
    )
    assert resp.status_code == 400


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
    assert resp.json()["items"][0]["uploader_name"] == "admin"


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
    assert resp.json()["document_status"] == "ocr"


def test_get_progress_maps_embedding_stage() -> None:
    _seed()
    _seed_document(status="embedding")

    async def _receipts() -> None:
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    IngestStepReceipt(
                        job_id="job-id",
                        step="parse_outline",
                        idempotency_key="k-parse",
                        status="succeeded",
                        payload_json={},
                    ),
                    IngestStepReceipt(
                        job_id="job-id",
                        step="section_aware_chunk",
                        idempotency_key="k-chunk",
                        status="succeeded",
                        payload_json={},
                    ),
                ]
            )
            await session.commit()

    asyncio.run(_receipts())
    client, token = _client_and_token()
    resp = client.get("/api/v2/documents/doc-id/progress", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["document_status"] == "embedding"
    assert resp.json()["progress"] == 55


def test_get_progress_maps_vector_stage() -> None:
    _seed()
    _seed_document(status="vector_indexing")

    async def _receipt() -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                IngestStepReceipt(
                    job_id="job-id",
                    step="track_a_write",
                    idempotency_key="k-track-a",
                    status="succeeded",
                    payload_json={},
                )
            )
            await session.commit()

    asyncio.run(_receipt())
    client, token = _client_and_token()
    resp = client.get("/api/v2/documents/doc-id/progress", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["document_status"] == "vector_indexing"
    assert resp.json()["progress"] == 82


def test_retry_document_requeues() -> None:
    _seed()
    _seed_document(status="failed")
    client, token = _client_and_token()
    resp = client.post("/api/v2/documents/doc-id/retry", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_delete_document_hard_deletes_related_rows() -> None:
    _seed()
    _seed_document()

    async def _add_related() -> None:
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    DocumentParseResult(
                        document_id="doc-id",
                        markdown_path="uploads/documents/markdown/doc-id.md",
                        markdown_sha256="markdown-sha",
                        outline_json={},
                        stats_json={},
                    ),
                    DocumentAsset(
                        document_id="doc-id",
                        kind="image",
                        storage_path="uploads/documents/assets/doc-id/image.jpg",
                    ),
                    IngestStepReceipt(
                        job_id="job-id",
                        step="upload_to_ocr",
                        idempotency_key="delete-doc-receipt",
                        status="succeeded",
                        payload_json={},
                    ),
                    KnowledgeChunkV2(
                        knowledge_base_id="kb-id",
                        document_id="doc-id",
                        chunk_index=0,
                        content="chunk",
                        section_path=["1"],
                        section_id="1",
                        doc_kind="plan",
                        tokens=1,
                        sha256="chunk-sha",
                    ),
                    KnowledgePageIndexV2(
                        document_id="doc-id",
                        page_no=1,
                        section_map_json={},
                        block_count=1,
                        text="chunk",
                    ),
                ]
            )
            await session.commit()

    asyncio.run(_add_related())
    client, token = _client_and_token()
    resp = client.delete("/api/v2/documents/doc-id", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"document_id": "doc-id", "deleted": True}

    async def _counts() -> tuple[int, int, int, int, int, int]:
        async with AsyncSessionLocal() as session:
            return (
                len(list(await session.scalars(select(Document)))),
                len(list(await session.scalars(select(DocumentParseResult)))),
                len(list(await session.scalars(select(DocumentAsset)))),
                len(list(await session.scalars(select(DocumentIngestJob)))),
                len(list(await session.scalars(select(KnowledgeChunkV2)))),
                len(list(await session.scalars(select(KnowledgePageIndexV2)))),
            )

    assert asyncio.run(_counts()) == (0, 0, 0, 0, 0, 0)


def test_delete_document_releases_ingest_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed()
    _seed_document()
    released: dict[str, list[str]] = {}

    async def _add_ocr_receipt() -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                IngestStepReceipt(
                    job_id="job-id",
                    step="upload_to_ocr",
                    idempotency_key="delete-doc-ocr-session",
                    status="succeeded",
                    payload_json={"ocr_session_id": "sid-1"},
                )
            )
            await session.commit()

    async def fake_release(resources: DocumentDeletionResources) -> None:
        released["job_ids"] = list(resources.job_ids)
        released["ocr_session_ids"] = list(resources.ocr_session_ids)

    asyncio.run(_add_ocr_receipt())
    monkeypatch.setattr("app.api.documents.release_document_ingest_resources", fake_release)
    client, token = _client_and_token()
    resp = client.delete("/api/v2/documents/doc-id", headers=_auth(token))
    assert resp.status_code == 200
    assert released == {"job_ids": ["job-id"], "ocr_session_ids": ["sid-1"]}


def test_batch_delete_documents() -> None:
    _seed()
    _seed_document(status="ready", filename="a.pdf")

    async def _add_second() -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                Document(
                    id="doc-2",
                    knowledge_base_id="kb-id",
                    uploader_id="admin-id",
                    title="doc 2",
                    filename="b.pdf",
                    mime="application/pdf",
                    size_bytes=20,
                    sha256="sha-2",
                    storage_path="uploads/documents/b.pdf",
                    status="ready",
                )
            )
            await session.commit()

    asyncio.run(_add_second())
    client, token = _client_and_token()
    resp = client.request(
        "DELETE",
        "/api/v2/knowledge-bases/kb-id/documents",
        headers=_auth(token),
        json={"document_ids": ["doc-id", "doc-2"]},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 2

    async def _count_documents() -> int:
        async with AsyncSessionLocal() as session:
            return len(list(await session.scalars(select(Document))))

    assert asyncio.run(_count_documents()) == 0


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
