from __future__ import annotations

from collections.abc import Iterator
from mimetypes import guess_type
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _record_audit
from app.api.deps import (
    AssetTokenUser,
    DbSession,
    PdfTokenUser,
    asset_token_user,
    current_user,
    pdf_token_user,
)
from app.api.knowledge_base_deps import require_document_role
from app.models.auth import User
from app.models.document import DocumentAsset
from app.schemas.pdf_preview import (
    AssetSignRequest,
    AssetSignResponse,
    PdfSignRequest,
    PdfSignResponse,
)
from app.security.jwt import issue_asset_token, issue_pdf_token

router = APIRouter(tags=["pdf-preview"])

CurrentUser = Annotated[User, Depends(current_user)]


@router.post("/api/v2/pdf/sign", response_model=PdfSignResponse)
async def sign_pdf(
    body: PdfSignRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> PdfSignResponse:
    document, _role = await require_document_role(
        db, user, body.document_id, {"viewer", "editor", "owner"}
    )
    issued = issue_pdf_token(
        subject=user.id,
        document_id=document.id,
        knowledge_base_id=document.knowledge_base_id,
    )
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="pdf.sign",
        target_type="document",
        target_id=document.id,
        request=request,
        details={"knowledge_base_id": document.knowledge_base_id},
    )
    await db.commit()
    return PdfSignResponse(
        token=issued.token,
        expires_at=issued.expires_at.isoformat(),
        document_id=document.id,
    )


@router.post("/api/v2/assets/sign", response_model=AssetSignResponse)
async def sign_asset(
    body: AssetSignRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> AssetSignResponse:
    asset = await _get_asset_or_404(db, body.asset_id)
    document, _role = await require_document_role(
        db, user, asset.document_id, {"viewer", "editor", "owner"}
    )
    issued = issue_asset_token(
        subject=user.id,
        document_id=document.id,
        asset_id=asset.id,
        knowledge_base_id=document.knowledge_base_id,
    )
    url = f"/api/v2/assets/preview?asset_id={asset.id}&token={quote(issued.token)}"
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="asset.sign",
        target_type="document_asset",
        target_id=asset.id,
        request=request,
        details={"document_id": document.id, "knowledge_base_id": document.knowledge_base_id},
    )
    await db.commit()
    return AssetSignResponse(
        token=issued.token,
        expires_at=issued.expires_at.isoformat(),
        asset_id=asset.id,
        document_id=document.id,
        url=url,
    )


@router.get("/api/v2/pdf/preview", response_model=None)
async def preview_pdf(
    request: Request,
    pdf_user: Annotated[PdfTokenUser, Depends(pdf_token_user)],
    db: DbSession,
    document_id: str = Query(...),
    page: int | None = Query(default=None, ge=1),
) -> FileResponse | StreamingResponse:
    if pdf_user.document_id != document_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PDF token 文档范围不匹配",
        )
    document, _role = await require_document_role(
        db, pdf_user.user, document_id, {"viewer", "editor", "owner"}
    )
    if pdf_user.knowledge_base_id and pdf_user.knowledge_base_id != document.knowledge_base_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="PDF token 知识库范围不匹配"
        )
    file_path = _resolve_existing_file(document.storage_path, "PDF 文件不存在")
    await _record_audit(
        db,
        actor_user_id=pdf_user.user.id,
        action="pdf.preview",
        target_type="document",
        target_id=document.id,
        request=request,
        details={"knowledge_base_id": document.knowledge_base_id, "page": page},
    )
    await db.commit()
    return _file_response(
        request,
        file_path=file_path,
        media_type="application/pdf",
        filename=document.filename,
        disposition="inline",
    )


