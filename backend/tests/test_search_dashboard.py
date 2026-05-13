from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.main import create_app
from app.models.auth import AuditLog, User
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document, KnowledgeChunkV2
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.models.search_export import SearchExportJob
from app.security.login_limiter import login_failure_limiter
from app.security.password import hash_password


@pytest.fixture(autouse=True)
def _reset() -> None:
    async def _inner() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        login_failure_limiter.clear_memory()

    asyncio.run(_inner())


def _seed_multi_kb() -> None:
    async def _inner() -> None:
        async with AsyncSessionLocal() as session:
            admin = User(
                id="admin-id",
                username="admin",
                display_name="管理员",
                role="admin",
                password_hash=hash_password("pass"),
            )
            normal = User(
                id="user-id",
                username="normal",
                display_name="普通用户",
                role="user",
                password_hash=hash_password("pass"),
            )
            kb1 = KnowledgeBase(id="kb-1", name="KB1", description="", creator_id=admin.id)
            kb2 = KnowledgeBase(id="kb-2", name="KB2", description="", creator_id=admin.id)
            session.add_all([admin, normal, kb1, kb2])

            session.add(
                KnowledgeBasePermission(knowledge_base_id=kb1.id, user_id=normal.id, role="viewer")
            )

            doc1 = Document(
                id="doc-1",
                knowledge_base_id=kb1.id,
                uploader_id=admin.id,
                title="施工方案",
                filename="plan.pdf",
                mime="application/pdf",
                size_bytes=100,
                sha256="sha1",
                storage_path="plan.pdf",
                status="ready",
                doc_kind="plan",
            )
            doc2 = Document(
                id="doc-2",
                knowledge_base_id=kb2.id,
                uploader_id=admin.id,
                title="技术规范",
                filename="spec.pdf",
                mime="application/pdf",
                size_bytes=100,
                sha256="sha2",
                storage_path="spec.pdf",
                status="ready",
                doc_kind="spec",
            )
            session.add_all([doc1, doc2])

            vec = [1.0] + [0.0] * 255
            session.add_all(
                [
                    KnowledgeChunkV2(
                        id="chunk-1",
                        knowledge_base_id=kb1.id,
                        document_id=doc1.id,
                        chunk_index=0,
                        content="施工方案 洞身开挖 采用台阶法施工",
                        section_path=["第4章", "4.3 洞身开挖"],
                        section_id="s-1",
                        page_start=37,
                        page_end=38,
                        bbox_json={"x": 82, "y": 310, "w": 430, "h": 56},
                        content_type="paragraph",
                        doc_kind="plan",
                        tokens=10,
                        sha256="sha-c1",
                        vector=vec,
                    ),
                    KnowledgeChunkV2(
                        id="chunk-1-table",
                        knowledge_base_id=kb1.id,
                        document_id=doc1.id,
                        chunk_index=1,
                        content="施工方案 工程数量表 机械设备配置",
                        section_path=["第4章", "4.4 资源配置"],
                        section_id="s-1-table",
                        page_start=39,
                        page_end=39,
                        content_type="table",
                        doc_kind="plan",
                        tokens=10,
                        sha256="sha-c1-table",
                        vector=vec,
                    ),
                    KnowledgeChunkV2(
                        id="chunk-2",
                        knowledge_base_id=kb2.id,
                        document_id=doc2.id,
                        chunk_index=0,
                        content="技术规范 质量标准 混凝土强度",
                        section_path=["第3章", "3.1 质量标准"],
                        section_id="s-2",
                        page_start=15,
                        page_end=16,
                        content_type="paragraph",
                        doc_kind="spec",
                        tokens=10,
                        sha256="sha-c2",
                        vector=vec,
                    ),
                ]
            )

            chat_session = ChatSession(
                id="sess-1",
                user_id=admin.id,
                knowledge_base_id=kb1.id,
                title="测试会话",
            )
            session.add(chat_session)
            session.add(
                ChatMessage(id="msg-1", session_id=chat_session.id, role="user", content="测试问题")
            )

            await session.commit()

    asyncio.run(_inner())


def _login(client: TestClient, username: str = "admin") -> str:
    resp = client.post("/api/v2/auth/login", json={"username": username, "password": "pass"})
    assert resp.status_code == 200
    return str(resp.json()["access_token"])


