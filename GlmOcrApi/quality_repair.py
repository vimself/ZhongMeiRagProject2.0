from __future__ import annotations

import base64
import io
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import requests
from PIL import Image

from config import (
    GLM_REQUEST_TIMEOUT_SECONDS,
    GLM_TEXT_LINE_REPAIR_DARK_THRESHOLD,
    GLM_TEXT_LINE_REPAIR_ENABLED,
    GLM_TEXT_LINE_REPAIR_LINE_GAP,
    GLM_TEXT_LINE_REPAIR_MAX_LINES,
    GLM_TEXT_LINE_REPAIR_MAX_REGIONS_PER_PAGE,
    GLM_TEXT_LINE_REPAIR_MAX_TOKENS,
    GLM_TEXT_LINE_REPAIR_MIN_DARK_RATIO,
    GLM_TEXT_LINE_REPAIR_MIN_LINES,
    GLM_TEXT_LINE_REPAIR_PAD_X,
    GLM_TEXT_LINE_REPAIR_PAD_Y,
    GLM_TEXT_LINE_REPAIR_POLICY,
    GLM_TEXT_LINE_REPAIR_REPETITION_PENALTY,
    GLM_TOP_K,
    GLM_TOP_P,
    GLM_TEMPERATURE,
    MODEL_NAME,
    PDF_RENDER_DPI,
    VLLM_BASE_URL,
)

logger = logging.getLogger("glm_ocr_api.quality_repair")


@dataclass(frozen=True)
class QualityRepairSettings:
    enabled: bool = GLM_TEXT_LINE_REPAIR_ENABLED
    policy: str = GLM_TEXT_LINE_REPAIR_POLICY
    min_lines: int = GLM_TEXT_LINE_REPAIR_MIN_LINES
    max_lines: int = GLM_TEXT_LINE_REPAIR_MAX_LINES
    max_regions_per_page: int = GLM_TEXT_LINE_REPAIR_MAX_REGIONS_PER_PAGE
    dark_threshold: int = GLM_TEXT_LINE_REPAIR_DARK_THRESHOLD
    min_dark_ratio: float = GLM_TEXT_LINE_REPAIR_MIN_DARK_RATIO
    line_gap: int = GLM_TEXT_LINE_REPAIR_LINE_GAP
    pad_x: int = GLM_TEXT_LINE_REPAIR_PAD_X
    pad_y: int = GLM_TEXT_LINE_REPAIR_PAD_Y
    line_max_tokens: int = GLM_TEXT_LINE_REPAIR_MAX_TOKENS
    repetition_penalty: float = GLM_TEXT_LINE_REPAIR_REPETITION_PENALTY
    request_timeout_seconds: int = GLM_REQUEST_TIMEOUT_SECONDS
    pdf_dpi: int = PDF_RENDER_DPI
    max_width_or_height: int = 3500


