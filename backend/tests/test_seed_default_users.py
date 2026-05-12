from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.cli.seed_default_users import seed_default_users
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models.auth import AuditLog, LoginRecord, User
from app.models.chat import ChatMessage, ChatMessageCitation, ChatSession
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.models.search_export import SearchExportJob
from app.security.password import hash_password, verify_password


@pytest.fixture(autouse=True)
def reset_database() -> None:
    async def _reset() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_reset())


def test_seed_default_users_keeps_only_admin_and_user() -> None:
    async def _seed_extra_user_data() -> None:
        async with AsyncSessionLocal() as session:
            extra = User(
                id="extra-user-id",
                username="developer",
                display_name="Developer",
                role="user",
                password_hash=hash_password("pass"),
            )
            kb = KnowledgeBase(id="kb-id", name="KB", description="", creator_id=extra.id)
            orphan_kb = KnowledgeBase(
                id="orphan-kb-id",
                name="Orphan KB",
                description="",
                creator_id="deleted-before-seed",
            )
            doc = Document(
                id="doc-id",
                knowledge_base_id=kb.id,
                uploader_id=extra.id,
                title="doc",
                filename="doc.pdf",
                mime="application/pdf",
                size_bytes=10,
                sha256="a" * 64,
                storage_path="uploads/documents/doc.pdf",
                status="completed",
            )
            login_record = LoginRecord(
                id="login-id",
                user_id=extra.id,
                refresh_token_jti="jti",
                ip_address="127.0.0.1",
                user_agent="pytest",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            chat_session = ChatSession(id="chat-id", user_id=extra.id, title="chat")
            chat_message = ChatMessage(id="msg-id", session_id=chat_session.id, role="user")
            citation = ChatMessageCitation(
                id="citation-id",
                message_id=chat_message.id,
                index=1,
                document_id=doc.id,
                knowledge_base_id=kb.id,
            )
            search_job = SearchExportJob(id="export-id", user_id=extra.id)
            audit_log = AuditLog(
                id="audit-id",
                actor_user_id=extra.id,
                action="test",
                target_type="user",
                target_id=extra.id,
            )
            permission = KnowledgeBasePermission(
                id="permission-id",
                knowledge_base_id=kb.id,
                user_id=extra.id,
                role="viewer",
            )
            session.add_all(
                [
                    extra,
                    kb,
                    orphan_kb,
                    doc,
                    login_record,
                    chat_session,
                    chat_message,
                    citation,
                    search_job,
                    audit_log,
                    permission,
                ]
            )
            await session.commit()

    async def _assert_cleaned() -> None:
        async with AsyncSessionLocal() as session:
            users = list(await session.scalars(select(User).order_by(User.username)))
            assert [user.username for user in users] == ["admin", "user"]

            admin = users[0]
            normal_user = users[1]
            assert admin.role == "admin"
            assert normal_user.role == "user"
            assert verify_password("Admin@123456", admin.password_hash)
            assert verify_password("User@123456", normal_user.password_hash)

            doc = await session.get(Document, "doc-id")
            kb = await session.get(KnowledgeBase, "kb-id")
            orphan_kb = await session.get(KnowledgeBase, "orphan-kb-id")
            audit_log = await session.get(AuditLog, "audit-id")
            assert doc is not None
            assert kb is not None
            assert orphan_kb is not None
            assert audit_log is not None
            assert doc.uploader_id == admin.id
            assert kb.creator_id == admin.id
            assert orphan_kb.creator_id == admin.id
            assert audit_log.actor_user_id is None

            assert await session.get(LoginRecord, "login-id") is None
            assert await session.get(KnowledgeBasePermission, "permission-id") is None
            assert await session.get(ChatSession, "chat-id") is None
            assert await session.get(ChatMessage, "msg-id") is None
            assert await session.get(ChatMessageCitation, "citation-id") is None
            assert await session.get(SearchExportJob, "export-id") is None

    asyncio.run(_seed_extra_user_data())
    result = asyncio.run(seed_default_users(reset_existing_passwords=True))

    assert result.kept_usernames == ("admin", "user")
    assert result.removed_user_count == 1
    asyncio.run(_assert_cleaned())
