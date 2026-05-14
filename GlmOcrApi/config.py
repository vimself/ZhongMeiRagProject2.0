from __future__ import annotations

import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return int(value)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODEL_PATH = os.getenv("GLM_MODEL_PATH", "/home/ubuntu/jiang/glm-ocr")
MODEL_NAME = os.getenv("GLM_MODEL_NAME", "glm-ocr")

VLLM_HOST = os.getenv("GLM_VLLM_HOST", "127.0.0.1")
VLLM_PORT = int(os.getenv("GLM_VLLM_PORT", "18080"))
VLLM_BASE_URL = os.getenv("GLM_VLLM_BASE_URL", f"http://{VLLM_HOST}:{VLLM_PORT}")
VLLM_STARTUP_TIMEOUT_SECONDS = int(os.getenv("GLM_VLLM_STARTUP_TIMEOUT_SECONDS", "900"))
VLLM_GPU_MEMORY_UTILIZATION = os.getenv("GLM_VLLM_GPU_MEMORY_UTILIZATION", "0.78")
VLLM_MAX_MODEL_LEN = os.getenv("GLM_VLLM_MAX_MODEL_LEN", "32768")
VLLM_ALLOWED_LOCAL_MEDIA_PATH = os.getenv("GLM_VLLM_ALLOWED_LOCAL_MEDIA_PATH", "/")
VLLM_LIMIT_MM_PER_PROMPT = os.getenv("GLM_VLLM_LIMIT_MM_PER_PROMPT", '{"image":4}')
VLLM_SPECULATIVE_CONFIG = os.getenv(
    "GLM_VLLM_SPECULATIVE_CONFIG",
    '{"method":"mtp","num_speculative_tokens":3}',
)

LAYOUT_MODEL_DIR = os.getenv("GLM_LAYOUT_MODEL_DIR", "PaddlePaddle/PP-DocLayoutV3_safetensors")
LAYOUT_DEVICE = os.getenv("GLM_LAYOUT_DEVICE", "cpu")
LAYOUT_BATCH_SIZE = int(os.getenv("GLM_LAYOUT_BATCH_SIZE", "1"))
LAYOUT_USE_POLYGON = _bool("GLM_LAYOUT_USE_POLYGON", False)

PDF_RENDER_DPI = int(os.getenv("GLM_PDF_DPI", "200"))
PDF_MAX_PAGES = _optional_int("GLM_PDF_MAX_PAGES")
GLM_MAX_WORKERS = int(os.getenv("GLM_MAX_WORKERS", "1"))
GLM_REGION_QUEUE_SIZE = int(os.getenv("GLM_REGION_QUEUE_SIZE", "1200"))
GLM_PAGE_QUEUE_SIZE = int(os.getenv("GLM_PAGE_QUEUE_SIZE", "80"))
GLM_MAX_TOKENS = int(os.getenv("GLM_MAX_TOKENS", "8192"))
GLM_REQUEST_TIMEOUT_SECONDS = int(os.getenv("GLM_REQUEST_TIMEOUT_SECONDS", "180"))
GLM_CONNECT_TIMEOUT_SECONDS = int(os.getenv("GLM_CONNECT_TIMEOUT_SECONDS", "60"))
GLM_LOG_LEVEL = os.getenv("GLM_LOG_LEVEL", "WARNING")
GLM_SAVE_LAYOUT_VIS = _bool("GLM_SAVE_LAYOUT_VIS", True)
GLM_PRELOAD_PIPELINE = _bool("GLM_PRELOAD_PIPELINE", False)

TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/glm_ocr_uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(200 * 1024 * 1024)))
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8899"))
QUEUE_SIZE = int(os.getenv("QUEUE_SIZE", "16"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(24 * 3600)))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", str(30 * 60)))
GENERATE_TIMEOUT_SECONDS = int(os.getenv("GENERATE_TIMEOUT_SECONDS", str(80 * 60)))

API_TOKEN = os.getenv("API_TOKEN", "")
DEFAULT_CALLBACK_URL = os.getenv(
    "DEFAULT_CALLBACK_URL",
    "http://127.0.0.1:18000/api/v2/ocr/callback",
)
OCR_CALLBACK_TOKEN = os.getenv("OCR_CALLBACK_TOKEN", "")
CALLBACK_TIMEOUT_SECONDS = float(os.getenv("CALLBACK_TIMEOUT_SECONDS", "10"))
CORS_ALLOW_ORIGINS = [
    item.strip() for item in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if item.strip()
]
