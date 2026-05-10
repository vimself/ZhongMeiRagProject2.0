from __future__ import annotations

import httpx
import pytest

from app.services.ocr.client import DeepSeekOCRClient
from app.services.ocr.exceptions import OCRFailed, OCRTimeout


@pytest.mark.asyncio
async def test_upload_success(tmp_path) -> None:
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/upload"
        return httpx.Response(200, json={"session_id": "sid-1"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ocr"
    ) as client:
        ocr = DeepSeekOCRClient(base_url="http://ocr", client=client)
        assert await ocr.upload(pdf_path) == "sid-1"


@pytest.mark.asyncio
async def test_poll_until_done_success() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed", "progress": 100})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ocr"
    ) as client:
        ocr = DeepSeekOCRClient(base_url="http://ocr", client=client)
        result = await ocr.poll_until_done("sid-1", interval_seconds=0.01, timeout_seconds=1)
        assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_poll_until_done_failed() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "failed", "error_message": "boom"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ocr"
    ) as client:
        ocr = DeepSeekOCRClient(base_url="http://ocr", client=client)
        with pytest.raises(OCRFailed):
            await ocr.poll_until_done("sid-1", interval_seconds=0.01, timeout_seconds=1)


@pytest.mark.asyncio
async def test_poll_until_done_timeout() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "running", "progress": 10})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ocr"
    ) as client:
        ocr = DeepSeekOCRClient(base_url="http://ocr", client=client)
        with pytest.raises(OCRTimeout):
            await ocr.poll_until_done("sid-1", interval_seconds=0.01, timeout_seconds=0.02)


@pytest.mark.asyncio
async def test_fetch_images_fallback_to_legacy_endpoint() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/assets"):
            return httpx.Response(404, json={"detail": "missing"})
        return httpx.Response(200, json={"images": [{"name": "a.jpg", "base64": "AA=="}]})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ocr"
    ) as client:
        ocr = DeepSeekOCRClient(base_url="http://ocr", client=client)
        result = await ocr.fetch_images_b64("sid-1")
        assert result["images"][0]["name"] == "a.jpg"
        assert calls == ["/result/sid-1/assets", "/result/sid-1/images/base64"]


@pytest.mark.asyncio
async def test_delete_session_404_is_idempotent() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "missing"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ocr"
    ) as client:
        ocr = DeepSeekOCRClient(base_url="http://ocr", client=client)
        assert await ocr.delete_session("sid-1") is False
