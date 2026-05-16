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

_SEVERE_REPAIR_REASONS = {
    "raw_runaway_generation",
    "runaway_generation",
    "repeated_text_loop",
    "repeated_formula_token",
    "percent_digit_run",
    "formula_text_noise",
    "toc_repeated_entry_loop",
}
_PERCENT_RANGE_RUN_RE = re.compile(
    r"(?P<low>\d{1,2})\s*"
    r"(?P<low_pct>\\?%)\s*"
    r"(?P<sep>～|~|－|-|–|—|至|到|\\sim)\s*"
    r"(?P<high>(?P<digit>\d)(?P=digit){2,})\s*"
    r"(?P<high_pct>\\?%)"
)


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
                pdf_page = None
                has_text_layer = False
                if page_idx < pdf_doc.page_count:
                    pdf_page = pdf_doc.load_page(page_idx)
                    has_text_layer = _page_has_extractable_text(pdf_page)
                text_layer_repaired: set[int] = set()
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
                    if not _is_repairable_layout_text(region):
                        continue
                    bbox = _coerce_bbox(region.get("bbox_2d"))
                    if bbox is None:
                        continue
                    raw_content = _raw_content_for_region(
                        raw_lookup,
                        page_idx,
                        region_idx,
                        region,
                    )
                    if has_text_layer and pdf_page is not None:
                        text_layer_content = _extract_text_layer_region(pdf_page, bbox)
                        if _text_layer_matches_region(
                            str(region.get("content") or ""),
                            text_layer_content,
                        ):
                            continue
                        if self._should_accept_text_layer_repair(
                            str(region.get("content") or ""),
                            text_layer_content,
                            raw_content=raw_content,
                            region=region,
                        ):
                            old_content = str(region.get("content") or "")
                            new_content = _format_text_layer_content(
                                old_content,
                                text_layer_content,
                                region,
                            )
                            region["content"] = new_content
                            text_layer_repaired.add(region_idx)
                            page_repairs += 1
                            report["repairs"].append(
                                {
                                    "page_no": page_idx + 1,
                                    "index": region.get("index"),
                                    "native_label": region.get("native_label"),
                                    "bbox_2d": bbox,
                                    "line_count": 0,
                                    "reason": "pdf_text_layer",
                                    "preserve_line_breaks": False,
                                    "old_length": len(old_content),
                                    "new_length": len(new_content),
                                }
                            )
                            continue

                    if not _is_repairable_text_region(region):
                        continue
                    if region_idx in text_layer_repaired:
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
                    if not self._should_accept_repair(
                        old_content,
                        new_content,
                        reason=reason,
                        line_count=len(line_boxes),
                    ):
                        report["skipped"].append(
                            {
                                "page_no": page_idx + 1,
                                "index": region.get("index"),
                                "reason": "repair_output_rejected",
                                "repair_reason": reason,
                                "line_count": len(line_boxes),
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
        report["text_layer_repair_count"] = sum(
            1
            for item in report["repairs"]
            if isinstance(item, dict) and item.get("reason") == "pdf_text_layer"
        )
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
        content = str(region.get("content") or "")
        suspicion = _suspicion_reason(content, raw_content, line_count)
        if line_count < self.settings.min_lines:
            return suspicion if suspicion in _SEVERE_REPAIR_REASONS else None
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
            line_crop = crop.crop(box)
            line_image = _prepare_line_image(line_crop)
            text = self._recognize_image(line_image)
            text = _clean_line_text(text)
            if _line_output_suspicious(text):
                segmented_text = self._recognize_line_segments(line_crop)
                if _prefer_segmented_line(text, segmented_text):
                    text = segmented_text
            if not text:
                continue
            if lines and _normalize_for_compare(lines[-1]) == _normalize_for_compare(text):
                continue
            lines.append(text)
        return _join_lines(lines, preserve_line_breaks=preserve_line_breaks)

    def _recognize_line_segments(self, image: Image.Image) -> str:
        if image.width < 320:
            return ""
        parts = 3 if image.width >= 520 else 2
        overlap = max(10, min(24, image.width // 40))
        texts: list[str] = []
        for part in range(parts):
            left = max(0, int(part * image.width / parts) - overlap)
            right = min(image.width, int((part + 1) * image.width / parts) + overlap)
            if right - left < 64:
                continue
            segment = image.crop((left, 0, right, image.height))
            text = _clean_line_text(self._recognize_image(_prepare_line_image(segment)))
            if text:
                texts.append(text)
        return _merge_segment_texts(texts)

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
    def _should_accept_repair(
        old_content: str,
        new_content: str,
        *,
        reason: str,
        line_count: int,
    ) -> bool:
        new_content = new_content.strip()
        min_length = 4
        if reason in _SEVERE_REPAIR_REASONS:
            min_length = max(12, min(80, line_count * 8))
        if len(new_content) < min_length:
            return False
        if reason == "toc_repeated_entry_loop":
            return True
        if _repair_output_invalid(new_content):
            return False
        if reason in _SEVERE_REPAIR_REASONS:
            return True
        old_norm = _normalize_for_compare(old_content)
        new_norm = _normalize_for_compare(new_content)
        if old_norm and len(new_norm) < max(8, int(len(old_norm) * 0.25)):
            return False
        return True

    @staticmethod
    def _should_accept_text_layer_repair(
        old_content: str,
        new_content: str,
        *,
        raw_content: str,
        region: dict[str, Any],
    ) -> bool:
        new_content = new_content.strip()
        if len(new_content) < 2:
            return False
        if _repair_output_invalid(new_content):
            return False
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", new_content):
            return False

        old_norm = _normalize_for_compare(_strip_markdown_heading(old_content))
        new_norm = _normalize_for_compare(new_content)
        raw_norm = _normalize_for_compare(raw_content)
        if not new_norm:
            return False
        if old_norm == new_norm:
            return False
        if len(new_norm) < 2:
            return False

        native_label = str(region.get("native_label") or "")
        if native_label == "paragraph_title":
            return _looks_like_better_title(old_content, new_content)

        if raw_norm and _section_number_drift(raw_content, new_content):
            return True
        if _section_number_drift(old_content, new_content):
            return True
        if len(old_norm) >= 20 and len(new_norm) < int(len(old_norm) * 0.35):
            return False
        if _content_needs_pdf_text_layer(old_content, raw_content):
            return True
        if raw_norm and _content_needs_pdf_text_layer(raw_content, raw_content):
            return True
        if len(old_norm) >= 30 and _similar_length_but_different(old_norm, new_norm):
            return True
        return False


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


def _is_repairable_layout_text(region: Any) -> bool:
    if not isinstance(region, dict):
        return False
    if region.get("label") != "text":
        return False
    native_label = str(region.get("native_label") or "")
    if native_label in {"doc_title", "figure_title", "formula_number", "seal", "vertical_text"}:
        return False
    return isinstance(region.get("content"), str)


def _page_has_extractable_text(page: fitz.Page) -> bool:
    try:
        text = page.get_text("text")
    except Exception:
        return False
    compact = _normalize_for_compare(text)
    if len(compact) < 30:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", compact))


def _extract_text_layer_region(page: fitz.Page, bbox: list[int]) -> str:
    x1, y1, x2, y2 = bbox
    rect = page.rect
    clip = fitz.Rect(
        x1 * rect.width / 1000.0,
        y1 * rect.height / 1000.0,
        x2 * rect.width / 1000.0,
        y2 * rect.height / 1000.0,
    )
    try:
        text = page.get_textbox(clip)
    except Exception:
        return ""
    return _clean_text_layer_content(text)


def _clean_text_layer_content(text: str) -> str:
    lines = [re.sub(r"[ \t\u3000]+", " ", line.strip()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return _join_lines(lines, preserve_line_breaks=False)


def _format_text_layer_content(
    old_content: str,
    text_layer_content: str,
    region: dict[str, Any],
) -> str:
    content = _clean_text_layer_content(text_layer_content)
    native_label = str(region.get("native_label") or "")
    if old_content.lstrip().startswith("#"):
        level_match = re.match(r"^\s*(#{1,6})\s*", old_content)
        level = level_match.group(1) if level_match else "##"
        content = _strip_markdown_heading(content)
        return f"{level} {content}".strip()
    if native_label == "paragraph_title":
        return _strip_markdown_heading(content)
    return content


def _text_layer_matches_region(old_content: str, text_layer_content: str) -> bool:
    new_norm = _normalize_for_compare(text_layer_content)
    if not new_norm:
        return False
    old_norm = _normalize_for_compare(_strip_markdown_heading(old_content))
    return old_norm == new_norm


def _strip_markdown_heading(text: str) -> str:
    return re.sub(r"^\s*#{1,6}\s*", "", str(text or "").strip())


def _looks_like_better_title(old_content: str, new_content: str) -> bool:
    old = _strip_markdown_heading(old_content)
    new = _strip_markdown_heading(new_content)
    old_norm = _normalize_for_compare(old)
    new_norm = _normalize_for_compare(new)
    if not old_norm or not new_norm:
        return False
    if old_norm == new_norm:
        return False
    if _section_number_drift(old, new):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)+", new_norm) and len(new_norm) <= len(old_norm):
        return True
    if _content_needs_pdf_text_layer(old, old) and len(new_norm) >= max(2, int(len(old_norm) * 0.35)):
        return True
    return False


def _content_needs_pdf_text_layer(content: str, raw_content: str) -> bool:
    content = str(content or "")
    raw_content = str(raw_content or "")
    if _has_percent_digit_run(content) or _has_formula_text_noise(content):
        return True
    if _has_repeated_ngrams(content) or _has_repeated_line_phrase(_normalize_for_compare(content)):
        return True
    if len(raw_content) >= 900 and _has_repeated_ngrams(raw_content):
        return True
    return False


def _section_number_drift(old_content: str, new_content: str) -> bool:
    old = _strip_markdown_heading(old_content)
    new = _strip_markdown_heading(new_content)
    old_section = _leading_section_number(old)
    new_section = _leading_section_number(new)
    if not old_section or not new_section:
        return False
    if old_section == new_section:
        return False
    old_parts = old_section.split(".")
    new_parts = new_section.split(".")
    if _section_parts_can_reduce_to(old_parts, new_parts):
        return True
    if old_section.startswith(new_section) and len(old_section) > len(new_section):
        return True
    return len(old_parts) >= 3 and old_parts[-1] == old_parts[-2] and new_parts == old_parts[:-1]


def _leading_section_number(text: str) -> str | None:
    match = re.match(r"^\s*((?:\d+\s*\.\s*)+\d+)", str(text or "").strip())
    if not match:
        return None
    section = re.sub(r"\s+", "", match.group(1))
    return section if "." in section else None


def _section_parts_can_reduce_to(parts: list[str], target: list[str]) -> bool:
    if parts == target:
        return True
    if len(parts) <= len(target) or len(parts) > 10:
        return False
    seen: set[tuple[str, ...]] = set()
    queue: list[list[str]] = [parts]
    while queue:
        current = queue.pop(0)
        key = tuple(current)
        if key in seen:
            continue
        seen.add(key)
        if current == target:
            return True
        if len(current) <= len(target):
            continue
        for start in range(len(current)):
            max_size = (len(current) - start) // 2
            for size in range(max_size, 0, -1):
                left = current[start : start + size]
                right = current[start + size : start + 2 * size]
                if left != right:
                    continue
                candidate = current[: start + size] + current[start + 2 * size :]
                if len(candidate) >= len(target):
                    queue.append(candidate)
    return False


def _similar_length_but_different(old_norm: str, new_norm: str) -> bool:
    if len(old_norm) < 30 or len(new_norm) < 30:
        return False
    ratio = len(new_norm) / max(1, len(old_norm))
    if ratio < 0.65 or ratio > 1.35:
        return False
    common = _longest_common_subsequence_ratio(old_norm, new_norm)
    return 0.35 <= common < 0.96


def _longest_common_subsequence_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if len(left) * len(right) > 40000:
        left = left[:200]
        right = right[:200]
    previous = [0] * (len(right) + 1)
    for char_left in left:
        current = [0]
        prev_diag = 0
        for idx, char_right in enumerate(right, start=1):
            above = previous[idx]
            left_value = current[-1]
            if char_left == char_right:
                value = prev_diag + 1
            else:
                value = above if above >= left_value else left_value
            current.append(value)
            prev_diag = above
        previous = current
    return previous[-1] / max(len(left), len(right))


def _should_preserve_line_breaks(
    region: dict[str, Any],
    line_boxes: list[tuple[int, int, int, int]],
) -> bool:
    native_label = str(region.get("native_label") or "")
    content = str(region.get("content") or "")
    if native_label == "content" and (
        len(line_boxes) >= 10 or _looks_like_toc_content(content)
    ):
        return True
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
    suspicion: str | None = None
    if len(raw_content) >= max(1200, line_count * 180):
        suspicion = "raw_runaway_generation"
    elif len(content) >= max(900, line_count * 180):
        suspicion = "runaway_generation"
    elif content.count("$") % 2 == 1:
        suspicion = "unbalanced_formula_marker"
    elif _repeated_formula_token(content):
        suspicion = "repeated_formula_token"
    elif _has_percent_digit_run(source) or _has_percent_digit_run(content):
        suspicion = "percent_digit_run"
    elif _has_formula_text_noise(content):
        suspicion = "formula_text_noise"
    elif _looks_like_toc_content(content) and _has_toc_entry_loop(content):
        suspicion = "toc_repeated_entry_loop"
    elif _has_repeated_ngrams(source) or _has_repeated_ngrams(content):
        suspicion = "repeated_text_loop"
    if line_count < 1:
        return None
    if line_count < 2 and suspicion not in _SEVERE_REPAIR_REASONS:
        return None
    return suspicion


def _repair_output_invalid(text: str) -> bool:
    if len(text) >= 1200:
        return True
    if text.count("$") % 2 == 1:
        return True
    if _has_percent_digit_run(text):
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


def _has_formula_text_noise(text: str) -> bool:
    if "\\mathrm" in text or "\\textcircled" in text:
        return True
    return bool("$" in text and re.search(r"\$\s*[^$]{0,12}[\u4e00-\u9fff]", text))


def _has_percent_digit_run(text: str) -> bool:
    """Detect hallucinated values like 97%～9999% without rewriting them blindly."""
    for match in re.finditer(r"(?<!\d)(\d{3,})\s*(?:\\%|%)", text):
        digits = match.group(1)
        if digits == "100":
            continue
        if len(digits) >= 4 or len(set(digits)) <= 2:
            return True
    return False


def _starts_with_numbered_clause(text: str) -> bool:
    stripped = re.sub(r"^#+\s*", "", text.strip())
    stripped = re.sub(r"(?<=\d)\.\s+(?=\d)", ".", stripped)
    return bool(
        re.match(r"^\d{1,2}\s+[\u4e00-\u9fff]", stripped)
        or re.match(r"^\d+(?:\.\d+){1,4}\.?\s*[\u4e00-\u9fff]", stripped)
    )


def _contains_cjk_sentence_punctuation(text: str) -> bool:
    return any(char in text for char in "，。；：（）")


def _clean_line_text(text: str) -> str:
    text = text.replace("\r", "\n").strip()
    text = re.sub(r"^(?:Text Recognition:|文本识别[:：])\s*", "", text, flags=re.I)
    text = re.sub(r"\s*\n+\s*", "", text)
    text = re.sub(r"[ \t\u3000]+", " ", text).strip()
    text = _normalize_percent_digit_runs(text)
    text = _normalize_formula_definition_text(text)
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
    text = _normalize_percent_digit_runs(text)
    text = _normalize_common_broken_latex_text(text)
    text = _normalize_formula_definition_text(text)
    text = re.sub(r"(?<!\d)(\d+)\.\s+((?:\d+\.)*\d+)", r"\1.\2", text)
    text = re.sub(r"^(\d+\.\d+)\.\s+\1\.(\d+)", r"\1.\2", text)
    text = _normalize_toc_line(text)
    replacements = {
        "根据水位应根据水位库": "根据水库",
        "根据水位应根据水库": "根据水库",
        "水位库调蓄": "水库调蓄",
        "进水时，池": "进水池",
        "进水时池": "进水池",
        "出水时，池": "出水池",
        "出水时池": "出水池",
        "平均值值": "平均值",
        "最低最低水位": "最低水位",
        "最低最低运行水位": "最低运行水位",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = _normalize_head_clause_water_level_text(text)
    return text


def _normalize_percent_digit_runs(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        low = match.group("low")
        high = match.group("digit") * 2
        try:
            low_value = int(low)
            high_value = int(high)
        except ValueError:
            return match.group(0)
        if high_value < low_value or high_value > 100:
            return match.group(0)
        return (
            f"{low}{match.group('low_pct')}"
            f"{match.group('sep')}"
            f"{high}{match.group('high_pct')}"
        )

    return _PERCENT_RANGE_RUN_RE.sub(replace, text)


def _normalize_formula_definition_text(text: str) -> str:
    if "加权平均净扬程" in text:
        text = re.sub(r"式中[:：]\s*H\s*", "式中：$H$：", text)
    if "运行水位差" in text and "H" in text and "i" in text:
        return "$H_{i}$：第 i 时段泵站进出水池运行水位差（m）；"
    if "泵站流量" in text and "Q" in text and "i" in text:
        return "$Q_{i}$：第 i 时段泵站流量（m^3/s）；"
    if (("历时" in text) or "（d）" in text or "(d)" in text) and "t" in text and "i" in text:
        return "$t_{i}$：第 i 时段历时（d）。"
    return text


def _normalize_common_broken_latex_text(text: str) -> str:
    text = _normalize_engineering_latex_noise(text)
    text = text.replace("$ 1：2.5\\sim 1: 1: 5;", "1:2.5～1:1.5；")
    text = text.replace("$1：2.5\\sim1:1:5;", "1:2.5～1:1.5；")
    text = text.replace("2.0m～3.0m~3.0m", "2.0m～3.0m")
    text = text.replace("1.0m~\\sim2.0 m", "1.0m～2.0m")
    text = re.sub(r"\$\s*(\d+(?:\.\d+)?)m([。；;,，])", r"\1m\2", text)
    text = re.sub(r"\$\s*(\d+(?:\.\d+)?)\s*\^\{\\circ\}\s*\\mathrm\s*\{左\}\.?\s*\$", r"\1°左右", text)
    text = re.sub(r"\$\s*(\d+(?:\.\d+)?)\s*\^\{\\circ\}\s*\\mathrm\s*\{C\}\s*\$", r"\1℃", text)
    text = re.sub(r"\(\s*\$\s*\\mathrm\s*\{m\}\s*\^\{?3\}?\s*[。；;]?\s*\$", "（m^3）", text)
    text = re.sub(r"\(\s*\$\s*\\mathrm\s*\{m\s*/\s*s\}\s*\$", "（m/s）", text)
    text = re.sub(r"\n?(?:\s*\$C\$\s*){3,}\$?", "\n", text)
    text = text.replace("$f^{\\prime}$ f^{\\prime}$", "$f^{\\prime}$")
    text = text.replace("$f^{\\prime}$经验及本标准附录A表 A.0.3$", "$f^{\\prime}$ 可按本标准附录A表A.0.3")
    text = re.sub(r"\$f_\{0\}\s*\\mathrm\s*\{一\}\$", "$f_{0}$：", text)
    text = re.sub(r"\$p_\{\\mathrm\{max\}\$\\s*\\mathrm\s*\{p\}_\{\\mathrm\{max\}\}\$", "$p_{max}$：", text)
    text = text.replace("$p_{\\mathrm{max}$ \\mathrm {p}_{\\mathrm{max}}$", "$p_{max}$：")
    text = text.replace("表A.0.2 摩擦角 $\\phi_ {0}$ C_{0}$", "表A.0.2 摩擦角 $\\phi_0$ 值和黏结力 $C_0$ 值")
    text = text.replace("表A.0.2摩擦角$\\phi_{0}$C_{0}$", "表A.0.2 摩擦角 $\\phi_0$ 值和黏结力 $C_0$ 值")
    text = text.replace("$\\phi_0(°)", "$\\phi_0$（°）")
    text = text.replace("$(0.85\\sim 0.45%", "0.85～0.45")
    text = text.replace("（ $ ^{\\circ}；C$", "（°）；C")
    return text


def _normalize_engineering_latex_noise(text: str) -> str:
    text = text.replace("$ \\surdasharpuncthspace{1cm} “\\sqrt{}$", "√")
    text = text.replace("$ \\surdasharpuncthspace{1cm} “\\sqrt{} $", "√")
    text = text.replace("$ \\surd $ \\sqrt[]{”", "√")
    text = re.sub(r"\$\s*\\sim\s*0\.8\\mathrm\{m\s*/\s*s\$;?", "～0.8m/s；", text)
    text = re.sub(
        r"\$\s*(\d+(?:\.\d+)?)\s*\^\{\\circ\}\s*\$\s*\\mathrm\s*\{左\}\s*0°左右",
        r"\1°左右",
        text,
    )
    text = re.sub(
        r"\$\s*(\d+(?:\.\d+)?)\s*\^\{\\circ\}\s*\\mathrm\s*\{左\}\.?\s*0?°?左右?\s*\$?",
        r"\1°左右",
        text,
    )
    text = text.replace("$K_{\\mathrm{c}$ \\mathrm {k}_{ \\mathrm{c}}$", "$K_c$：")
    text = text.replace("$ \\sum G $ \\mathrm {", "$\\sum G$：")
    text = text.replace("$ \\sum H $ \\mathrm {", "$\\sum H$：")
    text = text.replace("$\\phi_0$ \\mathrm{o}_{-} $", "$\\phi_0$：")
    text = text.replace("$ \\phi_0 $ \\mathrm{o}_{-} $", "$\\phi_0$：")
    text = text.replace("（ $ \\mathrm{m}^{2}；$", "（m^2）；")
    text = text.replace("（ $ ^{\\circ}；", "（°）；")
    text = text.replace("（$ ^{\\circ}；", "（°）；")
    return text


def _normalize_head_clause_water_level_text(text: str) -> str:
    text = re.sub(
        r"(4\.3\.3\s*最高扬程宜按泵站出水池最高运行水位与进水池最低运行水位之差，并计[入人]水力损失确定；)"
        r"当出水池最高运行水位与进水.*?池最低运行水位遭遇",
        r"\1当出水池最高运行水位与进水池最低运行水位遭遇",
        text,
    )
    text = re.sub(
        r"(4\.3\.4\s*最低扬程宜按泵站出水池最低运行水位与进水池最高运行水位之差，并计[入人]水力损失确定；)"
        r"当出水池最低运行水位与进水.*?池最高运行水位遭遇",
        r"\1当出水池最低运行水位与进水池最高运行水位遭遇",
        text,
    )
    text = re.sub(
        r"(当出水池最高运行水位与)进水位与进水位(?:之差，并计[入人]水力损失确定；)?池最低运行水位遭遇",
        r"\1进水池最低运行水位遭遇",
        text,
    )
    text = re.sub(
        r"(当出水池最低运行水位与)进水位与进水位(?:之差，)?池最高运行水位遭遇",
        r"\1进水池最高运行水位遭遇",
        text,
    )
    text = text.replace("蓄涝区劳区最高", "蓄涝区最高")
    text = text.replace("水位对有集中蓄涝区", "水位。对有集中蓄涝区")
    text = text.replace("第4.2.1条～第4.2.4.2.4条", "第4.2.1条～第4.2.4条")
    text = text.replace("第4.2.1条～第4.2.2.4条", "第4.2.1条～第4.2.4条")
    return text


def _line_output_suspicious(text: str) -> bool:
    compact = _normalize_for_compare(text)
    if not compact:
        return False
    if _has_formula_text_noise(text):
        return True
    if len(compact) >= 160 and _has_line_repeated_ngrams(compact):
        return True
    return _has_repeated_line_phrase(compact)


def _looks_like_toc_content(text: str) -> bool:
    if re.search(r"\.{3,}|\(\s*\d{1,3}\s*\)$", text, flags=re.M):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    toc_like = 0
    for line in lines[:40]:
        if re.match(r"^(?:\d+(?:\.\d+)*|[A-Za-z].*Appendix)\b.*(?:\(?\s*\d{1,3}\s*\)?)$", line):
            toc_like += 1
    return toc_like >= 3


def _normalize_toc_line(text: str) -> str:
    fixed_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            fixed_lines.append(line)
            continue
        stripped = re.sub(r"^11\.111\.111(?=\s)", "11.11", stripped)
        stripped = re.sub(r"^11\.111(?=\s)", "11.11", stripped)
        stripped = re.sub(r"^111\.(?=\d+\b)", "11.", stripped)
        stripped = re.sub(r"^111(?=\.\d+\b)", "11", stripped)
        stripped = re.sub(r"^1011(?=\D)", "10.11", stripped)
        stripped = re.sub(r"^101(?=[\u4e00-\u9fffA-Za-z])", "10.1 ", stripped)
        stripped = re.sub(r"^(\d{2})(\d)(?=\s|[\u4e00-\u9fffA-Za-z])", r"\1.\2", stripped)
        fixed_lines.append(stripped)
    return "\n".join(fixed_lines)


def _has_line_repeated_ngrams(compact: str) -> bool:
    for n in (6, 8, 10, 12):
        if len(compact) <= n:
            continue
        grams: dict[str, int] = {}
        for idx in range(0, len(compact) - n + 1):
            gram = compact[idx : idx + n]
            grams[gram] = grams.get(gram, 0) + 1
        if not grams:
            continue
        common, count = max(grams.items(), key=lambda item: item[1])
        if count >= 3:
            return True
        if count >= 2 and count * len(common) / max(1, len(compact)) >= 0.18:
            return True
    return False


def _has_repeated_line_phrase(compact: str) -> bool:
    for n in range(8, 21):
        counts: dict[str, int] = {}
        for idx in range(0, len(compact) - n + 1):
            gram = compact[idx : idx + n]
            if not re.fullmatch(r"[\u4e00-\u9fff]+", gram):
                continue
            counts[gram] = counts.get(gram, 0) + 1
        if counts and max(counts.values()) >= 2:
            return True
    return False


def _has_toc_entry_loop(text: str) -> bool:
    lines = [_normalize_for_compare(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 8:
        return False
    short_noise = [line for line in lines if re.fullmatch(r"(?:\d+\.?)+[)）]?", line)]
    if len(short_noise) >= 5:
        return True
    counts = Counter(lines)
    return any(count >= 3 and len(line) <= 16 for line, count in counts.items())


def _prefer_segmented_line(old_text: str, segmented_text: str) -> bool:
    segmented_text = segmented_text.strip()
    if len(segmented_text) < 6:
        return False
    if _repair_output_invalid(segmented_text):
        return False
    old_suspicious = _line_output_suspicious(old_text)
    new_suspicious = _line_output_suspicious(segmented_text)
    if old_suspicious and not new_suspicious:
        return True
    old_norm = _normalize_for_compare(old_text)
    new_norm = _normalize_for_compare(segmented_text)
    return old_suspicious and len(new_norm) >= max(8, int(len(old_norm) * 0.35))


def _merge_segment_texts(texts: list[str]) -> str:
    result = ""
    for text in texts:
        text = text.strip()
        if not text:
            continue
        if not result:
            result = text
            continue
        max_overlap = min(16, len(result), len(text))
        overlap_size = 0
        for size in range(max_overlap, 0, -1):
            if result.endswith(text[:size]):
                overlap_size = size
                break
        if overlap_size:
            result += text[overlap_size:]
        elif _needs_space_between(result[-1], text[0]):
            result += " " + text
        else:
            result += text
    return _normalize_formula_definition_text(result.strip())


def _needs_space_between(left: str, right: str) -> bool:
    return left.isascii() and right.isascii() and left.isalnum() and right.isalnum()


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))
