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


def _seed(admin: bool = True, with_chunk: bool = True) -> None:
    async def _inner() -> None:
        async with AsyncSessionLocal() as session:
            user = User(
                id="user-id",
                username="u",
                display_name="用户",
                role="admin" if admin else "user",
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
                sha256="sha",
                storage_path="a.pdf",
            )
            session.add_all([user, kb, doc])
            if with_chunk:
                session.add(
                    KnowledgeChunkV2(
                        id="chunk-id",
                        knowledge_base_id=kb.id,
                        document_id=doc.id,
                        chunk_index=0,
                        content="施工 方案 施工",
                        section_path=["总则"],
                        section_id="s",
                        content_type="paragraph",
                        doc_kind="plan",
                        tokens=3,
                        sha256="chunk-sha",
                    )
                )
            await session.commit()

    asyncio.run(_inner())


def _login(client: TestClient) -> str:
    resp = client.post("/api/v2/auth/login", json={"username": "u", "password": "pass"})
    assert resp.status_code == 200
    return str(resp.json()["access_token"])


def test_retrieval_debug_fuses_lexical_score() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/retrieval/debug",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "kb_id": "kb-id",
            "query": "施工",
            "k": 5,
            "filters": {"doc_kind": "plan"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["items"][0]["chunk_id"] == "chunk-id"


def test_retrieval_debug_requires_admin() -> None:
    _seed(admin=False)
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/retrieval/debug",
        headers={"Authorization": f"Bearer {token}"},
        json={"kb_id": "kb-id", "query": "施工"},
    )
    assert resp.status_code == 403


def test_retrieval_debug_empty_kb() -> None:
    _seed(with_chunk=False)
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/retrieval/debug",
        headers={"Authorization": f"Bearer {token}"},
        json={"kb_id": "kb-id", "query": "施工"},
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []
