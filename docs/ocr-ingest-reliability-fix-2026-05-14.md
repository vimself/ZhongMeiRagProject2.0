# 2026-05-14 OCR 与入库稳定性修复

## 问题摘要

- 文档上传后前端显示失败，但 `DeepseekOcrApi` 日志显示 OCR 任务实际已完成。
- `worker-ingest` 日志确认真实失败点在 `embed_batch` 步骤写入 `ingest_step_receipts` 时触发：
  `Got a packet bigger than 'max_allowed_packet' bytes`。
- `DeepseekOcrApi` 对命中 `max_tokens` 且未输出 `EOS` 的页面，仅做一次清洗；若判定低质量则直接整页丢弃，导致 RAG 可能丢失关键页内容。

## 后端修复

- 为 `IngestStepReceipt` 增加“大 payload 自动外置”策略：
  - 小回执仍内联写入数据库。
  - 大回执改为写入 `UPLOAD_DIR/ingest_receipts/<job_id>/` 下的 JSON 文件。
  - 数据库仅保存轻量指针、摘要和校验信息。
- `run_idempotent_step` 在读取回执时透明加载外置 JSON，保持幂等语义不变。
- 文档硬删除时，新增对外置回执文件的收集和清理，避免遗留垃圾文件。

## OCR 修复

- 对“整页生成命中 `max_tokens` 且未遇到 `EOS`”的页面，新增分段恢复流程。
- 分段恢复前先对整页清洗结果打分；达到可用阈值的截断页直接保留，不再强制重跑。
- 默认只对低质量截断页按纵向 3 段、带少量重叠重新 OCR，再合并去重后的文本。
- 单份 PDF 默认最多分段恢复 8 个异常页；单页恢复中若已有 1 个分段再次命中 `max_tokens`，停止后续分段，保留已有结果。
- 调整异常页可用性判断，不再因为阈值过严而轻易整页丢弃。
- 对仍然不完整但仍有有效文本的页面，优先保留低置信内容，减少 RAG 漏召回。
- OCR 会话元数据新增：
  - `recovered_pages`
  - `preserved_low_confidence_pages`
  - `skipped_pages`

## 新增 OCR 环境变量

- `OCR_PAGE_RECOVERY_SEGMENTS`
- `OCR_PAGE_RECOVERY_OVERLAP_RATIO`
- `OCR_PAGE_RECOVERY_ENABLED`
- `OCR_PAGE_RECOVERY_MAX_PAGES`
- `OCR_PAGE_RECOVERY_MAX_FAILED_SEGMENTS`
- `OCR_PAGE_RECOVERY_MIN_SCORE`
- `OCR_INCOMPLETE_PAGE_MIN_CHARS`

## 2026-05-14 追加：异常页恢复防长时间循环

- 现场日志中的 `/status/{session_id}` 重复请求是后端轮询，不是 OCR 无限循环。
- 真正耗时来自无 EOS 异常页的分段恢复：每个坏分段可能跑满 `max_tokens=8192`，约 20 秒；此前所有无 EOS 页都会强制跑 3 段。
- 修复后策略改为“先保留可用截断内容，低质量页才补救，补救有上限”。这符合“95%+ 成功率优先、不要为了 100% 页面成功拖死整份文档”的目标。

## 2026-05-14 追加：页索引超长文本入库失败

- `CJJT 269-2017 城市综合地下管线信息系统技术规范.pdf` 曾在 OCR 完成后失败，真实失败点不是 OCR，而是 Track B 页索引写库：
  `Data too long for column 'text' at row 1`。
- 原因是 `knowledge_page_index_v2.text` 把同页所有切片文本拼接后写入 MySQL `TEXT` 字段，规范类 PDF 的大表格页会超过约 64KB 上限。
- 修复后页索引文本按 UTF-8 字节上限截断并去除完全重复切片，默认 `INGEST_PAGE_INDEX_TEXT_MAX_BYTES=49152`。完整切片仍写入 `knowledge_chunks_v2` 并参与 embedding/向量召回，不截断主 RAG 证据。

## 2026-05-14 追加：49 份批量上传触发 GLM-OCR/vLLM 崩溃

- 现场日志中的前端“大量失败”不是上传 API 拒绝，也不是 PDF 入库记录缺失；真实失败点是 GLM-OCR 底层 vLLM：
  `image item with 6110 embedding tokens ... exceeds ... encoder cache size 6084`，随后触发 CUDA `device-side assert`，18080 端口不可用。
