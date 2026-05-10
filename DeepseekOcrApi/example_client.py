from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests


class DeepSeekOCRClient:
    def __init__(self, base_url: str = "http://localhost:8899", api_token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or os.getenv("API_TOKEN", "")

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_token:
            return {}
        return {"Authorization": f"Bearer {self.api_token}"}

    def upload_pdf(self, pdf_path: str, *, priority: int = 5) -> str:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        with path.open("rb") as file_obj:
            response = requests.post(
                f"{self.base_url}/upload",
                headers=self.headers,
                files={"file": (path.name, file_obj, "application/pdf")},
                data={"priority": str(priority)},
                timeout=120,
            )
        response.raise_for_status()
        session_id = response.json()["session_id"]
        print(f"PDF 已上传，Session ID: {session_id}")
        return str(session_id)

    def get_status(self, session_id: str) -> dict[str, Any]:
        response = requests.get(f"{self.base_url}/status/{session_id}", timeout=30)
        response.raise_for_status()
        return dict(response.json())

    def wait_for_completion(self, session_id: str, check_interval: int = 5, timeout: int = 3600) -> bool:
        started_at = time.time()
        while True:
            status_data = self.get_status(session_id)
            print(
                f"状态: {status_data.get('status')}，阶段: {status_data.get('stage')}，"
                f"进度: {status_data.get('progress')}%"
            )
            if status_data.get("status") == "completed":
                return True
            if status_data.get("status") == "failed":
                print(status_data.get("error_message"))
                return False
            if time.time() - started_at > timeout:
                return False
            time.sleep(check_interval)

    def get_markdown(self, session_id: str, include_meta: bool = False) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/result/{session_id}/markdown",
            params={"include_meta": "true"} if include_meta else None,
            timeout=60,
        )
        response.raise_for_status()
        return dict(response.json())

    def get_assets(self, session_id: str) -> dict[str, Any]:
        response = requests.get(f"{self.base_url}/result/{session_id}/assets", timeout=120)
        response.raise_for_status()
        return dict(response.json())

    def delete_session(self, session_id: str) -> bool:
        response = requests.delete(
            f"{self.base_url}/session/{session_id}",
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        return True

    def process_pdf(self, pdf_path: str) -> dict[str, Any]:
        session_id = self.upload_pdf(pdf_path)
        if not self.wait_for_completion(session_id):
            raise RuntimeError("OCR 处理失败或超时")
        return {
            "session_id": session_id,
            "markdown": self.get_markdown(session_id, include_meta=True),
            "assets": self.get_assets(session_id),
        }


if __name__ == "__main__":
    client = DeepSeekOCRClient("http://localhost:8899")
    result = client.process_pdf("test.pdf")
    markdown = result["markdown"]["markdown"]
    print(markdown[:500] + "..." if len(markdown) > 500 else markdown)
