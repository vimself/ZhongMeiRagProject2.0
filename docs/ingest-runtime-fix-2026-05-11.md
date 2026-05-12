# 2026-05-11 入库运行时修复记录

## 问题现象

上传 PDF 到知识库后，前端列表一直显示「排队」和 `0%`，进度接口持续返回无已完成步骤。

## 根因

1. `api` 容器把上传文件写入 `uploads-data:/app/backend/uploads`，但 `worker-ingest` 没有挂载同一个卷。Celery 已收到 `ingest.process` 任务，但在 `upload_to_ocr` 阶段读取 `uploads/documents/...pdf` 时触发 `FileNotFoundError`。
2. Celery 任务使用 `asyncio.run()` 调用异步 SQLAlchemy 逻辑。任务结束后连接池中的 `asyncmy` 连接可能被下一次任务的新事件循环复用，出现 `Future attached to a different loop`。
3. 搜索导出任务同样写入 `uploads/exports/`，需要和 API 容器共享 `uploads-data`，否则生成的 ZIP 无法由 API 下载。

## 修复内容

- `docker-compose.yml` 新增 `x-backend-upload-volume` 锚点，并将 `uploads-data:/app/backend/uploads` 同时挂载到 `api`、`worker-ingest`、`worker-default`。
- 新增 `backend/app/tasks/async_runner.py`，Celery 异步任务通过 `run_async_task()` 执行，并在任务结束前 `await engine.dispose()`，避免跨事件循环复用 async DB 连接。
- `backend/app/tasks/ingest.py` 和 `backend/app/tasks/search_export.py` 改用 `run_async_task()`。
- `DeepseekOcrApi/ocr_processor.py` 在 vLLM 支持 `task` 或 `runner` 参数时显式传入 `task="generate"` / `runner="generate"`，并在注册 `DeepseekOCR2ForCausalLM` 前为 vLLM registry 补充该类的 text-generation 判定，同时补齐 vLLM 0.8.x 生成模型接口所需的 `compute_logits(..., sampling_metadata)` 兼容包装和 `sample()` 方法。

## 运维注意

修改 Docker Compose 卷配置后，需要重建/重启相关服务：

```powershell
docker compose up --build -d api worker-ingest worker-default
```

如果已有文档因旧配置失败，可在前端文档详情中点击重试，或调用 `POST /api/v2/documents/{document_id}/retry` 重新投递入库任务。

如果 worker 已能写入 `upload_to_ocr` receipt，但随后失败为 `LLM.generate() is only supported...`，说明问题已推进到工作站 OCR 服务端。需要将本仓库的 `DeepseekOcrApi/ocr_processor.py` 同步到 `222.195.4.65` 工作站并重启 OCR API。重启日志应出现 `Initializing vLLM DeepSeek-OCR with task=generate ...`，并且不应再出现 `Defaulting to 'embed'`。如果出现 `This model does not support the 'generate' task`，说明工作站仍缺少 registry text-generation 判定补丁；如果出现 `object has no attribute 'sample'`，说明工作站仍缺少 vLLM 0.8.x 生成接口兼容补丁。

## 2026-05-11 15:00 补充：44% 入库失败

现象：`AQ 1083-2011 煤矿建设安全规范(非正式版)` 上传后停在 44% 并标记失败。进度 44% 对应 9 个入库步骤中已完成 4 个，数据库 receipt 显示已完成 `upload_to_ocr`、`poll_and_fetch_ocr`、`parse_outline`、`section_aware_chunk`，失败发生在 `embed_batch`。

根因：`qwen3-vl-embedding` 走 DashScope 原生多模态 embedding endpoint。阿里云文档要求该模型一次请求中 `input.contents` 内容元素总数不超过 20；当前上层入库批次为 25，229 个切片会按 25 条提交，DashScope 返回 `400 Bad Request`。

修复：

- `backend/app/services/llm/client.py` 在多模态 embedding 客户端内部按 20 条上限自动拆分请求，保持返回向量顺序不变。
- DashScope 4xx 错误改为抛出非重试的 `DashScopeRequestError`，错误信息保留响应体，避免以后只看到泛化 `HTTPStatusError`，也避免 400 无意义重试 5 次。
- 新增 `backend/tests/test_dashscope_client.py` 覆盖 45 条输入拆分为 `20 + 20 + 5` 以及 400 响应体透传。

验证：

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_dashscope_client.py backend\tests\test_ingest_task.py
docker compose up --build -d api worker-ingest
```

重试失败文档后，`documents.status=ready`、`document_ingest_jobs.status=succeeded`、9 个 receipt 全部成功，写入 229 个知识切片与 39 条页索引。
