from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import time
import traceback
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from config import (
    API_HOST,
    API_PORT,
    API_TOKEN,
    CALLBACK_TIMEOUT_SECONDS,
    CLEANUP_INTERVAL_SECONDS,
    CORS_ALLOW_ORIGINS,
    DEFAULT_CALLBACK_URL,
    GENERATE_TIMEOUT_SECONDS,
    GLM_PRELOAD_PIPELINE,
    MAX_FILE_SIZE,
    MODEL_NAME,
    OCR_CALLBACK_TOKEN,
    QUEUE_SIZE,
    SESSION_TTL_SECONDS,
    TEMP_DIR,
    VLLM_BASE_URL,
)
from glm_processor import GlmOCRProcessor

app = FastAPI(title="GLM OCR API", version="1.0.0")
logger = logging.getLogger("glm_ocr_api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)
processor = GlmOCRProcessor()
task_queue: asyncio.PriorityQueue[tuple[int, float, str]] = asyncio.PriorityQueue(maxsize=QUEUE_SIZE)
active_sessions: set[str] = set()
cancelled_sessions: set[str] = set()
worker_task: asyncio.Task[None] | None = None
cleanup_task: asyncio.Task[None] | None = None


class ErrorResponse(BaseModel):
    code: str
    message: str
    detail: Any = None


class ImageInfo(BaseModel):
    name: str
    url: str | None = None
    size: int
    width: int | None = None
    height: int | None = None


class ImageListResponse(BaseModel):
    session_id: str
    total: int
    images: list[ImageInfo]


class ImageDataResponse(BaseModel):
    name: str
    base64: str
    mime_type: str
    size: int
    page_no: int | None = None
    bbox: dict[str, float] | None = None


class ImagesDataResponse(BaseModel):
    session_id: str
    total: int
    images: list[ImageDataResponse]


class SessionCancelled(Exception):
    pass


@dataclass
class SessionMeta:
    session_id: str
    filename: str
    status: str = "queued"
    stage: str = "queued"
    progress: int = 0
    priority: int = 5
    callback_url: str | None = None
    uploaded_at: str = field(default_factory=lambda: _now_iso())
    started_at: str | None = None
    updated_at: str = field(default_factory=lambda: _now_iso())
    processed_at: str | None = None
    elapsed_ms: int = 0
    page_count: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    traceback_tail: str | None = None
    assets: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    formulas: list[dict[str, Any]] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_dir(session_id: str) -> Path:
    return Path(TEMP_DIR) / session_id


def _output_dir(session_id: str) -> Path:
    return _session_dir(session_id) / "output"


def _meta_path(session_id: str) -> Path:
    return _session_dir(session_id) / "meta.json"


def _status_path(session_id: str) -> Path:
    return _output_dir(session_id) / "status.txt"


def _write_meta(meta: SessionMeta) -> None:
    meta.updated_at = _now_iso()
    path = _meta_path(meta.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(meta), ensure_ascii=False, indent=2), encoding="utf-8")
    _output_dir(meta.session_id).mkdir(parents=True, exist_ok=True)
    _status_path(meta.session_id).write_text(_legacy_status(meta.status), encoding="utf-8")


def _read_meta(session_id: str) -> SessionMeta:
    path = _meta_path(session_id)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionMeta(**data)
    raise HTTPException(status_code=404, detail="Session not found.")


def _legacy_status(status_value: str) -> str:
    if status_value in {"failed", "completed", "queued"}:
        return status_value
    return "processing" if status_value == "running" else status_value


def require_write_token(authorization: str | None = Header(default=None)) -> None:
    if not API_TOKEN:
        return
    expected = f"Bearer {API_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid API token.")


@app.exception_handler(HTTPException)
async def structured_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and {"code", "message"} <= set(exc.detail):
        return await http_exception_handler(request, exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            code=f"http_{exc.status_code}",
            message=str(exc.detail),
            detail=None,
        ).model_dump(),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            code="validation_error",
            message="请求参数不正确",
            detail=exc.errors(),
        ).model_dump(),
    )


