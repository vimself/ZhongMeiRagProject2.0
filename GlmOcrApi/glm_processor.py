from __future__ import annotations

import asyncio
import json
import re
import threading
from pathlib import Path
from typing import Any

import requests

from config import (
    GLM_CONNECT_TIMEOUT_SECONDS,
    GLM_LOG_LEVEL,
    GLM_MAX_TOKENS,
    GLM_MAX_WORKERS,
    GLM_PAGE_QUEUE_SIZE,
    GLM_REGION_QUEUE_SIZE,
    GLM_REQUEST_TIMEOUT_SECONDS,
    GLM_SAVE_LAYOUT_VIS,
    LAYOUT_BATCH_SIZE,
    LAYOUT_DEVICE,
    LAYOUT_MODEL_DIR,
    LAYOUT_USE_POLYGON,
    MODEL_NAME,
    PDF_MAX_PAGES,
    PDF_RENDER_DPI,
    VLLM_BASE_URL,
    VLLM_HOST,
    VLLM_PORT,
)

PAGE_SPLIT = "<--- Page Split --->"


class GlmOCRProcessor:
    """Thin wrapper around the official GLM-OCR self-hosted SDK pipeline."""

    def __init__(self) -> None:
        self._parser: Any | None = None
        self._init_lock = threading.Lock()
        self._gpu_lock = asyncio.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._parser is not None

    def vllm_ready(self, timeout: float = 3.0) -> bool:
        try:
            response = requests.get(f"{VLLM_BASE_URL.rstrip('/')}/v1/models", timeout=timeout)
            if response.status_code != 200:
                return False
            payload = response.json()
            return isinstance(payload, dict) and isinstance(payload.get("data"), list)
        except Exception:
            return False

    def ensure_started(self) -> Any:
        if self._parser is not None:
            return self._parser
        with self._init_lock:
            if self._parser is not None:
                return self._parser

            from glmocr import GlmOcr

            dotted: dict[str, Any] = {
                "pipeline.maas.enabled": False,
                "pipeline.ocr_api.api_host": VLLM_HOST,
                "pipeline.ocr_api.api_port": VLLM_PORT,
                "pipeline.ocr_api.model": MODEL_NAME,
                "pipeline.ocr_api.api_path": "/v1/chat/completions",
                "pipeline.ocr_api.connect_timeout": GLM_CONNECT_TIMEOUT_SECONDS,
                "pipeline.ocr_api.request_timeout": GLM_REQUEST_TIMEOUT_SECONDS,
                "pipeline.ocr_api.connection_pool_size": max(128, GLM_MAX_WORKERS),
                "pipeline.max_workers": GLM_MAX_WORKERS,
                "pipeline.page_maxsize": GLM_PAGE_QUEUE_SIZE,
                "pipeline.region_maxsize": GLM_REGION_QUEUE_SIZE,
                "pipeline.page_loader.pdf_dpi": PDF_RENDER_DPI,
                "pipeline.page_loader.max_tokens": GLM_MAX_TOKENS,
                "pipeline.layout.model_dir": LAYOUT_MODEL_DIR,
                "pipeline.layout.batch_size": LAYOUT_BATCH_SIZE,
                "pipeline.layout.use_polygon": LAYOUT_USE_POLYGON,
            }
            if PDF_MAX_PAGES is not None:
                dotted["pipeline.page_loader.pdf_max_pages"] = PDF_MAX_PAGES
            if LAYOUT_DEVICE:
                dotted["pipeline.layout.device"] = LAYOUT_DEVICE

            self._parser = GlmOcr(
                mode="selfhosted",
                model=MODEL_NAME,
                ocr_api_host=VLLM_HOST,
                ocr_api_port=VLLM_PORT,
                layout_device=LAYOUT_DEVICE or None,
                log_level=GLM_LOG_LEVEL,
                _dotted=dotted,
            )
            return self._parser

    def close(self) -> None:
        parser = self._parser
        self._parser = None
        if parser is not None:
            try:
                parser.close()
            except Exception:
                return

    async def process_pdf_async(
        self,
        pdf_path: str,
        output_dir: str,
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        async with self._gpu_lock:
            return await asyncio.wait_for(
                asyncio.to_thread(self.process_pdf, pdf_path, output_dir),
                timeout=timeout_seconds,
            )

    def process_pdf(self, pdf_path: str, output_dir: str) -> dict[str, Any]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        images_dir = output_path / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        parser = self.ensure_started()
        result = parser.parse(
            pdf_path,
            save_layout_visualization=GLM_SAVE_LAYOUT_VIS,
            preserve_order=True,
        )

        json_result = _coerce_json(getattr(result, "json_result", []))
        raw_json_result = _coerce_json(getattr(result, "raw_json_result", None))
        _rewrite_json_image_paths(json_result)
        markdown = _markdown_from_layout(json_result) or _rewrite_image_links(
            getattr(result, "markdown_result", "") or ""
        )

        image_assets = _save_image_files(
            getattr(result, "image_files", None) or {},
            images_dir,
            json_result,
        )
        layout_vis_count = _save_layout_visualizations(
            getattr(result, "layout_vis_images", None) or {},
            output_path,
        )

        tables, formulas = _extract_structured_regions(json_result)
        (output_path / "result.md").write_text(markdown, encoding="utf-8")
        (output_path / "result.json").write_text(
            json.dumps(json_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if raw_json_result is not None:
            (output_path / "result_raw.json").write_text(
                json.dumps(raw_json_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        metadata = {
            "model": MODEL_NAME,
            "source": str(Path(pdf_path).resolve()),
            "page_count": _page_count(json_result),
            "image_count": len(image_assets),
            "table_count": len(tables),
            "formula_count": len(formulas),
            "layout_visualization_count": layout_vis_count,
        }
        (output_path / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "markdown": markdown,
            "json_result": json_result,
            "raw_json_result": raw_json_result,
            "assets": image_assets,
            "tables": tables,
            "formulas": formulas,
            "page_count": metadata["page_count"],
            "output_dir": str(output_path),
        }


def _coerce_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _rewrite_image_links(markdown: str) -> str:
    return markdown.replace("](imgs/", "](images/")


def _rewrite_json_image_paths(json_result: Any) -> None:
    if not isinstance(json_result, list):
        return
    for page in json_result:
        if not isinstance(page, list):
            continue
        for region in page:
            if not isinstance(region, dict):
                continue
            image_path = region.get("image_path")
            if isinstance(image_path, str):
                region["image_path"] = image_path.replace("imgs/", "images/")


def _markdown_from_layout(json_result: Any) -> str:
    if not isinstance(json_result, list):
        return ""
    page_parts: list[str] = []
    for page in json_result:
        if not isinstance(page, list):
            page_parts.append("")
            continue
        blocks: list[str] = []
        for region in sorted(
            (item for item in page if isinstance(item, dict)),
            key=lambda item: int(item.get("index") or 0),
        ):
            if region.get("label") == "image":
                image_path = region.get("image_path")
                if isinstance(image_path, str) and image_path:
                    blocks.append(f"![Image]({image_path})")
                continue
            content = region.get("content")
            if isinstance(content, str) and content.strip():
                blocks.append(content.strip())
        page_parts.append("\n\n".join(blocks).strip())
    return f"\n{PAGE_SPLIT}\n".join(page_parts).strip()


def _save_image_files(
    image_files: dict[str, Any],
    images_dir: Path,
    json_result: Any,
) -> list[dict[str, Any]]:
    meta_by_name = _image_region_meta(json_result)
    assets: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for raw_name, image in image_files.items():
        name = _dedupe_name(Path(raw_name).name, used_names)
        image.save(images_dir / name, quality=95)
        region_meta = meta_by_name.get(Path(raw_name).name, {})
        assets.append(
            {
                "name": name,
                "page_no": region_meta.get("page_no"),
                "bbox": region_meta.get("bbox"),
                "caption": region_meta.get("caption"),
            }
        )
    return assets


def _image_region_meta(json_result: Any) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    if not isinstance(json_result, list):
        return meta
    for page_idx, page in enumerate(json_result):
        if not isinstance(page, list):
            continue
        for region in page:
            if not isinstance(region, dict) or region.get("label") != "image":
                continue
            image_path = region.get("image_path")
            if not isinstance(image_path, str) or not image_path:
                continue
            name = Path(image_path).name
            meta[name] = {
                "page_no": page_idx + 1,
                "bbox": _bbox_dict(region.get("bbox_2d")),
                "caption": _nearby_caption(page),
            }
    return meta


def _nearby_caption(page: list[Any]) -> str | None:
    for region in page:
        if not isinstance(region, dict):
            continue
        label = str(region.get("native_label") or region.get("label") or "")
        content = str(region.get("content") or "").strip()
        if label in {"figure_title", "chart_title"} and content:
            return content[:500]
    return None


def _save_layout_visualizations(layout_vis_images: dict[int, Any], output_path: Path) -> int:
    if not layout_vis_images:
        return 0
    layout_dir = output_path / "layout_vis"
    layout_dir.mkdir(parents=True, exist_ok=True)
    pdf_images = []
    for page_idx, image in sorted(layout_vis_images.items()):
        rgb = image.convert("RGB") if getattr(image, "mode", "RGB") != "RGB" else image
        rgb.save(layout_dir / f"page_{int(page_idx) + 1}.jpg", quality=90)
        pdf_images.append(rgb)
    if pdf_images:
        first, *rest = pdf_images
        first.save(output_path / "result_layout.pdf", save_all=True, append_images=rest)
    return len(layout_vis_images)


def _extract_structured_regions(json_result: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    formulas: list[dict[str, Any]] = []
    if not isinstance(json_result, list):
        return tables, formulas
    for page_idx, page in enumerate(json_result):
        if not isinstance(page, list):
            continue
        for region in page:
            if not isinstance(region, dict):
                continue
            label = region.get("label")
            item = {
                "page_no": page_idx + 1,
                "index": region.get("index"),
                "bbox": _bbox_dict(region.get("bbox_2d")),
                "content": region.get("content") or "",
            }
            if label == "table":
                tables.append(item)
            elif label == "formula":
                formulas.append(item)
    return tables, formulas


def _bbox_dict(bbox: Any) -> dict[str, float] | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(item) for item in bbox]
    except (TypeError, ValueError):
        return None
    x1, x2 = sorted((max(0.0, min(1000.0, x1)), max(0.0, min(1000.0, x2))))
    y1, y2 = sorted((max(0.0, min(1000.0, y1)), max(0.0, min(1000.0, y2))))
    return {
        "x": x1 / 1000.0,
        "y": y1 / 1000.0,
        "width": max(0.0, x2 - x1) / 1000.0,
        "height": max(0.0, y2 - y1) / 1000.0,
    }


def _page_count(json_result: Any) -> int:
    if isinstance(json_result, list):
        return len(json_result)
    return 0


def _dedupe_name(name: str, used: set[str]) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "image.jpg"
    candidate = safe
    stem = Path(safe).stem or "image"
    suffix = Path(safe).suffix or ".jpg"
    counter = 1
    while candidate in used:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    used.add(candidate)
    return candidate
