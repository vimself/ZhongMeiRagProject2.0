## 用户要求

总是使用中文回答我。
禁止批量删除文件或目录。
不要使用：
- `del /s`
- `rd /s`
- `rmdir /s`
- `Remove-Item -Recurse`
- `rm -rf`
需要删除文件时，只能一次删除一个明确路径的文件。
正确示例：
`Remove-Item "C:\path\to\file.txt"`
如果需要批量删除文件，应停止操作，并询问用户，让用户手动删除。
完成任务后，你需要检查更新docs文件夹下的md文件，以及按情况去更新AGENTS.md文件内容。

## github远程仓库地址

origin=https://github.com/vimself/ZhongMeiRagProject2.0.git

## 工程约定

- 项目采用 monorepo：`backend/`、`frontend/`、`docs/`、`ops/`、`docker/`、`DeepseekOcrApi/`。
- 后端目标运行时为 Python 3.11 + FastAPI + Celery。
- 前端目标运行时为 Vue 3 + TypeScript + Vite。
- 基础设施通过 Docker Compose 启动，配置文件集中放在 `ops/` 和 `docker/`。
- OCR 服务使用自托管 DeepSeek-OCR-2，部署在校园网工作站 `222.195.4.65:8899`；本机开启校园网 VPN 后直接访问工作站 API，工作站回调 Windows 本机时通过 SSH 反向隧道连接。

## 当前实现状态

- Stage 1 基础设施与工程骨架已完成，进度记录见 `docs/stage-1-infrastructure-progress.md`。
- Stage 2 数据层与认证内核已完成，进度记录见 `docs/stage-2-data-auth-progress.md`。
- Stage 3 用户与后台管理已完成，进度记录见 `docs/stage-3-user-admin-progress.md`。
- Stage 4 知识库骨架已完成，进度记录见 `docs/stage-4-knowledge-base-progress.md`。
- Stage 5 入库链路核心已完成，进度记录见 `docs/stage-5-ingest-progress.md`。
- Stage 6 文档预览与 RAG 元数据闭环已完成，进度记录见 `docs/stage-6-document-preview-rag-progress.md`。
- 后端认证入口统一位于 `/api/v2/auth/*`，包含登录、刷新、登出、改密与当前用户查询。
- 个人中心 API 位于 `/api/v2/user/*`，包含资料读取/更新、头像上传/删除、改密。
- 管理员 API 位于 `/api/v2/admin/*`，包含用户 CRUD、重置密码、停用、审计日志查询、知识库管理。
- 知识库 API 位于 `/api/v2/knowledge-bases/*`，包含 CRUD、权限管理（owner/editor/viewer）。
- 文档入库 API 位于 `/api/v2/knowledge-bases/{kb_id}/documents` 与 `/api/v2/documents/*`，包含 PDF 上传、列表、详情、进度、重试与软停用。
- 入库链路通过 Celery `ingest` 队列执行，核心步骤为 OCR 上传/轮询、章节解析、章节感知切片、embedding、Track A/B 写入、资产登记和 finalize。
- OCR 客户端位于 `backend/app/services/ocr/client.py`，兼容 DeepseekOcrApi 新版 `/healthz`、`/queue`、扩展 `/status`、`/assets` 与旧版 markdown/images/base64 端点。
- `knowledge_chunks_v2` 在本地 SQLite 测试中使用 JSON 存储 `vector`/`sparse`；SeekDB 迁移会尝试启用 `VECTOR(1024)` / `SPARSE_VECTOR` 和索引，如当前本地 SeekDB 镜像不支持对应 DDL，则保留 JSON/fallback 检索路径并继续启动。
- 知识库权限矩阵：admin 完全管理、owner 可编辑删除管理权限、editor 可编辑、viewer 只读。
- 知识库权限候选用户接口位于 `/api/v2/knowledge-bases/{id}/permission-candidates`，owner/admin 可用；管理员可通过 `/api/v2/admin/knowledge-bases/{id}/permissions` 查看任意知识库权限记录（包括已停用知识库）。
- 知识库写操作审计 action 包含 `knowledge_base.create`、`knowledge_base.update`、`knowledge_base.disable`、`knowledge_base.permissions.update`，均需记录操作者。
- 首次部署创建管理员账号时，在迁移完成后运行 `python -m app.cli.seed_admin`，并确保 `ADMIN_SEED_PASSWORD` 已配置为非示例值。
- 头像文件存储在 `uploads/avatars/{user_id}/` 目录，Docker Compose 通过 `uploads-data:/app/backend/uploads` 持久化。
- 前端 `.stylelintrc.json` 配置了 Vue `:deep` 伪类支持，修改样式时请注意。
- Stage 4/5 不迁移旧 RAG 项目数据，所有测试数据均为新建数据。抛弃旧版本的数据库表设计和所有数据，全部按系统架构重新设计，并创建新的数据进行测试。
- 文档 OCR 识别使用校园网工作站自托管 DeepSeek-OCR-2 API（`222.195.4.65:8899`），代码位于 `DeepseekOcrApi/` 目录，API 采用异步上传-轮询-下载模式，并支持通过 `OCR_CALLBACK_BASE_URL` 接收工作站完成/失败回调。
- PDF 预览 API 位于 `/api/v2/pdf/*`：`POST /api/v2/pdf/sign` 签发 5 分钟短时 JWT，`GET /api/v2/pdf/preview` 支持 HTTP Range（`200/206/416`）。Token 含 `sub`、`doc`、`kb`、`scope=pdf_preview`，校验用户、文档、KB 权限、文档未停用。
- PDF 下载 API 位于 `GET /api/v2/documents/{document_id}/download?token=`，复用 PDF 短时 token。
- 文档资产预览 API 位于 `/api/v2/assets/*`：`POST /api/v2/assets/sign` 签发 5 分钟资产 token，`GET /api/v2/assets/preview` 校验资产、文档、KB 权限后返回文件。
- RAG 检索服务位于 `backend/app/services/rag/retriever.py`，`Retriever` 类实现 Track A 向量召回 + Track B BM25 召回 + RRF 融合（K=60）。SeekDB 原生 `cosine_distance` / `MATCH ... AGAINST` 优先，SQLite 或当前 SeekDB DDL/查询不支持时使用 Python 余弦相似度和词频打分 fallback。
- `POST /api/v2/retrieval/debug`（admin 权限）已升级为正式检索冒烟 API，返回 Stage 7 引用协议字段（含短时 `preview_url` 与 `download_url`）。
- 前端 PDF 查看器基于 `pdfjs-dist`，组件位于 `frontend/src/components/PdfViewer.vue`，支持页码跳转、缩放、bbox 高亮覆层。
- 文档权限校验共享函数 `require_document_role()` 位于 `backend/app/api/knowledge_base_deps.py`。
- PDF/资产预览审计 action：`pdf.sign`、`pdf.preview`、`pdf.download`、`asset.sign`、`asset.preview`。
