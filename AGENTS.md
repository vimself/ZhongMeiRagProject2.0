## 用户要求

总是使用中文回答。
禁止批量删除文件或目录（`del /s`、`rd /s`、`rmdir /s`、`Remove-Item -Recurse`、`rm -rf`）。
删除文件只能一次删除一个明确路径的文件，需要批量删除时停止操作并询问用户。
完成任务后检查更新docs文件夹和AGENTS.md。
前端代码更改只在代码层面review，不需要应用内浏览器检验。

## GitHub 远程仓库

origin=https://github.com/vimself/ZhongMeiRagProject2.0.git

## 工程约定

- Monorepo 结构：`backend/`、`frontend/`、`docs/`、`ops/`、`docker/`、`GlmOcrApi/`
- 后端：Python 3.11 + FastAPI + Celery
- 前端：Vue 3 + TypeScript + Vite
- 基础设施：Docker Compose，配置文件在 `ops/` 和 `docker/`
- Docker 持久化：SeekDB、Redis、后端上传文件使用项目目录固定 bind mount，默认分别为 `./data/seekdb`、`./data/redis`、`./uploads`；禁止使用 `docker compose down -v` 等会清除运行时数据的操作
- OCR 服务：自托管 GLM-OCR，`GlmOcrApi/` 启动 vLLM（默认 `127.0.0.1:18080`）和兼容 OCR API（默认 `0.0.0.0:8899`）；RAG 后端通过 `OCR_BASE_URL=http://host.docker.internal:8899` 上传、轮询并下载 Markdown/图片/版面 JSON。旧 `DeepseekOcrApi/` 已下线，不再作为入库服务启动。

## 实现状态

| Stage | 描述 | 进度文档 |
|-------|------|----------|
| 1 | 基础设施与工程骨架 | `docs/stage-1-infrastructure-progress.md` |
| 2 | 数据层与认证内核 | `docs/stage-2-data-auth-progress.md` |
| 3 | 用户与后台管理 | `docs/stage-3-user-admin-progress.md` |
| 4 | 知识库骨架 | `docs/stage-4-knowledge-base-progress.md` |
| 5 | 入库链路核心 | `docs/stage-5-ingest-progress.md` |
| 6 | 文档预览与 RAG 元数据闭环 | `docs/stage-6-document-preview-rag-progress.md` |
| 7 | RAG 问答链路 | `docs/stage-7-rag-chat-progress.md` |
| 8 | 搜索与仪表板 | `docs/stage-8-search-dashboard-progress.md` |

当前进度：Stage 8 已完成第一阶段 bug 修复，第二阶段优化进行中。

## API 端点

- **认证** `/api/v2/auth/*`：登录、刷新、登出、改密、当前用户
- **用户** `/api/v2/user/*`：资料、头像、改密
- **管理员** `/api/v2/admin/*`：用户 CRUD、审计日志、知识库治理
- **知识库** `/api/v2/knowledge-bases/*`：列表、详情、文档管理
- **文档** `/api/v2/documents/*`：上传（支持单次最多 50 份 PDF 批量入队）、列表、详情、进度、重试、删除
- **PDF** `/api/v2/pdf/*`：签名、预览（支持 Range）、下载
- **资产** `/api/v2/assets/*`：签名、预览
- **检索** `/api/v2/retrieval/debug`：检索冒烟测试
- **聊天** `/api/v2/chat/*`：SSE 流式问答、会话管理
- **搜索** `/api/v2/search/*`：全库搜索、热词、文档类型、导出
- **仪表板** `/api/v2/dashboard/*`：统计、数据库/Redis/OCR/LLM/运行时间系统状态、知识库治理近期操作

## 核心架构

