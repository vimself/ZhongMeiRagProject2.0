from __future__ import annotations

import argparse
import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import requests


DEFAULT_BASE_URL = os.getenv("OCR_API_URL", "http://127.0.0.1:8899")
DEFAULT_PDF_PATH = Path(
    "/home/ubuntu/jiang/ragproject/deepseek-ocr/DeepSeek-code2/DeepseekOcrApi/test/source/original.pdf"
)
DEFAULT_OUTPUT_DIR = Path(
    "/home/ubuntu/jiang/ragproject/deepseek-ocr/DeepSeek-code2/DeepseekOcrApi/test/out"
)


class DeepSeekOCRRequest:
    def __init__(self, base_url: str, api_token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_token:
            return {}
        return {"Authorization": f"Bearer {self.api_token}"}

    def upload(self, pdf_path: Path, priority: int) -> str:
        with pdf_path.open("rb") as file_obj:
            response = requests.post(
                f"{self.base_url}/upload",
                headers=self.headers,
                files={"file": (pdf_path.name, file_obj, "application/pdf")},
                data={"priority": str(priority)},
                timeout=120,
            )
        response.raise_for_status()
        payload = response.json()
        return str(payload["session_id"])

    def status(self, session_id: str) -> dict[str, Any]:
        response = requests.get(f"{self.base_url}/status/{session_id}", timeout=30)
        response.raise_for_status()
        return dict(response.json())

    def wait(self, session_id: str, interval: float, timeout: float) -> dict[str, Any]:
        started_at = time.monotonic()
        while True:
            payload = self.status(session_id)
            status = payload.get("status")
            stage = payload.get("stage")
            progress = payload.get("progress")
            print(f"status={status} stage={stage} progress={progress}%")

            if status == "completed":
                return payload
            if status == "failed":
                raise RuntimeError(payload.get("error_message") or "OCR task failed")
            if time.monotonic() - started_at > timeout:
                raise TimeoutError(f"OCR task timed out after {timeout:.0f}s: {session_id}")

            time.sleep(interval)

    def markdown(self, session_id: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/result/{session_id}/markdown",
            params={"include_meta": "true"},
            timeout=120,
        )
        response.raise_for_status()
        return dict(response.json())

    def assets(self, session_id: str) -> dict[str, Any]:
        response = requests.get(f"{self.base_url}/result/{session_id}/assets", timeout=120)
        response.raise_for_status()
        return dict(response.json())


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_outputs(output_dir: Path, status: dict[str, Any], markdown: dict[str, Any], assets: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "ocr.md").write_text(str(markdown.get("markdown", "")), encoding="utf-8")
    write_json(output_dir / "metadata.json", {"status": status, "markdown_meta": markdown})
    write_json(output_dir / "assets.json", assets)

    image_items = assets.get("images") or []
    for item in image_items:
        name = Path(str(item["name"])).name
        image_data = base64.b64decode(str(item["base64"]))
        (assets_dir / name).write_bytes(image_data)

    print(f"saved markdown: {output_dir / 'ocr.md'}")
    print(f"saved metadata: {output_dir / 'metadata.json'}")
    print(f"saved assets json: {output_dir / 'assets.json'}")
    print(f"saved images: {assets_dir} ({len(image_items)} files)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit a PDF to DeepSeek-OCR API and save OCR outputs.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="DeepSeek-OCR API base URL.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF_PATH, help="PDF path to OCR.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory.")
    parser.add_argument("--priority", type=int, default=5, help="OCR queue priority.")
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds.")
    parser.add_argument("--timeout", type=float, default=3600.0, help="Polling timeout in seconds.")
    parser.add_argument("--api-token", default=os.getenv("API_TOKEN", ""), help="Bearer token for protected upload.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = args.pdf.expanduser().resolve()
    output_dir = args.out.expanduser().resolve()

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    client = DeepSeekOCRRequest(args.base_url, args.api_token)
    session_id = client.upload(pdf_path, args.priority)
    print(f"session_id={session_id}")

    final_status = client.wait(session_id, args.interval, args.timeout)
    markdown = client.markdown(session_id)
    assets = client.assets(session_id)
    save_outputs(output_dir, final_status, markdown, assets)


if __name__ == "__main__":
    main()
