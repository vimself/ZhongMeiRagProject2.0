from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import IngestStepReceipt

T = TypeVar("T")


def payload_hash(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def idempotency_key(job_id: str, step: str, payload: object) -> str:
    return f"{job_id}:{step}:{payload_hash(payload)}"


async def get_receipt_payload(
    db: AsyncSession,
    *,
    key: str,
) -> dict[str, Any] | None:
    receipt = await db.scalar(
        select(IngestStepReceipt).where(IngestStepReceipt.idempotency_key == key)
    )
    if receipt is None or receipt.status != "succeeded":
        return None
    return receipt.payload_json


async def write_receipt(
    db: AsyncSession,
    *,
    job_id: str,
    step: str,
    key: str,
    payload: dict[str, Any],
    status: str = "succeeded",
) -> IngestStepReceipt:
    receipt = IngestStepReceipt(
        job_id=job_id,
        step=step,
        idempotency_key=key,
        status=status,
        payload_json=payload,
    )
    db.add(receipt)
    await db.flush()
    return receipt


async def run_idempotent_step(
    db: AsyncSession,
    *,
    job_id: str,
    step: str,
    input_payload: object,
    runner: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    key = idempotency_key(job_id, step, input_payload)
    cached = await get_receipt_payload(db, key=key)
    if cached is not None:
        return cached
    output = await runner()
    await write_receipt(db, job_id=job_id, step=step, key=key, payload=output)
    return output
