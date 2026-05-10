#!/bin/bash
set -euo pipefail

CODE_ROOT="/home/ubuntu/jiang/ragproject/deepseek-ocr/DeepSeek-code2/DeepSeek-OCR-2-main/DeepSeek-OCR2-master/DeepSeek-OCR2-vllm"
API_ROOT="/home/ubuntu/jiang/ragproject/deepseek-ocr/DeepSeek-code2/DeepseekOcrApi"
LOG_DIR="/home/ubuntu/jiang/ragproject/deepseek-ocr/log"
LOG_FILE="${LOG_DIR}/api-$(date +%Y%m%d-%H%M%S).log"

mkdir -p "${LOG_DIR}"

echo "DeepSeek OCR API starting..."
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi
else
  echo "nvidia-smi not found"
fi

export PYTHONPATH="${CODE_ROOT}:${PYTHONPATH:-}"
cd "${API_ROOT}"

# 1. 激活 conda 环境（确保依赖库版本正确）
source /home/ubuntu/anaconda3/etc/profile.d/conda.sh
conda activate deepseek-ocr

# 2. 使用 nohup 和 & 将服务放入后台运行
# 日志重定向到文件，标准错误合并到标准输出
nohup python -m uvicorn app:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8899}" --workers 1 >> "${LOG_FILE}" 2>&1 &

PID=$!
echo "✅ DeepSeek OCR API started in background."
echo "🆔 Process ID (PID): $PID"
echo "📄 Log file: ${LOG_FILE}"
echo "🔗 API URL: http://localhost:8899"