- 后端原先把 OCR 状态里的 `HealthWatchdog: OCR service at 127.0.0.1:18080 is no longer available` 当成永久 `OCRFailed`，文档立刻进入 failed；同时 `upload_to_ocr` 幂等缓存会让重试继续轮询同一个已失败 session。
- 修复后：
  - `worker-ingest` 默认改为 `--concurrency=1 --prefetch-multiplier=1`，批量上传按文档依次进入 OCR/embedding/入库，优先稳定性。
  - `GlmOCRClient` 将 vLLM 连接拒绝、HealthWatchdog、EngineDead、CUDA device-side assert 等识别为 `OCRTransient`，交给 Celery 退避重试。
  - `upload_to_ocr` 幂等键加入任务 attempt，OCR 临时故障重试时会创建新的 OCR session，不再卡在旧失败 session。
  - GLM-OCR API 在 vLLM 未就绪时直接返回 503，避免继续接收必然失败的 OCR session。
  - `GlmOcrApi/start.sh` 默认传入 `GLM_VLLM_LIMIT_MM_PER_PROMPT={"image":4}`、`GLM_VLLM_MAX_NUM_BATCHED_TOKENS=16384`、`GLM_VLLM_MAX_NUM_SEQS=1`；其中 `max_num_batched_tokens` 会提高 vLLM 多模态 encoder cache 基础上限，`max_num_seqs` 限制同时推理请求数。
  - `GLM_MAX_WORKERS` 默认从 8 降到 1，降低单份 PDF 页/区域并发，避免批量入库把 vLLM 打崩。

## 验证情况

- `python -m compileall backend/app backend/tests DeepseekOcrApi` 已通过。
- 本次异常页恢复策略追加修复后，重新执行 `python -m compileall DeepseekOcrApi` 已通过。
- 本次页索引超长文本修复后，新增 `backend/tests/test_track_b_indexer.py` 覆盖 UTF-8 安全截断和重复切片去重。
- 本次 49 份批量上传稳定性修复后，执行 `python -m compileall backend/app GlmOcrApi` 与 `bash -n GlmOcrApi/start.sh` 均已通过；当前本机和容器环境均缺少 `pytest`，未能执行新增单测。
- `pytest backend/tests/test_ingest_task.py` 在当前环境未能执行完成，原因是本机 Python 环境缺少 `aiosqlite` 依赖，属于测试环境问题，不是本次补丁的语法错误。

## 风险说明

- “识别成功率 95%+”需要基于真实样本文档集做统计验证，本次改动解决了已知的整页截断后直接丢弃问题，能显著提高页内容保留率，但是否达到 95% 仍需用实际文档回归验证。

## 2026-05-14 追加：批量入库 OCR 吞吐优化与日志降噪

- 本机工作站为 i9-14900K、188GiB 内存、RTX 5880 Ada 48GiB；GLM-OCR/vLLM 运行时已占用约 40GiB 显存。为避免再次触发 vLLM 多模态缓存和 CUDA 稳定性问题，不提高 vLLM `max_num_seqs`，OCR 推理仍保持单路。
- 后端 Celery 入库改为两段流水线：
  - `ingest-ocr` 队列：`ingest.process` / `ingest.retry`，默认 `INGEST_OCR_WORKER_CONCURRENCY=1`，只做 OCR 上传、轮询、结果拉取和回执落盘。
  - `ingest` 队列：`ingest.postprocess`，默认 `INGEST_WORKER_CONCURRENCY=2`，做章节解析、切片、embedding、Track A/B 写入、资产登记和 finalize。
- 批量上传时，一份文档 OCR 完成后会立即释放 OCR worker 并投递后处理任务；当后端正在 embedding 或向量入库时，OCR worker 会继续取下一份文档，避免 GLM-OCR 空闲。
- `docker-compose.yml` 新增 `worker-ingest-ocr` 服务，原 `worker-ingest` 改为后处理 worker。
- GLM-OCR 日志降噪：
  - vLLM 默认增加 `--no-enable-log-requests`、`--disable-uvicorn-access-log` 与 `--disable-log-stats`，去掉高频 `POST /v1/chat/completions 200 OK` 和周期吞吐 metrics。
  - `VLLM_LOGGING_LEVEL` 默认 `WARNING`，只保留 warning/error 等关键问题。
  - API 服务默认 `--no-access-log`，但保留 `ocr_queued`、`ocr_started`、`ocr_completed`、`ocr_failed`、`ocr_callback_failed` 这类任务级关键日志。

新增环境变量：

- `INGEST_OCR_WORKER_CONCURRENCY`
- `GLM_VLLM_DISABLE_LOG_REQUESTS`
- `GLM_VLLM_DISABLE_LOG_STATS`
- `VLLM_LOGGING_LEVEL`
- `API_LOG_LEVEL`
- `API_ACCESS_LOG`

## 2026-05-14 追加：后端重建后上传 502

- 现象：后端 API/worker 重建后，前端批量上传立即显示失败；nginx 日志显示：
  `connect() failed (111: Connection refused) while connecting to upstream ... upstream: "http://172.18.0.7:8000/.../documents"`。
- 根因：nginx 通过静态 upstream 解析 `api:8000`，API 容器重建后 Docker 分配了新 IP，但运行中的 nginx 仍然缓存旧 IP，导致上传请求被代理到已经不存在的 API 容器地址。
- 修复：`ops/nginx/nginx.conf` 增加 Docker 内置 DNS `resolver 127.0.0.11 valid=10s ipv6=off`，并使用变量 `$api_backend=http://api:8000` 进行代理，让 nginx 在容器 IP 变化后重新解析 API 服务名。