def _seed_dashboard_activities() -> None:
    async def _inner() -> None:
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    AuditLog(
                        actor_user_id="admin-id",
                        action="knowledge_base.create",
                        target_type="knowledge_base",
                        target_id="kb-1",
                        ip_address="127.0.0.1",
                        details={"name": "KB1"},
                    ),
                    AuditLog(
                        actor_user_id="admin-id",
                        action="knowledge_base.permissions.update",
                        target_type="knowledge_base",
                        target_id="kb-1",
                        ip_address="127.0.0.1",
                    ),
                    AuditLog(
                        actor_user_id="admin-id",
                        action="knowledge_base.delete",
                        target_type="knowledge_base",
                        target_id="deleted-kb",
                        ip_address="127.0.0.1",
                        details={"name": "Deleted KB"},
                    ),
                    AuditLog(
                        actor_user_id="admin-id",
                        action="document.upload",
                        target_type="document",
                        target_id="doc-1",
                        ip_address="127.0.0.1",
                    ),
                ]
            )
            await session.commit()

    asyncio.run(_inner())


def test_search_single_kb() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/search/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "施工", "kb_id": "kb-1", "page": 1, "page_size": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["document_id"] == "doc-1"
    assert "preview_url" in item
    assert "download_url" in item
    assert item["preview_url"].startswith("/api/v2/pdf/preview")
    assert item["knowledge_base_id"] == "kb-1"


def test_search_cross_kb() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/search/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "施工 规范", "page": 1, "page_size": 20},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    doc_ids = {item["document_id"] for item in data["items"]}
    assert "doc-1" in doc_ids or "doc-2" in doc_ids


def test_search_permission_filter() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client, "normal")
    resp = client.post(
        "/api/v2/search/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "施工", "page": 1, "page_size": 20},
    )
    assert resp.status_code == 200
    data = resp.json()
    for item in data["items"]:
        assert item["knowledge_base_id"] == "kb-1"