@app.on_event("startup")
async def startup() -> None:
    global worker_task, cleanup_task
    worker_task = asyncio.create_task(_worker_loop())
    cleanup_task = asyncio.create_task(_cleanup_loop())
    if GLM_PRELOAD_PIPELINE:
        asyncio.create_task(asyncio.to_thread(processor.ensure_started))


@app.on_event("shutdown")
async def shutdown() -> None:
    for task in (worker_task, cleanup_task):
        if task is not None:
            task.cancel()
    processor.close()


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "message": "GLM OCR API",
        "version": "1.0.0",
        "model": MODEL_NAME,
        "endpoints": {
            "/upload": "POST - Upload PDF for OCR processing",
            "/queue": "GET - Queue status",
            "/healthz": "GET - Process health",
            "/readyz": "GET - vLLM and pipeline readiness",
            "/status/{session_id}": "GET - Check processing status",
            "/result/{session_id}/markdown": "GET - Get markdown content",
            "/result/{session_id}/json": "GET - Get GLM layout JSON",
            "/result/{session_id}/assets": "GET - Get extracted assets",
            "/result/{session_id}/images/base64": "GET - Backward compatible images endpoint",
            "/session/{session_id}": "DELETE - Delete session",
        },
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    vllm_ready = processor.vllm_ready()
    return {
        "status": "ready" if vllm_ready else "not_ready",
        "model": MODEL_NAME,
        "vllm_base_url": VLLM_BASE_URL,
        "vllm_ready": vllm_ready,
        "pipeline_loaded": processor.is_loaded,
    }


@app.get("/queue")
async def queue_status() -> dict[str, int]:
    return {"queued": task_queue.qsize(), "active": len(active_sessions), "capacity": QUEUE_SIZE}


@app.post("/upload", dependencies=[Depends(require_write_token)])
async def upload_pdf(
    file: UploadFile = File(...),
    priority: int = Form(default=5),
    callback_url: str | None = Form(default=None),
) -> dict[str, Any]:
    if not processor.vllm_ready(timeout=1.0):
        raise HTTPException(status_code=503, detail="OCR backend is not ready.")
    content = await file.read()
    _validate_pdf(file, content)
    session_id = str(uuid.uuid4())
    session_dir = _session_dir(session_id)
    output_dir = _output_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "document.pdf").name
    pdf_path = session_dir / filename
    pdf_path.write_bytes(content)
    meta = SessionMeta(
        session_id=session_id,
        filename=filename,
        status="queued",
        stage="queued",
        progress=0,
        priority=priority,
        callback_url=callback_url or DEFAULT_CALLBACK_URL or None,
    )
    _write_meta(meta)
    try:
        task_queue.put_nowait((priority, time.time(), session_id))
    except asyncio.QueueFull as exc:
        meta.status = "failed"
        meta.error_code = "queue_full"
        meta.error_message = "OCR 队列已满"
        _write_meta(meta)
        raise HTTPException(status_code=429, detail="OCR queue is full.") from exc
    logger.info(
        "ocr_queued session_id=%s filename=%s size_mb=%.1f queued=%s active=%s",
        session_id,
        filename,
        len(content) / 1024 / 1024,
        task_queue.qsize(),
        len(active_sessions),
    )
    return {
        "session_id": session_id,
        "status": "queued",
        "message": "PDF uploaded successfully. Processing queued.",
    }


@app.get("/status/{session_id}")
async def get_status(session_id: str) -> dict[str, Any]:
    meta = _read_meta(session_id)
    payload = asdict(meta)
    payload.update(
        {
            "is_completed": meta.status == "completed",
            "is_failed": meta.status == "failed",
        }
    )
    return payload


