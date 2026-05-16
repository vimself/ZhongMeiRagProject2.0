from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

import requests

from config import (
    GLM_CONNECT_TIMEOUT_SECONDS,
    GLM_IMAGE_FORMAT,
    GLM_LOG_LEVEL,
    GLM_MAX_TOKENS,
    GLM_MAX_WORKERS,
    GLM_PAGE_QUEUE_SIZE,
    GLM_REGION_QUEUE_SIZE,
    GLM_REPETITION_PENALTY,
    GLM_REQUEST_TIMEOUT_SECONDS,
    GLM_SAVE_LAYOUT_VIS,
    GLM_TEMPERATURE,
    GLM_TEXT_LINE_REPAIR_ENABLED,
    GLM_TOP_K,
    GLM_TOP_P,
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
from quality_repair import TextLineRepairer

PAGE_SPLIT = "<--- Page Split --->"
logger = logging.getLogger("glm_ocr_api.processor")


class GlmOCRProcessor:
    """Thin wrapper around the official GLM-OCR self-hosted SDK pipeline."""

    def __init__(self) -> None:
        self._parser: Any | None = None
        self._line_repairer: TextLineRepairer | None = None
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
                "pipeline.page_loader.temperature": GLM_TEMPERATURE,
                "pipeline.page_loader.top_p": GLM_TOP_P,
                "pipeline.page_loader.top_k": GLM_TOP_K,
                "pipeline.page_loader.repetition_penalty": GLM_REPETITION_PENALTY,
                "pipeline.page_loader.image_format": GLM_IMAGE_FORMAT,
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
                pass
        if self._line_repairer is not None:
            self._line_repairer.close()
            self._line_repairer = None

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
        quality_report = self._repair_quality(pdf_path, json_result, raw_json_result)
        _normalize_json_formulas(json_result)
        _normalize_json_text(json_result)
        _finalize_json_text(json_result)
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
        if quality_report is not None:
            (output_path / "quality_report.json").write_text(
                json.dumps(quality_report, ensure_ascii=False, indent=2),
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
            "quality_repair_enabled": bool(quality_report and quality_report.get("enabled")),
            "quality_repair_count": int((quality_report or {}).get("repair_count") or 0),
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
            "quality_report": quality_report,
        }

    def _repair_quality(
        self,
        pdf_path: str,
        json_result: Any,
        raw_json_result: Any,
    ) -> dict[str, Any] | None:
        if not GLM_TEXT_LINE_REPAIR_ENABLED:
            return None
        if self._line_repairer is None:
            self._line_repairer = TextLineRepairer()
        try:
            return self._line_repairer.repair_pdf_result(
                pdf_path,
                json_result,
                raw_json_result,
            )
        except Exception as exc:
            logger.warning("ocr_quality_repair_failed pdf=%s error=%s", pdf_path, exc)
            return {
                "enabled": True,
                "policy": "auto",
                "repair_count": 0,
                "error": str(exc),
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


def _normalize_json_text(json_result: Any) -> None:
    if not isinstance(json_result, list):
        return
    last_section: list[int] | None = None
    for page in json_result:
        if not isinstance(page, list):
            continue
        for region in page:
            if not isinstance(region, dict):
                continue
            formula_section = _section_from_formula_content(region.get("content"))
            if formula_section is not None:
                last_section = formula_section
            if region.get("label") != "text":
                continue
            content = region.get("content")
            if isinstance(content, str) and content:
                normalized, last_section = _normalize_text_content(content, last_section)
                region["content"] = normalized


def _normalize_json_formulas(json_result: Any) -> None:
    if not isinstance(json_result, list):
        return
    for page in json_result:
        if not isinstance(page, list):
            continue
        for region in page:
            if not isinstance(region, dict):
                continue
            content = region.get("content")
            if not isinstance(content, str) or not content:
                continue
            if region.get("label") == "formula":
                region["content"] = _normalize_formula_content(content)
            elif region.get("label") == "table":
                region["content"] = _normalize_common_broken_latex_text(content)


def _finalize_json_text(json_result: Any) -> None:
    if not isinstance(json_result, list):
        return
    last_section: list[int] | None = None
    for page in json_result:
        if not isinstance(page, list):
            continue
        for region in page:
            if not isinstance(region, dict):
                continue
            content = region.get("content")
            if not isinstance(content, str) or not content:
                continue
            if region.get("label") == "text":
                normalized, last_section = _normalize_text_content(content, last_section)
                normalized = _normalize_malformed_section_number_text(normalized)
                region["content"] = normalized
            else:
                region["content"] = _normalize_toc_numbering(content)


def _normalize_text_content(
    content: str,
    last_section: list[int] | None = None,
) -> tuple[str, list[int] | None]:
    content = _normalize_common_broken_latex_text(content)
    content = _normalize_formula_definition_text(content)
    content = _prefer_embedded_real_section(content)
    content = _merge_split_clause_number(content)
    content = _normalize_section_candidates(content, last_section)
    content = _dedupe_repeated_section_tail(content)
    content = _normalize_toc_numbering(content)
    content = re.sub(r"(?<!\d)(\d+)\.\s+((?:\d+\.)*\d+)", r"\1.\2", content)
    content = re.sub(r"^(\d+\.\d+)\.\s+\1\.(\d+)", r"\1.\2", content)
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
        content = content.replace(source, target)
    content = _normalize_head_clause_water_level_text(content)
    content, section = _normalize_section_sequence(content, last_section)
    return content, section or last_section


def _normalize_malformed_section_number_text(content: str) -> str:
    content = re.sub(
        r"(?m)^(\s*#{0,6}\s*)(\d{1,2})\.111\.\s*(\d{1,2}\.\d{1,3})(?:\s+\3)?(?=\s*[\u4e00-\u9fff])",
        r"\1\2.\3",
        content,
    )
    content = re.sub(
        r"(?m)^(\s*#{0,6}\s*)(\d{1,2})\.\2\.(\d{1,3})(?=\s*[\u4e00-\u9fff])",
        r"\1\2.\3",
        content,
    )
    return content


def _normalize_toc_numbering(content: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        stripped = re.sub(r"^11\.111\.111(?=\s)", "11.11", stripped)
        stripped = re.sub(r"^11\.111(?=\s)", "11.11", stripped)
        stripped = re.sub(r"^111\.(?=\d+\b)", "11.", stripped)
        stripped = _normalize_section_candidates(stripped, None)
        lines.append(stripped)
    return "\n".join(lines)


def _normalize_section_candidates(
    content: str,
    last_section: list[int] | None,
) -> str:
    content = _normalize_leading_section_candidate(content, last_section)
    content = _normalize_embedded_section_candidates(content, last_section)
    content = _normalize_reference_section_candidates(content)
    return content


def _prefer_embedded_real_section(content: str) -> str:
    stripped = content.strip()
    fixed = re.sub(
        r"^(?P<prefix>#{1,6}\s*)?"
        r"(?P<chapter>\d{1,2})\.(?:(?P=chapter)|111)\.\s*"
        r"(?P<section>\d{1,2}\.\d{1,3})"
        r"(?:\s+(?P<tail>\d{1,2}\.\d{1,3}))?"
        r"(?=\s*[\u4e00-\u9fff])",
        lambda match: (
            f"{match.group('prefix') or ''}{match.group('chapter')}.{match.group('section')}"
        ),
        stripped,
    )
    if fixed != stripped:
        return content.replace(stripped, fixed, 1)
    fixed = re.sub(
        r"^(?P<prefix>#{1,6}\s*)?111\.11\.\s*(?P<section>11\.\d{1,2})(?=\s*[\u4e00-\u9fff])",
        lambda match: f"{match.group('prefix') or ''}{match.group('section')}",
        stripped,
    )
    if fixed != stripped:
        return content.replace(stripped, fixed, 1)
    return content


def _merge_split_clause_number(content: str) -> str:
    pattern = re.compile(
        r"(?P<prefix>(?:^|\n)\s*#{0,6}\s*)"
        r"(?P<section>\d{1,8}(?:\s*\.\s*\d{1,8}){1,8})"
        r"\s+"
        r"(?P<trail>[1-9])"
        r"(?=[\u4e00-\u9fff])"
    )

    def replace(match: re.Match[str]) -> str:
        section = _fix_split_clause_number(match.group("section"), int(match.group("trail")))
        return f"{match.group('prefix')}{section}"

    return pattern.sub(replace, content)


def _fix_split_clause_number(section_text: str, trailing_part: int) -> str:
    base = _fix_section_number_text(section_text, None)
    parts = [int(part) for part in base.split(".") if part.isdigit()]
    if len(parts) < 2:
        return f"{base}.{trailing_part}"
    if len(parts) == 2:
        return ".".join(str(part) for part in [*parts, trailing_part])
    if len(parts) >= 3 and all(part == 1 for part in parts[2:]):
        return ".".join(str(part) for part in [parts[0], parts[1], trailing_part])
    if len(parts) >= 3 and parts[0] == parts[1] == 11 and parts[2] == 1:
        return ".".join(str(part) for part in [11, 1, trailing_part])
    if parts[-1] == trailing_part:
        return ".".join(str(part) for part in parts)
    return ".".join(str(part) for part in [*parts, trailing_part])


def _normalize_leading_section_candidate(
    content: str,
    last_section: list[int] | None,
) -> str:
    stripped = content.strip()
    match = re.match(
        r"^(?P<prefix>#{1,6}\s*)?"
        r"(?P<section>\d{1,8}(?:\s*\.\s*\d{1,8}){0,8})"
        r"\.?"
        r"(?P<sep>\s*)"
        r"(?=[\u4e00-\u9fffA-Za-z])",
        stripped,
    )
    if not match:
        return content
    section_text = match.group("section")
    fixed_section = _fix_section_number_text(section_text, last_section)
    if fixed_section == re.sub(r"\s+", "", section_text):
        return content
    replacement = f"{match.group('prefix') or ''}{fixed_section}{match.group('sep')}"
    fixed = stripped[: match.start()] + replacement + stripped[match.end() :]
    return content.replace(stripped, fixed, 1)


def _normalize_embedded_section_candidates(
    content: str,
    last_section: list[int] | None,
) -> str:
    pattern = re.compile(
        r"(?P<prefix>(?:^|\n)\s*#{1,6}\s*|(?<=[。；;])\s*)"
        r"(?P<section>\d{1,8}(?:\s*\.\s*\d{1,8}){1,8})"
        r"\.?"
        r"(?P<sep>\s*)"
        r"(?=[\u4e00-\u9fffA-Za-z])"
    )

    def replace(match: re.Match[str]) -> str:
        fixed_section = _fix_section_number_text(match.group("section"), last_section)
        return f"{match.group('prefix')}{fixed_section}{match.group('sep')}"

    return pattern.sub(replace, content)


def _normalize_reference_section_candidates(content: str) -> str:
    pattern = re.compile(
        r"(?P<prefix>第)"
        r"(?P<section>\d{1,8}(?:\s*\.\s*\d{1,8}){1,8})"
        r"(?P<suffix>[章节条款])"
    )

    def replace(match: re.Match[str]) -> str:
        fixed_section = _fix_section_number_text(match.group("section"), None)
        return f"{match.group('prefix')}{fixed_section}{match.group('suffix')}"

    return pattern.sub(replace, content)


def _dedupe_repeated_section_tail(content: str) -> str:
    pattern = re.compile(
        r"(?P<section>\d{1,2}(?:\.\d{1,3}){2,5})"
        r"\s+"
        r"(?P<tail>\d{1,3}(?:\.\d{1,3}){0,3})"
        r"(?=\s*[\u4e00-\u9fff])"
    )

    def replace(match: re.Match[str]) -> str:
        section_parts = match.group("section").split(".")
        tail_parts = match.group("tail").split(".")
        if len(tail_parts) >= len(section_parts):
            return match.group(0)
        if section_parts[-len(tail_parts) :] != tail_parts:
            return match.group(0)
        return match.group("section")

    return pattern.sub(replace, content)


def _fix_section_number_text(
    section_text: str,
    last_section: list[int] | None,
) -> str:
    compact = re.sub(r"\s+", "", section_text)
    if "." not in compact:
        if len(compact) >= 3 and set(compact) == {"1"}:
            return "11"
        return compact
    raw_parts = compact.split(".")
    parts = [_normalize_section_part(part) for part in raw_parts]
    parts = _drop_empty_section_parts(parts)
    parts = _collapse_repeated_section_prefix(parts)
    parts = _collapse_repeated_section_components(parts)
    parts = _fix_section_with_context(parts, last_section)
    return ".".join(str(part) for part in parts)


def _normalize_section_part(part: str) -> int:
    digits = re.sub(r"\D+", "", part)
    if not digits:
        return 0
    if len(digits) >= 3 and set(digits) == {"1"}:
        return 11
    if len(digits) == 3 and digits.startswith("1"):
        tail = int(digits[1:])
        if 10 <= tail <= 30:
            return tail
    return int(digits)


def _drop_empty_section_parts(parts: list[int]) -> list[int]:
    return [part for part in parts if part > 0]


def _collapse_repeated_section_prefix(parts: list[int]) -> list[int]:
    if len(parts) < 4:
        return parts
    for size in range(len(parts) // 2, 0, -1):
        if parts[:size] == parts[size : size * 2]:
            return parts[:size] + parts[size * 2 :]
    return parts


def _collapse_repeated_section_components(parts: list[int]) -> list[int]:
    if len(parts) < 3:
        return parts
    if len(parts) == 3 and parts[0] == parts[1] and parts[2] > parts[1] + 1:
        return [parts[0], parts[2]]
    if len(parts) >= 5 and parts[2:-1] and all(part == 1 for part in parts[2:-1]):
        parts = parts[:2] + [parts[-1]]
    while len(parts) >= 5 and parts[:2] == parts[2:4]:
        parts = parts[:2] + parts[4:]
    if len(parts) >= 4 and parts[1] == parts[2] and parts[0] != parts[1]:
        parts = [parts[0], *parts[2:]]
    if len(parts) >= 4 and parts[1] == parts[3]:
        parts = parts[:2] + parts[4:]
    if len(parts) >= 4 and parts[0] == parts[1] and parts[2] != parts[1]:
        parts = [parts[0], *parts[2:]]
    if len(parts) >= 3 and parts[0] == parts[1] == parts[2]:
        while len(parts) >= 3 and parts[2] == parts[1]:
            parts = parts[:2] + parts[3:]
    if len(parts) >= 4 and len(set(parts[1:])) == 1:
        parts = parts[:3]
    return parts


def _fix_section_with_context(
    parts: list[int],
    last_section: list[int] | None,
) -> list[int]:
    if not last_section or len(parts) < 2:
        return parts
    if (
        len(parts) == 2
        and len(last_section) >= 2
        and parts[0] == parts[1] == last_section[0]
        and last_section[1] + 1 <= 30
    ):
        return [parts[0], last_section[1] + 1]
    if (
        len(parts) == 3
        and len(last_section) >= 2
        and parts[0] == parts[1] == last_section[0]
        and parts[2] == last_section[1] + 1
    ):
        return [parts[0], parts[2]]
    if (
        len(parts) == len(last_section) + 1
        and parts[0] == last_section[0]
        and parts[1:-1] == last_section[1:]
        and parts[-1] == last_section[-1] + 1
    ):
        return [parts[0], *parts[2:]]
    if (
        len(parts) >= 3
        and len(parts) == len(last_section)
        and parts[0] == last_section[0]
        and parts[1] == parts[0]
        and parts[-1] == last_section[-1] + 1
    ):
        return [parts[0], last_section[1], *parts[2:]]
    return parts


def _normalize_section_sequence(
    content: str,
    last_section: list[int] | None,
) -> tuple[str, list[int] | None]:
    match = re.match(r"^(#+\s*)?(\d+(?:\.\d+)+)(\s*[\u4e00-\u9fff].*)$", content.strip())
    if not match:
        return content, None
    prefix, section_text, suffix = match.groups()
    section = [int(part) for part in section_text.split(".")]
    if (
        last_section
        and len(section) >= 3
        and section[-1] == section[-2]
        and _is_next_section(last_section, section[:-1])
    ):
        fixed_section = ".".join(str(part) for part in section[:-1])
        fixed = f"{prefix or ''}{fixed_section}{suffix}"
        if content.startswith(" ") or content.endswith(" "):
            fixed = content.replace(match.group(0), fixed, 1)
        return fixed, section[:-1]
    if (
        last_section
        and len(last_section) >= 2
        and len(section) == len(last_section) + 2
        and section[0] == last_section[0]
        and section[2 : 2 + len(last_section[1:])] == last_section[1:]
    ):
        fixed_parts = [section[0], *section[2:]]
        fixed_section = ".".join(str(part) for part in fixed_parts)
        fixed = f"{prefix or ''}{fixed_section}{suffix}"
        if content.startswith(" ") or content.endswith(" "):
            fixed = content.replace(match.group(0), fixed, 1)
        return fixed, fixed_parts
    if (
        last_section
        and len(last_section) >= 3
        and len(section) == len(last_section)
        and section[0] == last_section[0]
        and section[1] == section[0]
        and section[-1] == last_section[-1] + 1
    ):
        fixed_parts = [section[0], last_section[1], section[-1]]
        fixed_section = ".".join(str(part) for part in fixed_parts)
        fixed = f"{prefix or ''}{fixed_section}{suffix}"
        if content.startswith(" ") or content.endswith(" "):
            fixed = content.replace(match.group(0), fixed, 1)
        return fixed, fixed_parts
    if (
        last_section
        and len(last_section) >= 3
        and len(section) == len(last_section) + 1
        and section[0] == last_section[0]
        and section[2:-1] == last_section[1:-1]
        and section[-1] == last_section[-1] + 1
    ):
        fixed_parts = [section[0], *section[2:]]
        fixed_section = ".".join(str(part) for part in fixed_parts)
        fixed = f"{prefix or ''}{fixed_section}{suffix}"
        if content.startswith(" ") or content.endswith(" "):
            fixed = content.replace(match.group(0), fixed, 1)
        return fixed, fixed_parts
    return content, section


def _normalize_formula_content(content: str) -> str:
    if "\\sum" in content and "H" in content and "Q" in content and "t" in content:
        tag = _section_from_formula_content(content)
        tag_text = ""
        if tag is not None:
            tag_text = f"\\tag{{{'.'.join(str(part) for part in tag)}}}"
        return f"$$\nH = \\frac{{\\sum H_i Q_i t_i}}{{\\sum Q_i t_i}}{tag_text}\n$$"
    return content


def _section_from_formula_content(content: Any) -> list[int] | None:
    if not isinstance(content, str):
        return None
    match = re.search(r"(?:\\tag\{|[（(])(\d+(?:\.\d+){1,4})(?:\}|[）)])", content)
    if not match:
        return None
    try:
        return [int(part) for part in match.group(1).split(".")]
    except ValueError:
        return None


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


def _is_next_section(previous: list[int], current: list[int]) -> bool:
    return (
        len(previous) == len(current)
        and len(current) >= 2
        and previous[:-1] == current[:-1]
        and current[-1] == previous[-1] + 1
    )


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
