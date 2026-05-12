# Stage 8 · 搜索与仪表板 进度报告

## 目标

在 Stage 7（RAG 问答链路）之上实现全库搜索和管理员仪表板，不破坏现有 API、权限、测试和前端风格。

## 主要交付

### 后端

- 新增搜索 API：
  - `POST /api/v2/search/documents` — 全库搜索，支持 query、kb_id、doc_kind、content_type、日期范围、分页、排序。结果包含 Stage 7 引用协议全部字段（chunk_id、document_id、document_title、knowledge_base_id、section_path、section_text、page_start/page_end、bbox、snippet、score、preview_url、download_url），preview/download token 每次请求重新签发。当前搜索页不开放 `doc_kind` 筛选，但后端保留该字段以兼容将来的入库分类能力。
  - `GET /api/v2/search/hot-keywords` — 基于真实数据的关键词聚合，使用 `text_term_weights()` 分词。
  - `GET /api/v2/search/doc-types` — 文档类型聚合统计；`doc_kind=other` 表示上传时未指定更细分类的“其他/未分类”文档。
  - `POST /api/v2/search/export` — 异步导出 ZIP 任务。
  - `GET /api/v2/search/export/{job_id}` — 导出任务状态轮询。
  - `GET /api/v2/search/export/{job_id}/download` — 导出文件下载。
- 新增管理员仪表板 API：
  - `GET /api/v2/dashboard/stats` — 真实统计：用户、知识库、文档状态/类型、chunks、assets、聊天会话/消息、入库任务状态、最近活动、7/14 天趋势。
  - `GET /api/v2/dashboard/system-status` — 真实探活：SeekDB/数据库 ping、Redis ping、DashScope 健康检查。Redis 断开立即返回 down，DashScope 无 key 返回 not_configured。
- 搜索服务 `SearchService` 复用 `Retriever`（Track A/B + RRF），跨知识库搜索按可访问 KB 串行聚合，避免同一 `AsyncSession` 并发使用。
- 导出 Celery 任务 `search.export_generate`，生成 JSON/CSV + metadata ZIP 包。
- 新增 `search_export_jobs` 表，Alembic 迁移 `stage_8_search_dashboard`。
- 搜索/仪表板写操作审计：`search.documents`、`search.export`、`dashboard.view`、`dashboard.system_status`。

## 审计修复

- `SearchService` 不再在同一个 `AsyncSession` 上并发跨 KB 检索，避免 SQLAlchemy async session 并发使用导致的生产隐患；跨 KB 仍按用户可访问 KB 聚合。
- `content_type` 筛选已下沉到 `Retriever` 的 SQLite fallback 与 SeekDB native SQL 过滤条件，表格/图片/段落等内容类型过滤真实生效。
- 搜索导出任务已修复 `kb_id` 丢失问题，异步导出会严格沿用用户选择的知识库范围。
- 导出完成状态返回 5 分钟短时 `search_export` token 下载 URL，浏览器普通 `<a>` 下载无需 Bearer 头也能正常下载，且 token 校验 `sub` 与 `job` 范围。
- 仪表板趋势统计不再使用 SQLite 专属 `strftime()`，改为数据库无关的 Python 聚合，兼容 SeekDB/MySQL 风格数据库。
- DashScope 状态从“只要配置 key 就显示 ok”改为真实 `/models` 探活：无 key 为 `not_configured`，认证失败/网络失败为 `down`，非 2xx 非认证错误为 `degraded`。
- 前端导出弹窗使用后端返回的短时下载 URL；ECharts 被拆为独立 `charts` chunk，避免管理员仪表板页面主 chunk 被图表库放大。

### 前端

- 新增搜索页 `/search`：筛选栏（query、KB、排序）、热词快捷筛选、结果卡片、分页、空状态、加载态、导出 ZIP 按钮与异步进度。点击结果复用 `PreviewModal`（Stage 6/7）进行 PDF 预览 + bbox 高亮。由于当前上传入口未让用户选择文档类型，搜索页暂不展示文档类型筛选，避免把默认 `other` 误解为系统自动分类结果。
- 新增管理员仪表板 `/admin/dashboard`：统计概览卡片、7 天文档入库/聊天趋势折线图（ECharts）、文档类型饼图、系统状态灯（绿/红/黄/灰）、最近活动表格。
- 首页更新：Stage 标识更新到 Stage 8，新增「知识检索」卡片（所有用户）和「系统仪表盘」卡片（仅 admin）。
- 路由守卫：`/search` 需登录，`/admin/dashboard` 需 admin。
- 视觉语言与 Stage 7 一致：白色/近白背景、细灰边框、teal 主色 `#0F766E`、圆角 ≤ 8px。

## 新增/变更依赖

- 前端：`echarts` ^5.5.0、`vue-echarts` ^7.0.0

## 新增/变更环境变量

- `EXPORT_DIR`（默认 `uploads/exports`）— 导出文件存储目录

## 测试结果

- `backend/tests/test_search_dashboard.py`：17 个用例覆盖搜索权限隔离、跨 KB 搜索、筛选、`content_type` 过滤、引用协议字段、热词/类型聚合、导出创建与轮询、导出 `kb_id` 范围、短时 token 下载、dashboard admin 权限、stats 真实聚合、system-status admin 权限。
- `pytest backend/tests -q`：175 passed（Stage 8 新增/强化 17 个）。
- `ruff check backend eval`：通过。
- `mypy backend/app`：通过。
- `npm run lint` / `npm run stylelint` / `npm run build`：通过。
- `docker compose config --quiet`：通过。
- 容器 Alembic：`stage_8_search_dashboard (head)`。

> 备注：前端生产构建仍提示独立 `charts` chunk minified 体积约 534 kB（gzip 约 181 kB），该 chunk 仅管理员仪表板懒加载，不影响登录后首页/搜索/聊天首屏；当前未通过调高 Vite 阈值隐藏该提示。
