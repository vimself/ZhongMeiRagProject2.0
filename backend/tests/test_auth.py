from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.main import create_app
from app.models.auth import AuditLog, AuthLoginAttempt, LoginRecord, User
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


def seed_user(username: str = "admin", password: str = "old-password") -> None:
    async def _seed() -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                User(
                    username=username,
                    display_name="系统管理员",
                    role="admin",
                    password_hash=hash_password(password),
                )
            )
            await session.commit()

    asyncio.run(_seed())


def test_login_refresh_logout_chain() -> None:
    seed_user()
    client = TestClient(create_app())

    login_response = client.post(
        "/api/v2/auth/login",
        json={"username": "admin", "password": "old-password"},
    )
    assert login_response.status_code == 200
    login_body = login_response.json()
    assert login_body["token_type"] == "bearer"
    assert login_body["user"]["role"] == "admin"

    refresh_response = client.post(
        "/api/v2/auth/refresh",
        json={"refresh_token": login_body["refresh_token"]},
    )
    assert refresh_response.status_code == 200
    assert refresh_response.json()["access_token"]

    logout_response = client.post(
        "/api/v2/auth/logout",
        json={"refresh_token": login_body["refresh_token"]},
    )
    assert logout_response.status_code == 200

    refresh_after_logout = client.post(
        "/api/v2/auth/refresh",
        json={"refresh_token": login_body["refresh_token"]},
    )
    assert refresh_after_logout.status_code == 401


def test_change_password_writes_audit_log() -> None:
    seed_user()
    client = TestClient(create_app())
    tokens = client.post(
        "/api/v2/auth/login",
        json={"username": "admin", "password": "old-password"},
    ).json()

    response = client.post(
        "/api/v2/auth/change-password",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"old_password": "old-password", "new_password": "new-password"},
    )
    assert response.status_code == 200

    relogin = client.post(
        "/api/v2/auth/login",
        json={"username": "admin", "password": "new-password"},
    )
    assert relogin.status_code == 200

    async def _audit_actions() -> list[str]:
        async with AsyncSessionLocal() as session:
            rows = await session.scalars(select(AuditLog.action))
            return list(rows)

    assert "auth.change_password" in asyncio.run(_audit_actions())


def test_login_failure_limit_and_attempt_records() -> None:
    seed_user()
    client = TestClient(create_app())

    last_response = None
    for _ in range(5):
        last_response = client.post(
            "/api/v2/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )

    assert last_response is not None
    assert last_response.status_code == 429

    blocked = client.post(
        "/api/v2/auth/login",
        json={"username": "admin", "password": "old-password"},
    )
    assert blocked.status_code == 429

    async def _counts() -> tuple[int, int]:
        async with AsyncSessionLocal() as session:
            attempts = await session.scalars(select(AuthLoginAttempt))
            records = await session.scalars(select(LoginRecord))
            return len(list(attempts)), len(list(records))

    attempt_count, login_record_count = asyncio.run(_counts())
    assert attempt_count == 5
    assert login_record_count == 0
