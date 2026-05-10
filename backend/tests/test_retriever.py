from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.main import create_app
from app.models.auth import User
from app.models.document import Document, KnowledgeChunkV2
from app.models.knowledge_base import KnowledgeBase
from app.security.login_limiter import login_failure_limiter
from app.security.password import hash_password


@pytest.fixture(autouse=True)
def reset_database() -> None:
    async def _reset() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        login_failure_limiter.clear_memory()

    asyncio.run(_reset())


def _seed(*, with_chunks: bool = True) -> None:
    async def _inner() -> None:
        async with AsyncSessionLocal() as session:
            user = User(
                id="user-id",
                username="u",
                display_name="用户",
                role="admin",
                password_hash=hash_password("pass"),
            )
            kb = KnowledgeBase(id="kb-id", name="KB", description="", creator_id=user.id)
            doc1 = Document(
                id="doc-1",
                knowledge_base_id=kb.id,
                uploader_id=user.id,
                title="施工方案文档",
                filename="plan.pdf",
                mime="application/pdf",
                size_bytes=100,
                sha256="sha1",
                storage_path="plan.pdf",
                status="ready",
            )
            doc2 = Document(
                id="doc-2",
                knowledge_base_id=kb.id,
                uploader_id=user.id,
                title="技术规范文档",
                filename="spec.pdf",
                mime="application/pdf",
                size_bytes=100,
                sha256="sha2",
                storage_path="spec.pdf",
                status="ready",
            )
            session.add_all([user, kb, doc1, doc2])
            if with_chunks:
                vec_a = [1.0] + [0.0] * 255  # Simple vector
                vec_b = [0.0] * 128 + [1.0] + [0.0] * 127
                session.add_all(
                    [
                        KnowledgeChunkV2(
                            id="chunk-a",
                            knowledge_base_id=kb.id,
                            document_id=doc1.id,
                            chunk_index=0,
                            content="施工方案 洞身开挖 采用台阶法施工",
                            section_path=["第4章", "4.3 洞身开挖"],
                            section_id="s-a",
                            page_start=37,
                            page_end=38,
                            bbox_json={"x": 82, "y": 310, "w": 430, "h": 56},
                            content_type="paragraph",
                            doc_kind="plan",
                            tokens=10,
                            sha256="chunk-sha-a",
                            vector=vec_a,
                        ),
                        KnowledgeChunkV2(
                            id="chunk-b",
                            knowledge_base_id=kb.id,
                            document_id=doc2.id,
                            chunk_index=0,
                            content="技术规范 质量标准 混凝土强度要求",
                            section_path=["第3章", "3.1 质量标准"],
                            section_id="s-b",
                            page_start=15,
                            page_end=16,
                            content_type="paragraph",
                            doc_kind="spec",
                            tokens=10,
                            sha256="chunk-sha-b",
                            vector=vec_b,
                        ),
                    ]
                )
            await session.commit()

    asyncio.run(_inner())


def _login(client: TestClient) -> str:
    resp = client.post("/api/v2/auth/login", json={"username": "u", "password": "pass"})
    assert resp.status_code == 200
    return str(resp.json()["access_token"])


def test_retriever_returns_results() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/retrieval/debug",
        headers={"Authorization": f"Bearer {token}"},
        json={"kb_id": "kb-id", "query": "施工 方案", "k": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0
    item = data["items"][0]
    assert "chunk_id" in item
    assert "score" in item
    assert item["preview_url"].startswith("/api/v2/pdf/preview")
    assert item["download_url"].startswith("/api/v2/documents/")
    assert item["document_id"] in ("doc-1", "doc-2")


def test_retriever_empty_kb() -> None:
    _seed(with_chunks=False)
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/retrieval/debug",
        headers={"Authorization": f"Bearer {token}"},
        json={"kb_id": "kb-id", "query": "施工", "k": 10},
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_retriever_doc_kind_filter() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/retrieval/debug",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "kb_id": "kb-id",
            "query": "施工",
            "k": 10,
            "filters": {"doc_kind": "plan"},
        },
    )
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["document_id"] == "doc-1"


def test_retriever_rrf_ranking() -> None:
    """Chunk appearing in both tracks should rank higher."""
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/retrieval/debug",
        headers={"Authorization": f"Bearer {token}"},
        json={"kb_id": "kb-id", "query": "施工 方案 洞身开挖", "k": 10},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    # chunk-a has both "施工" and "方案" and "洞身开挖", should rank first
    assert items[0]["chunk_id"] == "chunk-a"


def test_retriever_stage7_fields() -> None:
    """All Stage 7 reference protocol fields must be present."""
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/retrieval/debug",
        headers={"Authorization": f"Bearer {token}"},
        json={"kb_id": "kb-id", "query": "施工", "k": 5},
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    required_fields = [
        "chunk_id",
        "document_id",
        "document_title",
        "knowledge_base_id",
        "section_path",
        "section_text",
        "page_start",
        "page_end",
        "bbox",
        "snippet",
        "score",
        "preview_url",
    ]
    for field in required_fields:
        assert field in item, f"Missing field: {field}"


def test_retriever_requires_admin() -> None:
    _seed()
    client = TestClient(create_app())

    # Login as non-admin
    async def _make_user() -> None:
        async with AsyncSessionLocal() as session:
            user = User(
                id="regular-id",
                username="regular",
                display_name="普通用户",
                role="user",
                password_hash=hash_password("pass"),
            )
            session.add(user)
            await session.commit()

    asyncio.run(_make_user())
    resp = client.post("/api/v2/auth/login", json={"username": "regular", "password": "pass"})
    token = resp.json()["access_token"]
    resp = client.post(
        "/api/v2/retrieval/debug",
        headers={"Authorization": f"Bearer {token}"},
        json={"kb_id": "kb-id", "query": "施工"},
    )
    assert resp.status_code == 403
