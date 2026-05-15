#!/bin/bash
set -euo pipefail

API_ROOT="/home/ubuntu/jiang/ragproject3/GlmOcrApi"
LOG_DIR="/home/ubuntu/jiang/ragproject3/ocr_log"
RUN_DIR="/tmp/glm_ocr_api"
MODEL_PATH="${GLM_MODEL_PATH:-/home/ubuntu/jiang/glm-ocr}"
MODEL_NAME="${GLM_MODEL_NAME:-glm-ocr}"
VLLM_HOST="${GLM_VLLM_HOST:-127.0.0.1}"
VLLM_PORT="${GLM_VLLM_PORT:-18080}"
VLLM_LIMIT_MM_PER_PROMPT="${GLM_VLLM_LIMIT_MM_PER_PROMPT:-}"
VLLM_MAX_NUM_BATCHED_TOKENS="${GLM_VLLM_MAX_NUM_BATCHED_TOKENS:-16384}"
VLLM_MAX_NUM_SEQS="${GLM_VLLM_MAX_NUM_SEQS:-1}"
VLLM_ENFORCE_EAGER="${GLM_VLLM_ENFORCE_EAGER:-1}"
VLLM_DISABLE_CUSTOM_ALL_REDUCE="${GLM_VLLM_DISABLE_CUSTOM_ALL_REDUCE:-1}"
VLLM_SPECULATIVE_CONFIG="${GLM_VLLM_SPECULATIVE_CONFIG:-}"
VLLM_DISABLE_LOG_REQUESTS="${GLM_VLLM_DISABLE_LOG_REQUESTS:-1}"
VLLM_DISABLE_LOG_STATS="${GLM_VLLM_DISABLE_LOG_STATS:-1}"
VLLM_LOGGING_LEVEL="${VLLM_LOGGING_LEVEL:-WARNING}"
LOG_FILTER_SCRIPT="${API_ROOT}/log_filter.py"
LOG_FILTER_NCCL_BROKEN_PIPE="${GLM_LOG_FILTER_NCCL_BROKEN_PIPE:-1}"
LOG_FILTER_SUMMARY_INTERVAL_SECONDS="${GLM_LOG_FILTER_SUMMARY_INTERVAL_SECONDS:-600}"
API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8899}"
API_LOG_LEVEL="${API_LOG_LEVEL:-info}"
API_ACCESS_LOG="${API_ACCESS_LOG:-0}"
VLLM_LOG_FILE="${LOG_DIR}/glm-vllm-$(date +%Y%m%d-%H%M%S).log"
API_LOG_FILE="${LOG_DIR}/glm-api-$(date +%Y%m%d-%H%M%S).log"

if [[ -z "${VLLM_LIMIT_MM_PER_PROMPT}" ]]; then
  VLLM_LIMIT_MM_PER_PROMPT='{"image":4}'
fi

mkdir -p "${LOG_DIR}" "${RUN_DIR}"

source /home/ubuntu/anaconda3/etc/profile.d/conda.sh
conda activate glm-ocr
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export GLM_LOG_FILTER_NCCL_BROKEN_PIPE="${LOG_FILTER_NCCL_BROKEN_PIPE}"
export GLM_LOG_FILTER_SUMMARY_INTERVAL_SECONDS="${LOG_FILTER_SUMMARY_INTERVAL_SECONDS}"

echo "GLM-OCR service starting..."
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi
else
  echo "nvidia-smi not found"
fi

is_vllm_ready() {
  python - "$VLLM_HOST" "$VLLM_PORT" <<'PY'
import json
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(f"http://{host}:{port}/v1/models", timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))
    sys.exit(0 if isinstance(payload.get("data"), list) else 1)
except Exception:
    sys.exit(1)
PY
}

start_filtered() {
  local source="$1"
  local log_file="$2"
  shift 2
  setsid nohup bash -c '
    source_name="$1"
    log_file="$2"
    filter_script="$3"
    shift 3
    "$@" 2>&1 | python "${filter_script}" --source "${source_name}" >> "${log_file}"
  ' bash "${source}" "${log_file}" "${LOG_FILTER_SCRIPT}" "$@" >/dev/null 2>&1 &
  echo "$!"
}

