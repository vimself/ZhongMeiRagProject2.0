from __future__ import annotations

import asyncio
import ast
import inspect
import io
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import img2pdf
import fitz
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from tqdm import tqdm

try:
    import cv2
except Exception:  # pragma: no cover - optional fallback dependency
    cv2 = None

if torch.version.cuda == "11.8":
    ptxas_candidates = [
        "/usr/local/cuda-11.8/bin/ptxas",
        "/usr/local/cuda-12.1/bin/ptxas",
        "/usr/local/cuda/bin/ptxas",
    ]
    for ptxas_path in ptxas_candidates:
        if os.path.isfile(ptxas_path) and os.access(ptxas_path, os.X_OK):
            os.environ["TRITON_PTXAS_PATH"] = ptxas_path
            break
os.environ["VLLM_USE_V1"] = "0"

from config import (  # noqa: E402
    CROP_MODE,
    GENERATE_TIMEOUT_SECONDS,
    GPU_MEMORY_UTILIZATION,
    INCOMPLETE_PAGE_MIN_CHARS,
    IMAGE_CROP_MIN_HEIGHT,
    IMAGE_CROP_MIN_INK_RATIO,
    IMAGE_CROP_MIN_WIDTH,
    IMAGE_CROP_PADDING_RATIO,
    MAX_CONCURRENCY,
    MODEL_PATH,
    NUM_WORKERS,
    PAGE_RECOVERY_ENABLED,
    PAGE_RECOVERY_MAX_FAILED_SEGMENTS,
    PAGE_RECOVERY_MAX_PAGES,
    PAGE_RECOVERY_MIN_SCORE,
    PAGE_RECOVERY_OVERLAP_RATIO,
    PAGE_RECOVERY_SEGMENTS,
    PDF_RENDER_DPI,
    PROMPT,
    REPEAT_NGRAM_SIZE,
    REPEAT_WINDOW_SIZE,
    SKIP_REPEAT,
)
from deepseek_ocr2 import DeepseekOCR2ForCausalLM  # noqa: E402
from process.image_process import DeepseekOCR2Processor  # noqa: E402
from process.ngram_norepeat import NoRepeatNGramLogitsProcessor  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402,F401
from vllm import LLM, SamplingParams  # noqa: E402
from vllm.model_executor.layers.sampler import get_sampler  # noqa: E402
import vllm.model_executor.models.registry as vllm_model_registry  # noqa: E402
from vllm.model_executor.models.registry import ModelRegistry  # noqa: E402

_original_compute_logits = getattr(DeepseekOCR2ForCausalLM, "compute_logits", None)
_original_is_text_generation_model = getattr(
    vllm_model_registry,
    "is_text_generation_model",
    None,
)


def _is_text_generation_model(model: object) -> bool:
    if model is DeepseekOCR2ForCausalLM or getattr(model, "__name__", "") == "DeepseekOCR2ForCausalLM":
        return True
    if callable(_original_is_text_generation_model):
        return bool(_original_is_text_generation_model(model))
    return False


if callable(_original_is_text_generation_model):
    vllm_model_registry.is_text_generation_model = _is_text_generation_model


def _compute_logits(self: object, hidden_states: torch.Tensor, sampling_metadata: object = None):
    if _original_compute_logits is None:
        language_model = getattr(self, "language_model", None)
        return language_model.compute_logits(hidden_states, sampling_metadata)
    compute_params = inspect.signature(_original_compute_logits).parameters
    if "sampling_metadata" in compute_params:
        return _original_compute_logits(self, hidden_states, sampling_metadata)
    return _original_compute_logits(self, hidden_states)


def _sample(self: object, logits: torch.Tensor, sampling_metadata: object):
    sampler = getattr(self, "_zhongmei_sampler", None)
    if sampler is None:
        sampler = get_sampler()
        setattr(self, "_zhongmei_sampler", sampler)
    return sampler(logits, sampling_metadata)