- **入库链路**：Celery 拆分 `ingest-ocr` 与 `ingest` 队列。`worker-ingest-ocr` 默认单并发、`prefetch=1`，只负责 OCR 上传/轮询/拉取结果，保护 GLM-OCR/vLLM 质量和稳定性；OCR 完成后投递 `ingest.postprocess` 到 `worker-ingest`，由后处理队列并发执行章节解析、切片、embedding、Track A/B、资产登记和 finalize。这样批量上传时后端正在 embedding/向量入库，OCR 队列也能继续处理下一份文档。
- **OCR 解析**：GLM-OCR 官方 self-hosted pipeline 负责 PDF 页面渲染、PP-DocLayoutV3 版面检测、区域识别、Markdown 分页输出、图片裁剪和 JSON 版面信息；后端 `GlmOCRClient` 保持上传-轮询-下载协议，OCR/vLLM 短时不可用按临时异常退避重试。
- **页索引保护**：`knowledge_page_index_v2.text` 是辅助页级索引，默认按 `INGEST_PAGE_INDEX_TEXT_MAX_BYTES=49152` 做 UTF-8 安全截断；完整 RAG 证据以 `knowledge_chunks_v2` 切片为准
- **入库前端状态**：正常流转统一展示为排队、OCR、Embedding、向量入库、完成；失败仅作为异常状态显示
- **RAG 检索**：Track A 向量召回 + Track B BM25/稀疏召回 + RRF 融合（K=60）+ `qwen3-rerank`；`/chat` 支持单知识库和 `kb_id="__all__"` 全部知识库问答，后端按当前用户权限展开为可访问的全部启用知识库
- **RAG Graph**：plan_query→contextualize_query→retrieve_track_a/b→rrf_fusion→rerank→dedupe→should_answer→generate_stream→rewrite→persist
- **LLM**：DashScope qwen3-vl-embedding（embedding）、qwen3.6-plus（聊天/历史感知 query rewrite）、`qwen3-rerank`（重排序），429 降级 qwen3-turbo
- **搜索服务**：复用 Retriever，跨 KB 串行聚合
- **导出**：Celery 异步任务，生成 JSON/CSV + metadata ZIP

## 数据设计

- 知识库/文档删除为物理删除：删除知识库会清理其文档、OCR 解析、资产、向量/稀疏索引、权限记录，并解除历史聊天会话的知识库绑定；删除文档会清理对应文档记录、OCR 解析、资产、入库任务和向量/稀疏索引。
- 系统业务时间记录统一使用北京时间（Asia/Shanghai, UTC+8），API 时间输出统一带 `+08:00` 偏移；JWT 协议过期校验仍按 UTC 处理。
- 聊天引用不落库 `preview_url`/`download_url`，每次重新签发 5 分钟 JWT
- SeekDB 使用原生向量/稀疏向量/全文索引，SQLite 测试用 JSON fallback
- 默认账号：admin 和 user，通过 `seed_default_users` 初始化

## 前端规范

- 聊天三栏布局：MessageList / Composer / CitationPane；知识库下拉包含“全部知识库”虚拟选项，用于跨当前用户可访问的所有启用知识库检索
- 引用展示：回答框参考文档 + 右侧证据面板，无命中不展示；引用按相关度 `score` 降序展示，两个区域保持同一顺序
- 聊天引用跳转：点击右侧参考文档详情直接新开 `/api/v2/pdf/preview?...#page={page_start}`，不在 `/chat` 内嵌预览窗口
- PDF 预览：pdfjs-dist + bbox 高亮覆层
- 视觉风格：白色极简 RAG 工作台，主色 teal `#0F766E`，禁止紫色渐变

## 环境变量（Stage 7/8 新增）

```
DASHSCOPE_NATIVE_BASE_URL
DASHSCOPE_CHAT_MODEL_FALLBACK
DASHSCOPE_CHAT_ENABLE_THINKING
DASHSCOPE_EMBEDDING_DIMENSION
CHAT_HISTORY_LIMIT
CHAT_MIN_SCORE_THRESHOLD
CHAT_TOPK
CHAT_NO_HIT_MESSAGE
DASHSCOPE_RERANK_MODEL
RAG_RERANK_ENABLED
RAG_RERANK_MAX_CANDIDATES
EXPORT_DIR
UPLOAD_MAX_FILES
```

## 审计 Action

认证：`auth.login`、`auth.refresh`、`auth.logout`、`auth.change_password`
用户：`user.profile.update`、`user.avatar.upload`、`user.avatar.delete`、`user.password.change`
知识库：`knowledge_base.create`、`knowledge_base.update`、`knowledge_base.delete`、`knowledge_base.permissions.update`
文档：`document.upload`、`document.retry`、`document.delete`、`document.delete.batch`
PDF/资产：`pdf.sign`、`pdf.preview`、`pdf.download`、`asset.sign`、`asset.preview`
搜索/仪表板：`search.documents`、`search.export`、`dashboard.view`、`dashboard.system_status`