@router.get("/api/v2/documents/{document_id}/download", response_model=None)
async def download_pdf(
    request: Request,
    document_id: str,
    pdf_user: Annotated[PdfTokenUser, Depends(pdf_token_user)],
    db: DbSession,
) -> FileResponse | StreamingResponse:
    if pdf_user.document_id != document_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="PDF token 文档范围不匹配"
        )
    document, _role = await require_document_role(
        db, pdf_user.user, document_id, {"viewer", "editor", "owner"}
    )
    if pdf_user.knowledge_base_id and pdf_user.knowledge_base_id != document.knowledge_base_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="PDF token 知识库范围不匹配"
        )
    file_path = _resolve_existing_file(document.storage_path, "PDF 文件不存在")
    await _record_audit(
        db,
        actor_user_id=pdf_user.user.id,
        action="pdf.download",
        target_type="document",
        target_id=document.id,
        request=request,
        details={"knowledge_base_id": document.knowledge_base_id},
    )
    await db.commit()
    return _file_response(
        request,
        file_path=file_path,
        media_type="application/pdf",
        filename=document.filename,
        disposition="attachment",
    )


@router.get("/api/v2/assets/preview", response_model=None)
async def preview_asset(
    request: Request,
    asset_user: Annotated[AssetTokenUser, Depends(asset_token_user)],
    db: DbSession,
    asset_id: str = Query(...),
) -> FileResponse | StreamingResponse:
    if asset_user.asset_id != asset_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="资产 token 范围不匹配")
    asset = await _get_asset_or_404(db, asset_id)
    document, _role = await require_document_role(
        db, asset_user.user, asset.document_id, {"viewer", "editor", "owner"}
    )
    if asset_user.document_id != document.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="资产 token 文档范围不匹配"
        )
    if asset_user.knowledge_base_id and asset_user.knowledge_base_id != document.knowledge_base_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="资产 token 知识库范围不匹配"
        )
    file_path = _resolve_existing_file(asset.storage_path, "资产文件不存在")
    await _record_audit(
        db,
        actor_user_id=asset_user.user.id,
        action="asset.preview",
        target_type="document_asset",
        target_id=asset.id,
        request=request,
        details={"document_id": document.id, "knowledge_base_id": document.knowledge_base_id},
    )
    await db.commit()
    media_type = guess_type(file_path.name)[0] or "application/octet-stream"
    return _file_response(
        request,
        file_path=file_path,
        media_type=media_type,
        filename=file_path.name,
        disposition="inline",
    )


async def _get_asset_or_404(db: AsyncSession, asset_id: str) -> DocumentAsset:
    asset = await db.scalar(select(DocumentAsset).where(DocumentAsset.id == asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在")
    return asset


def _resolve_existing_file(storage_path: str, missing_detail: str) -> Path:
    file_path = Path(storage_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=missing_detail)
    return file_path


def _file_response(
    request: Request,
    *,
    file_path: Path,
    media_type: str,
    filename: str,
    disposition: str,
) -> FileResponse | StreamingResponse:
    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")
    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=60",
        "Content-Disposition": _content_disposition(disposition, filename),
    }
    if not range_header:
        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            filename=filename,
            headers=base_headers,
        )
    start, end = _parse_range(range_header, file_size)
    content_length = end - start + 1
    headers = {
        **base_headers,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(content_length),
    }
    return StreamingResponse(
        _iter_file_range(file_path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    if not range_header.startswith("bytes=") or "," in range_header:
        raise _range_not_satisfiable(file_size)
    value = range_header.removeprefix("bytes=").strip()
    start_text, separator, end_text = value.partition("-")
    if separator != "-":
        raise _range_not_satisfiable(file_size)
    try:
        if start_text == "":
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
    except ValueError as exc:
        raise _range_not_satisfiable(file_size) from exc
    if start < 0 or end < start or start >= file_size:
        raise _range_not_satisfiable(file_size)
    return start, min(end, file_size - 1)


def _range_not_satisfiable(file_size: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
        detail="Range 请求范围无效",
        headers={"Content-Range": f"bytes */{file_size}"},
    )


def _iter_file_range(file_path: Path, start: int, end: int) -> Iterator[bytes]:
    chunk_size = 1024 * 1024
    with file_path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _content_disposition(disposition: str, filename: str) -> str:
    safe_name = Path(filename).name or "document.pdf"
    return f"{disposition}; filename*=UTF-8''{quote(safe_name)}"
