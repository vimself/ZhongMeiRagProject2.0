from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.services.ocr.exceptions import OCRFailed, OCRTimeout, OCRTransient

TRANSIENT_FAILURE_MARKERS = (
    "healthwatchdog",
    "service at",
    "no longer available",
    "connection refused",
    "failed to establish a new connection",
    "max retries exceeded",
    "internal server error",
    "enginecore encountered",
    "enginedeaderror",
    "cuda error",
    "device-side assert",
)


class GlmOCRClient:
    """GLM-OCR 自托管解析服务客户端。

    服务端保持既有上传、轮询、下载 HTTP 协议，便于入库链路无缝替换。
    """

    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ocr_base_url).rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0),
        )

    async def __aenter__(self) -> GlmOCRClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def healthz(self) -> dict[str, Any]:
        response = await self._client.get("/healthz")
        response.raise_for_status()
        return dict(response.json())

    async def queue(self) -> dict[str, Any]:
        response = await self._client.get("/queue")
        response.raise_for_status()
        return dict(response.json())

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type((OCRTransient, httpx.HTTPError)),
        reraise=True,
    )
    async def upload(
        self,
        pdf_path: str | Path,
        *,
        priority: int = 5,
        callback_url: str | None = None,
    ) -> str:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        data: dict[str, str] = {"priority": str(priority)}
        if callback_url:
            data["callback_url"] = callback_url
        with path.open("rb") as file_obj:
            files = {"file": (path.name, file_obj, "application/pdf")}
            response = await self._client.post("/upload", data=data, files=files)
        self._raise_for_ocr_error(response)
        body = response.json()
        session_id = body.get("session_id") or body.get("sid")
        if not isinstance(session_id, str) or not session_id:
            raise OCRTransient("OCR 上传响应缺少 session_id")
        return session_id

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type((OCRTransient, httpx.HTTPError)),
        reraise=True,
    )
    async def get_status(self, session_id: str) -> dict[str, Any]:
        response = await self._client.get(f"/status/{session_id}")
        self._raise_for_ocr_error(response)
        return dict(response.json())

    async def poll_until_done(
        self,
        session_id: str,
        *,
        interval_seconds: float | None = None,
        timeout_seconds: float | None = None,
        cancel_checker: Callable[[], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        interval = interval_seconds or settings.ocr_poll_interval_seconds
        timeout = timeout_seconds or settings.ocr_max_poll_minutes * 60
        start = asyncio.get_running_loop().time()
        while True:
            if cancel_checker is not None:
                await cancel_checker()
            status_payload = await self.get_status(session_id)
            status_text = self._status_text(status_payload)
            if status_text in {"completed", "done", "succeeded", "ready"}:
                return status_payload
            if status_text.startswith("failed") or status_text in {"dead", "error"}:
                message = status_payload.get("error_message") or status_payload.get("detail")
                if self._is_transient_failure_message(message):
                    raise OCRTransient(str(message or status_text))
                raise OCRFailed(str(message or status_text))
            if asyncio.get_running_loop().time() - start >= timeout:
                raise OCRTimeout(f"OCR 会话 {session_id} 超过 {int(timeout)} 秒仍未完成")
            await self._sleep_with_cancel_check(interval, cancel_checker)

    async def fetch_markdown(
        self,
        session_id: str,
        *,
        include_meta: bool = False,
    ) -> dict[str, Any]:
        params = {"include_meta": "true"} if include_meta else None
        response = await self._client.get(f"/result/{session_id}/markdown", params=params)
        self._raise_for_ocr_error(response)
        body = response.json()
        if isinstance(body, dict) and "markdown" in body:
            return body
        raise OCRTransient("OCR markdown 响应格式不正确")

    async def fetch_images_b64(self, session_id: str) -> dict[str, Any]:
        response = await self._client.get(f"/result/{session_id}/assets")
        if response.status_code == 404:
            response = await self._client.get(f"/result/{session_id}/images/base64")
        self._raise_for_ocr_error(response)
        body = response.json()
        if "images" in body:
            return dict(body)
        return {"session_id": session_id, "images": []}

    async def fetch_layout(self, session_id: str) -> dict[str, Any]:
        response = await self._client.get(f"/result/{session_id}/json")
        if response.status_code == 404:
            return {"session_id": session_id, "layout": []}
        self._raise_for_ocr_error(response)
        body = response.json()
        if isinstance(body, dict):
            return body
        return {"session_id": session_id, "layout": []}

    async def delete_session(self, session_id: str) -> bool:
        response = await self._client.delete(f"/session/{session_id}")
        if response.status_code == 404:
            return False
        self._raise_for_ocr_error(response)
        return True

    def _raise_for_ocr_error(self, response: httpx.Response) -> None:
        if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
            raise OCRTransient(response.text)
        if response.status_code == 202:
            raise OCRTransient("OCR 结果尚未就绪")
        response.raise_for_status()

    def _status_text(self, payload: dict[str, Any]) -> str:
        status = payload.get("status")
        if isinstance(status, str):
            return status.lower()
        if payload.get("is_completed") is True:
            return "completed"
        if payload.get("is_failed") is True:
            return "failed"
        return "processing"

    def _is_transient_failure_message(self, message: Any) -> bool:
        if not isinstance(message, str):
            return False
        normalized = message.casefold()
        return any(marker in normalized for marker in TRANSIENT_FAILURE_MARKERS)

    async def _sleep_with_cancel_check(
        self,
        interval: float,
        cancel_checker: Callable[[], Awaitable[None]] | None,
    ) -> None:
        if cancel_checker is None:
            await asyncio.sleep(interval)
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + interval
        while True:
            await cancel_checker()
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(1.0, remaining))
