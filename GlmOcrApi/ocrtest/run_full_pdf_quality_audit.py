from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import fitz


TEST_DIR = Path(__file__).resolve().parent
API_ROOT = TEST_DIR.parent
DEFAULT_PDF = TEST_DIR / "泵站设计标准.pdf"
DEFAULT_OUTPUT = TEST_DIR / "output"
PAGE_SPLIT = "<--- Page Split --->"
LOCAL_LAYOUT_SNAPSHOT = Path(
    "/home/ubuntu/.cache/huggingface/hub/models--PaddlePaddle--PP-DocLayoutV3_safetensors/"
    "snapshots/3ec586e86ed9245a567bb13395a3db64d5c077cc"
)

PERCENT_DIGIT_RUN_RE = re.compile(r"(?<!\d)(\d{3,})\s*(?:\\%|%)")
LATEX_NOISE_RE = re.compile(
    r"\\textcircled|"
    r"\\mathrm\s*\{[^}\n$]*(?:\$|$)|"
    r"\\mathrm\s*\{[^}\n]*[\u4e00-\u9fff][^}\n]*\}"
)
BROKEN_FORMULA_RE = re.compile(r"\$[^$\n]{0,8}$|^\s*[^$\n]{0,8}\$")
SECTION_RE = re.compile(r"^(?:#{1,6}\s*)?(\d+(?:\.\d+){1,4})\s*[\u4e00-\u9fff]", re.M)


@dataclass
class PageAudit:
    page_no: int
    char_count: int = 0
    raw_char_count: int = 0
    text_region_count: int = 0
    pdf_text_char_count: int = 0
    is_blank_page: bool = False
    repair_count: int = 0
    skipped_repair_count: int = 0
    issue_score: int = 0
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    preview: str = ""