@app.get("/result/{session_id}")
async def get_result(session_id: str) -> FileResponse:
    _ensure_completed(session_id)
    output_dir = _output_dir(session_id)
    zip_path = Path(TEMP_DIR) / f"{session_id}_results.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _dirs, files in os.walk(output_dir):
            for file in files:
                if file == "status.txt":
                    continue
                file_path = Path(root) / file
                zipf.write(file_path, file_path.relative_to(output_dir))
    return FileResponse(path=zip_path, media_type="application/zip", filename=f"{session_id}_results.zip")


@app.get("/result/{session_id}/markdown")
async def get_markdown(session_id: str, include_meta: bool = False) -> dict[str, Any]:
    meta = _ensure_completed(session_id)
    markdown_path = _output_dir(session_id) / "result.md"
    if not markdown_path.exists():
        raise HTTPException(status_code=404, detail="Markdown result not found.")
    markdown = markdown_path.read_text(encoding="utf-8")
    if include_meta:
        return {
            "session_id": session_id,
            "markdown": markdown,
            "page_count": meta.page_count,
            "outline": _extract_outline(markdown),
            "processed_at": meta.processed_at,
        }
    return {"session_id": session_id, "markdown": markdown}


@app.get("/result/{session_id}/json")
async def get_json_result(session_id: str) -> dict[str, Any]:
    _ensure_completed(session_id)
    json_path = _output_dir(session_id) / "result.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="JSON result not found.")
    return {"session_id": session_id, "layout": json.loads(json_path.read_text(encoding="utf-8"))}


@app.get("/result/{session_id}/layout")
async def get_layout_result(session_id: str) -> dict[str, Any]:
    return await get_json_result(session_id)


@app.get("/result/{session_id}/images")
async def get_images(session_id: str) -> FileResponse:
    _ensure_completed(session_id)
    images_dir = _output_dir(session_id) / "images"
    if not images_dir.exists():
        raise HTTPException(status_code=404, detail="No images found.")
    zip_path = Path(TEMP_DIR) / f"{session_id}_images.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in sorted(images_dir.iterdir()):
            if file_path.is_file():
                zipf.write(file_path, file_path.name)
    return FileResponse(path=zip_path, media_type="application/zip", filename=f"{session_id}_images.zip")


@app.get("/result/{session_id}/image/{image_name}")
async def get_single_image(session_id: str, image_name: str) -> FileResponse:
    _ensure_completed(session_id)
    image_path = _output_dir(session_id) / "images" / Path(image_name).name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(path=image_path, media_type=_mime_for(image_path.name))


@app.get("/result/{session_id}/images/list", response_model=ImageListResponse)
async def get_images_list(session_id: str, request: Request) -> ImageListResponse:
    _ensure_completed(session_id)
    images_dir = _output_dir(session_id) / "images"
    if not images_dir.exists():
        return ImageListResponse(session_id=session_id, total=0, images=[])
    images = []
    for file_path in sorted(images_dir.iterdir()):
        if not _is_image(file_path.name):
            continue
        images.append(
            ImageInfo(
                name=file_path.name,
                url=str(request.url_for("get_single_image", session_id=session_id, image_name=file_path.name)),
                size=file_path.stat().st_size,
            )
        )
    return ImageListResponse(session_id=session_id, total=len(images), images=images)


@app.get("/result/{session_id}/assets")
async def get_assets(session_id: str) -> dict[str, Any]:
    meta = _ensure_completed(session_id)
    images_payload = _image_base64_payload(session_id, meta)
    return {
        "session_id": session_id,
        "images": images_payload,
        "tables": meta.tables,
        "formulas": meta.formulas,
        "layout_url": f"/result/{session_id}/json",
    }


@app.get("/result/{session_id}/images/base64", response_model=ImagesDataResponse)
async def get_images_base64(session_id: str) -> ImagesDataResponse:
    meta = _ensure_completed(session_id)
    images = [
        ImageDataResponse(
            name=item["name"],
            base64=item["base64"],
            mime_type=item["mime"],
            size=item["size"],
            page_no=item.get("page_no"),
            bbox=item.get("bbox"),
        )
        for item in _image_base64_payload(session_id, meta)
    ]
    return ImagesDataResponse(session_id=session_id, total=len(images), images=images)


