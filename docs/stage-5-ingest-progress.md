# Stage 5 · 入库链路核心 — 进度报告

生成时间：2026-05-09

---

## 1. 开发流程

1. 阅读 `docs/task.md` 与 `docs/ultimate-refactor.md` Stage 5 要求。
2. 复核 Stage 4 知识库权限、审计日志、路由和前端结构，确保不改变既有权限语义。
3. 实现后端数据层：SQLAlchemy 模型、Alembic 迁移、配置项和 Celery ingest 队列。
4. 实现服务层：OCR 客户端、DashScope 客户端、章节解析、章节感知切片、Track A/B 写入、资产登记、幂等 receipt、死信审计。
5. 实现 API：文档上传、列表、详情、进度、重试、删除、检索调试。
6. 实现前端：文档 API、类型扩展、知识库文档页、路由和首页 Stage 标识。
7. 优化 `DeepseekOcrApi/`：持久化 `meta.json`、内部队列、结构化状态、鉴权、健康检查、资产接口。
8. 补充测试、文档和本地 `.env` 配置，执行验证矩阵。

---

## 2. 完成情况

### 2.1 数据模型

新增 `backend/app/models/document.py` 与 Alembic revision `stage_5_ingest_core`，新增表：

| 表 | 说明 |
|----|------|
| `documents` | 文档元数据、上传者、知识库、状态、存储路径、sha256、doc_kind |
| `document_parse_results` | OCR markdown、outline、统计信息 |
| `document_assets` | OCR 图片资产登记，含页码和 bbox |
| `document_ingest_jobs` | 入库任务队列状态、attempt、trace_id |
| `ingest_step_receipts` | 每个入库步骤幂等 receipt |
| `ingest_callback_receipts` | 回调 receipt 预留 |
| `knowledge_chunks_v2` | 章节感知切片，含 section_path、section_id、页码、向量/稀疏字段 |
| `knowledge_page_index_v2` | 按页聚合的页面索引 |

SQLite 下 `vector` / `sparse` 使用 JSON。Stage 7 复核 SeekDB 官方语法后，当前实现改为同时保留 JSON fallback 字段，并在 SeekDB 中启用 `vector_native VECTOR(1024)` / `sparse_native SPARSEVECTOR` 原生列与 HNSW/SINDI 索引。

### 2.2 服务层

新增模块：

- `app/services/ocr/client.py`：异步 DeepSeek OCR 客户端，支持直接访问 `http://222.195.4.65:8899`、上传、轮询、markdown、assets/images 兼容获取、会话删除，并在上传时传入回调地址。
- `app/services/llm/client.py`：DashScope OpenAI 兼容客户端，提供 embedding batch 和流式 chat 预留。
- `app/services/llm/rate_limiter.py`：Redis token bucket，Redis 不可用时退化为进程内桶。
- `app/services/llm/cost.py`：token 成本估算。
- `app/services/ingest/outline_parser.py`：支持 Markdown 标题、数字章节、中文章节。
- `app/services/ingest/chunker.py`：章节内语义切片，支持 token 限制和 overlap。
- `app/services/ingest/track_a_indexer.py`：embedding 批量处理、sha256 缓存、切片写入。
- `app/services/ingest/track_b_indexer.py`：页面索引覆盖写入。
- `app/services/ingest/asset_registry.py`：图片资产落盘和登记。
- `app/services/ingest/idempotency.py`：步骤幂等 receipt。
- `app/services/ingest/dead_letter.py`：失败入死信并写 `ingest.step_failed` 审计。
- `app/tasks/ingest.py`：`ingest.process`、`ingest.retry`、`ingest.dead_letter_handler`。

### 2.3 API

新增 `backend/app/api/documents.py`：