if ! is_vllm_ready; then
  export VLLM_LOGGING_LEVEL="${VLLM_LOGGING_LEVEL}"
  VLLM_ARGS=(
    vllm serve "${MODEL_PATH}"
    --host "${VLLM_HOST}"
    --port "${VLLM_PORT}"
    --served-model-name "${MODEL_NAME}"
    --allowed-local-media-path "${GLM_VLLM_ALLOWED_LOCAL_MEDIA_PATH:-/}"
    --gpu-memory-utilization "${GLM_VLLM_GPU_MEMORY_UTILIZATION:-0.78}"
    --max-model-len "${GLM_VLLM_MAX_MODEL_LEN:-32768}"
    --max-num-batched-tokens "${VLLM_MAX_NUM_BATCHED_TOKENS}"
    --max-num-seqs "${VLLM_MAX_NUM_SEQS}"
  )
  if [[ "${VLLM_ENFORCE_EAGER}" == "1" ]]; then
    VLLM_ARGS+=(--enforce-eager)
  fi
  if [[ "${VLLM_DISABLE_CUSTOM_ALL_REDUCE}" == "1" ]]; then
    VLLM_ARGS+=(--disable-custom-all-reduce)
  fi
  if [[ "${VLLM_DISABLE_LOG_REQUESTS}" == "1" ]]; then
    VLLM_ARGS+=(--no-enable-log-requests --disable-uvicorn-access-log)
  fi
  if [[ "${VLLM_DISABLE_LOG_STATS}" == "1" ]]; then
    VLLM_ARGS+=(--disable-log-stats)
  fi
  if [[ -n "${VLLM_LIMIT_MM_PER_PROMPT}" ]]; then
    VLLM_ARGS+=(--limit-mm-per-prompt "${VLLM_LIMIT_MM_PER_PROMPT}")
  fi
  if [[ -n "${VLLM_SPECULATIVE_CONFIG}" ]]; then
    VLLM_ARGS+=(--speculative-config "${VLLM_SPECULATIVE_CONFIG}")
  fi
  echo "vLLM conservative mode: enforce_eager=${VLLM_ENFORCE_EAGER}, disable_custom_all_reduce=${VLLM_DISABLE_CUSTOM_ALL_REDUCE}, speculative_config=${VLLM_SPECULATIVE_CONFIG:-disabled}"
  start_filtered vllm "${VLLM_LOG_FILE}" "${VLLM_ARGS[@]}" > "${RUN_DIR}/vllm.pid"
  echo "vLLM PID: $(cat "${RUN_DIR}/vllm.pid")"
  echo "vLLM log: ${VLLM_LOG_FILE}"
else
  echo "vLLM port ${VLLM_PORT} already has a process; reusing it."
fi

echo "Waiting for vLLM at http://${VLLM_HOST}:${VLLM_PORT}/v1/models ..."
for _ in $(seq 1 "${GLM_VLLM_STARTUP_TIMEOUT_SECONDS:-900}"); do
  if is_vllm_ready; then
    break
  fi
  sleep 1
done
if ! is_vllm_ready; then
  echo "vLLM did not become ready. Check ${VLLM_LOG_FILE}"
  exit 1
fi

if lsof -t -i:"${API_PORT}" >/dev/null 2>&1; then
  echo "API port ${API_PORT} is already in use."
  exit 1
fi

export GLM_MODEL_PATH="${MODEL_PATH}"
export GLM_MODEL_NAME="${MODEL_NAME}"
export GLM_VLLM_HOST="${VLLM_HOST}"
export GLM_VLLM_PORT="${VLLM_PORT}"
export GLM_VLLM_LIMIT_MM_PER_PROMPT="${VLLM_LIMIT_MM_PER_PROMPT}"
export GLM_VLLM_MAX_NUM_BATCHED_TOKENS="${VLLM_MAX_NUM_BATCHED_TOKENS}"
export GLM_VLLM_MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS}"
export API_HOST="${API_HOST}"
export API_PORT="${API_PORT}"

cd "${API_ROOT}"
API_ARGS=(
  python -m uvicorn app:app
  --host "${API_HOST}"
  --port "${API_PORT}"
  --workers 1
  --log-level "${API_LOG_LEVEL}"
)
if [[ "${API_ACCESS_LOG}" != "1" ]]; then
  API_ARGS+=(--no-access-log)
fi
start_filtered api "${API_LOG_FILE}" "${API_ARGS[@]}" > "${RUN_DIR}/api.pid"

echo "GLM-OCR API PID: $(cat "${RUN_DIR}/api.pid")"
echo "API log: ${API_LOG_FILE}"
echo "API URL: http://localhost:${API_PORT}"
