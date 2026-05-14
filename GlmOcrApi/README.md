# GLM-OCR API 服务

这是给 ZhongMei RAG 项目替换 DeepSeek-OCR API 的自托管 GLM-OCR 服务。外部 HTTP 协议保持兼容原 `DeepseekOcrApi`：RAG 后端仍可按上传、轮询、取 Markdown、取图片资产的方式调用；内部改为官方 `glmocr` self-hosted pipeline，经 vLLM OpenAI 兼容接口调用本地 `/home/ubuntu/jiang/glm-ocr` 模型。

官方 self-hosted pipeline 负责：

- PDF 渲染为页面图像
- PP-DocLayoutV3 版面检测
- 按版面区域并发识别文本、表格、公式
- 生成 Markdown、JSON 版面信息和图片裁剪集

## 启动

```bash
cd /home/ubuntu/jiang/ragproject3/GlmOcrApi
pip install -r requirements.txt
bash start.sh
```

默认端口：

- GLM-OCR vLLM：`127.0.0.1:18080`
- 兼容 OCR API：`0.0.0.0:8899`

## 关键环境变量

- `GLM_MODEL_PATH`：默认 `/home/ubuntu/jiang/glm-ocr`
- `GLM_MODEL_NAME`：默认 `glm-ocr`，需与 vLLM `--served-model-name` 一致
- `GLM_VLLM_PORT`：默认 `18080`，避免和 RAG 前端 nginx 默认 `8080` 冲突
- `API_PORT`：默认 `8899`
- `GLM_LAYOUT_DEVICE`：默认 `cpu`，单 GPU 时避免和 vLLM 抢显存；多 GPU 可设为 `cuda:1`
- `GLM_LAYOUT_MODEL_DIR`：默认 `PaddlePaddle/PP-DocLayoutV3_safetensors`
- `GLM_MAX_WORKERS`：区域 OCR 并发，默认 `1`；批量入库优先稳定性，确认 GPU 余量后再调大
- `GLM_PDF_DPI`：PDF 渲染 DPI，默认 `200`
- `GLM_VLLM_LIMIT_MM_PER_PROMPT`：默认 `{"image":4}`，用于提高 vLLM 多模态 encoder cache 上限，避免大页面图片 token 超过默认缓存
- `GLM_VLLM_MAX_NUM_BATCHED_TOKENS`：默认 `16384`，直接决定 vLLM 多模态 encoder cache 的基础上限
- `GLM_VLLM_MAX_NUM_SEQS`：默认 `1`，批量入库时限制 vLLM 同时处理的请求数
- `GLM_VLLM_DISABLE_LOG_REQUESTS`：默认 `1`，关闭 vLLM 请求详情和 uvicorn access log
- `GLM_VLLM_DISABLE_LOG_STATS`：默认 `1`，关闭 vLLM 周期 stats log
- `VLLM_LOGGING_LEVEL`：默认 `WARNING`，只保留 vLLM warning/error 等关键日志
- `API_LOG_LEVEL`：默认 `info`，保留 OCR 任务级关键日志
- `API_ACCESS_LOG`：默认 `0`，关闭 API 高频 access log；调试 HTTP 请求时可设为 `1`
- `GLM_VLLM_MAX_MODEL_LEN`：默认 `32768`
- `GLM_VLLM_GPU_MEMORY_UTILIZATION`：默认 `0.78`
- `GLM_PRELOAD_PIPELINE`：默认 `false`，设为 `true` 时 API 启动后预加载 layout pipeline
- `TEMP_DIR`：默认 `/tmp/glm_ocr_uploads`
- `DEFAULT_CALLBACK_URL`：默认 `http://127.0.0.1:18000/api/v2/ocr/callback`

## API

兼容原服务：

- `GET /healthz`
- `GET /readyz`
- `GET /queue`
- `POST /upload`
- `GET /status/{session_id}`
- `GET /result/{session_id}/markdown`
- `GET /result/{session_id}/markdown?include_meta=true`
- `GET /result/{session_id}/assets`
- `GET /result/{session_id}/images/base64`
- `GET /result/{session_id}/images/list`
- `GET /result/{session_id}/image/{image_name}`
- `GET /result/{session_id}`
- `DELETE /session/{session_id}`

新增：

- `GET /result/{session_id}/json`
- `GET /result/{session_id}/layout`

`/result/{session_id}/assets` 会返回图片、表格、公式和 JSON 版面结果入口。

## 测试案例

```bash
curl -F "file=@/home/ubuntu/jiang/ocrtest/DB32T 4077.1-2021  矿山生态修复工程技术规程1+通则.pdf" \
  http://127.0.0.1:8899/upload
```

轮询 `/status/{session_id}` 到 `completed` 后：

```bash
curl "http://127.0.0.1:8899/result/${session_id}/markdown?include_meta=true" \
  -o /home/ubuntu/jiang/ocrtest/output/glm_result.json
curl "http://127.0.0.1:8899/result/${session_id}" \
  -o /home/ubuntu/jiang/ocrtest/output/glm_result.zip
```
