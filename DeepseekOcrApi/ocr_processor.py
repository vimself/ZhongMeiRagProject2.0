from __future__ import annotations

import asyncio
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
    MAX_CONCURRENCY,
    MODEL_PATH,
    NUM_WORKERS,
    PROMPT,
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
        ngram_size=20,
        window_size=50,
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


class PDFOCRProcessor:
    def __init__(self) -> None:
        self.prompt = PROMPT
        self.gpu_lock = asyncio.Lock()

    def iter_pdf_images(self, pdf_path: str, dpi: int = 144) -> Any:
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

    def extract_coordinates_and_label(self, ref_text: Any) -> tuple[str, list[Any]] | None:
        try:
            label_type = str(ref_text[1])
            cor_list = eval(ref_text[2], {"__builtins__": {}})
        except Exception:
            return None
        return label_type, cor_list

    def draw_bounding_boxes(
        self,
        image: Image.Image,
        refs: list[Any],
        page_no: int,
        output_dir: str,
    ) -> tuple[Image.Image, list[dict[str, Any]]]:
        image_width, image_height = image.size
        img_draw = image.copy()
        draw = ImageDraw.Draw(img_draw)
        overlay = Image.new("RGBA", img_draw.size, (0, 0, 0, 0))
        draw2 = ImageDraw.Draw(overlay)
        font = ImageFont.load_default()
        _ = font
        img_idx = 0
        image_assets: list[dict[str, Any]] = []
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
                x1, y1, x2, y2 = points
                x1 = int(x1 / 999 * image_width)
                y1 = int(y1 / 999 * image_height)
                x2 = int(x2 / 999 * image_width)
                y2 = int(y2 / 999 * image_height)
                bbox = {
                    "x": x1 / image_width,
                    "y": y1 / image_height,
                    "width": (x2 - x1) / image_width,
                    "height": (y2 - y1) / image_height,
                }
                if label_type == "image":
                    cropped = image.crop((x1, y1, x2, y2))
                    name = f"{page_no}_{img_idx}.jpg"
                    img_path = Path(output_dir) / name
                    cropped.save(img_path)
                    image_assets.append({"name": name, "page_no": page_no + 1, "bbox": bbox})
                    img_idx += 1
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
        return img_draw, image_assets

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
        for (page_no, img), output in zip(page_images, outputs_list, strict=True):
            content = output.outputs[0].text
            if "<｜end▁of▁sentence｜>" in content:
                content = content.replace("<｜end▁of▁sentence｜>", "")
            elif SKIP_REPEAT:
                continue
            page_split = "\n<--- Page Split --->"
            contents_det += content + f"\n{page_split}\n"
            matches_ref, matches_images, matches_other = self.re_match(content)
            result_image, page_assets = self.draw_bounding_boxes(
                img.copy(),
                matches_ref,
                page_no,
                str(images_dir),
            )
            draw_images.append(result_image)
            assets.extend(page_assets)
            for idx, match_image in enumerate(matches_images):
                content = content.replace(match_image, f"![](images/{page_no}_{idx}.jpg)\n")
            for match_other in matches_other:
                content = content.replace(match_other, "")
                content = content.replace("\\coloneqq", ":=")
                content = content.replace("\\eqqcolon", "=:")
            content = content.replace("\n\n\n\n", "\n\n").replace("\n\n\n", "\n\n")
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
            "output_dir": output_dir,
        }

    def release_cuda_cache(self) -> None:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