@app.delete("/session/{session_id}", dependencies=[Depends(require_write_token)])
async def delete_session(session_id: str) -> dict[str, str]:
    session_dir = _session_dir(session_id).resolve()
    temp_dir = Path(TEMP_DIR).resolve()
    if not session_dir.exists() or temp_dir not in session_dir.parents:
        raise HTTPException(status_code=404, detail="Session not found.")
    cancelled_sessions.add(session_id)
    removed_from_queue = _drop_queued_session(session_id)
    was_active = session_id in active_sessions
    if session_dir.exists():
        shutil.rmtree(session_dir)
    if not was_active:
        cancelled_sessions.discard(session_id)
    message = "Session cancellation requested." if was_active else "Session deleted successfully."
    return {
        "session_id": session_id,
        "status": "cancelled",
        "queue_removed": str(removed_from_queue),
        "message": message,
    }


async def _worker_loop() -> None:
    while True:
        _priority, _queued_at, session_id = await task_queue.get()
        if _is_cancelled(session_id):
            _remove_session_dir(session_id)
            cancelled_sessions.discard(session_id)
            task_queue.task_done()
            continue
        active_sessions.add(session_id)
        try:
            await _process_session(session_id)
        finally:
            active_sessions.discard(session_id)
            if _is_cancelled(session_id):
                _remove_session_dir(session_id)
                cancelled_sessions.discard(session_id)
            task_queue.task_done()


async def _process_session(session_id: str) -> None:
    if _is_cancelled(session_id):
        raise SessionCancelled
    meta = _read_meta(session_id)
    started = time.time()
    meta.status = "running"
    meta.stage = "glm_pipeline"
    meta.progress = 10
    meta.started_at = _now_iso()
    _write_meta(meta)
    logger.info("ocr_started session_id=%s filename=%s", session_id, meta.filename)
    try:
        if _is_cancelled(session_id):
            raise SessionCancelled
        pdf_path = _session_dir(session_id) / meta.filename
        result = await processor.process_pdf_async(
            str(pdf_path),
            str(_output_dir(session_id)),
            timeout_seconds=GENERATE_TIMEOUT_SECONDS,
        )
        if _is_cancelled(session_id):
            raise SessionCancelled
        meta.stage = "post_processing"
        meta.progress = 90
        meta.page_count = int(result.get("page_count") or 0)
        meta.assets = list(result.get("assets") or [])
        meta.tables = list(result.get("tables") or [])
        meta.formulas = list(result.get("formulas") or [])
        _write_meta(meta)
        meta.status = "completed"
        meta.progress = 100
        meta.processed_at = _now_iso()
        meta.elapsed_ms = int((time.time() - started) * 1000)
        _write_meta(meta)
        logger.info(
            "ocr_completed session_id=%s filename=%s pages=%s elapsed_ms=%s",
            session_id,
            meta.filename,
            meta.page_count,
            meta.elapsed_ms,
        )
        await _send_callback(meta)
    except SessionCancelled:
        _remove_session_dir(session_id)
    except Exception as exc:
        if _is_cancelled(session_id):
            _remove_session_dir(session_id)
            return
        meta.status = "failed"
        meta.error_code = exc.__class__.__name__
        meta.error_message = str(exc)
        meta.traceback_tail = "\n".join(traceback.format_exc().splitlines()[-20:])
        meta.elapsed_ms = int((time.time() - started) * 1000)
        _write_meta(meta)
        logger.warning(
            "ocr_failed session_id=%s filename=%s error=%s elapsed_ms=%s",
            session_id,
            meta.filename,
            meta.error_message,
            meta.elapsed_ms,
        )
        await _send_callback(meta)


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        now = time.time()
        for session_dir in sorted(Path(TEMP_DIR).iterdir()):
            if not session_dir.is_dir():
                continue
            meta_path = session_dir / "meta.json"
            updated_at = meta_path.stat().st_mtime if meta_path.exists() else session_dir.stat().st_mtime
            if now - updated_at > SESSION_TTL_SECONDS:
                shutil.rmtree(session_dir)


