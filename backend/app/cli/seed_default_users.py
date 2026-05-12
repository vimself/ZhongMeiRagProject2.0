from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.auth import AuditLog, LoginRecord, User
from app.models.chat import ChatMessage, ChatMessageCitation, ChatSession
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.models.search_export import SearchExportJob
from app.security.password import hash_password


@dataclass(frozen=True)
class SeedUserSpec:
    username: str
    display_name: str
    password: str
    role: str
    require_password_change: bool


@dataclass(frozen=True)
class SeedDefaultUsersResult:
    kept_usernames: tuple[str, str]
    removed_user_count: int


def _normalize_username(username: str) -> str:
    return username.strip().lower()


async def _upsert_seed_user(
    session: AsyncSession,
    spec: SeedUserSpec,
    *,
    reset_existing_passwords: bool,
) -> User:
    user = await session.scalar(select(User).where(User.username == spec.username))
    if user is None:
        user = User(
            username=spec.username,
            display_name=spec.display_name,
            role=spec.role,
            password_hash=hash_password(spec.password),
            is_active=True,
            require_password_change=spec.require_password_change,
        )
        session.add(user)
        await session.flush()
        return user

    user.display_name = spec.display_name
    user.role = spec.role
    user.is_active = True
    if reset_existing_passwords:
        user.password_hash = hash_password(spec.password)
        user.require_password_change = spec.require_password_change
    return user


async def seed_default_users(
    *,
    reset_existing_passwords: bool | None = None,
) -> SeedDefaultUsersResult:
    settings = get_settings()
    if settings.admin_seed_password is None:
        raise RuntimeError("ADMIN_SEED_PASSWORD 未配置，无法创建默认管理员账号")

    admin_username = _normalize_username(settings.admin_seed_username)
    user_username = _normalize_username(settings.user_seed_username)
    if admin_username == user_username:
        raise RuntimeError("ADMIN_SEED_USERNAME 和 USER_SEED_USERNAME 不能相同")

    reset_passwords = (
        settings.default_users_reset_passwords
        if reset_existing_passwords is None
        else reset_existing_passwords
    )
    admin_spec = SeedUserSpec(
        username=admin_username,
        display_name=settings.admin_seed_display_name,
        password=settings.admin_seed_password.get_secret_value(),
        role="admin",
        require_password_change=True,
    )
    user_spec = SeedUserSpec(
        username=user_username,
        display_name=settings.user_seed_display_name,
        password=settings.user_seed_password.get_secret_value(),
        role="user",
        require_password_change=False,
    )

    async with AsyncSessionLocal() as session:
        admin = await _upsert_seed_user(
            session, admin_spec, reset_existing_passwords=reset_passwords
        )
        normal_user = await _upsert_seed_user(
            session, user_spec, reset_existing_passwords=reset_passwords
        )
        keep_user_ids = (admin.id, normal_user.id)
        keep_usernames = (admin.username, normal_user.username)

        invalid_user_ids = list(
            await session.scalars(select(User.id).where(User.username.not_in(keep_usernames)))
        )
        if invalid_user_ids:
            await session.execute(
                update(Document)
                .where(Document.uploader_id.in_(invalid_user_ids))
                .values(uploader_id=admin.id)
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                update(KnowledgeBase)
                .where(KnowledgeBase.creator_id.in_(invalid_user_ids))
                .values(creator_id=admin.id)
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                update(AuditLog)
                .where(AuditLog.actor_user_id.in_(invalid_user_ids))
                .values(actor_user_id=None)
                .execution_options(synchronize_session=False)
            )

            invalid_session_ids = select(ChatSession.id).where(
                ChatSession.user_id.in_(invalid_user_ids)
            )
            invalid_message_ids = select(ChatMessage.id).where(
                ChatMessage.session_id.in_(invalid_session_ids)
            )
            await session.execute(
                delete(ChatMessageCitation)
                .where(ChatMessageCitation.message_id.in_(invalid_message_ids))
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                delete(ChatMessage)
                .where(ChatMessage.session_id.in_(invalid_session_ids))
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                delete(ChatSession)
                .where(ChatSession.user_id.in_(invalid_user_ids))
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                delete(SearchExportJob)
                .where(SearchExportJob.user_id.in_(invalid_user_ids))
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                delete(KnowledgeBasePermission)
                .where(KnowledgeBasePermission.user_id.in_(invalid_user_ids))
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                delete(LoginRecord)
                .where(LoginRecord.user_id.in_(invalid_user_ids))
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                delete(User)
                .where(User.id.in_(invalid_user_ids))
                .execution_options(synchronize_session=False)
            )

        await session.execute(
            update(KnowledgeBase)
            .where(
                or_(
                    KnowledgeBase.creator_id.is_(None),
                    KnowledgeBase.creator_id.not_in(keep_user_ids),
                )
            )
            .values(creator_id=admin.id)
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            delete(KnowledgeBasePermission)
            .where(KnowledgeBasePermission.user_id.not_in(keep_user_ids))
            .execution_options(synchronize_session=False)
        )

        # A final guard keeps role/name collisions from leaving extra rows behind.
        await session.execute(
            delete(User)
            .where(User.id.not_in(keep_user_ids))
            .execution_options(synchronize_session=False)
        )
        await session.commit()

    return SeedDefaultUsersResult(
        kept_usernames=keep_usernames,
        removed_user_count=len(invalid_user_ids),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed and prune default users.")
    parser.add_argument(
        "--reset-passwords",
        action="store_true",
        help="Reset passwords for existing admin/user accounts from environment settings.",
    )
    args = parser.parse_args()

    result = asyncio.run(
        seed_default_users(
            reset_existing_passwords=True if args.reset_passwords else None,
        )
    )
    print(
        "Seeded default users: "
        f"{', '.join(result.kept_usernames)}; "
        f"removed {result.removed_user_count} invalid user(s)."
    )


if __name__ == "__main__":
    main()
