from __future__ import annotations

import asyncio
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.main import create_app
from app.models.auth import AuditLog, User
from app.models.document import Document, DocumentAsset
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.security.jwt import _encode_token
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


def _seed(
    *,
    with_permission: bool = True,
    disabled_doc: bool = False,
    with_asset: bool = False,
) -> None:
    async def _inner() -> None:
        async with AsyncSessionLocal() as session:
            user = User(
                id="user-id",
                username="u",
                display_name="用户",
                role="user",
                password_hash=hash_password("pass"),
            )
            admin = User(
                id="admin-id",
                username="a",
                display_name="管理员",
                role="admin",
                password_hash=hash_password("pass"),
            )
            kb = KnowledgeBase(id="kb-id", name="KB", description="", creator_id=admin.id)
            doc = Document(
                id="doc-id",
                knowledge_base_id=kb.id,
                uploader_id=user.id,
                title="测试文档",
                filename="test.pdf",
                mime="application/pdf",
                size_bytes=100,
                sha256="abc123",
                storage_path=str(_test_pdf_path()),
                status="disabled" if disabled_doc else "ready",
            )
            rows: list[object] = [user, admin, kb, doc]
            if with_asset:
                asset_path = _test_asset_path()
                asset_path.write_bytes(b"\x89PNG\r\n\x1a\n")
                rows.append(
                    DocumentAsset(
                        id="asset-id",
                        document_id=doc.id,
                        kind="image",
                        page_no=1,
                        bbox_json={"x": 1, "y": 2, "w": 3, "h": 4},
                        storage_path=str(asset_path),
                        caption="测试图片",
                    )
                )
            session.add_all(rows)
            if with_permission:
                session.add(
                    KnowledgeBasePermission(knowledge_base_id=kb.id, user_id=user.id, role="viewer")
                )
            # Write a minimal PDF for FileResponse
            _test_pdf_path().write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF")
            await session.commit()

    asyncio.run(_inner())


def _test_pdf_path() -> Path:
    return Path(tempfile.gettempdir()) / "zhongmei-stage6-test.pdf"


def _test_asset_path() -> Path:
    return Path(tempfile.gettempdir()) / "zhongmei-stage6-asset.png"


def _login(client: TestClient, username: str = "u") -> str:
    resp = client.post("/api/v2/auth/login", json={"username": username, "password": "pass"})
    assert resp.status_code == 200
    return str(resp.json()["access_token"])


def _expired_pdf_token(user_id: str, document_id: str) -> str:
    issued = _encode_token(
        subject=user_id,
        token_type="pdf_preview",
        expires_delta=timedelta(seconds=-1),
        doc=document_id,
        kb="kb-id",
        scope="pdf_preview",
    )
    return issued.token


def test_sign_pdf_token_success() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["document_id"] == "doc-id"
    assert "expires_at" in data


def test_sign_pdf_token_requires_permission() -> None:
    _seed(with_permission=False)
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    assert resp.status_code == 403


def test_sign_pdf_token_disabled_doc() -> None:
    _seed(disabled_doc=True)
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    assert resp.status_code == 404


def test_sign_pdf_token_nonexistent_doc() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "nonexistent"},
    )
    assert resp.status_code == 404


def test_sign_pdf_token_admin_bypasses_permission() -> None:
    _seed(with_permission=False)
    client = TestClient(create_app())
    token = _login(client, username="a")
    resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    assert resp.status_code == 200


def test_preview_pdf_success() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    # Sign first
    sign_resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    pdf_token = sign_resp.json()["token"]
    # Preview
    resp = client.get(
        "/api/v2/pdf/preview",
        params={"document_id": "doc-id", "token": pdf_token},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "Accept-Ranges" in resp.headers


def test_preview_pdf_range_request() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    sign_resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    pdf_token = sign_resp.json()["token"]
    resp = client.get(
        "/api/v2/pdf/preview",
        headers={"Range": "bytes=0-7"},
        params={"document_id": "doc-id", "token": pdf_token},
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"].startswith("bytes 0-7/")
    assert resp.headers["content-length"] == "8"
    assert resp.content == b"%PDF-1.4"


def test_preview_pdf_invalid_range() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    sign_resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    pdf_token = sign_resp.json()["token"]
    resp = client.get(
        "/api/v2/pdf/preview",
        headers={"Range": "bytes=9999-10000"},
        params={"document_id": "doc-id", "token": pdf_token},
    )
    assert resp.status_code == 416
    assert resp.headers["content-range"].startswith("bytes */")


def test_download_pdf_uses_pdf_token() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    sign_resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    pdf_token = sign_resp.json()["token"]
    resp = client.get(f"/api/v2/documents/doc-id/download?token={pdf_token}")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment;")


def test_asset_sign_and_preview_success() -> None:
    _seed(with_asset=True)
    client = TestClient(create_app())
    token = _login(client)
    sign_resp = client.post(
        "/api/v2/assets/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"asset_id": "asset-id"},
    )
    assert sign_resp.status_code == 200
    data = sign_resp.json()
    assert data["asset_id"] == "asset-id"
    resp = client.get(
        "/api/v2/assets/preview",
        params={"asset_id": "asset-id", "token": data["token"]},
    )
    assert resp.status_code == 200
    assert resp.content.startswith(b"\x89PNG")


def test_preview_pdf_expired_token() -> None:
    _seed()
    client = TestClient(create_app())
    expired = _expired_pdf_token("user-id", "doc-id")
    resp = client.get(
        "/api/v2/pdf/preview",
        params={"document_id": "doc-id", "token": expired},
    )
    assert resp.status_code == 401


def test_preview_pdf_mismatched_document() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    sign_resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    pdf_token = sign_resp.json()["token"]
    # Request with wrong document_id
    resp = client.get(
        "/api/v2/pdf/preview",
        params={"document_id": "other-doc", "token": pdf_token},
    )
    assert resp.status_code == 403


def test_preview_pdf_no_token() -> None:
    _seed()
    client = TestClient(create_app())
    resp = client.get(
        "/api/v2/pdf/preview",
        params={"document_id": "doc-id"},
    )
    assert resp.status_code == 422  # missing required query param


def test_sign_writes_audit_log() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )

    async def _check() -> list[AuditLog]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(AuditLog).where(AuditLog.action == "pdf.sign"))
            return list(result.scalars().all())

    logs = asyncio.run(_check())
    assert len(logs) == 1
    assert logs[0].target_id == "doc-id"


def test_preview_writes_audit_log() -> None:
    _seed()
    client = TestClient(create_app())
    token = _login(client)
    sign_resp = client.post(
        "/api/v2/pdf/sign",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_id": "doc-id"},
    )
    pdf_token = sign_resp.json()["token"]
    client.get(
        "/api/v2/pdf/preview",
        params={"document_id": "doc-id", "token": pdf_token},
    )

    async def _check() -> list[AuditLog]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(AuditLog).where(AuditLog.action == "pdf.preview"))
            return list(result.scalars().all())

    logs = asyncio.run(_check())
    assert len(logs) == 1
    assert logs[0].target_id == "doc-id"