def _validate_pdf(file: UploadFile, content: bytes) -> None:
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file. Only PDF files are allowed.")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File size exceeds {MAX_FILE_SIZE // (1024 * 1024)}MB limit.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Invalid file magic. PDF header is required.")


def _is_cancelled(session_id: str) -> bool:
    return session_id in cancelled_sessions


def _drop_queued_session(session_id: str) -> int:
    removed = 0
    retained: list[tuple[int, float, str]] = []
    while True:
        try:
            item = task_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if item[2] == session_id:
            removed += 1
            task_queue.task_done()
            continue
        task_queue.task_done()
        retained.append(item)
    for item in retained:
        task_queue.put_nowait(item)
    return removed


def _remove_session_dir(session_id: str) -> None:
    session_dir = _session_dir(session_id).resolve()
    temp_dir = Path(TEMP_DIR).resolve()
    if temp_dir in session_dir.parents:
        shutil.rmtree(session_dir, ignore_errors=True)


async def _send_callback(meta: SessionMeta) -> None:
    if not meta.callback_url:
        return
    payload = {
        "idempotency_key": f"ocr-callback:{meta.session_id}:{meta.status}",
        "session_id": meta.session_id,
        "filename": meta.filename,
        "status": meta.status,
        "stage": meta.stage,
        "progress": meta.progress,
        "page_count": meta.page_count,
        "uploaded_at": meta.uploaded_at,
        "started_at": meta.started_at,
        "updated_at": meta.updated_at,
        "processed_at": meta.processed_at,
        "elapsed_ms": meta.elapsed_ms,
        "error_code": meta.error_code,
        "error_message": meta.error_message,
    }
    headers = {}
    if OCR_CALLBACK_TOKEN:
        headers["Authorization"] = f"Bearer {OCR_CALLBACK_TOKEN}"
    try:
        await asyncio.to_thread(
            requests.post,
            meta.callback_url,
            json=payload,
            headers=headers,
            timeout=CALLBACK_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning(
            "ocr_callback_failed session_id=%s callback_url=%s",
            meta.session_id,
            meta.callback_url,
        )


def _ensure_completed(session_id: str) -> SessionMeta:
    meta = _read_meta(session_id)
    if meta.status != "completed":
        if meta.status in {"queued", "running"}:
            raise HTTPException(status_code=202, detail="Processing is still in progress.")
        raise HTTPException(status_code=500, detail=meta.error_message or "Processing failed.")
    return meta


def _image_base64_payload(session_id: str, meta: SessionMeta) -> list[dict[str, Any]]:
    images_dir = _output_dir(session_id) / "images"
    if not images_dir.exists():
        return []
    asset_map = {asset.get("name"): asset for asset in meta.assets}
    payload = []
    for file_path in sorted(images_dir.iterdir()):
        if not _is_image(file_path.name):
            continue
        data = base64.b64encode(file_path.read_bytes()).decode("utf-8")
        meta_item = asset_map.get(file_path.name, {})
        payload.append(
            {
                "name": file_path.name,
                "base64": data,
                "mime": _mime_for(file_path.name),
                "mime_type": _mime_for(file_path.name),
                "size": file_path.stat().st_size,
                "page_no": meta_item.get("page_no"),
                "bbox": meta_item.get("bbox"),
            }
        )
    return payload


def _extract_outline(markdown: str) -> list[dict[str, Any]]:
    items = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            items.append({"level": level, "title": stripped.lstrip("#").strip()})
        elif stripped.startswith("第") or _looks_numbered_heading(stripped):
            items.append({"level": 1, "title": stripped})
    return items[:200]


def _looks_numbered_heading(text: str) -> bool:
    parts = text.split(maxsplit=1)
    return bool(parts and parts[0].replace(".", "").isdigit() and "." in parts[0])


def _is_image(name: str) -> bool:
    return name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))


def _mime_for(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=API_HOST, port=API_PORT, workers=1)