def test_search_admin_all() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client, "admin")
    resp = client.post(
        "/api/v2/search/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "施工 规范", "page": 1, "page_size": 20},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


def test_search_pagination() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/search/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "施工", "page": 1, "page_size": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["page_size"] == 1
    assert len(data["items"]) <= 1


def test_search_content_type_filter() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/search/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "query": "工程数量",
            "kb_id": "kb-1",
            "content_type": "table",
            "page": 1,
            "page_size": 10,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["chunk_id"] == "chunk-1-table"


def test_hot_keywords() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.get(
        "/api/v2/search/hot-keywords",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) > 0
    assert "keyword" in data["items"][0]
    assert "count" in data["items"][0]


def test_doc_types() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.get(
        "/api/v2/search/doc-types",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "doc_kinds" in data
    assert len(data["doc_kinds"]) >= 1


def test_export_create_and_poll() -> None:
    _seed_multi_kb()
    with patch("app.api.search.celery_app") as mock_celery:
        mock_celery.send_task = lambda *a, **kw: None
        client = TestClient(create_app())
        token = _login(client)
        resp = client.post(
            "/api/v2/search/export",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "施工", "format": "json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "pending"

        job_id = data["job_id"]
        resp2 = client.get(
            f"/api/v2/search/export/{job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["job_id"] == job_id


def test_export_other_user_forbidden() -> None:
    _seed_multi_kb()
    with patch("app.api.search.celery_app") as mock_celery:
        mock_celery.send_task = lambda *a, **kw: None
        client = TestClient(create_app())
        token = _login(client, "admin")
        resp = client.post(
            "/api/v2/search/export",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "施工"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

    normal_token = _login(client, "normal")
    resp2 = client.get(
        f"/api/v2/search/export/{job_id}",
        headers={"Authorization": f"Bearer {normal_token}"},
    )
    assert resp2.status_code == 404


def test_export_download_uses_signed_url_without_authorization(tmp_path: Path) -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client, "admin")

    export_file = tmp_path / "export.zip"
    export_file.write_bytes(b"zip-content")

    async def _seed_job() -> str:
        async with AsyncSessionLocal() as session:
            job = SearchExportJob(
                id="job-signed",
                user_id="admin-id",
                status="succeeded",
                format="json",
                filters_json={"query": "施工"},
                result_count=1,
                file_path=str(export_file),
                file_size=export_file.stat().st_size,
            )
            job.set_defaults()
            session.add(job)
            await session.commit()
            return job.id

    job_id = asyncio.run(_seed_job())
    status_resp = client.get(
        f"/api/v2/search/export/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    download_url = status_resp.json()["download_url"]
    assert "token=" in download_url

    download_resp = client.get(download_url)
    assert download_resp.status_code == 200
    assert download_resp.content == b"zip-content"


def test_export_generation_respects_kb_filter(tmp_path: Path) -> None:
    _seed_multi_kb()

    from app.core.config import get_settings
    from app.tasks.search_export import _run_export

    get_settings().export_dir = str(tmp_path)

    async def _seed_job() -> str:
        async with AsyncSessionLocal() as session:
            job = SearchExportJob(
                id="job-kb-filter",
                user_id="admin-id",
                status="pending",
                format="json",
                filters_json={"query": "规范", "kb_id": "kb-1"},
            )
            job.set_defaults()
            session.add(job)
            await session.commit()
            return job.id

    job_id = asyncio.run(_seed_job())
    result = asyncio.run(_run_export(job_id, "admin-id"))
    assert result["status"] == "succeeded"

    async def _load_count() -> int:
        async with AsyncSessionLocal() as session:
            job = await session.get(SearchExportJob, job_id)
            assert job is not None
            return job.result_count

    assert asyncio.run(_load_count()) == 0


def test_dashboard_stats_admin() -> None:
    _seed_multi_kb()
    _seed_dashboard_activities()
    client = TestClient(create_app())
    token = _login(client, "admin")
    resp = client.get(
        "/api/v2/dashboard/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_count"] == 2
    assert data["kb_count"] == 2
    assert data["kb_active_count"] == 2
    assert data["document_total"] == 2
    assert data["chunk_count"] == 3
    assert data["chat_session_count"] == 1
    assert data["chat_message_count"] == 1
    assert "document_by_status" in data
    assert "document_by_kind" in data
    assert "ingest_by_status" in data
    assert "recent_activities" in data
    assert {item["action"] for item in data["recent_activities"]} == {
        "knowledge_base.create",
        "knowledge_base.delete",
        "knowledge_base.permissions.update",
    }
    assert all("ip_address" not in item for item in data["recent_activities"])
    assert all(item["actor_username"] == "admin" for item in data["recent_activities"])
    names_by_action = {
        item["action"]: item["knowledge_base_name"] for item in data["recent_activities"]
    }
    assert names_by_action["knowledge_base.create"] == "KB1"
    assert names_by_action["knowledge_base.permissions.update"] == "KB1"
    assert names_by_action["knowledge_base.delete"] == "Deleted KB"
    assert all(item["created_at"] for item in data["recent_activities"])
    assert "trends_7d" in data
    assert "trends_14d" in data
    assert "dates" in data["trends_7d"]
    assert "documents" in data["trends_7d"]
    assert "chat_sessions" in data["trends_7d"]


def test_dashboard_stats_forbidden() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client, "normal")
    resp = client.get(
        "/api/v2/dashboard/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_system_status_admin() -> None:
    _seed_multi_kb()

    async def fake_ocr() -> dict[str, object]:
        return {"status": "ok", "latency_ms": 1.0}

    async def fake_llm() -> dict[str, object]:
        return {"status": "not_configured"}

    client = TestClient(create_app())
    token = _login(client, "admin")
    with (
        patch("app.api.dashboard._check_ocr", fake_ocr),
        patch("app.api.dashboard._check_llm", fake_llm),
    ):
        resp = client.get(
            "/api/v2/dashboard/system-status",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["database"]["status"] in ("ok", "down")
    assert data["redis"]["status"] in ("ok", "down")
    assert data["ocr"]["status"] in ("ok", "down", "not_configured")
    assert data["llm"]["status"] in ("ok", "degraded", "down", "not_configured")
    assert data["dashscope"] == data["llm"]
    assert "uptime_seconds" in data


def test_system_status_forbidden() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client, "normal")
    resp = client.get(
        "/api/v2/dashboard/system-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_search_stage7_fields() -> None:
    _seed_multi_kb()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/search/documents",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "施工", "kb_id": "kb-1"},
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    required = [
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
        "download_url",
    ]
    for field in required:
        assert field in item, f"Missing: {field}"