DeepseekOCR2ForCausalLM.compute_logits = _compute_logits
DeepseekOCR2ForCausalLM.sample = _sample

ModelRegistry.register_model("DeepseekOCR2ForCausalLM", DeepseekOCR2ForCausalLM)

llm_signature = inspect.signature(LLM).parameters
llm_kwargs: dict[str, Any] = {
    "model": MODEL_PATH,
    "hf_overrides": {"architectures": ["DeepseekOCR2ForCausalLM"]},
    "block_size": 256,
    "enforce_eager": False,
    "trust_remote_code": True,
    "max_model_len": 8192,
    "swap_space": 0,
    "max_num_seqs": MAX_CONCURRENCY,
    "tensor_parallel_size": 1,
    "gpu_memory_utilization": GPU_MEMORY_UTILIZATION,
    "disable_mm_preprocessor_cache": True,
}
if "task" in llm_signature:
    llm_kwargs["task"] = "generate"
if "runner" in llm_signature:
    llm_kwargs["runner"] = "generate"
print(
    "Initializing vLLM DeepSeek-OCR with "
    f"task={llm_kwargs.get('task', '<unsupported>')} "
    f"runner={llm_kwargs.get('runner', '<unsupported>')}",
    flush=True,
)

llm = LLM(**llm_kwargs)

logits_processors = [
    NoRepeatNGramLogitsProcessor(
        ngram_size=REPEAT_NGRAM_SIZE,
        window_size=REPEAT_WINDOW_SIZE,
        whitelist_token_ids={128821, 128822},
    )
]

sampling_params = SamplingParams(
    temperature=0.0,
    max_tokens=8192,
    logits_processors=logits_processors,
    skip_special_tokens=False,
    include_stop_str_in_output=True,
)
EOS_TOKEN = "<｜end▁of▁sentence｜>"


