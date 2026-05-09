from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.auth import User
from app.security.password import hash_password


async def seed_admin() -> None:
    settings = get_settings()
    if settings.admin_seed_password is None:
        raise RuntimeError("ADMIN_SEED_PASSWORD 未配置，无法创建管理员种子账号")

    username = settings.admin_seed_username.strip().lower()
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == username))
        password_hash = hash_password(settings.admin_seed_password.get_secret_value())
        if user is None:
            session.add(
                User(
                    username=username,
                    display_name=settings.admin_seed_display_name,
                    role="admin",
                    password_hash=password_hash,
                    require_password_change=True,
                )
            )
        else:
            user.display_name = settings.admin_seed_display_name
            user.role = "admin"
            user.password_hash = password_hash
            user.require_password_change = True
            user.is_active = True
        await session.commit()


def main() -> None:
    asyncio.run(seed_admin())


if __name__ == "__main__":
    main()
