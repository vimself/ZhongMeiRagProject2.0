from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import IngestStepReceipt

T = TypeVar("T")
EXTERNAL_PAYLOAD_MARKER = "__external_payload__"


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
    return load_stored_payload(receipt.payload_json)


async def write_receipt(
    db: AsyncSession,
    *,
    job_id: str,
    step: str,
    key: str,
    payload: dict[str, Any],
    status: str = "succeeded",
) -> IngestStepReceipt:
    stored_payload, external_path = store_payload(job_id=job_id, step=step, payload=payload)
    receipt = IngestStepReceipt(
        job_id=job_id,
        step=step,
        idempotency_key=key,
        status=status,
        payload_json=stored_payload,
    )
    db.add(receipt)
    try:
        await db.flush()
    except Exception:
        if external_path is not None:
            external_path.unlink(missing_ok=True)
        raise
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


def load_stored_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not is_external_payload_pointer(payload):
        return payload
    path = payload.get("path")
    if not isinstance(path, str) or not path:
        return None
    receipt_path = Path(path)
    try:
        raw = receipt_path.read_text(encoding="utf-8")
        loaded = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def is_external_payload_pointer(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get(EXTERNAL_PAYLOAD_MARKER) is True


def external_payload_path(payload: object) -> str | None:
    if not is_external_payload_pointer(payload):
        return None
    path = payload.get("path")
    return path if isinstance(path, str) and path else None


def store_payload(
    *,
    job_id: str,
    step: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], Path | None]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    raw_bytes = raw.encode("utf-8")
    settings = get_settings()
    if len(raw_bytes) <= settings.ingest_receipt_inline_max_bytes:
        return payload, None

    digest = hashlib.sha256(raw_bytes).hexdigest()
    receipt_dir = _receipt_dir(job_id)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{step}-{digest}.json"
    receipt_path.write_text(raw, encoding="utf-8")
    stored_payload = {
        EXTERNAL_PAYLOAD_MARKER: True,
        "path": str(receipt_path),
        "sha256": digest,
        "size_bytes": len(raw_bytes),
        "summary": summarize_payload(payload),
    }
    return stored_payload, receipt_path


def summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"keys": sorted(payload.keys())}
    count = payload.get("count")
    if isinstance(count, int):
        summary["count"] = count
    vectors = payload.get("vectors")
    if isinstance(vectors, list):
        summary["vector_count"] = len(vectors)
        first_vector = next((item for item in vectors if isinstance(item, list)), None)
        if first_vector is not None:
            summary["vector_dimension"] = len(first_vector)
    chunks = payload.get("chunks")
    if isinstance(chunks, list):
        summary["chunk_count"] = len(chunks)
    markdown = payload.get("markdown")
    if isinstance(markdown, str):
        summary["markdown_chars"] = len(markdown)
    return summary


def _receipt_dir(job_id: str) -> Path:
    settings = get_settings()
    base = Path(settings.upload_dir)
    return base / "ingest_receipts" / job_id
