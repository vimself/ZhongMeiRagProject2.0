# Stage 6 · 文档预览与 RAG 元数据闭环 — 进度报告

生成时间：2026-05-10

---

## 1. 开发流程

1. 阅读 `docs/ultimate-refactor.md` Stage 6 要求。
2. 复核 Stage 5 代码，确认 PDF token 基础设施（`jwt.py:issue_pdf_token`、`deps.py:pdf_token_user`）已就绪但无 API 端点调用。
3. 实现 6.1 文档资产短时签名 URL。
4. 实现 6.2 PDF 预览服务（后端路由 + 前端组件）。
5. 实现 6.3 RAG 检索元数据闭环（Retriever 服务 + 升级 retrieval_debug 端点）。
6. 编写测试、运行验证矩阵、更新文档。

---

## 2. 完成情况

### 2.1 文档资产 URL（6.1）

新增 `AssetOut` Pydantic 模型，`DocumentDetailResponse.assets` 类型从 `list[dict]` 改为 `list[AssetOut]`。
`_asset_payload()` 增加 5 分钟短时签名 `url` 字段，指向 `/api/v2/assets/preview?asset_id=&token=`，不再暴露资产 `/uploads` 直链。
新增：
- `POST /api/v2/assets/sign`：按 `asset_id` 签发短时资产 token。
- `GET /api/v2/assets/preview`：校验 token、用户、文档、知识库权限后返回资产文件。

### 2.2 PDF 预览服务（6.2）

**后端**：

- 提取 `require_document_role()` 到 `knowledge_base_deps.py`，供 `documents.py` 和 `pdf_preview.py` 共用。
- 新建 `backend/app/api/pdf_preview.py`，包含两个端点：
  - `POST /api/v2/pdf/sign`：签发 5 分钟 PDF 短时 JWT，校验文档存在且用户有 viewer 权限，写审计日志。
  - `GET /api/v2/pdf/preview`：通过 `PdfTokenUser` 依赖验证 token，校验文档仍存在、用户仍有 KB 权限，支持 HTTP Range，返回 `200` 或 `206 Partial Content`，写审计日志。
  - `GET /api/v2/documents/{document_id}/download`：复用 PDF token，提供附件下载 URL。
- 新建 `backend/app/schemas/pdf_preview.py`（`PdfSignRequest`、`PdfSignResponse`、`AssetSignRequest`、`AssetSignResponse`）。
- 路由注册到 `main.py`。

**前端**：

- 安装 `pdfjs-dist ^4.9.155`。
- 新建 `frontend/src/api/pdfPreview.ts`：`signPdfToken()`、`signAssetToken()` 和 `pdfPreviewUrl()` 函数。
- 新建 `frontend/src/composables/usePdfPreview.ts`：管理 PDF URL、loading、error、token 过期、当前页、bbox 高亮状态。
- 新建 `frontend/src/components/PdfViewer.vue`：基于 pdfjs-dist 的 PDF 查看器，支持页码跳转、缩放/适宽、bbox 高亮覆层、loading/error 提示。
- 修改 `KnowledgeDocumentsView.vue`：表格操作列增加"预览"按钮（status=ready）、详情抽屉增加"预览 PDF"按钮、新增 PDF 预览抽屉，并在资产列表中提供签名资产预览入口。

### 2.3 RAG 检索元数据闭环（6.3）

- 新建 `backend/app/services/rag/retriever.py`，`Retriever` 类实现：
  - Track A 向量召回（SeekDB 原生 `cosine_distance(... ) APPROXIMATE` 优先，SQLite/不支持时 Python 余弦相似度 fallback）
  - Track B BM25/全文召回（SeekDB `MATCH ... AGAINST` 优先，SQLite/不支持时词频+短语打分 fallback）
  - RRF 融合（K=60）
  - 文档标题加载、snippet 构建
- `RetrievalDebugItem` schema 新增 Stage 7 引用协议字段（`document_title`、`knowledge_base_id`、`section_text`、`bbox`、`snippet`、`preview_url`、`download_url`），均有默认值，向后兼容。
- 升级 `POST /api/v2/retrieval/debug` 端点，使用 `Retriever.retrieve()` 替代本地 `_debug_score`，并为 `preview_url` / `download_url` 生成短时 PDF token。
- 新增 Alembic revision `stage_6_pdf_preview_rag`，为 `knowledge_chunks_v2.content` 尝试创建全文索引；Stage 7 复核后已改为 SeekDB NGRAM FULLTEXT，并保留 fallback 检索以兼容不支持对应 DDL 的环境。

### 2.4 审计

新增 action：
- `pdf.sign`：PDF 签名操作
- `pdf.preview`：PDF 预览访问
- `pdf.download`：PDF 下载访问
- `asset.sign`：资产签名操作
- `asset.preview`：资产预览访问

---