class TextLineRepairer:
    """Repair low-confidence multiline text regions by recognizing each line.

    GLM-OCR is much more stable on short line crops than on watermark-heavy
    multiline paragraph crops. The official pipeline remains the primary pass;
    this repair step only rewrites text-like regions that are likely to contain
    generation loops or wrapped engineering clauses.
    """

    def __init__(
        self,
        *,
        settings: QualityRepairSettings | None = None,
        base_url: str = VLLM_BASE_URL,
        model_name: str = MODEL_NAME,
    ) -> None:
        self.settings = settings or QualityRepairSettings()
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def repair_pdf_result(
        self,
        pdf_path: str | Path,
        json_result: Any,
        raw_json_result: Any = None,
    ) -> dict[str, Any]:
        report: dict[str, Any] = {
            "enabled": self.settings.enabled,
            "policy": self.settings.policy,
            "repairs": [],
            "skipped": [],
        }
        if not self.settings.enabled:
            return report
        if self.settings.policy in {"off", "false", "0", "disabled"}:
            report["enabled"] = False
            return report
        if not isinstance(json_result, list):
            report["skipped"].append({"reason": "json_result_not_list"})
            return report

        raw_lookup = _build_raw_lookup(raw_json_result)
        rendered_pages: dict[int, Image.Image] = {}
        pdf_doc = fitz.open(str(pdf_path))
        try:
            for page_idx, page_regions in enumerate(json_result):
                if not isinstance(page_regions, list):
                    continue
                page_repairs = 0
                for region_idx, region in enumerate(page_regions):
                    if page_repairs >= self.settings.max_regions_per_page:
                        report["skipped"].append(
                            {
                                "page_no": page_idx + 1,
                                "reason": "page_repair_limit_reached",
                            }
                        )
                        break
                    if not _is_repairable_text_region(region):
                        continue
                    bbox = _coerce_bbox(region.get("bbox_2d"))
                    if bbox is None:
                        continue

                    page_image = rendered_pages.get(page_idx)
                    if page_image is None:
                        if page_idx >= pdf_doc.page_count:
                            report["skipped"].append(
                                {"page_no": page_idx + 1, "reason": "page_missing"}
                            )
                            continue
                        page_image = _render_page(
                            pdf_doc.load_page(page_idx),
                            dpi=self.settings.pdf_dpi,
                            max_width_or_height=self.settings.max_width_or_height,
                        )
                        rendered_pages[page_idx] = page_image

                    crop = _crop_bbox(page_image, bbox)
                    line_boxes = self._segment_lines(crop)
                    raw_content = _raw_content_for_region(
                        raw_lookup,
                        page_idx,
                        region_idx,
                        region,
                    )
                    reason = self._repair_reason(region, raw_content, line_boxes)
                    if reason is None:
                        continue

                    old_content = str(region.get("content") or "")
                    preserve_line_breaks = _should_preserve_line_breaks(region, line_boxes)
                    new_content = self._recognize_lines(
                        crop,
                        line_boxes,
                        preserve_line_breaks=preserve_line_breaks,
                    )
                    if not self._should_accept_repair(old_content, new_content):
                        report["skipped"].append(
                            {
                                "page_no": page_idx + 1,
                                "index": region.get("index"),
                                "reason": "repair_output_rejected",
                                "old_length": len(old_content),
                                "new_length": len(new_content or ""),
                            }
                        )
                        continue

                    region["content"] = new_content
                    page_repairs += 1
                    report["repairs"].append(
                        {
                            "page_no": page_idx + 1,
                            "index": region.get("index"),
                            "native_label": region.get("native_label"),
                            "bbox_2d": bbox,
                            "line_count": len(line_boxes),
                            "reason": reason,
                            "preserve_line_breaks": preserve_line_breaks,
                            "old_length": len(old_content),
                            "new_length": len(new_content),
                        }
                    )
        finally:
            pdf_doc.close()

        report["repair_count"] = len(report["repairs"])
        report["skipped_count"] = len(report["skipped"])
        return report

    def _segment_lines(self, crop: Image.Image) -> list[tuple[int, int, int, int]]:
        if crop.width < 16 or crop.height < 10:
            return []
        gray = np.array(crop.convert("L"))
        mask = gray < int(self.settings.dark_threshold)
        row_threshold = max(2, int(mask.shape[1] * self.settings.min_dark_ratio))
        active_rows = np.where(mask.sum(axis=1) >= row_threshold)[0]
        if active_rows.size == 0:
            return []

        groups: list[list[int]] = []
        start = prev = int(active_rows[0])
        for row in active_rows[1:]:
            row = int(row)
            if row - prev > self.settings.line_gap:
                if prev - start >= 3:
                    groups.append([start, prev])
                start = row
            prev = row
        if prev - start >= 3:
            groups.append([start, prev])

        line_boxes: list[tuple[int, int, int, int]] = []
        for y1, y2 in groups:
            y1 = max(0, y1 - self.settings.pad_y)
            y2 = min(crop.height, y2 + self.settings.pad_y + 1)
            if y2 - y1 < 10:
                continue
            line_mask = mask[y1:y2, :]
            active_cols = np.where(line_mask.sum(axis=0) > 0)[0]
            if active_cols.size == 0:
                x1, x2 = 0, crop.width
            else:
                x1 = max(0, int(active_cols[0]) - self.settings.pad_x)
                x2 = min(crop.width, int(active_cols[-1]) + self.settings.pad_x + 1)
            if x2 - x1 >= 12:
                line_boxes.append((x1, y1, x2, y2))
        return line_boxes

    def _repair_reason(
        self,
        region: dict[str, Any],
        raw_content: str,
        line_boxes: list[tuple[int, int, int, int]],
    ) -> str | None:
        line_count = len(line_boxes)
        if line_count < self.settings.min_lines:
            return None

        content = str(region.get("content") or "")
        suspicion = _suspicion_reason(content, raw_content, line_count)
        if line_count > self.settings.max_lines and suspicion is None:
            return None
        if suspicion is not None:
            return suspicion

        if self.settings.policy == "always":
            return "policy_always"

        if _starts_with_numbered_clause(content) and line_count >= 2:
            return "numbered_multiline_clause"
        if line_count >= 5 and _contains_cjk_sentence_punctuation(content):
            return "long_multiline_text"
        return None

    def _recognize_lines(
        self,
        crop: Image.Image,
        line_boxes: list[tuple[int, int, int, int]],
        *,
        preserve_line_breaks: bool = False,
    ) -> str:
        lines: list[str] = []
        for box in line_boxes:
            line_image = _prepare_line_image(crop.crop(box))
            text = self._recognize_image(line_image)
            text = _clean_line_text(text)
            if not text:
                continue
            if lines and _normalize_for_compare(lines[-1]) == _normalize_for_compare(text):
                continue
            lines.append(text)
        return _join_lines(lines, preserve_line_breaks=preserve_line_breaks)

    def _recognize_image(self, image: Image.Image) -> str:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            },
                        },
                        {"type": "text", "text": "Text Recognition:"},
                    ],
                }
            ],
            "max_tokens": self.settings.line_max_tokens,
            "temperature": GLM_TEMPERATURE,
            "top_p": GLM_TOP_P,
            "top_k": GLM_TOP_K,
            "repetition_penalty": self.settings.repetition_penalty,
        }
        response = self._session.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        if response.status_code != 200:
            logger.warning(
                "line_repair_ocr_failed status=%s response=%s",
                response.status_code,
                response.text[:300],
            )
            return ""
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            logger.warning("line_repair_bad_response response=%s", str(data)[:300])
            return ""

    @staticmethod
    def _should_accept_repair(old_content: str, new_content: str) -> bool:
        new_content = new_content.strip()
        if len(new_content) < 4:
            return False
        if _repair_output_invalid(new_content):
            return False
        old_norm = _normalize_for_compare(old_content)
        new_norm = _normalize_for_compare(new_content)
        if old_norm and len(new_norm) < max(8, int(len(old_norm) * 0.25)):
            return False
        return True