class PDFOCRProcessor:
    def __init__(self) -> None:
        self.prompt = PROMPT
        self.gpu_lock = asyncio.Lock()

    def iter_pdf_images(self, pdf_path: str, dpi: int = PDF_RENDER_DPI) -> Any:
        pdf_document = fitz.open(pdf_path)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        try:
            for page_num in range(pdf_document.page_count):
                page = pdf_document[page_num]
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                Image.MAX_IMAGE_PIXELS = None
                img_data = pixmap.tobytes("png")
                yield page_num, Image.open(io.BytesIO(img_data)).copy()
        finally:
            pdf_document.close()

    def re_match(self, text: str) -> tuple[list[Any], list[str], list[str]]:
        pattern = r"(<\|ref\|>(.*?)<\|/ref\|><\|det\|>(.*?)<\|/det\|>)"
        matches = re.findall(pattern, text, re.DOTALL)
        matches_image = []
        matches_other = []
        for item in matches:
            if "<|ref|>image<|/ref|>" in item[0]:
                matches_image.append(item[0])
            else:
                matches_other.append(item[0])
        return matches, matches_image, matches_other

    def collapse_repeated_lines(self, text: str, max_repeats: int = 2) -> str:
        collapsed: list[str] = []
        seen: dict[str, int] = {}
        for line in text.splitlines():
            normalized = re.sub(r"\s+", "", line)
            if not normalized:
                if collapsed and not collapsed[-1].strip():
                    continue
                collapsed.append(line)
                continue
            repeat_count = seen.get(normalized, 0)
            if repeat_count >= max_repeats:
                continue
            seen[normalized] = repeat_count + 1
            collapsed.append(line)
        return "\n".join(collapsed)

    def collapse_repeated_units(self, text: str, max_repeats: int = 1) -> str:
        parts = re.split(r"([，,。；;！？\n])", text)
        seen: dict[str, int] = {}
        collapsed: list[str] = []
        for idx in range(0, len(parts), 2):
            unit = parts[idx]
            separator = parts[idx + 1] if idx + 1 < len(parts) else ""
            normalized = re.sub(r"\s+", "", unit)
            if len(normalized) >= 6:
                count = seen.get(normalized, 0)
                if count >= max_repeats:
                    continue
                seen[normalized] = count + 1
            collapsed.append(unit + separator)
        return "".join(collapsed)

    def strip_grounding_fragments(self, text: str) -> str:
        grounding_markers = ("<|ref|>", "<|/ref|>", "<|det|>", "<|/det|>")
        lines = []
        for line in text.splitlines():
            if any(marker in line for marker in grounding_markers):
                continue
            lines.append(line)
        return "\n".join(lines)

    def trim_repetitive_numbered_headings(self, text: str) -> str:
        lines = text.splitlines()
        heading_pattern = re.compile(r"^\s*((?:\d+\.)+\d+)\s+(.{2,80}?)\s*$")
        headings: list[tuple[int, str, str]] = []
        for idx, line in enumerate(lines):
            match = heading_pattern.match(line)
            if not match:
                continue
            title = re.sub(r"\s+", "", match.group(2))
            if title:
                headings.append((idx, match.group(1), title))

        window_size = 8
        for start in range(0, max(0, len(headings) - window_size + 1)):
            window = headings[start : start + window_size]
            unique_titles = {title for _idx, _number, title in window}
            span = window[-1][0] - window[0][0] + 1
            if len(unique_titles) <= 3 and span <= window_size * 4:
                trim_at = window[0][0]
                return "\n".join(lines[:trim_at]).rstrip()
        return text

    def sanitize_markdown_content(self, text: str) -> str:
        text = self.collapse_repeated_units(text, max_repeats=1)
        text = self.collapse_repeated_lines(text)
        text = self.trim_repetitive_numbered_headings(text)
        return text.replace("\n\n\n\n", "\n\n").replace("\n\n\n", "\n\n")

    def is_usable_incomplete_content(self, text: str) -> bool:
        return self.content_quality_score(text) >= PAGE_RECOVERY_MIN_SCORE

    def content_quality_score(self, text: str) -> int:
        normalized = re.sub(r"\s+", "", text)
        if len(normalized) < INCOMPLETE_PAGE_MIN_CHARS:
            return 0
        lines = [re.sub(r"\s+", "", line) for line in text.splitlines() if line.strip()]
        informative_lines = [line for line in lines if len(line) >= 8]
        unique_ratio = len(set(lines)) / max(1, len(lines))
        signal_ratio = (
            len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", normalized)) / max(1, len(normalized))
        )
        score = 0
        if len(normalized) >= 40:
            score += 2
        elif len(normalized) >= INCOMPLETE_PAGE_MIN_CHARS:
            score += 1
        if len(informative_lines) >= 2:
            score += 1
        if unique_ratio >= 0.6:
            score += 1
        if signal_ratio >= 0.5:
            score += 1
        return score

    def detect_graphic_region(self, image: Image.Image) -> tuple[Image.Image, dict[str, float]] | None:
        if cv2 is None:
            return None
        gray = image.convert("L")
        original_width, original_height = gray.size
        scale = min(1.0, 1200 / max(original_width, original_height))
        work_size = (max(1, int(original_width * scale)), max(1, int(original_height * scale)))
        work = gray.resize(work_size)
        pixels = np.asarray(work)
        binary = (pixels < 200).astype("uint8") * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 15))
        dilated = cv2.dilate(binary, kernel, iterations=1)
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(dilated, 8)
        best: tuple[int, int, int, int] | None = None
        best_area = 0
        work_width, work_height = work_size
        for idx in range(1, count):
            x, y, width, height, area = [int(value) for value in stats[idx]]
            bbox_area = width * height
            if bbox_area <= best_area:
                continue
            if width < work_width * 0.18 or height < work_height * 0.08:
                continue
            if width > work_width * 0.95 or height > work_height * 0.55:
                continue
            fill_ratio = area / bbox_area
            if fill_ratio > 0.7:
                continue
            best = (x, y, width, height)
            best_area = bbox_area
        if best is None:
            return None
        x, y, width, height = best
        inv_scale = 1 / scale
        pad_x = int(width * inv_scale * 0.04)
        pad_y = int(height * inv_scale * 0.06)
        x1 = max(0, int(x * inv_scale) - pad_x)
        y1 = max(0, int(y * inv_scale) - pad_y)
        x2 = min(original_width, int((x + width) * inv_scale) + pad_x)
        y2 = min(original_height, int((y + height) * inv_scale) + pad_y)
        crop = image.crop((x1, y1, x2, y2))
        if not self.is_informative_crop(crop):
            return None
        bbox = {
            "x": x1 / original_width,
            "y": y1 / original_height,
            "width": (x2 - x1) / original_width,
            "height": (y2 - y1) / original_height,
        }
        return crop, bbox

    def maybe_extract_graphic_fallback(
        self,
        image: Image.Image,
        page_no: int,
        content: str,
        output_dir: str,
        start_idx: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if "![](images/" in content or "图" not in content:
            return [], []
        detected = self.detect_graphic_region(image)
        if detected is None:
            return [], []
        crop, bbox = detected
        name = f"{page_no}_{start_idx}.jpg"
        crop.save(Path(output_dir) / name, quality=95)
        return [{"name": name, "page_no": page_no + 1, "bbox": bbox}], [name]

    def insert_image_links(self, content: str, image_names: list[str]) -> str:
        if not image_names:
            return content
        links = [f"![](images/{name})" for name in image_names]
        lines = content.splitlines()
        insert_at = 0
        for idx, line in enumerate(lines):
            if "图" in line:
                insert_at = idx
                break
        for link in reversed(links):
            lines.insert(insert_at, link)
        return "\n".join(lines)

    def extract_coordinates_and_label(self, ref_text: Any) -> tuple[str, list[Any]] | None:
        try:
            label_type = str(ref_text[1])
            cor_list = ast.literal_eval(ref_text[2])
        except Exception:
            return None
        return label_type, cor_list

    def normalize_bbox(
        self,
        points: Any,
        image_width: int,
        image_height: int,
        *,
        padding_ratio: float = 0.0,
    ) -> tuple[tuple[int, int, int, int], dict[str, float]] | None:
        try:
            x1_raw, y1_raw, x2_raw, y2_raw = [float(value) for value in points]
        except (TypeError, ValueError):
            return None
        x1_raw, x2_raw = sorted((max(0.0, min(999.0, x1_raw)), max(0.0, min(999.0, x2_raw))))
        y1_raw, y2_raw = sorted((max(0.0, min(999.0, y1_raw)), max(0.0, min(999.0, y2_raw))))
        x1 = int(x1_raw / 999 * image_width)
        y1 = int(y1_raw / 999 * image_height)
        x2 = int(x2_raw / 999 * image_width)
        y2 = int(y2_raw / 999 * image_height)
        if x2 <= x1 or y2 <= y1:
            return None
        if padding_ratio > 0:
            pad_x = max(1, int((x2 - x1) * padding_ratio))
            pad_y = max(1, int((y2 - y1) * padding_ratio))
            x1 = max(0, x1 - pad_x)
            y1 = max(0, y1 - pad_y)
            x2 = min(image_width, x2 + pad_x)
            y2 = min(image_height, y2 + pad_y)
        bbox = {
            "x": x1 / image_width,
            "y": y1 / image_height,
            "width": (x2 - x1) / image_width,
            "height": (y2 - y1) / image_height,
        }
        return (x1, y1, x2, y2), bbox

    def is_informative_crop(self, image: Image.Image) -> bool:
        width, height = image.size
        if width < IMAGE_CROP_MIN_WIDTH or height < IMAGE_CROP_MIN_HEIGHT:
            return False
        gray = image.convert("L")
        pixels = np.asarray(gray)
        ink_ratio = float(np.mean(pixels < 245))
        return ink_ratio >= IMAGE_CROP_MIN_INK_RATIO

    def draw_bounding_boxes(
        self,
        image: Image.Image,
        refs: list[Any],
        page_no: int,
        output_dir: str,
    ) -> tuple[Image.Image, list[dict[str, Any]], list[tuple[str, str | None]]]:
        image_width, image_height = image.size
        img_draw = image.copy()
        draw = ImageDraw.Draw(img_draw)
        overlay = Image.new("RGBA", img_draw.size, (0, 0, 0, 0))
        draw2 = ImageDraw.Draw(overlay)
        font = ImageFont.load_default()
        _ = font
        img_idx = 0
        image_assets: list[dict[str, Any]] = []
        image_replacements: list[tuple[str, str | None]] = []
        for ref in refs:
            result = self.extract_coordinates_and_label(ref)
            if result is None:
                continue
            label_type, points_list = result
            color = (
                int(np.random.randint(0, 200)),
                int(np.random.randint(0, 200)),
                int(np.random.randint(0, 255)),
            )
            color_a = color + (20,)
            for points in points_list:
                normalized = self.normalize_bbox(
                    points,
                    image_width,
                    image_height,
                    padding_ratio=IMAGE_CROP_PADDING_RATIO if label_type == "image" else 0.0,
                )
                if normalized is None:
                    continue
                (x1, y1, x2, y2), bbox = normalized
                if label_type == "image":
                    cropped = image.crop((x1, y1, x2, y2))
                    name = None
                    if self.is_informative_crop(cropped):
                        name = f"{page_no}_{img_idx}.jpg"
                        img_path = Path(output_dir) / name
                        cropped.save(img_path, quality=95)
                        image_assets.append({"name": name, "page_no": page_no + 1, "bbox": bbox})
                        img_idx += 1
                    image_replacements.append((ref[0], name))
                try:
                    width = 4 if label_type == "title" else 2
                    draw.rectangle([x1, y1, x2, y2], outline=color, width=width)
                    draw2.rectangle(
                        [x1, y1, x2, y2],
                        fill=color_a,
                        outline=(0, 0, 0, 0),
                        width=1,
                    )
                except Exception:
                    continue
        img_draw.paste(overlay, (0, 0), overlay)
        return img_draw, image_assets, image_replacements

    def process_single_image(self, image: Image.Image) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "multi_modal_data": {
                "image": DeepseekOCR2Processor().tokenize_with_images(
                    images=[image],
                    bos=True,
                    eos=True,
                    cropping=CROP_MODE,
                )
            },
        }

    def run_single_page_ocr(self, image: Image.Image) -> tuple[str, bool]:
        output = llm.generate([self.process_single_image(image)], sampling_params=sampling_params)[0]
        content = output.outputs[0].text
        is_finished = EOS_TOKEN in content
        if is_finished:
            content = content.replace(EOS_TOKEN, "")
        return content, is_finished

    def cleanup_generated_content(
        self,
        content: str,
        *,
        matches_images: list[str] | None = None,
        matches_other: list[str] | None = None,
        fallback_image_names: list[str] | None = None,
    ) -> str:
        if matches_images is None or matches_other is None:
            _matches_ref, matches_images, matches_other = self.re_match(content)
        for match_image in matches_images:
            content = content.replace(match_image, "")
        for match_other in matches_other:
            content = content.replace(match_other, "")
        content = content.replace("\\coloneqq", ":=")
        content = content.replace("\\eqqcolon", "=:")
        content = self.strip_grounding_fragments(content)
        content = self.insert_image_links(content, fallback_image_names or [])
        return self.sanitize_markdown_content(content)

    def split_page_for_recovery(
        self,
        image: Image.Image,
        *,
        segments: int,
        overlap_ratio: float = PAGE_RECOVERY_OVERLAP_RATIO,
    ) -> list[Image.Image]:
        width, height = image.size
        if segments <= 1 or height < IMAGE_CROP_MIN_HEIGHT * 2:
            return [image]
        overlap = max(16, int(height * overlap_ratio / max(1, segments)))
        page_segments: list[Image.Image] = []
        for idx in range(segments):
            start_y = 0 if idx == 0 else max(0, int(height * idx / segments) - overlap)
            end_y = (
                height
                if idx == segments - 1
                else min(height, int(height * (idx + 1) / segments) + overlap)
            )
            page_segments.append(image.crop((0, start_y, width, end_y)))
        return page_segments

    def recover_incomplete_page(self, image: Image.Image, page_no: int) -> tuple[str, int, int]:
        segment_count = max(2, PAGE_RECOVERY_SEGMENTS)
        max_failed_segments = max(0, PAGE_RECOVERY_MAX_FAILED_SEGMENTS)
        segments = self.split_page_for_recovery(image, segments=segment_count)
        recovered_parts: list[str] = []
        completed_segments = 0
        failed_segments = 0
        for segment_idx, segment in enumerate(segments):
            segment_content, segment_finished = self.run_single_page_ocr(segment)
            if not segment_finished:
                failed_segments += 1
                print(
                    f"Retry segment {page_no + 1}.{segment_idx + 1}: OCR generation still reached max tokens without EOS.",
                    flush=True,
                )
            cleaned_segment = self.cleanup_generated_content(segment_content)
            if cleaned_segment.strip():
                recovered_parts.append(cleaned_segment)
            if segment_finished:
                completed_segments += 1
            elif failed_segments >= max_failed_segments:
                print(
                    f"Stopping segmented retry for page {page_no + 1}: {failed_segments} segment(s) still hit max tokens.",
                    flush=True,
                )
                break
        recovered = self.sanitize_markdown_content("\n\n".join(recovered_parts))
        return recovered, completed_segments, len(segments)

    def pil_to_pdf_img2pdf(self, pil_images: list[Image.Image], output_path: str) -> None:
        if not pil_images:
            return
        image_bytes_list = []
        for img in pil_images:
            if img.mode != "RGB":
                img = img.convert("RGB")
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="JPEG", quality=95)
            image_bytes_list.append(img_buffer.getvalue())
        pdf_bytes = img2pdf.convert(image_bytes_list)
        Path(output_path).write_bytes(pdf_bytes)

    async def process_pdf_async(
        self,
        pdf_path: str,
        output_dir: str,
        *,
        timeout_seconds: int = GENERATE_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        async with self.gpu_lock:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self.process_pdf, pdf_path, output_dir),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                self.release_cuda_cache()
                raise
            except Exception:
                self.release_cuda_cache()
                raise

    def process_pdf(self, pdf_path: str, output_dir: str) -> dict[str, Any]:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        images_dir = Path(output_dir) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        page_images = list(self.iter_pdf_images(pdf_path))
        images = [image for _page_no, image in page_images]
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            batch_inputs = list(
                tqdm(
                    executor.map(self.process_single_image, images),
                    total=len(images),
                    desc="Pre-processed images",
                )
            )
        outputs_list = llm.generate(batch_inputs, sampling_params=sampling_params)
        contents_det = ""
        contents = ""
        draw_images: list[Image.Image] = []
        assets: list[dict[str, Any]] = []
        recovered_pages = 0
        recovery_attempted_pages = 0
        preserved_low_confidence_pages = 0
        skipped_pages = 0
        for (page_no, img), output in zip(page_images, outputs_list, strict=True):
            content = output.outputs[0].text
            is_finished = EOS_TOKEN in content
            if is_finished:
                content = content.replace(EOS_TOKEN, "")
            elif SKIP_REPEAT:
                print(
                    f"Sanitizing page {page_no + 1}: OCR generation reached max tokens without EOS.",
                    flush=True,
                )
            page_split = "\n<--- Page Split --->"
            contents_det += content + f"\n{page_split}\n"
            matches_ref, matches_images, matches_other = self.re_match(content)
            result_image, page_assets, image_replacements = self.draw_bounding_boxes(
                img.copy(),
                matches_ref,
                page_no,
                str(images_dir),
            )
            draw_images.append(result_image)
            assets.extend(page_assets)
            fallback_assets, fallback_image_names = self.maybe_extract_graphic_fallback(
                img,
                page_no,
                content,
                str(images_dir),
                len(page_assets),
            )
            assets.extend(fallback_assets)
            for match_image, image_name in image_replacements:
                replacement = f"![](images/{image_name})\n" if image_name else ""
                content = content.replace(match_image, replacement, 1)
            content = self.cleanup_generated_content(
                content,
                matches_images=matches_images,
                matches_other=matches_other,
                fallback_image_names=fallback_image_names,
            )
            if not is_finished and SKIP_REPEAT:
                original_score = self.content_quality_score(content)
                if original_score >= PAGE_RECOVERY_MIN_SCORE:
                    preserved_low_confidence_pages += 1
                    print(
                        f"Preserving page {page_no + 1}: incomplete OCR content is usable; segmented retry skipped.",
                        flush=True,
                    )
                else:
                    recovery_allowed = PAGE_RECOVERY_ENABLED and recovery_attempted_pages < max(
                        0, PAGE_RECOVERY_MAX_PAGES
                    )
                    if recovery_allowed:
                        recovery_attempted_pages += 1
                        (
                            recovered_content,
                            completed_segments,
                            total_segments,
                        ) = self.recover_incomplete_page(img, page_no)
                        recovered_score = self.content_quality_score(recovered_content)
                        if recovered_content and (
                            recovered_score > original_score
                            or len(re.sub(r"\s+", "", recovered_content))
                            > len(re.sub(r"\s+", "", content))
                        ):
                            content = recovered_content
                            original_score = recovered_score
                            recovered_pages += 1
                            print(
                                f"Recovered page {page_no + 1} with segmented retry ({completed_segments}/{total_segments} segments finished).",
                                flush=True,
                            )
                    else:
                        print(
                            f"Skipping segmented retry for page {page_no + 1}: recovery budget exhausted or disabled.",
                            flush=True,
                        )
                if original_score < PAGE_RECOVERY_MIN_SCORE:
                    normalized = re.sub(r"\s+", "", content)
                    if len(normalized) < INCOMPLETE_PAGE_MIN_CHARS:
                        print(
                            f"Skipping page {page_no + 1}: OCR content is still too short after cleanup/recovery.",
                            flush=True,
                        )
                        skipped_pages += 1
                        continue
                    preserved_low_confidence_pages += 1
                    print(
                        f"Preserving page {page_no + 1}: keeping incomplete OCR content with low confidence.",
                        flush=True,
                    )
            contents += content + f"\n{page_split}\n"
        mmd_path = Path(output_dir) / "result.md"
        mmd_det_path = Path(output_dir) / "result_det.md"
        pdf_out_path = Path(output_dir) / "result_layout.pdf"
        mmd_det_path.write_text(contents_det, encoding="utf-8")
        mmd_path.write_text(contents, encoding="utf-8")
        self.pil_to_pdf_img2pdf(draw_images, str(pdf_out_path))
        return {
            "markdown": contents,
            "markdown_det": contents_det,
            "images": [asset["name"] for asset in assets],
            "assets": assets,
            "page_count": len(page_images),
            "recovered_pages": recovered_pages,
            "preserved_low_confidence_pages": preserved_low_confidence_pages,
            "skipped_pages": skipped_pages,
            "output_dir": output_dir,
        }

    def release_cuda_cache(self) -> None:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
