#!/bin/bash
set -euo pipefail

RUN_DIR="/tmp/glm_ocr_api"
API_PORT="${API_PORT:-8899}"
VLLM_PORT="${GLM_VLLM_PORT:-18080}"

stop_pid_file() {
  local file="$1"
  local label="$2"
  if [[ -f "${file}" ]]; then
    local pid
    pid="$(cat "${file}")"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
      echo "Stopping ${label} PID ${pid}"
      local pgid
      pgid="$(ps -o pgid= -p "${pid}" 2>/dev/null | tr -d ' ' || true)"
      if [[ -n "${pgid}" ]]; then
        kill -- "-${pgid}" || true
      else
        kill "${pid}" || true
      fi
    fi
    rm -f "${file}"
  fi
}

stop_port() {
  local port="$1"
  local label="$2"
  local pids
  pids="$(lsof -t -i:"${port}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping ${label} process(es) on port ${port}: ${pids}"
    kill ${pids} || true
  fi
}

stop_pid_file "${RUN_DIR}/api.pid" "GLM-OCR API"
stop_pid_file "${RUN_DIR}/vllm.pid" "GLM-OCR vLLM"
sleep 2
stop_port "${API_PORT}" "GLM-OCR API"
stop_port "${VLLM_PORT}" "GLM-OCR vLLM"

echo "GLM-OCR service stopped."