## 3. 本地验证结果

验证时间：2026-05-10。

| 检查项 | 结果 |
|--------|------|
| `.venv\Scripts\ruff.exe check backend` | ✅ All checks passed |
| `.venv\Scripts\black.exe --check backend` | ✅ unchanged |
| `.venv\Scripts\mypy.exe backend\app` | ✅ Success: no issues found |
| `.venv\Scripts\pytest.exe backend\tests -q` | ✅ 143 passed |
| `npm run lint` | ✅ clean |
| `npm run stylelint` | ✅ clean |
| `npm run build` | ✅ built in 12.28s |
| `docker compose config --quiet` | ✅ valid |
| `docker compose up --build -d` | ✅ API/Redis/SeekDB/worker/Nginx 均已启动，Alembic 当前版本 `stage_6_pdf_preview_rag` |
| `GET http://222.195.4.65:8899/healthz` | ✅ `{"status":"ok"}` |
| `GET http://222.195.4.65:8899/queue` | ✅ `{"queued":0,"active":0,"capacity":16}` |
| 容器内 PDF Range 烟测 | ✅ `206 Partial Content`，`Content-Range: bytes 0-7/51` |

说明：PDF 预览测试写入系统临时目录中的 `%PDF-1.4` 文件验证 `200/206/416`；检索测试使用 mock 向量和词频打分。容器级烟测使用临时文档记录与临时 PDF，完成后已清理。未找到仓库内适合 OCR 的真实 PDF，因此未触发完整 OCR 入库任务。

---

## 4. 变更日志

### 新增文件

- `backend/app/api/pdf_preview.py`：PDF 签名 + 预览路由。
- `backend/app/schemas/pdf_preview.py`：PdfSignRequest / PdfSignResponse / AssetSignRequest / AssetSignResponse。
- `backend/app/services/rag/__init__.py`：RAG 服务包。
- `backend/app/services/rag/retriever.py`：检索器（向量+BM25+RRF）。
- `backend/alembic/versions/20260510_stage_6_pdf_preview_rag.py`：Stage 6 迁移，尝试创建全文索引。
- `backend/tests/test_pdf_preview.py`：PDF/资产签名预览测试（14 个用例）。
- `backend/tests/test_retriever.py`：检索器测试（7 个用例）。
- `frontend/src/api/pdfPreview.ts`：PDF 预览 API 客户端。
- `frontend/src/components/PdfViewer.vue`：PDF 查看器组件。
- `frontend/src/composables/usePdfPreview.ts`：PDF 预览 composable。

### 修改文件

- `backend/app/main.py`：注册 pdf_preview_router。
- `backend/app/api/documents.py`：迁移 require_document_role、升级 retrieval_debug、AssetOut 返回类型。
- `backend/app/api/knowledge_base_deps.py`：新增 require_document_role。
- `backend/app/schemas/document.py`：新增 AssetOut 模型。
- `backend/app/schemas/ingest.py`：RetrievalDebugItem 新增 Stage 7 字段。
- `backend/app/security/jwt.py`、`backend/app/api/deps.py`：新增资产 token 签发与校验。
- `backend/alembic/versions/20260510_stage_5_ingest_core.py`：SeekDB 原生向量 DDL 改为可降级执行，避免本地测试镜像不支持向量 DDL 时阻断启动。
- `backend/pyproject.toml`：将 `httpx` 提升为运行时依赖，供 OCR/LLM 客户端在容器镜像中使用。
- `frontend/package.json`：添加 pdfjs-dist。
- `frontend/src/api/types.ts`：新增 AssetOut、更新 DocumentDetailResponse。
- `frontend/src/views/KnowledgeDocumentsView.vue`：PDF 预览按钮 + 抽屉 + 资产签名预览入口。

---

## 5. 剩余问题

- `pdfPreviewUrl` 中 token 通过 URL query 参数传递（pdfjs-dist 需要），安全性通过 5 分钟过期 + 文档级 scope 保证。
- Stage 7 已确认当前本地 `seekdb-v1.2.0.0` 镜像支持 `VECTOR(1024)`、`SPARSEVECTOR`、HNSW/SINDI 和 NGRAM FULLTEXT；迁移仍保留可降级策略，便于兼容能力较弱的测试镜像或未来部署差异。
- 前端 PdfViewer 的 bbox 坐标转换按 PDF 坐标系原点左下实现，已通过单元/构建和 Range 链路验证；仍建议在 Stage 7 使用真实 OCR bbox 样本做视觉复核。

---

## 6. 结论

Stage 6 文档预览与 RAG 元数据闭环已完成并通过本地、容器和 OCR 工作站连通验证。PDF/资产签名、HTTP Range 预览、下载 URL、RAG 检索（向量+BM25+RRF）和 Stage 7 引用协议字段均已就绪，可直接供 Stage 7 RAG 问答链路使用。
