#!/bin/bash

cd /media/ubuntu/f96afdb3-35e3-4b0e-811f-0568e7f7bd2a/home/ubuntu/ragproject/deepseek-ocr/DeepSeek-code2/DeepSeek-OCR-2-main/DeepSeek-OCR2-master/DeepSeek-OCR2-vllm

export PYTHONPATH="/media/ubuntu/f96afdb3-35e3-4b0e-811f-0568e7f7bd2a/home/ubuntu/ragproject/deepseek-ocr/DeepSeek-code2/DeepSeek-OCR-2-main/DeepSeek-OCR2-master/DeepSeek-OCR2-vllm:$PYTHONPATH"

cd /media/ubuntu/f96afdb3-35e3-4b0e-811f-0568e7f7bd2a/home/ubuntu/ragproject/deepseek-ocr/DeepSeek-code2/api

python3 -m uvicorn app:app --host 0.0.0.0 --port 8899 --workers 1
