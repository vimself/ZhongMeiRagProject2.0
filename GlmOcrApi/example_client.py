from __future__ import annotations

import argparse
import time
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8899")
    parser.add_argument("--output", type=Path, default=Path("/home/ubuntu/jiang/ocrtest/output"))
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    with args.pdf.open("rb") as file_obj:
        response = requests.post(
            f"{args.base_url.rstrip('/')}/upload",
            files={"file": (args.pdf.name, file_obj, "application/pdf")},
            timeout=120,
        )
    response.raise_for_status()
    session_id = response.json()["session_id"]
    print(f"session_id={session_id}")

    while True:
        status = requests.get(
            f"{args.base_url.rstrip('/')}/status/{session_id}",
            timeout=30,
        ).json()
        print(status.get("status"), status.get("stage"), status.get("progress"))
        if status.get("status") == "completed":
            break
        if status.get("status") == "failed":
            raise RuntimeError(status.get("error_message"))
        time.sleep(5)

    markdown = requests.get(
        f"{args.base_url.rstrip('/')}/result/{session_id}/markdown",
        timeout=120,
    )
    markdown.raise_for_status()
    (args.output / "glm_ocr.md").write_text(markdown.json()["markdown"], encoding="utf-8")

    layout = requests.get(f"{args.base_url.rstrip('/')}/result/{session_id}/json", timeout=120)
    layout.raise_for_status()
    (args.output / "glm_ocr_layout.json").write_text(layout.text, encoding="utf-8")


if __name__ == "__main__":
    main()