| 端点 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/api/v2/knowledge-bases/{kb_id}/documents` | POST | editor | PDF 上传、校验、落盘、创建任务 |
| `/api/v2/knowledge-bases/{kb_id}/documents` | GET | viewer | 分页、搜索、状态筛选 |
| `/api/v2/documents/{id}` | GET | viewer | 文档详情、最新 job、解析结果、资产 |
| `/api/v2/documents/{id}/progress` | GET | viewer | receipt 汇总进度 |
| `/api/v2/documents/{id}/retry` | POST | owner/admin | 重新入队 |
| `/api/v2/documents/{id}` | DELETE | owner/admin | 物理删除文档及其 OCR、资产、入库任务、向量/稀疏索引 |
| `/api/v2/knowledge-bases/{kb_id}/documents` | DELETE | owner/admin | 批量物理删除同一知识库下的文档 |
| `/api/v2/retrieval/debug` | POST | admin | Stage 6/7 预留调试检索 |

新增 schema：`backend/app/schemas/document.py`、`backend/app/schemas/ingest.py`。

2026-05-13 追加：文档上传接口已扩展为兼容单文件 `file` 与批量 `files` 字段，单次最多 50 份 PDF。每份有效 PDF 仍独立创建 `documents`、`document_ingest_jobs` 并投递到 Celery `ingest` 队列，避免在 API 请求线程内同步执行多份 OCR/embedding。

2026-05-13 追加：入库进度对前端统一暴露 5 个正常业务状态：`pending`（排队）、`ocr`、`embedding`、`vector_indexing`（向量入库）、`ready`（完成）。worker 在 OCR、Embedding、向量入库边界显式提交状态，`/documents/{id}/progress` 按阶段 receipt 计算进度百分比。

### 2.4 审计

新增 action：

- `document.upload`
- `document.retry`
- `document.delete`
- `document.delete.batch`
- `ingest.step_failed`

API 写操作记录当前用户；worker 失败使用文档上传者作为 actor，避免 `actor_user_id` 为空。

### 2.5 前端

新增/修改：

- `frontend/src/api/document.ts`：文档上传、列表、详情、进度、重试、删除、批量删除。
- `frontend/src/api/types.ts`：新增文档和入库进度类型。
- `frontend/src/views/KnowledgeDocumentsView.vue`：上传、搜索、筛选、进度轮询、详情抽屉、资产概览。
- `frontend/src/views/KnowledgeListView.vue`：点击知识库行进入 `/knowledge/:kbId/documents`。
- `frontend/src/router/index.ts`：新增文档页路由和进入前权限检查。
- `frontend/src/views/HomeView.vue`：Stage 标识更新为 Stage 5。

2026-05-13 追加：知识库文档页上传区支持一次选择/拖拽最多 50 份 PDF，并通过批量 multipart 请求提交；上传成功后显示入队数量并刷新列表。

2026-05-13 追加：知识库文档页状态列优先使用轮询接口返回的实时 `document_status`，进度条按排队、OCR、Embedding、向量入库、完成五阶段动态更新，避免批量上传后长时间显示“排队”但进度已变化。

### 2.6 DeepseekOcrApi

完成工作站侧代码优化：

- `/upload` 改为入内部 `asyncio.PriorityQueue` 并立即返回。
- 默认后端直接访问工作站 `http://222.195.4.65:8899`；工作站回调 Windows 本机通过 SSH 反向隧道访问 `http://127.0.0.1:18000/api/v2/ocr/callback`。
- session 目录写入 `meta.json`，同时保留 `status.txt` 兼容旧客户端。
- `/status/{sid}` 返回 `progress`、`stage`、`started_at`、`updated_at`、`elapsed_ms` 和结构化错误。
- 新增 `/queue`、`/healthz`、`/readyz`、`/result/{sid}/assets`。
- `/result/{sid}/markdown?include_meta=true` 返回 markdown、页数、outline、processed_at。
- 写操作支持 `API_TOKEN` Bearer 鉴权，未配置时保持兼容。
- `CORS_ALLOW_ORIGINS` 支持环境变量白名单。
- `MAX_FILE_SIZE` 调整到 200MB。
- `start.sh` 增加 `set -euo pipefail`、GPU 信息和日志 tee。

---

## 3. 本地验证结果

验证时间：2026-05-09。

