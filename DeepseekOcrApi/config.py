import os

BASE_SIZE = 1024
IMAGE_SIZE = 768
CROP_MODE = True
MIN_CROPS = 2
MAX_CROPS = 6
MAX_CONCURRENCY = 100
NUM_WORKERS = 64
PRINT_NUM_VIS_TOKENS = False
SKIP_REPEAT = True
MODEL_PATH = '/media/ubuntu/f96afdb3-35e3-4b0e-811f-0568e7f7bd2a/home/ubuntu/ragproject/deepseek-ocr/model2'

PROMPT = '<image>\n<|grounding|>Convert the document to markdown.'

TEMP_DIR = '/tmp/deepseek_ocr_uploads'
MAX_FILE_SIZE = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {'pdf'}

API_HOST = '0.0.0.0'
API_PORT = 8899
API_WORKERS = 4

GPU_MEMORY_UTILIZATION = 0.6

from transformers import AutoTokenizer

TOKENIZER = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