def _render_page(page: fitz.Page, *, dpi: int, max_width_or_height: int) -> Image.Image:
    scale = dpi / 72.0
    long_side_pt = max(page.rect.width, page.rect.height)
    if long_side_pt * scale > max_width_or_height:
        scale = max_width_or_height / long_side_pt
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _crop_bbox(image: Image.Image, bbox: list[int]) -> Image.Image:
    width, height = image.size
    x1, y1, x2, y2 = bbox
    left = max(0, min(width, int(x1 * width / 1000)))
    top = max(0, min(height, int(y1 * height / 1000)))
    right = max(0, min(width, int(x2 * width / 1000)))
    bottom = max(0, min(height, int(y2 * height / 1000)))
    if right <= left:
        right = min(width, left + 1)
    if bottom <= top:
        bottom = min(height, top + 1)
    return image.crop((left, top, right, bottom))


def _prepare_line_image(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    if image.height >= 64:
        return image
    scale = 64 / max(1, image.height)
    width = max(1, int(image.width * scale))
    return image.resize((width, 64), Image.Resampling.BICUBIC)


def _is_repairable_text_region(region: Any) -> bool:
    if not isinstance(region, dict):
        return False
    if region.get("label") != "text":
        return False
    native_label = str(region.get("native_label") or "")
    if native_label in {
        "doc_title",
        "paragraph_title",
        "figure_title",
        "formula_number",
        "seal",
        "vertical_text",
    }:
        return False
    return isinstance(region.get("content"), str)


def _should_preserve_line_breaks(
    region: dict[str, Any],
    line_boxes: list[tuple[int, int, int, int]],
) -> bool:
    native_label = str(region.get("native_label") or "")
    if native_label == "content" and len(line_boxes) >= 10:
        return True
    content = str(region.get("content") or "")
    return len(line_boxes) >= 10 and "..." in content


def _coerce_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(item))) for item in value]
    except (TypeError, ValueError):
        return None
    x1, x2 = sorted((max(0, min(1000, x1)), max(0, min(1000, x2))))
    y1, y2 = sorted((max(0, min(1000, y1)), max(0, min(1000, y2))))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _build_raw_lookup(raw_json_result: Any) -> dict[int, list[dict[str, Any]]]:
    lookup: dict[int, list[dict[str, Any]]] = {}
    if not isinstance(raw_json_result, list):
        return lookup
    for page_idx, page in enumerate(raw_json_result):
        if isinstance(page, list):
            lookup[page_idx] = [item for item in page if isinstance(item, dict)]
    return lookup


