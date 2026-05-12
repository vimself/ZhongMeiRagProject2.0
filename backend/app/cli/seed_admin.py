from __future__ import annotations

import asyncio

from app.cli.seed_default_users import seed_default_users


async def seed_admin() -> None:
    await seed_default_users(reset_existing_passwords=True)


def main() -> None:
    asyncio.run(seed_admin())


if __name__ == "__main__":
    main()
