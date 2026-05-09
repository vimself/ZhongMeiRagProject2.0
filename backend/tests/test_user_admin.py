from __future__ import annotations

import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.main import create_app
from app.models.auth import AuditLog, User
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


def _seed_user(username: str = "normaluser", role: str = "user") -> str:
    user_id = None

    async def _seed() -> None:
        nonlocal user_id
        async with AsyncSessionLocal() as session:
            user = User(
                username=username,
                display_name="普通用户",
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


def _login(client: TestClient, username: str = "admin", password: str = "admin-pass") -> dict:
    resp = client.post("/api/v2/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


# ── User Profile ───────────────────────────────────────────────────────


class TestUserProfile:
    def test_get_profile(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.get("/api/v2/user/profile", headers=_auth_header(tokens["access_token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["display_name"] == "系统管理员"
        assert data["role"] == "admin"
        assert data["is_active"] is True
        assert "created_at" in data
        assert "updated_at" in data

    def test_update_profile(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.put(
            "/api/v2/user/profile",
            headers=_auth_header(tokens["access_token"]),
            json={"display_name": "新名字"},
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "新名字"

        # Verify audit log
        async def _check() -> list[str]:
            async with AsyncSessionLocal() as session:
                rows = await session.scalars(
                    select(AuditLog.action).where(AuditLog.action == "user.update_profile")
                )
                return list(rows)

        assert "user.update_profile" in asyncio.run(_check())

    def test_update_profile_strips_whitespace(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.put(
            "/api/v2/user/profile",
            headers=_auth_header(tokens["access_token"]),
            json={"display_name": "  带空格的名字  "},
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "带空格的名字"


# ── Avatar ─────────────────────────────────────────────────────────────


class TestAvatar:
    def test_upload_avatar_valid(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        # Create a minimal valid PNG (1x1 pixel)
        png_data = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        resp = client.post(
            "/api/v2/user/avatar",
            headers=_auth_header(tokens["access_token"]),
            files={"file": ("avatar.png", io.BytesIO(png_data), "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["avatar_url"] is not None
        assert "/uploads/avatars/" in data["avatar_url"]

    def test_upload_avatar_invalid_mime(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.post(
            "/api/v2/user/avatar",
            headers=_auth_header(tokens["access_token"]),
            files={"file": ("avatar.txt", io.BytesIO(b"not an image"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_upload_avatar_too_large(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        large_data = b"x" * (6 * 1024 * 1024)  # 6 MB
        resp = client.post(
            "/api/v2/user/avatar",
            headers=_auth_header(tokens["access_token"]),
            files={"file": ("big.png", io.BytesIO(large_data), "image/png")},
        )
        assert resp.status_code == 400

    def test_delete_avatar(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.delete(
            "/api/v2/user/avatar",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["avatar_url"] is None

        async def _check() -> list[str]:
            async with AsyncSessionLocal() as session:
                rows = await session.scalars(
                    select(AuditLog.action).where(AuditLog.action == "user.delete_avatar")
                )
                return list(rows)

        assert "user.delete_avatar" in asyncio.run(_check())


# ── Change Password via User endpoint ──────────────────────────────────


class TestUserChangePassword:
    def test_change_password(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.post(
            "/api/v2/user/change-password",
            headers=_auth_header(tokens["access_token"]),
            json={"old_password": "admin-pass", "new_password": "new-admin-pass-123"},
        )
        assert resp.status_code == 200

        # Re-login with new password
        resp2 = _login(client, "admin", "new-admin-pass-123")
        assert resp2["access_token"]

    def test_change_password_wrong_old(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.post(
            "/api/v2/user/change-password",
            headers=_auth_header(tokens["access_token"]),
            json={"old_password": "wrong-old", "new_password": "new-pass-12345"},
        )
        assert resp.status_code == 400


# ── Admin User Management ──────────────────────────────────────────────


class TestAdminUsers:
    def test_list_users(self) -> None:
        _seed_admin()
        _seed_user()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.get(
            "/api/v2/admin/users",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["page"] == 1

    def test_list_users_search(self) -> None:
        _seed_admin()
        _seed_user()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.get(
            "/api/v2/admin/users?search=admin",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["username"] == "admin"

    def test_list_users_filter_role(self) -> None:
        _seed_admin()
        _seed_user()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.get(
            "/api/v2/admin/users?role=user",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_users_filter_active(self) -> None:
        _seed_admin()
        _seed_user()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.get(
            "/api/v2/admin/users?is_active=true",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_create_user(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.post(
            "/api/v2/admin/users",
            headers=_auth_header(tokens["access_token"]),
            json={
                "username": "newuser",
                "display_name": "新用户",
                "password": "password123",
                "role": "user",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "user"

        # Verify audit
        async def _check() -> list[tuple[str, str | None]]:
            async with AsyncSessionLocal() as session:
                rows = await session.execute(
                    select(AuditLog.action, AuditLog.target_id).where(
                        AuditLog.action == "admin.user.create"
                    )
                )
                return list(rows)

        assert ("admin.user.create", data["id"]) in asyncio.run(_check())

    def test_create_user_duplicate(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        client.post(
            "/api/v2/admin/users",
            headers=_auth_header(tokens["access_token"]),
            json={
                "username": "dup",
                "display_name": "Dup",
                "password": "password123",
            },
        )
        resp = client.post(
            "/api/v2/admin/users",
            headers=_auth_header(tokens["access_token"]),
            json={
                "username": "dup",
                "display_name": "Dup2",
                "password": "password456",
            },
        )
        assert resp.status_code == 409

    def test_update_user(self) -> None:
        _seed_admin()
        user_id = _seed_user()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.put(
            f"/api/v2/admin/users/{user_id}",
            headers=_auth_header(tokens["access_token"]),
            json={"display_name": "更新后", "role": "admin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "更新后"
        assert data["role"] == "admin"

    def test_update_user_not_found(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.put(
            "/api/v2/admin/users/nonexistent",
            headers=_auth_header(tokens["access_token"]),
            json={"display_name": "x"},
        )
        assert resp.status_code == 404

    def test_reset_password(self) -> None:
        _seed_admin()
        user_id = _seed_user()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.post(
            f"/api/v2/admin/users/{user_id}/reset-password",
            headers=_auth_header(tokens["access_token"]),
            json={"new_password": "reset-pass-123"},
        )
        assert resp.status_code == 200
        assert resp.json()["require_password_change"] is True

        # The user can login with the new password
        login_resp = client.post(
            "/api/v2/auth/login",
            json={"username": "normaluser", "password": "reset-pass-123"},
        )
        assert login_resp.status_code == 200

        async def _check() -> list[str]:
            async with AsyncSessionLocal() as session:
                rows = await session.scalars(
                    select(AuditLog.action).where(AuditLog.action == "admin.user.reset_password")
                )
                return list(rows)

        assert "admin.user.reset_password" in asyncio.run(_check())

    def test_disable_user(self) -> None:
        _seed_admin()
        user_id = _seed_user()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.delete(
            f"/api/v2/admin/users/{user_id}",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        # The disabled user cannot login
        login_resp = client.post(
            "/api/v2/auth/login",
            json={"username": "normaluser", "password": "user-pass"},
        )
        assert login_resp.status_code == 401

        async def _check() -> list[str]:
            async with AsyncSessionLocal() as session:
                rows = await session.scalars(
                    select(AuditLog.action).where(AuditLog.action == "admin.user.disable")
                )
                return list(rows)

        assert "admin.user.disable" in asyncio.run(_check())

    def test_admin_cannot_disable_self(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        admin_id = tokens["user"]["id"]
        resp = client.delete(
            f"/api/v2/admin/users/{admin_id}",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 400

    def test_admin_cannot_demote_self(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        admin_id = tokens["user"]["id"]
        resp = client.put(
            f"/api/v2/admin/users/{admin_id}",
            headers=_auth_header(tokens["access_token"]),
            json={"role": "user"},
        )
        assert resp.status_code == 400

    def test_admin_cannot_deactivate_self(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        admin_id = tokens["user"]["id"]
        resp = client.put(
            f"/api/v2/admin/users/{admin_id}",
            headers=_auth_header(tokens["access_token"]),
            json={"is_active": False},
        )
        assert resp.status_code == 400


# ── Permission Boundary ────────────────────────────────────────────────


class TestPermissionBoundary:
    def test_normal_user_cannot_list_users(self) -> None:
        _seed_admin()
        _seed_user()
        client = TestClient(create_app())
        tokens = _login(client, "normaluser", "user-pass")

        resp = client.get(
            "/api/v2/admin/users",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 403

    def test_normal_user_cannot_create_user(self) -> None:
        _seed_admin()
        _seed_user()
        client = TestClient(create_app())
        tokens = _login(client, "normaluser", "user-pass")

        resp = client.post(
            "/api/v2/admin/users",
            headers=_auth_header(tokens["access_token"]),
            json={
                "username": "hacker",
                "display_name": "Hacker",
                "password": "password123",
            },
        )
        assert resp.status_code == 403

    def test_normal_user_cannot_update_user(self) -> None:
        _seed_admin()
        user_id = _seed_user()
        client = TestClient(create_app())
        tokens = _login(client, "normaluser", "user-pass")

        resp = client.put(
            f"/api/v2/admin/users/{user_id}",
            headers=_auth_header(tokens["access_token"]),
            json={"display_name": "hacked"},
        )
        assert resp.status_code == 403

    def test_normal_user_cannot_reset_password(self) -> None:
        _seed_admin()
        user_id = _seed_user()
        client = TestClient(create_app())
        tokens = _login(client, "normaluser", "user-pass")

        resp = client.post(
            f"/api/v2/admin/users/{user_id}/reset-password",
            headers=_auth_header(tokens["access_token"]),
            json={"new_password": "hacked-pass"},
        )
        assert resp.status_code == 403

    def test_normal_user_cannot_disable_user(self) -> None:
        _seed_admin()
        user_id = _seed_user()
        client = TestClient(create_app())
        tokens = _login(client, "normaluser", "user-pass")

        resp = client.delete(
            f"/api/v2/admin/users/{user_id}",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 403

    def test_normal_user_cannot_view_audit_logs(self) -> None:
        _seed_admin()
        _seed_user()
        client = TestClient(create_app())
        tokens = _login(client, "normaluser", "user-pass")

        resp = client.get(
            "/api/v2/admin/audit-logs",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 403

    def test_unauthenticated_cannot_access_user_profile(self) -> None:
        _seed_admin()
        client = TestClient(create_app())

        resp = client.get("/api/v2/user/profile")
        assert resp.status_code == 401 or resp.status_code == 403


# ── Audit Logs ─────────────────────────────────────────────────────────


class TestAuditLogs:
    def test_list_audit_logs(self) -> None:
        _seed_admin()
        _seed_user()
        client = TestClient(create_app())
        tokens = _login(client)

        # Generate some audit entries
        client.put(
            "/api/v2/user/profile",
            headers=_auth_header(tokens["access_token"]),
            json={"display_name": "管理员改名"},
        )

        resp = client.get(
            "/api/v2/admin/audit-logs",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert "items" in data

    def test_audit_logs_filter_by_target(self) -> None:
        _seed_admin()
        user_id = _seed_user()
        client = TestClient(create_app())
        tokens = _login(client)

        # Create audit entries
        client.put(
            f"/api/v2/admin/users/{user_id}",
            headers=_auth_header(tokens["access_token"]),
            json={"display_name": "改名"},
        )

        resp = client.get(
            f"/api/v2/admin/audit-logs?target_type=user&target_id={user_id}",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["target_id"] == user_id

    def test_audit_logs_pagination(self) -> None:
        _seed_admin()
        client = TestClient(create_app())
        tokens = _login(client)

        resp = client.get(
            "/api/v2/admin/audit-logs?page=1&page_size=5",
            headers=_auth_header(tokens["access_token"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 5