| 检查项 | 结果 |
|--------|------|
| `.venv\Scripts\ruff.exe check backend` | ✅ All checks passed |
| `.venv\Scripts\black.exe --check backend` | ✅ unchanged |
| `.venv\Scripts\mypy.exe backend\app` | ✅ Success: no issues found |
| `.venv\Scripts\pytest.exe backend\tests -q` | ✅ 120 passed |
| 临时 SQLite `alembic upgrade head → downgrade -1 → upgrade head` | ✅ 最终 `stage_5_ingest_core (head)` |
| `npm run lint` | ✅ clean |
| `npm run stylelint` | ✅ clean |
| `npm run build` | ✅ built |
| `docker compose config` | ✅ valid |

说明：测试全部 mock OCR、DashScope、向量数据库外部能力；未真实调用 DashScope 或 OCR 工作站。

---

## 4. 变更日志

### 新增文件

- `backend/alembic/versions/20260510_stage_5_ingest_core.py`：Stage 5 迁移。
- `backend/app/models/document.py`：文档、任务、receipt、切片、页索引模型。
- `backend/app/api/documents.py`：文档与检索调试路由。
- `backend/app/schemas/document.py`、`backend/app/schemas/ingest.py`：API schema。
- `backend/app/services/ocr/*`、`backend/app/services/llm/*`、`backend/app/services/ingest/*`：入库服务层。
- `backend/app/tasks/ingest.py`：Celery 入库任务。
- `backend/tests/test_ocr_client.py`、`test_outline_parser.py`、`test_chunker.py`、`test_track_a_indexer.py`、`test_ingest_task.py`、`test_documents_api.py`、`test_retrieval_debug.py`、`test_alembic_stage_5.py`：Stage 5 测试。
- `frontend/src/api/document.ts`、`frontend/src/views/KnowledgeDocumentsView.vue`：前端文档能力。
- `mypy.ini`：根目录 mypy 配置，保证项目根命令可复现。

### 修改文件

- `backend/app/core/config.py`、`.env.example`：新增 DashScope/OCR/上传/切片配置项。
- `backend/app/main.py`：挂载 documents 路由。
- `backend/app/celery_app.py`：补齐 ingest 队列 imports 和 annotations。
- `backend/app/models/__init__.py`、`backend/alembic/env.py`：注册 Stage 5 模型。
- `backend/pyproject.toml`：新增 `tenacity`、`respx` 依赖。
- `docker-compose.yml`：`worker-ingest` 并发调整为 4。
- `frontend/src/api/types.ts`、`frontend/src/router/index.ts`、`frontend/src/views/HomeView.vue`、`frontend/src/views/KnowledgeListView.vue`：接入文档页。
- `DeepseekOcrApi/app.py`、`ocr_processor.py`、`config.py`、`example_client.py`、`requirements.txt`、`start.sh`、`stop.sh`、`README.md`：OCR 服务端契约升级。
- `AGENTS.md`、`docs/INDEX.md`：同步 Stage 5 状态。

### 删除内容说明

未执行批量删除命令。仅在验证 Alembic 时，按单个明确路径删除了临时文件 `backend/alembic_stage5_test.sqlite`。

---

## 5. 剩余问题

- 冒烟链路使用 mock OCR 与 mock DashScope 覆盖，未连接真实工作站和真实 DashScope。
- `retrieval/debug` 当前为 Stage 6/7 铺垫的轻量调试实现，真实 RRF、BM25、向量召回排序将在 Stage 6 完整化。
- OCR 工作站代码已在本仓库改造，已部署到 `222.195.4.65:8899` 并运行（Stage 6 确认）。

---

## 6. 下一步建议（Stage 6）

- 实现正式检索服务：向量召回、BM25、RRF、过滤器、权限裁剪。 ✅ 已在 Stage 6 完成
- 增加 PDF 预览与 bbox 高亮接口。 ✅ 已在 Stage 6 完成
- 为 `knowledge_chunks_v2` 接入 SeekDB 真实向量查询语法并补压测。✅ Stage 7 已修正为 `VECTOR(1024)` / `SPARSEVECTOR` + HNSW/SINDI，并在当前本地 `seekdb-v1.2.0.0` 镜像中通过原生向量、稀疏和 NGRAM 全文探针；生产前仍需按真实数据规模压测。

---

## 7. 结论

Stage 5 入库链路核心已完成并通过本地验证。后端、前端、Celery、DeepSeek OCR 服务端代码、测试和文档均已同步更新。
