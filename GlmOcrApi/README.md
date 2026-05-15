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
- `GLM_MAX_TOKENS`：单个版面区域生成上限，默认 `2048`，降低长段落进入重复循环的概率
- `GLM_REPETITION_PENALTY`：默认 `1.2`
- `GLM_IMAGE_FORMAT`：官方 pipeline 传给 vLLM 的区域图像格式，默认 `PNG`，优先保留扫描件细节
- `GLM_TEXT_LINE_REPAIR_ENABLED`：默认 `true`，开启 OCR 质量修复
- `GLM_TEXT_LINE_REPAIR_POLICY`：默认 `auto`；可设 `always` 强制多行文本块逐行重识别，或设 `off` 关闭
- `GLM_TEXT_LINE_REPAIR_MAX_LINES`：默认 `36`，单区域行级修复的常规行数上限
- `GLM_TEXT_LINE_REPAIR_MAX_REGIONS_PER_PAGE`：默认 `24`，单页最多修复区域数
- `GLM_TEXT_LINE_REPAIR_MAX_TOKENS`：默认 `192`，单行重识别生成上限
- `GLM_VLLM_LIMIT_MM_PER_PROMPT`：默认 `{"image":4}`，用于提高 vLLM 多模态 encoder cache 上限，避免大页面图片 token 超过默认缓存
- `GLM_VLLM_MAX_NUM_BATCHED_TOKENS`：默认 `16384`，直接决定 vLLM 多模态 encoder cache 的基础上限
- `GLM_VLLM_MAX_NUM_SEQS`：默认 `1`，批量入库时限制 vLLM 同时处理的请求数
- `GLM_VLLM_ENFORCE_EAGER`：默认 `1`，稳定性优先，关闭 CUDA graph/`torch.compile` 相关激进路径；确认运行稳定后再考虑设为 `0`
- `GLM_VLLM_DISABLE_CUSTOM_ALL_REDUCE`：默认 `1`，单机 OCR 服务优先避免额外通信路径；确认多卡收益后再考虑设为 `0`
- `GLM_VLLM_SPECULATIVE_CONFIG`：默认空，即默认关闭 speculative decoding；多模态 OCR 默认不建议开启，确需启用时显式传 JSON，例如 `{"method":"mtp","num_speculative_tokens":3}`
- `GLM_VLLM_DISABLE_LOG_REQUESTS`：默认 `1`，关闭 vLLM 请求详情和 uvicorn access log
- `GLM_VLLM_DISABLE_LOG_STATS`：默认 `1`，关闭 vLLM 周期 stats log
- `VLLM_LOGGING_LEVEL`：默认 `WARNING`，只保留 vLLM warning/error 等关键日志
- `API_LOG_LEVEL`：默认 `info`，保留 OCR 任务级关键日志
- `API_ACCESS_LOG`：默认 `0`，关闭 API 高频 access log；调试 HTTP 请求时可设为 `1`
- `GLM_LOG_FILTER_NCCL_BROKEN_PIPE`：默认 `1`，过滤 PyTorch/NCCL TCPStore 心跳 `Broken pipe` 噪声；排查底层分布式通信时可设为 `0`
- `GLM_LOG_FILTER_SUMMARY_INTERVAL_SECONDS`：默认 `600`，日志过滤器最多每 10 分钟输出一次累计过滤摘要；设为 `0` 可关闭摘要
- `GLM_VLLM_MAX_MODEL_LEN`：默认 `32768`
- `GLM_VLLM_GPU_MEMORY_UTILIZATION`：默认 `0.78`
- `GLM_PRELOAD_PIPELINE`：默认 `false`，设为 `true` 时 API 启动后预加载 layout pipeline
- `TEMP_DIR`：默认 `/tmp/glm_ocr_uploads`
- `DEFAULT_CALLBACK_URL`：默认 `http://127.0.0.1:18000/api/v2/ocr/callback`

## 稳定性优先默认值

`start.sh` 当前默认按单卡 OCR 稳定性优先启动 vLLM：

- 默认开启 `--enforce-eager`
- 默认开启 `--disable-custom-all-reduce`
- 默认不传 `--speculative-config`

如果要恢复更激进的吞吐调优，建议一次只打开一项，并单独观察 `ocr_log/` 中是否重新出现 NCCL/TCPStore 异常日志。

## 日志降噪与 OCR 质量判断

日志中反复出现的 `ProcessGroupNCCL` / `TCPStore sendBytes failed` / `Failed to check the "should dump" flag on TCPStore` 通常来自 PyTorch 分布式通信的后台心跳或诊断线程：TCPStore 已关闭、连接被断开，后台线程仍在尝试检查诊断开关，所以持续向 stderr 打出 `Broken pipe` 和 C++ 栈。

这些提醒本身不参与 GLM-OCR 的版面检测、页面渲染、区域识别或 Markdown/JSON 生成。判断是否影响 OCR 质量时以任务结果为准：

- 如果 `/status/{session_id}` 为 `completed`，页数、Markdown、JSON 版面信息和图片资产完整，这类日志只属于运行时噪声，不代表 OCR 文本质量下降。
- 如果同时出现 vLLM 进程退出、请求超时、session `failed`、页数缺失或结果文件不完整，则影响的是 OCR 任务可用性/完整性，需要按失败任务排查；此时可临时设置 `GLM_LOG_FILTER_NCCL_BROKEN_PIPE=0` 保留完整底层日志。

`start.sh` 默认让 vLLM 和 API 日志先经过 `log_filter.py`，只过滤上述已知噪声及紧跟的 C++ 栈；普通 warning/error、OCR 任务排队、开始、完成、失败和 callback 失败日志会继续写入 `ocr_log/`。

注意：日志过滤器由 `start.sh` 的独立 `nohup bash` 管道 wrapper 持有，`stop.sh` 会按进程组停止 wrapper、服务进程和过滤器。不要改回 Bash process substitution，否则 `start.sh` 退出后过滤器可能先关闭，API 进程后续写 stderr 会触发 `BrokenPipeError` 并导致 OCR session 失败。

## OCR 质量修复

针对扫描版规范 PDF 中常见的水印干扰和多行正文重复循环，服务在官方 GLM-OCR self-hosted pipeline 后增加一次轻量质量修复：

- 官方 pipeline 仍负责 PDF 渲染、PP-DocLayoutV3 版面检测、区域 OCR、表格/公式/图片资产输出。
- 修复器只处理文本区域：发现长输出重复、公式标记异常、编号条文多行换行等情况时，按深色文字投影把区域切成文本行，逐行调用 vLLM `Text Recognition:`，再合并为段落。
- 对目录类大块 `content` 区域保留行换行，避免所有目录项挤成一行。
- 每个 session 输出 `quality_report.json`，记录修复页码、区域、行数、原因和修复前后长度；`metadata.json` 增加 `quality_repair_enabled` 与 `quality_repair_count`。
- 如果需要对比官方原始效果，可临时设置 `GLM_TEXT_LINE_REPAIR_ENABLED=0` 后重启服务。

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

本地质量回归脚本：

```bash
cd /home/ubuntu/jiang/ragproject3/GlmOcrApi
python ocrtest/run_glm_ocr_quality_test.py --page 16 --case-name pump-page16
python ocrtest/run_glm_ocr_quality_test.py --page 0 --max-pages 6 --case-name pump-first6
python ocrtest/run_glm_ocr_quality_test.py --page 16 --no-repair --case-name pump-page16-baseline
```
