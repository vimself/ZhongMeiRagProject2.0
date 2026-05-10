from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentAsset


async def register_assets(
    db: AsyncSession,
    *,
    document_id: str,
    assets_payload: dict[str, Any],
    output_dir: Path,
) -> int:
    await db.execute(delete(DocumentAsset).where(DocumentAsset.document_id == document_id))
    images = assets_payload.get("images", [])
    if not isinstance(images, list):
        images = []
    asset_dir = output_dir / "assets" / document_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        name = str(image.get("name") or f"image_{index}.jpg")
        safe_name = Path(name).name
        storage_path = asset_dir / safe_name
        encoded = image.get("base64")
        if isinstance(encoded, str) and encoded:
            storage_path.write_bytes(base64.b64decode(encoded))
        else:
            storage_path.write_bytes(b"")
        db.add(
            DocumentAsset(
                document_id=document_id,
                kind="image",
                page_no=_optional_int(image.get("page_no")),
                bbox_json=image.get("bbox") if isinstance(image.get("bbox"), dict) else None,
                storage_path=str(storage_path),
                caption=str(image.get("caption")) if image.get("caption") else None,
            )
        )
        count += 1
    await db.flush()
    return count


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None
