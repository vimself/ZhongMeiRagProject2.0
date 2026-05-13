# 2026-05-13 · 知识库 PDF 批量上传改造

## 背景

知识库文档页原先一次只能选择并上传一份 PDF。为支持批量入库，本次将上传接口扩展为单次最多 50 份 PDF，并继续复用现有 Celery `ingest` 队列逐份处理文档，避免上传后同步执行 50 份 OCR/embedding 链路。

## 后端变更

- `POST /api/v2/knowledge-bases/{kb_id}/documents` 同时支持旧字段 `file` 和新字段 `files`。
- 新增配置项 `UPLOAD_MAX_FILES`，默认值 `50`。
- 每份通过校验的 PDF 独立创建：
  - `documents(status='pending')`
  - `document_ingest_jobs(status='queued')`
  - `document.upload` 审计日志
  - `ingest.process` Celery 任务
- 单文件上传保持旧兼容字段：`document_id`、`job_id`、`trace_id`。
- 批量响应新增 `documents`、`rejected`、`accepted_count`、`rejected_count`、`max_count`。
- 上传前按同一知识库内未删除文档的 `filename` 判重；本次批量请求内重复出现的文件名也会判为重复。
- 重复文件进入 `rejected`，原因固定为 `文件名已存在`；未重复文件继续创建文档、任务并进入入库队列。

## 前端变更

- 知识库文档页上传区支持多选/拖拽多份 PDF。
- 前端限制单次最多 50 份，并在上传前过滤非 PDF 文件。
- 新增 `uploadDocuments()` API，使用 multipart 字段 `files` 批量提交。
- 上传完成后展示成功入队数量，并刷新文档列表继续沿用原有进度轮询。
- 若后端返回同名重复文件，前端明确提示被跳过的文件名；其余文件继续显示成功入队。
- 进度展示抽象为 5 个正常业务状态：排队、OCR、Embedding、向量入库、完成。前端状态列使用轮询接口的实时 `document_status` 覆盖列表初始状态，进度条按阶段动态更新。

## 进度映射

| 状态 | 入库步骤 | 进度范围 |
|------|----------|----------|
| 排队 | 任务已创建，worker 尚未开始 | 0% |
| OCR | `upload_to_ocr`、`poll_and_fetch_ocr` | 8% ~ 35% |
| Embedding | `parse_outline`、`section_aware_chunk`、`embed_batch` | 40% ~ 70% |
| 向量入库 | `track_a_write`、`track_b_write`、`asset_register` | 75% ~ 96% |
| 完成 | `finalize` | 100% |

失败仍作为异常状态显示，不计入正常 5 阶段流转。

## OCR 工作站

本次无需修改 `DeepseekOcrApi/`。批量上传只改变 API 接收和任务投递方式，OCR 工作站仍按单个 PDF session 处理，由 Celery worker 按队列并发度调度。

## 验证

| 检查项 | 结果 |
|--------|------|
| `.venv\Scripts\python.exe -m pytest backend\tests\test_documents_api.py` | ✅ 19 passed |
| `.venv\Scripts\python.exe -m ruff check backend\app\api\documents.py backend\app\schemas\document.py backend\app\core\config.py backend\tests\test_documents_api.py` | ✅ All checks passed |
| `npm run build` | ✅ built；仅保留 Vite chunk 体积提示 |

2026-05-13 追加验证：

| 检查项 | 结果 |
|--------|------|
| `.venv\Scripts\python.exe -m pytest backend\tests\test_documents_api.py backend\tests\test_ingest_task.py` | ✅ 31 passed |
| `.venv\Scripts\python.exe -m ruff check backend\app\api\documents.py backend\app\tasks\ingest.py backend\tests\test_documents_api.py` | ✅ All checks passed |
| `npm run build` | ✅ built；仅保留 Vite chunk 体积提示 |

2026-05-13 追加同名判重验证：

| 检查项 | 结果 |
|--------|------|
| `.venv\Scripts\python.exe -m pytest backend\tests\test_documents_api.py -q` | ✅ 24 passed |
| `.venv\Scripts\python.exe -m ruff check backend\app\api\documents.py backend\tests\test_documents_api.py` | ✅ All checks passed |
| `npx eslint src/views/KnowledgeDocumentsView.vue` | ✅ clean |
| `npx stylelint "src/views/KnowledgeDocumentsView.vue"` | ✅ clean |
| `npm run build` | ✅ built；仅保留 Vite chunk 体积提示 |

## 注意事项

- 单次最多上传 50 份 PDF；单文件大小仍受 `UPLOAD_MAX_MB` 控制，默认 200MB。
- 若批量请求中部分文件未通过后端校验，接口会返回已入队和被拒绝的文件清单；若没有任何有效 PDF，则返回 400。
- 若请求中只有重复文件，接口返回 `202` 与 `accepted_count=0`、`rejected` 清单，用于前端直接提示重复文件名。
- 实际 OCR/embedding 并发由 `worker-ingest` 的 Celery 并发度和下游限流控制，不会在 API 请求线程内直接处理文档内容。
