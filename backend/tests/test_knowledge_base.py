from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.main import create_app
from app.models.auth import AuditLog, User
from app.models.chat import ChatMessage, ChatMessageCitation, ChatSession
from app.models.document import Document, KnowledgeChunkV2
from app.models.knowledge_base import KnowledgeBasePermission
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


def _seed_admin() -> None:
    async def _seed() -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                User(
                    username="admin",
                    display_name="系统管理员",
                    role="admin",
                    password_hash=hash_password("admin-pass"),
                )
            )
            await session.commit()

    asyncio.run(_seed())


def _seed_user(username: str = "stage4user", role: str = "user") -> str:
    user_id = None

    async def _seed() -> None:
        nonlocal user_id
        async with AsyncSessionLocal() as session:
            user = User(
                username=username,
                display_name="Stage4用户",
                role=role,
                password_hash=hash_password("user-pass"),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            user_id = user.id

    asyncio.run(_seed())
    assert user_id is not None
    return user_id


def _seed_user2(username: str = "stage4user2") -> str:
    return _seed_user(username=username)


def _login(client: TestClient, username: str = "admin", password: str = "admin-pass") -> dict:
    resp = client.post("/api/v2/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


# ── Knowledge Base CRUD ────────────────────────────────────────────────


class TestKnowledgeBaseCRUD:
    def test_create_kb_auto_owner(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "stage4测试知识库", "description": "测试描述"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "stage4测试知识库"
        assert data["description"] == "测试描述"
        assert data["my_role"] == "admin"
        assert data["is_active"] is True
        assert data["creator_id"] == tokens["user"]["id"]
        assert data["creator_username"] == "admin"
        assert data["creator_name"] == "系统管理员"

        # Verify permission record created
        async def _check() -> str | None:
            async with AsyncSessionLocal() as session:
                perm = await session.scalar(
                    select(KnowledgeBasePermission.role).where(
                        KnowledgeBasePermission.knowledge_base_id == data["id"]
                    )
                )
                return perm

        assert asyncio.run(_check()) == "owner"

    def test_normal_user_cannot_create_kb(self) -> None:
        _seed_admin()
        _seed_user("normal_creator")
        client = TestClient(create_app())
        tokens = _login(client, "normal_creator", "user-pass")

        resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "普通用户创建"},
        )
        assert resp.status_code == 403
        assert "只有管理员可以创建知识库" in resp.json()["detail"]

    def test_create_kb_audit_log(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "审计测试KB"},
        )
        assert resp.status_code == 201

        async def _check() -> list[str]:
            async with AsyncSessionLocal() as session:
                rows = await session.scalars(
                    select(AuditLog.action).where(AuditLog.action == "knowledge_base.create")
                )
                return list(rows)

        assert "knowledge_base.create" in asyncio.run(_check())

    def test_list_knowledge_bases(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        # Create two KBs
        client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "KB-1"},
        )
        client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "KB-2"},
        )

        resp = client.get(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_list_knowledge_bases_search(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "搜索引擎测试"},
        )
        client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "另一个知识库"},
        )

        resp = client.get(
            "/api/v2/knowledge-bases?search=搜索引擎",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_get_knowledge_base(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "详情测试"},
        )
        kb_id = create_resp.json()["id"]

        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "详情测试"

    def test_update_knowledge_base(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "原名"},
        )
        kb_id = create_resp.json()["id"]

        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "新名称", "description": "新描述"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名称"
        assert resp.json()["description"] == "新描述"

    def test_update_knowledge_base_audit_log(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "审计更新测试"},
        )
        kb_id = create_resp.json()["id"]

        client.put(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "更新后"},
        )

        async def _check() -> tuple[list[str], list[str | None]]:
            async with AsyncSessionLocal() as session:
                rows = (
                    await session.execute(
                        select(AuditLog.action, AuditLog.actor_user_id).where(
                            AuditLog.action == "knowledge_base.update"
                        )
                    )
                ).all()
                return (
                    [row.action for row in rows],
                    [row.actor_user_id for row in rows],
                )

        actions, actor_ids = asyncio.run(_check())
        assert "knowledge_base.update" in actions
        assert tokens["user"]["id"] in actor_ids

    def test_delete_knowledge_base_hard_deletes_documents_and_detaches_chat(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "停用测试"},
        )
        kb_id = create_resp.json()["id"]

        async def _add_related() -> None:
            async with AsyncSessionLocal() as session:
                document = Document(
                    id="doc-hard-delete",
                    knowledge_base_id=kb_id,
                    uploader_id=tokens["user"]["id"],
                    title="待删除文档",
                    filename="delete.pdf",
                    mime="application/pdf",
                    size_bytes=10,
                    sha256="delete-sha",
                    storage_path="uploads/documents/delete.pdf",
                    status="ready",
                )
                chat_session = ChatSession(
                    id="chat-hard-delete",
                    user_id=tokens["user"]["id"],
                    knowledge_base_id=kb_id,
                    title="历史会话",
                )
                session.add_all([document, chat_session])
                await session.flush()
                chat_message = ChatMessage(
                    id="message-hard-delete",
                    session_id=chat_session.id,
                    role="assistant",
                    content="旧答案",
                )
                session.add(chat_message)
                session.add(
                    ChatMessageCitation(
                        message_id=chat_message.id,
                        index=1,
                        document_id=document.id,
                        knowledge_base_id=kb_id,
                        document_title=document.title,
                        section_path_json=[],
                        section_text="旧证据",
                        snippet="旧证据",
                    )
                )
                session.add(
                    KnowledgeChunkV2(
                        knowledge_base_id=kb_id,
                        document_id=document.id,
                        chunk_index=0,
                        content="旧向量内容",
                        section_path=["1"],
                        section_id="1",
                        doc_kind="plan",
                        tokens=4,
                        sha256="chunk-hard-delete",
                    )
                )
                await session.commit()

        asyncio.run(_add_related())
        resp = client.delete(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        # Should not be visible in list
        list_resp = client.get(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
        )
        assert list_resp.json()["total"] == 0

        async def _check_deleted() -> tuple[int, int, str | None, int]:
            async with AsyncSessionLocal() as session:
                return (
                    len(list(await session.scalars(select(Document)))),
                    len(list(await session.scalars(select(KnowledgeChunkV2)))),
                    await session.scalar(
                        select(ChatSession.knowledge_base_id).where(
                            ChatSession.id == "chat-hard-delete"
                        )
                    ),
                    len(list(await session.scalars(select(ChatMessageCitation)))),
                )

        assert asyncio.run(_check_deleted()) == (0, 0, None, 0)

    def test_delete_knowledge_base_audit_log(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "停用审计测试"},
        )
        kb_id = create_resp.json()["id"]

        client.delete(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(tokens["access_token"]),
        )

        async def _check() -> tuple[list[str], list[str | None]]:
            async with AsyncSessionLocal() as session:
                rows = (
                    await session.execute(
                        select(AuditLog.action, AuditLog.actor_user_id).where(
                            AuditLog.action == "knowledge_base.delete"
                        )
                    )
                ).all()
                return (
                    [row.action for row in rows],
                    [row.actor_user_id for row in rows],
                )

        actions, actor_ids = asyncio.run(_check())
        assert "knowledge_base.delete" in actions
        assert tokens["user"]["id"] in actor_ids

    def test_get_nonexistent_kb_returns_404(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.get(
            "/api/v2/knowledge-bases/nonexistent",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 404


# ── Permission Boundary ────────────────────────────────────────────────


class TestKnowledgeBasePermissionBoundary:
    def test_admin_can_edit_and_delete(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "Owner测试"},
        )
        kb_id = create_resp.json()["id"]

        # Admin can update
        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "Owner更新"},
        )
        assert resp.status_code == 200

        # Admin can delete
        resp = client.delete(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200

    def test_regular_owner_can_edit_but_not_delete_kb(self) -> None:
        _seed_admin()
        user_id = _seed_user("regular_owner")
        client = TestClient(create_app())
        admin_tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "普通Owner测试"},
        )
        kb_id = create_resp.json()["id"]
        client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(admin_tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": admin_tokens["user"]["id"], "role": "owner"},
                    {"user_id": user_id, "role": "owner"},
                ]
            },
        )

        user_tokens = _login(client, "regular_owner", "user-pass")
        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
            json={"name": "普通Owner可编辑"},
        )
        assert resp.status_code == 200

        resp = client.delete(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 403
        assert "只有管理员可以删除知识库" in resp.json()["detail"]

    def test_editor_can_edit_but_not_delete(self) -> None:
        _seed_admin()
        user_id = _seed_user("editor_user")
        client = TestClient(create_app())
        admin_tokens = _login(client)

        # Create KB as admin
        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "Editor测试"},
        )
        kb_id = create_resp.json()["id"]

        # Grant editor permission
        client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(admin_tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": admin_tokens["user"]["id"], "role": "owner"},
                    {"user_id": user_id, "role": "editor"},
                ]
            },
        )

        # Login as editor
        user_tokens = _login(client, "editor_user", "user-pass")

        # Editor can view
        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["my_role"] == "editor"

        # Editor can update
        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
            json={"name": "Editor更新"},
        )
        assert resp.status_code == 200

        # Editor cannot delete
        resp = client.delete(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 403

        # Editor cannot manage permissions
        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(user_tokens["access_token"]),
            json={"permissions": []},
        )
        assert resp.status_code == 403

    def test_viewer_can_only_view(self) -> None:
        _seed_admin()
        user_id = _seed_user("viewer_user")
        client = TestClient(create_app())
        admin_tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "Viewer测试"},
        )
        kb_id = create_resp.json()["id"]

        # Grant viewer permission
        client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(admin_tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": admin_tokens["user"]["id"], "role": "owner"},
                    {"user_id": user_id, "role": "viewer"},
                ]
            },
        )

        user_tokens = _login(client, "viewer_user", "user-pass")

        # Viewer can view
        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["my_role"] == "viewer"

        # Viewer cannot update
        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
            json={"name": "Viewer改名"},
        )
        assert resp.status_code == 403

        # Viewer cannot delete
        resp = client.delete(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 403

    def test_no_permission_user_gets_403(self) -> None:
        _seed_admin()
        _seed_user("noperm_user")
        client = TestClient(create_app())
        admin_tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "无权限测试"},
        )
        kb_id = create_resp.json()["id"]

        user_tokens = _login(client, "noperm_user", "user-pass")

        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        admin_tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "未认证测试"},
        )
        kb_id = create_resp.json()["id"]

        # No auth header
        resp = client.get(f"/api/v2/knowledge-bases/{kb_id}")
        assert resp.status_code == 401 or resp.status_code == 403

    def test_admin_can_manage_all_knowledge_bases(self) -> None:
        _seed_admin()
        user_id = _seed_user("kb_owner_user")
        client = TestClient(create_app())

        # Create KB as admin, then transfer owner permission to a regular user.
        admin_tokens = _login(client)
        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "用户创建的KB"},
        )
        kb_id = create_resp.json()["id"]
        client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"permissions": [{"user_id": user_id, "role": "owner"}]},
        )

        # Admin can view it
        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(admin_tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["my_role"] == "admin"

        # Admin can update it
        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "Admin改名"},
        )
        assert resp.status_code == 200

        # Admin can delete it
        resp = client.delete(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(admin_tokens["access_token"]),
        )
        assert resp.status_code == 200

    def test_normal_user_only_sees_permitted_kbs(self) -> None:
        _seed_admin()
        user_id = _seed_user("kb_list_user")
        client = TestClient(create_app())
        admin_tokens = _login(client)

        # Create two KBs
        resp1 = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "KB-可见"},
        )
        kb1_id = resp1.json()["id"]

        client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "KB-不可见"},
        )

        # Grant permission only to KB-1
        client.put(
            f"/api/v2/knowledge-bases/{kb1_id}/permissions",
            headers=_auth_header(admin_tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": admin_tokens["user"]["id"], "role": "owner"},
                    {"user_id": user_id, "role": "viewer"},
                ]
            },
        )

        # Regular user should only see KB-1
        user_tokens = _login(client, "kb_list_user", "user-pass")
        resp = client.get(
            "/api/v2/knowledge-bases",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "KB-可见"


# ── Permission Management ──────────────────────────────────────────────


class TestKnowledgeBasePermissionManagement:
    def test_list_permissions(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "权限列表测试"},
        )
        kb_id = create_resp.json()["id"]

        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        perms = resp.json()
        assert len(perms) == 1
        assert perms[0]["role"] == "owner"

    def test_update_permissions_add_editor(self) -> None:
        _seed_admin()
        user_id = _seed_user("perm_editor")
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "权限添加测试"},
        )
        kb_id = create_resp.json()["id"]

        # Add editor permission (keep owner)
        admin_user_id = tokens["user"]["id"]
        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": admin_user_id, "role": "owner"},
                    {"user_id": user_id, "role": "editor"},
                ]
            },
        )
        assert resp.status_code == 200
        perms = resp.json()
        assert len(perms) == 2

    def test_update_permissions_immediate_effect(self) -> None:
        _seed_admin()
        user_id = _seed_user("perm_immediate")
        client = TestClient(create_app())
        admin_tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "即时生效测试"},
        )
        kb_id = create_resp.json()["id"]

        # Initially no access
        user_tokens = _login(client, "perm_immediate", "user-pass")
        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 403

        # Grant viewer
        admin_user_id = admin_tokens["user"]["id"]
        client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(admin_tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": admin_user_id, "role": "owner"},
                    {"user_id": user_id, "role": "viewer"},
                ]
            },
        )

        # Now has access
        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 200

    def test_cannot_remove_last_owner(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "最后Owner测试"},
        )
        kb_id = create_resp.json()["id"]

        _seed_user("another_user")

        # Try to change owner to viewer (removes last owner)
        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": tokens["user"]["id"], "role": "viewer"},
                ]
            },
        )
        assert resp.status_code == 400
        assert "不能移除最后一个 owner" in resp.json()["detail"]

    def test_cannot_set_invalid_role(self) -> None:
        _seed_admin()
        user_id = _seed_user("invalid_role_user")
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "非法角色测试"},
        )
        kb_id = create_resp.json()["id"]

        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": user_id, "role": "superadmin"},
                ]
            },
        )
        assert resp.status_code == 422  # Validation error

    def test_permission_update_audit_log(self) -> None:
        _seed_admin()
        user_id = _seed_user("perm_audit_user")
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "权限审计测试"},
        )
        kb_id = create_resp.json()["id"]

        admin_user_id = tokens["user"]["id"]
        client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": admin_user_id, "role": "owner"},
                    {"user_id": user_id, "role": "viewer"},
                ]
            },
        )

        async def _check() -> tuple[list[str], list[str | None]]:
            async with AsyncSessionLocal() as session:
                rows = (
                    await session.execute(
                        select(AuditLog.action, AuditLog.actor_user_id).where(
                            AuditLog.action == "knowledge_base.permissions.update"
                        )
                    )
                ).all()
                return (
                    [row.action for row in rows],
                    [row.actor_user_id for row in rows],
                )

        actions, actor_ids = asyncio.run(_check())
        assert "knowledge_base.permissions.update" in actions
        assert tokens["user"]["id"] in actor_ids

    def test_update_permissions_rejects_missing_user(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "不存在用户测试"},
        )
        kb_id = create_resp.json()["id"]

        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": tokens["user"]["id"], "role": "owner"},
                    {"user_id": "missing-user-id", "role": "viewer"},
                ]
            },
        )
        assert resp.status_code == 400
        assert "不存在的用户" in resp.json()["detail"]

    def test_update_permissions_rejects_duplicate_user(self) -> None:
        _seed_admin()
        user_id = _seed_user("duplicate_perm_user")
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "重复权限测试"},
        )
        kb_id = create_resp.json()["id"]

        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": tokens["user"]["id"], "role": "owner"},
                    {"user_id": user_id, "role": "viewer"},
                    {"user_id": user_id, "role": "editor"},
                ]
            },
        )
        assert resp.status_code == 400
        assert "重复用户" in resp.json()["detail"]

    def test_admin_can_list_permission_candidates(self) -> None:
        _seed_admin()
        _seed_user("candidate_user")
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "候选用户测试"},
        )
        kb_id = create_resp.json()["id"]

        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}/permission-candidates",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        usernames = {item["username"] for item in resp.json()}
        assert "candidate_user" in usernames

    def test_regular_owner_cannot_manage_permissions(self) -> None:
        _seed_admin()
        owner_id = _seed_user("regular_perm_owner")
        client = TestClient(create_app())
        admin_tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(admin_tokens["access_token"]),
            json={"name": "普通Owner权限边界"},
        )
        kb_id = create_resp.json()["id"]
        client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(admin_tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": admin_tokens["user"]["id"], "role": "owner"},
                    {"user_id": owner_id, "role": "owner"},
                ]
            },
        )

        owner_tokens = _login(client, "regular_perm_owner", "user-pass")
        resp = client.get(
            f"/api/v2/knowledge-bases/{kb_id}/permission-candidates",
            headers=_auth_header(owner_tokens["access_token"]),
        )
        assert resp.status_code == 403
        assert "需要管理员权限" in resp.json()["detail"]

        resp = client.put(
            f"/api/v2/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(owner_tokens["access_token"]),
            json={
                "permissions": [
                    {"user_id": owner_id, "role": "owner"},
                ]
            },
        )
        assert resp.status_code == 403
        assert "需要管理员权限" in resp.json()["detail"]


