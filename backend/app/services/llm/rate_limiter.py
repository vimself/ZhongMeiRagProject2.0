from __future__ import annotations

import asyncio
import time
from typing import Any


class RedisTokenBucket:
    """基于 Redis 的简易令牌桶；Redis 不可用时退化为进程内限流。"""

    def __init__(
        self,
        redis_client: Any | None = None,
        *,
        capacity: int = 10,
        refill_per_second: float = 10.0,
    ) -> None:
        self.redis = redis_client
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._local_lock = asyncio.Lock()
        self._local_tokens: dict[str, float] = {}
        self._local_updated: dict[str, float] = {}

    async def acquire(self, model_id: str, tokens: int = 1) -> None:
        if self.redis is None:
            await self._acquire_local(model_id, tokens)
            return
        key = f"llm:bucket:{model_id}"
        while True:
            now = time.time()
            try:
                payload = await self.redis.hgetall(key)
                current = float(payload.get(b"tokens", self.capacity))
                updated = float(payload.get(b"updated", now))
                current = min(self.capacity, current + (now - updated) * self.refill_per_second)
                if current >= tokens:
                    await self.redis.hset(
                        key,
                        mapping={"tokens": current - tokens, "updated": now},
                    )
                    await self.redis.expire(key, 60)
                    return
                wait_for = (tokens - current) / self.refill_per_second
            except Exception:
                await self._acquire_local(model_id, tokens)
                return
            await asyncio.sleep(max(0.05, wait_for))

    async def _acquire_local(self, model_id: str, tokens: int) -> None:
        async with self._local_lock:
            now = time.time()
            current = self._local_tokens.get(model_id, float(self.capacity))
            updated = self._local_updated.get(model_id, now)
            current = min(self.capacity, current + (now - updated) * self.refill_per_second)
            if current >= tokens:
                self._local_tokens[model_id] = current - tokens
                self._local_updated[model_id] = now
                return
            wait_for = (tokens - current) / self.refill_per_second
            self._local_tokens[model_id] = current
            self._local_updated[model_id] = now
        await asyncio.sleep(max(0.05, wait_for))
        await self._acquire_local(model_id, tokens)
