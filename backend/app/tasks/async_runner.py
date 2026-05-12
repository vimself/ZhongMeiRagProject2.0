from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from app.db.session import engine

T = TypeVar("T")


async def _run_and_dispose(awaitable: Awaitable[T]) -> T:
    try:
        return await awaitable
    finally:
        await engine.dispose()


def run_async_task(awaitable: Awaitable[T]) -> T:
    """Run one async Celery task without reusing pooled connections across loops."""
    return asyncio.run(_run_and_dispose(awaitable))
