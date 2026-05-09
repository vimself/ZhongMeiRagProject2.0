from __future__ import annotations

import time

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings


class LoginFailureLimiter:
    def __init__(self) -> None:
        self._memory: dict[str, tuple[int, float]] = {}
        self._redis: Redis | None = None

    def _client(self) -> Redis | None:
        settings = get_settings()
        if settings.app_env == "test":
            return None
        if self._redis is None:
            self._redis = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
        return self._redis

    async def ensure_allowed(self, subject: str, ip_address: str) -> None:
        settings = get_settings()
        subject_key, ip_key = self._keys(subject, ip_address)
        subject_count = await self._get_count(subject_key)
        ip_count = await self._get_count(ip_key)
        if max(subject_count, ip_count) >= settings.login_failed_limit:
            raise self._blocked()

    async def record_failure(self, subject: str, ip_address: str) -> None:
        settings = get_settings()
        subject_key, ip_key = self._keys(subject, ip_address)
        subject_count = await self._increment(subject_key)
        ip_count = await self._increment(ip_key)
        if max(subject_count, ip_count) >= settings.login_failed_limit:
            raise self._blocked()

    async def clear(self, subject: str, ip_address: str) -> None:
        subject_key, ip_key = self._keys(subject, ip_address)
        client = self._client()
        if client is not None:
            try:
                await client.delete(subject_key, ip_key)
                return
            except RedisError:
                pass
        self._memory.pop(subject_key, None)
        self._memory.pop(ip_key, None)

    def clear_memory(self) -> None:
        self._memory.clear()

    def _keys(self, subject: str, ip_address: str) -> tuple[str, str]:
        normalized_subject = subject.strip().lower()
        return (
            f"auth:login-fail:subject:{normalized_subject}",
            f"auth:login-fail:ip:{ip_address}",
        )

    async def _get_count(self, key: str) -> int:
        client = self._client()
        if client is not None:
            try:
                raw = await client.get(key)
                return int(raw or 0)
            except (RedisError, ValueError):
                pass
        value = self._memory.get(key)
        if value is None:
            return 0
        count, expires_at = value
        if expires_at <= time.monotonic():
            self._memory.pop(key, None)
            return 0
        return count

    async def _increment(self, key: str) -> int:
        settings = get_settings()
        client = self._client()
        if client is not None:
            try:
                value = await client.incr(key)
                if value == 1:
                    await client.expire(key, settings.login_failed_window_seconds)
                return int(value)
            except RedisError:
                pass
        count, expires_at = self._memory.get(
            key, (0, time.monotonic() + settings.login_failed_window_seconds)
        )
        if expires_at <= time.monotonic():
            count = 0
            expires_at = time.monotonic() + settings.login_failed_window_seconds
        count += 1
        self._memory[key] = (count, expires_at)
        return count

    def _blocked(self) -> HTTPException:
        settings = get_settings()
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"登录失败次数过多，请 {settings.login_failed_window_seconds // 60} 分钟后再试",
        )


login_failure_limiter = LoginFailureLimiter()