def _raw_content_for_region(
    raw_lookup: dict[int, list[dict[str, Any]]],
    page_idx: int,
    region_idx: int,
    region: dict[str, Any],
) -> str:
    raw_page = raw_lookup.get(page_idx) or []
    raw_region = None
    region_index = region.get("index")
    for item in raw_page:
        if item.get("index") == region_index:
            raw_region = item
            break
    if raw_region is None and 0 <= region_idx < len(raw_page):
        raw_region = raw_page[region_idx]
    if raw_region is None:
        return ""
    return str(raw_region.get("content") or "")


def _suspicion_reason(content: str, raw_content: str, line_count: int) -> str | None:
    source = raw_content or content
    if len(raw_content) >= max(1200, line_count * 180):
        return "raw_runaway_generation"
    if len(content) >= max(900, line_count * 180):
        return "runaway_generation"
    if content.count("$") % 2 == 1:
        return "unbalanced_formula_marker"
    if _repeated_formula_token(content):
        return "repeated_formula_token"
    if _has_repeated_ngrams(source):
        return "repeated_text_loop"
    if _has_repeated_ngrams(content):
        return "repeated_text_loop"
    return None


def _repair_output_invalid(text: str) -> bool:
    if len(text) >= 1200:
        return True
    if text.count("$") % 2 == 1:
        return True
    normalized = _normalize_for_compare(text)
    if len(normalized) >= 400 and _has_repeated_ngrams(text, n=10):
        return True
    return False


def _has_repeated_ngrams(text: str, *, n: int = 8) -> bool:
    normalized = _normalize_for_compare(text)
    if len(normalized) < 100:
        return False
    grams = [normalized[i : i + n] for i in range(0, len(normalized) - n + 1)]
    if not grams:
        return False
    common, count = Counter(grams).most_common(1)[0]
    if count >= 6:
        return True
    return count >= 4 and (count * len(common) / max(1, len(normalized))) >= 0.08


def _repeated_formula_token(text: str) -> bool:
    tokens = re.findall(r"(?:\\%|%|\\sim|95|97)", text)
    if len(tokens) >= 10:
        return True
    return text.count("95\\%") + text.count("95%") >= 4


def _starts_with_numbered_clause(text: str) -> bool:
    stripped = re.sub(r"^#+\s*", "", text.strip())
    return bool(
        re.match(r"^\d{1,2}\s+[\u4e00-\u9fff]", stripped)
        or re.match(r"^\d+(?:\.\d+){1,3}\s*[\u4e00-\u9fff]", stripped)
    )


def _contains_cjk_sentence_punctuation(text: str) -> bool:
    return any(char in text for char in "，。；：（）")


def _clean_line_text(text: str) -> str:
    text = text.replace("\r", "\n").strip()
    text = re.sub(r"^(?:Text Recognition:|文本识别[:：])\s*", "", text, flags=re.I)
    text = re.sub(r"\s*\n+\s*", "", text)
    text = re.sub(r"[ \t\u3000]+", " ", text).strip()
    return text


def _join_lines(lines: list[str], *, preserve_line_breaks: bool = False) -> str:
    if preserve_line_breaks:
        return "\n".join(_postprocess_joined_text(line.strip()) for line in lines if line.strip())

    result = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not result:
            result = line
            continue
        if _needs_space_between(result[-1], line[0]):
            result += " " + line
        else:
            result += line
    return _postprocess_joined_text(result.strip())


def _postprocess_joined_text(text: str) -> str:
    text = re.sub(r"(?<!\d)(\d+)\.\s+((?:\d+\.)*\d+)", r"\1.\2", text)
    replacements = {
        "根据水位应根据水位库": "根据水库",
        "根据水位应根据水库": "根据水库",
        "水位库调蓄": "水库调蓄",
        "进水时，池": "进水池",
        "进水时池": "进水池",
        "出水时，池": "出水池",
        "出水时池": "出水池",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _needs_space_between(left: str, right: str) -> bool:
    return left.isascii() and right.isascii() and left.isalnum() and right.isalnum()


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))
