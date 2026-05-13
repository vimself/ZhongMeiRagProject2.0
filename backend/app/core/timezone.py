from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_beijing(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(BEIJING_TZ)


def isoformat_beijing(value: datetime | None) -> str:
    converted = as_beijing(value)
    return converted.isoformat() if converted else ""
