from __future__ import annotations

import os

BASE_SIZE = int(os.getenv("OCR_BASE_SIZE", "1024"))
IMAGE_SIZE = int(os.getenv("OCR_IMAGE_SIZE", "768"))
CROP_MODE = os.getenv("OCR_CROP_MODE", "true").lower() not in {"0", "false", "no", "off"}
MIN_CROPS = int(os.getenv("OCR_MIN_CROPS", "2"))
MAX_CROPS = int(os.getenv("OCR_MAX_CROPS", "6"))
PDF_RENDER_DPI = int(os.getenv("OCR_PDF_DPI", "300"))
IMAGE_CROP_MIN_WIDTH = int(os.getenv("OCR_IMAGE_CROP_MIN_WIDTH", "80"))
IMAGE_CROP_MIN_HEIGHT = int(os.getenv("OCR_IMAGE_CROP_MIN_HEIGHT", "80"))
IMAGE_CROP_MIN_INK_RATIO = float(os.getenv("OCR_IMAGE_CROP_MIN_INK_RATIO", "0.001"))
IMAGE_CROP_PADDING_RATIO = float(os.getenv("OCR_IMAGE_CROP_PADDING_RATIO", "0.02"))
REPEAT_NGRAM_SIZE = int(os.getenv("OCR_REPEAT_NGRAM_SIZE", "20"))
REPEAT_WINDOW_SIZE = int(os.getenv("OCR_REPEAT_WINDOW_SIZE", "50"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "16"))
NUM_WORKERS = int(os.getenv("NUM_WORKERS", "8"))
PRINT_NUM_VIS_TOKENS = False
SKIP_REPEAT = True
MODEL_PATH = os.getenv(
    "MODEL_PATH",
    "/home/ubuntu/jiang/ragproject/deepseek-ocr/model2",
)

PROMPT = os.getenv(
    "OCR_PROMPT",
    "<image>\n<|grounding|>Convert the document to markdown.",
)

TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/deepseek_ocr_uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(200 * 1024 * 1024)))
ALLOWED_EXTENSIONS = {"pdf"}

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8899"))
API_WORKERS = int(os.getenv("API_WORKERS", "1"))
QUEUE_SIZE = int(os.getenv("QUEUE_SIZE", "16"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(24 * 3600)))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", str(30 * 60)))
GENERATE_TIMEOUT_SECONDS = int(os.getenv("GENERATE_TIMEOUT_SECONDS", str(50 * 60)))
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

GPU_MEMORY_UTILIZATION = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.8"))

try:
    from transformers import AutoTokenizer

    TOKENIZER = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
except Exception:
    TOKENIZER = None