# ── Admin Knowledge Base Management ────────────────────────────────────


class TestAdminKnowledgeBase:
    def test_admin_list_all_knowledge_bases(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        kb_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "Admin-KB-1"},
        )
        kb_id = kb_resp.json()["id"]
        client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "Admin-KB-2"},
        )

        async def _add_documents() -> None:
            async with AsyncSessionLocal() as session:
                session.add_all(
                    [
                        Document(
                            knowledge_base_id=kb_id,
                            uploader_id=tokens["user"]["id"],
                            title="可用文档",
                            filename="ready.pdf",
                            mime="application/pdf",
                            size_bytes=10,
                            sha256="ready-sha",
                            storage_path="uploads/ready.pdf",
                            status="ready",
                        ),
                        Document(
                            knowledge_base_id=kb_id,
                            uploader_id=tokens["user"]["id"],
                            title="已删除文档",
                            filename="deleted.pdf",
                            mime="application/pdf",
                            size_bytes=10,
                            sha256="deleted-sha",
                            storage_path="uploads/deleted.pdf",
                            status="disabled",
                        ),
                    ]
                )
                await session.commit()

        asyncio.run(_add_documents())

        resp = client.get(
            "/api/v2/admin/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        first = next(item for item in data["items"] if item["id"] == kb_id)
        assert first["document_count"] == 2
        assert first["active_document_count"] == 1
        assert first["permission_count"] == 1
        assert first["creator_id"] == tokens["user"]["id"]
        assert first["creator_username"] == "admin"
        assert first["creator_name"] == "系统管理员"
        assert first["deleted_at"] is None

    def test_admin_list_kbs_search(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "搜索目标"},
        )
        client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "其他"},
        )

        resp = client.get(
            "/api/v2/admin/knowledge-bases?search=搜索",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_admin_list_kbs_after_delete_omits_removed_row(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "将停用"},
        )
        kb_id = create_resp.json()["id"]

        client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "保持启用"},
        )

        client.delete(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(tokens["access_token"]),
        )

        resp = client.get(
            "/api/v2/admin/knowledge-bases?is_active=true",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.json()["total"] == 1

        resp = client.get(
            "/api/v2/admin/knowledge-bases?is_active=false",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.json()["total"] == 0

    def test_deleted_kb_permissions_are_removed(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        create_resp = client.post(
            "/api/v2/knowledge-bases",
            headers=_auth_header(tokens["access_token"]),
            json={"name": "停用权限查看"},
        )
        kb_id = create_resp.json()["id"]

        client.delete(
            f"/api/v2/knowledge-bases/{kb_id}",
            headers=_auth_header(tokens["access_token"]),
        )

        resp = client.get(
            f"/api/v2/admin/knowledge-bases/{kb_id}/permissions",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 404

    def test_normal_user_cannot_access_admin_kb(self) -> None:
        _seed_admin()
        _seed_user("nonadmin_kb")
        client = TestClient(create_app())

        user_tokens = _login(client, "nonadmin_kb", "user-pass")
        resp = client.get(
            "/api/v2/admin/knowledge-bases",
            headers=_auth_header(user_tokens["access_token"]),
        )
        assert resp.status_code == 403


# ── Alembic Migration ──────────────────────────────────────────────────


class TestAlembicMigration:
    def test_upgrade_creates_tables(self) -> None:
        """Tables exist after create_all (simulates upgrade)."""

        async def _check() -> bool:
            async with engine.begin() as conn:
                result = await conn.run_sync(
                    lambda sync_conn: sync_conn.dialect.has_table(sync_conn, "knowledge_bases")
                )
                return result

        assert asyncio.run(_check()) is True

        async def _check_perm() -> bool:
            async with engine.begin() as conn:
                result = await conn.run_sync(
                    lambda sync_conn: sync_conn.dialect.has_table(
                        sync_conn, "knowledge_base_permissions"
                    )
                )
                return result

        assert asyncio.run(_check_perm()) is True
