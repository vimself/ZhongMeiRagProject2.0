## 用户要求

总是使用中文回答。
禁止批量删除文件或目录（`del /s`、`rd /s`、`rmdir /s`、`Remove-Item -Recurse`、`rm -rf`）。
删除文件只能一次删除一个明确路径的文件，需要批量删除时停止操作并询问用户。
完成任务后检查更新docs文件夹和AGENTS.md。
前端代码更改只在代码层面review，不需要应用内浏览器检验。

## GitHub 远程仓库

origin=https://github.com/vimself/ZhongMeiRagProject2.0.git

## 工程约定

- Monorepo 结构：`backend/`、`frontend/`、`docs/`、`ops/`、`docker/`、`DeepseekOcrApi/`
- 后端：Python 3.11 + FastAPI + Celery
- 前端：Vue 3 + TypeScript + Vite
- 基础设施：Docker Compose，配置文件在 `ops/` 和 `docker/`
- OCR 服务：自托管 DeepSeek-OCR-2（校园网工作站 `222.195.4.65:8899`），通过 SSH 反向隧道回调

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

- **入库链路**：Celery `ingest` 队列，流程为 OCR→章节解析→切片→embedding→Track A/B→资产登记→finalize
- **入库前端状态**：正常流转统一展示为排队、OCR、Embedding、向量入库、完成；失败仅作为异常状态显示
- **RAG 检索**：Track A 向量召回 + Track B BM25/稀疏召回 + RRF 融合（K=60）+ `qwen3-rerank`
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

- 聊天三栏布局：MessageList / Composer / CitationPane
- 引用展示：回答框参考文档 + 右侧证据面板，无命中不展示
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