@dataclass
class BatchAudit:
    start_page: int
    end_page: int
    output_dir: str
    elapsed_ms: int
    page_count: int
    repair_count: int
    skipped_repair_count: int
    blocker_pages: list[int]
    warning_pages: list[int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full PDF GLM-OCR quality audit in batches.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="PDF path.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="Output root.")
    parser.add_argument("--case-name", default="pump-full-quality-audit", help="Output case directory.")
    parser.add_argument("--batch-size", type=int, default=6, help="Pages per OCR batch.")
    parser.add_argument("--start-page", type=int, default=1, help="1-based start page.")
    parser.add_argument("--end-page", type=int, default=0, help="1-based end page. 0 means PDF end.")
    parser.add_argument("--max-batches", type=int, default=0, help="Limit OCR batches for smoke tests.")
    parser.add_argument("--resume", action="store_true", help="Reuse completed batch outputs.")
    parser.add_argument("--audit-only", action="store_true", help="Only audit existing batch outputs.")
    parser.add_argument("--layout-vis", action="store_true", help="Save layout visualization.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = args.pdf.resolve()
    case_dir = (args.output_dir / args.case_name).resolve()
    batches_dir = case_dir / "batches"
    case_dir.mkdir(parents=True, exist_ok=True)
    batches_dir.mkdir(parents=True, exist_ok=True)

    page_count = _pdf_page_count(pdf_path)
    start_page = max(1, args.start_page)
    end_page = page_count if args.end_page <= 0 else min(page_count, args.end_page)
    if start_page > end_page:
        raise ValueError(f"invalid page range: {start_page}-{end_page}")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1")

    os.environ["GLM_SAVE_LAYOUT_VIS"] = "1" if args.layout_vis else "0"
    os.environ.pop("GLM_PDF_MAX_PAGES", None)
    _prefer_local_layout_model()
    sys.path.insert(0, str(API_ROOT))
    from glm_processor import GlmOCRProcessor

    processor: GlmOCRProcessor | None = None
    if not args.audit_only:
        processor = GlmOCRProcessor()

    all_pages: list[PageAudit] = []
    batch_summaries: list[BatchAudit] = []
    started = time.time()
    try:
        processed_batches = 0
        for batch_start in range(start_page, end_page + 1, args.batch_size):
            if args.max_batches > 0 and processed_batches >= args.max_batches:
                break
            processed_batches += 1
            batch_end = min(end_page, batch_start + args.batch_size - 1)
            batch_dir = batches_dir / f"pages_{batch_start:03d}_{batch_end:03d}"
            batch_dir.mkdir(parents=True, exist_ok=True)
            if not args.audit_only and not _batch_completed(batch_dir, args.resume):
                if processor is None:
                    raise RuntimeError("processor is not initialized")
                source_pdf = batch_dir / f"source_pages_{batch_start:03d}_{batch_end:03d}.pdf"
                _extract_pages(pdf_path, source_pdf, batch_start, batch_end)
                batch_started = time.time()
                processor.process_pdf(str(source_pdf), str(batch_dir))
                elapsed_ms = int((time.time() - batch_started) * 1000)
            else:
                elapsed_ms = 0

            pages, batch_audit = _audit_batch(batch_dir, batch_start, batch_end, elapsed_ms)
            all_pages.extend(pages)
            batch_summaries.append(batch_audit)
            print(
                f"batch={batch_start:03d}-{batch_end:03d} "
                f"blockers={len(batch_audit.blocker_pages)} "
                f"warnings={len(batch_audit.warning_pages)} "
                f"repairs={batch_audit.repair_count} "
                f"skipped={batch_audit.skipped_repair_count}",
                flush=True,
            )
    finally:
        if processor is not None:
            processor.close()

    summary = _build_summary(
        pdf_path=pdf_path,
        case_dir=case_dir,
        start_page=start_page,
        end_page=end_page,
        elapsed_ms=int((time.time() - started) * 1000),
        pages=all_pages,
        batches=batch_summaries,
    )
    _write_outputs(case_dir, summary, all_pages, batch_summaries)
    print(f"summary={case_dir / 'quality_summary.json'}")
    print(
        f"pages={len(all_pages)} blockers={len(summary['blocker_pages'])} "
        f"warnings={len(summary['warning_pages'])} score={summary['quality_score']}",
        flush=True,
    )


def _prefer_local_layout_model() -> None:
    if "GLM_LAYOUT_MODEL_DIR" in os.environ:
        return
    if not LOCAL_LAYOUT_SNAPSHOT.exists():
        return
    os.environ["GLM_LAYOUT_MODEL_DIR"] = str(LOCAL_LAYOUT_SNAPSHOT)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _pdf_page_count(pdf_path: Path) -> int:
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def _extract_pages(pdf_path: Path, output_pdf: Path, start_page: int, end_page: int) -> None:
    with fitz.open(pdf_path) as src:
        dst = fitz.open()
        dst.insert_pdf(src, from_page=start_page - 1, to_page=end_page - 1)
        dst.save(output_pdf)
        dst.close()


def _batch_completed(batch_dir: Path, resume: bool) -> bool:
    if not resume:
        return False
    return (batch_dir / "result.json").exists() and (batch_dir / "metadata.json").exists()


def _audit_batch(
    batch_dir: Path,
    start_page: int,
    end_page: int,
    elapsed_ms: int,
) -> tuple[list[PageAudit], BatchAudit]:
    result = _read_json(batch_dir / "result.json", [])
    raw_result = _read_json(batch_dir / "result_raw.json", [])
    quality_report = _read_json(batch_dir / "quality_report.json", {})
    repairs_by_page = _count_report_items(quality_report.get("repairs"))
    skipped_by_page = _count_report_items(quality_report.get("skipped"))
    source_pdf = next(batch_dir.glob("source_pages_*.pdf"), None)
    pdf_page_text_lengths = _pdf_page_text_lengths(source_pdf, end_page - start_page + 1)

    pages: list[PageAudit] = []
    for idx in range(end_page - start_page + 1):
        page_no = start_page + idx
        page_regions = result[idx] if isinstance(result, list) and idx < len(result) else []
        raw_regions = raw_result[idx] if isinstance(raw_result, list) and idx < len(raw_result) else []
        page = _audit_page(
            page_no=page_no,
            page_regions=page_regions,
            raw_regions=raw_regions,
            repair_count=repairs_by_page.get(idx + 1, 0),
            skipped_repair_count=skipped_by_page.get(idx + 1, 0),
            pdf_text_char_count=pdf_page_text_lengths.get(idx, 0),
        )
        pages.append(page)

    batch = BatchAudit(
        start_page=start_page,
        end_page=end_page,
        output_dir=str(batch_dir),
        elapsed_ms=elapsed_ms,
        page_count=len(pages),
        repair_count=sum(page.repair_count for page in pages),
        skipped_repair_count=sum(page.skipped_repair_count for page in pages),
        blocker_pages=[page.page_no for page in pages if page.blockers],
        warning_pages=[page.page_no for page in pages if page.warnings and not page.blockers],
    )
    return pages, batch


def _audit_page(
    *,
    page_no: int,
    page_regions: Any,
    raw_regions: Any,
    repair_count: int,
    skipped_repair_count: int,
    pdf_text_char_count: int,
) -> PageAudit:
    text_regions = [item for item in page_regions if isinstance(item, dict) and item.get("label") == "text"]
    text = "\n".join(str(item.get("content") or "") for item in text_regions)
    raw_text = "\n".join(
        str(item.get("content") or "")
        for item in raw_regions
        if isinstance(item, dict) and item.get("label") == "text"
    )
    page = PageAudit(
        page_no=page_no,
        char_count=len(_compact(text)),
        raw_char_count=len(_compact(raw_text)),
        text_region_count=len(text_regions),
        pdf_text_char_count=pdf_text_char_count,
        is_blank_page=pdf_text_char_count == 0 and not text_regions,
        repair_count=repair_count,
        skipped_repair_count=skipped_repair_count,
        sections=SECTION_RE.findall(text),
        preview=_compact(text)[:180],
    )

    _add_issue_flags(page, text, raw_text)
    return page


def _add_issue_flags(page: PageAudit, text: str, raw_text: str) -> None:
    compact = _compact(text)
    raw_compact = _compact(raw_text)
    toc_page = _looks_like_toc_page(text)
    if page.is_blank_page:
        return
    if page.char_count == 0:
        _block(page, "empty_ocr_page", 10)
    elif page.char_count < 20 and page.text_region_count == 0:
        _block(page, "no_text_regions", 8)

    if page.skipped_repair_count > 0:
        _warn(page, f"skipped_repairs:{page.skipped_repair_count}", 2)
    if _has_percent_digit_run(text):
        _block(page, "percent_digit_run", 10)
    if _has_runaway_loop(text):
        if toc_page:
            _warn(page, "toc_repeated_text_pattern", 2)
        else:
            _block(page, "repeated_text_loop", 10)
    if _has_repeated_long_phrase(text):
        _warn(page, "repeated_long_phrase", 2)
    if text.count("$") % 2 == 1:
        _block(page, "unbalanced_formula_marker", 7)
    if LATEX_NOISE_RE.search(text):
        _block(page, "latex_noise_in_text", 6)
    if page.raw_char_count >= 1200 and page.char_count >= 1200 and _has_runaway_loop(raw_text):
        _block(page, "raw_runaway_not_repaired", 10)
    if page.raw_char_count > page.char_count * 4 and page.raw_char_count >= 900 and page.repair_count == 0:
        _warn(page, "large_raw_to_final_shrink_without_report", 4)
    if len(page.sections) != len(set(page.sections)):
        _warn(page, "duplicate_section_numbers_on_page", 2)
    malformed_sections = _malformed_section_numbers(text)
    if malformed_sections:
        issue = "malformed_section_numbers:" + ",".join(malformed_sections[:5])
        if toc_page:
            _warn(page, issue, 4)
        else:
            _block(page, issue, 8)
    if _has_repeated_section_tail(text):
        _warn(page, "repeated_section_tail", 3)
    if re.search(r"(\d+(?:\.\d+){1,4})\.\1", compact):
        _warn(page, "section_number_repeat_pattern", 3)
    if re.search(r"([\u4e00-\u9fff]{2,12})\1{3,}", compact):
        _block(page, "cjk_phrase_repeated_4x", 9)
    if raw_compact and page.char_count < max(30, int(len(raw_compact) * 0.08)) and page.repair_count == 0:
        _warn(page, "final_text_much_shorter_than_raw", 3)


def _has_percent_digit_run(text: str) -> bool:
    for match in PERCENT_DIGIT_RUN_RE.finditer(text):
        digits = match.group(1)
        if digits == "100":
            continue
        if len(digits) >= 4 or len(set(digits)) <= 2:
            return True
    return False


def _malformed_section_numbers(text: str) -> list[str]:
    candidates = re.findall(
        r"(?:^|[。\n#；;])\s*(\d{1,8}(?:\.\s*\d{1,8}){1,8})(?=\s*[\u4e00-\u9fff])",
        text,
    )
    candidates.extend(
        re.findall(
            r"(?:^|[。\n#；;])\s*(\d{1,8}(?:\.\s*\d{1,8}){1,8})(?=\s+\d{1,3}(?:\.\d{1,3})?\s*[\u4e00-\u9fff])",
            text,
        )
    )
    malformed: list[str] = []
    for section in candidates:
        normalized = re.sub(r"\s+", "", section)
        parts = [int(part) for part in normalized.split(".") if part.isdigit()]
        if len(parts) < 2:
            continue
        if _section_has_unlikely_long_part(parts):
            malformed.append(normalized)
            continue
        if _section_has_repeated_prefix(parts):
            malformed.append(normalized)
            continue
        if _section_depth_unlikely(parts):
            malformed.append(normalized)
            continue
    return malformed


def _has_repeated_section_tail(text: str) -> bool:
    for match in re.finditer(
        r"(\d{1,2}(?:\.\d{1,3}){2,5})\s+(\d{1,3}(?:\.\d{1,3}){0,3})(?=\s*[\u4e00-\u9fff])",
        text,
    ):
        section_parts = match.group(1).split(".")
        tail_parts = match.group(2).split(".")
        if len(tail_parts) < len(section_parts) and section_parts[-len(tail_parts) :] == tail_parts:
            return True
    return False


def _section_has_unlikely_long_part(parts: list[int]) -> bool:
    if parts[0] > 30:
        return True
    return any(part > 99 for part in parts[1:])


def _section_has_repeated_prefix(parts: list[int]) -> bool:
    if len(parts) >= 3 and parts[0] == parts[1] == 11:
        return True
    if len(parts) >= 4 and parts[:2] == parts[2:4]:
        return True
    if len(parts) >= 5 and parts[1] == parts[2] == parts[3]:
        return True
    return False


def _section_depth_unlikely(parts: list[int]) -> bool:
    if len(parts) <= 4:
        return False
    if len(parts) >= 5 and len(set(parts[-3:])) == 1:
        return True
    return len(parts) >= 6


def _has_runaway_loop(text: str) -> bool:
    compact = _compact(text)
    if len(compact) < 800:
        return False
    for n in (6, 8, 10, 12):
        counts: dict[str, int] = {}
        for idx in range(0, len(compact) - n + 1):
            gram = compact[idx : idx + n]
            counts[gram] = counts.get(gram, 0) + 1
        if not counts:
            continue
        common, count = max(counts.items(), key=lambda item: item[1])
        if _is_benign_repeated_gram(common):
            continue
        coverage = count * len(common) / len(compact)
        if count >= 10 and coverage >= 0.08:
            return True
        if count >= 5 and coverage >= 0.12:
            return True
    return False


def _has_repeated_long_phrase(text: str) -> bool:
    compact = _compact(text)
    if len(compact) < 120:
        return False
    for n in range(10, 19):
        counts: dict[str, int] = {}
        for idx in range(0, len(compact) - n + 1):
            gram = compact[idx : idx + n]
            if not re.search(r"[\u4e00-\u9fff]{6,}", gram):
                continue
            if _is_benign_repeated_gram(gram):
                continue
            counts[gram] = counts.get(gram, 0) + 1
        if counts and max(counts.values()) >= 3:
            return True
    return False


def _is_benign_repeated_gram(gram: str) -> bool:
    if re.fullmatch(r"[A-Za-z]+", gram):
        return True
    benign_terms = {
        "矿山生态修复",
        "矿山生态修复工程",
        "中华人民共和国",
        "自然资源",
        "具有法人资格",
        "自然资源部门颁发",
        "部门颁发的地质",
        "地质灾害防治",
        "企业法人或其合法代表机构",
        "资质等级证书",
        "与建设单位签订",
        "生态环境",
    }
    return any(term in gram or gram in term for term in benign_terms)


def _looks_like_toc_page(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 8:
        return False
    toc_lines = 0
    for line in lines:
        if re.match(r"^(?:\d+(?:\.\d+)*|Appendix\b|[A-Z][A-Za-z].*)", line) and re.search(
            r"(?:\(?\s*\d{1,3}\s*\)?|\d{1,3})$",
            line,
        ):
            toc_lines += 1
    return toc_lines >= max(6, int(len(lines) * 0.45))


def _count_report_items(items: Any) -> dict[int, int]:
    counts: dict[int, int] = {}
    if not isinstance(items, list):
        return counts
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            page_no = int(item.get("page_no") or 0)
        except (TypeError, ValueError):
            continue
        if page_no > 0:
            counts[page_no] = counts.get(page_no, 0) + 1
    return counts


def _pdf_page_text_lengths(pdf_path: Path | None, expected_pages: int) -> dict[int, int]:
    if pdf_path is None or not pdf_path.exists():
        return {}
    lengths: dict[int, int] = {}
    try:
        with fitz.open(pdf_path) as doc:
            for idx in range(min(expected_pages, doc.page_count)):
                lengths[idx] = len(_compact(doc.load_page(idx).get_text("text")))
    except Exception:
        return {}
    return lengths


def _block(page: PageAudit, reason: str, score: int) -> None:
    page.blockers.append(reason)
    page.issue_score += score


def _warn(page: PageAudit, reason: str, score: int) -> None:
    page.warnings.append(reason)
    page.issue_score += score


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _build_summary(
    *,
    pdf_path: Path,
    case_dir: Path,
    start_page: int,
    end_page: int,
    elapsed_ms: int,
    pages: list[PageAudit],
    batches: list[BatchAudit],
) -> dict[str, Any]:
    blocker_pages = [page.page_no for page in pages if page.blockers]
    warning_pages = [page.page_no for page in pages if page.warnings and not page.blockers]
    total_issue_score = sum(page.issue_score for page in pages)
    quality_score = max(0.0, round(100.0 - total_issue_score / max(1, len(pages)), 2))
    issue_counts: dict[str, int] = {}
    for page in pages:
        for issue in [*page.blockers, *page.warnings]:
            issue_name = issue.split(":", 1)[0]
            issue_counts[issue_name] = issue_counts.get(issue_name, 0) + 1
    return {
        "pdf": str(pdf_path),
        "case_dir": str(case_dir),
        "start_page": start_page,
        "end_page": end_page,
        "page_count": len(pages),
        "blank_pages": [page.page_no for page in pages if page.is_blank_page],
        "batch_count": len(batches),
        "elapsed_ms": elapsed_ms,
        "quality_score": quality_score,
        "blocker_pages": blocker_pages,
        "warning_pages": warning_pages,
        "issue_counts": dict(sorted(issue_counts.items())),
        "repair_count": sum(page.repair_count for page in pages),
        "skipped_repair_count": sum(page.skipped_repair_count for page in pages),
    }


def _write_outputs(
    case_dir: Path,
    summary: dict[str, Any],
    pages: list[PageAudit],
    batches: list[BatchAudit],
) -> None:
    (case_dir / "quality_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "page_audit.json").write_text(
        json.dumps([asdict(page) for page in pages], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "batch_audit.json").write_text(
        json.dumps([asdict(batch) for batch in batches], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_lines = [
        "# GLM-OCR 全 PDF 质量评测",
        "",
        f"- PDF: `{summary['pdf']}`",
        f"- 页范围: {summary['start_page']}-{summary['end_page']}",
        f"- 页数: {summary['page_count']}",
        f"- 空白页: {summary['blank_pages']}",
        f"- 质量分: {summary['quality_score']}",
        f"- 阻断页: {summary['blocker_pages']}",
        f"- 警告页: {summary['warning_pages']}",
        f"- 修复区域数: {summary['repair_count']}",
        f"- 拒绝修复数: {summary['skipped_repair_count']}",
        "",
        "## 问题统计",
        "",
    ]
    for issue, count in summary["issue_counts"].items():
        md_lines.append(f"- `{issue}`: {count}")
    md_lines.extend(["", "## 问题页明细", ""])
    for page in pages:
        if not page.blockers and not page.warnings:
            continue
        md_lines.append(
            f"- 第 {page.page_no} 页：blockers={page.blockers} warnings={page.warnings} "
            f"chars={page.char_count} repairs={page.repair_count} preview={page.preview}"
        )
    (case_dir / "quality_report.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
