# Stage 7 · RAG 问答链路 进度报告

## 目标

在 Stage 6（PDF 预览 + RAG 元数据闭环）之上打通端到端的 RAG 问答链路：
把 Track A 向量 + Track B BM25 的召回、RRF 融合、去重、引用重写，以及
DashScope 流式生成、无命中兜底、会话历史、引用预览 token 重签等串起来，
并提供白色极简的工程 RAG 工作台前端。

## 主要交付

- 后端 LangGraph 风格节点化 RAG pipeline，覆盖 plan_query → retrieve_track_a/b
  → rrf_fusion → dedupe_citations → should_answer → generate_stream →
  rewrite_citations → persist。
- SSE 聊天 API `POST /api/v2/chat/stream`，依次下发 `references` / `content`
  / `done` / `error` 事件。
- 会话历史 API：`GET /api/v2/chat/sessions` 列表、
  `GET /api/v2/chat/sessions/{id}` 详情（每次调用都重新签发引用
  `preview_url` / `download_url`，不持久化短时 token）、
  `DELETE /api/v2/chat/sessions/{id}` 软删除。
- 数据库新增 `chat_sessions` / `chat_messages` / `chat_message_citations`
  / `rag_eval_runs`，Alembic 迁移 `20260510_stage_6_pdf_preview_rag.py`
  随 Stage 6 并入，Stage 7 迁移位于 Stage 6 迁移之后。
- DashScope 客户端支持 429 按配置降级到 `qwen3-turbo`。
- DashScope embedding 已兼容 `qwen3-vl-embedding` 的原生多模态
  embedding 端点；chat 仍走 OpenAI 兼容 `/chat/completions`，SSE 只向前端透出
  `delta.content` 文本。
- SeekDB 原生检索已启用：`vector_native VECTOR(1024)` + HNSW、
  `sparse_native SPARSEVECTOR` + SINDI、`content` + NGRAM FULLTEXT，同时保留
  JSON `vector`/`sparse` fallback。
- 前端新增 `views/ChatView.vue` 与 `features/chat/*`（MessageList、
  Composer、CitationCard、CitationPane、PreviewModal），路由 `/chat`，
  首页 RAG 问答卡片直达。
- 评测骨架 `eval/ragas_runbook.py` + 20 条中文工程金标数据
  `eval/golden_cases.json`，支持启发式指标 + 可选 ragas。

## 接口协议

### `POST /api/v2/chat/stream`

请求体：

```json
{
  "kb_id": "<uuid>",
  "question": "施工现场临时用电如何设置？",
  "session_id": null,
  "k": 6
}
```

响应为 `text/event-stream`，严格依次推送：

1. `event: references`
   ```json
   { "session_id": "…", "references": [ ChatCitation, … ] }
   ```
2. `event: content`
   ```json
   { "delta": "……" }
   ```
3. `event: done`
   ```json
   {
     "session_id": "…",
     "finish_reason": "stop",
     "model": "qwen3.6-plus",
     "citations": 6,
     "min_score_threshold": 0.05
   }
   ```
4. 任意环节失败 → `event: error` `{ "message": "…" }`。

`ChatCitation` 字段（12 项）：

```
id, index, chunk_id, document_id, document_title, knowledge_base_id,
section_path[], section_text, page_start, page_end,
bbox{x,y,width,height}, snippet, score, preview_url, download_url
```

- `preview_url` / `download_url` 为 **短时 token**，每次读取会话详情/流式
  回答都会 **重新签发**（5 min 有效），不落库。
- `content` 里的 `[cite:i]` 将在 `rewrite_citations` 节点统一改写为
  `^[n]`，`n` 与 references 中的 `index` 对应。

### 历史会话

- `GET /api/v2/chat/sessions?page=&page_size=`：分页返回 `ChatSessionSummary`。
- `GET /api/v2/chat/sessions/{session_id}`：返回完整消息 + 引用；每次调用
  都重新签发预览 token。
- `DELETE /api/v2/chat/sessions/{session_id}`：软删除（`is_active=false`）。

## 图节点说明

| 节点 | 作用 |
|------|------|
| `plan_query` | 归一化问题、补齐检索参数（topk/阈值）、落在 `GraphState` |
| `retrieve_track_a` | SeekDB 原生向量召回优先，失败时走 Python 向量 fallback |
| `retrieve_track_b` | SeekDB BM25 / SPARSEVECTOR 召回优先，失败时走词频 fallback |
| `rrf_fusion` | K=60 的 Reciprocal Rank Fusion |
| `dedupe_citations` | 按 `document_id+section_path+page_start` 去重 |
| `should_answer` | 若 `max(score) < chat_min_score_threshold` 则走无命中兜底 |
| `generate_stream` | DashScope 流式生成，429 自动降级到 `qwen3-turbo` |
| `rewrite_citations` | `[cite:i]` → `^[n]`，只保留实际命中的引用 |
| `persist` | 写入 `chat_sessions/messages/citations`，引用仅保存稳定元数据 |

无命中兜底：`chat_no_hit_message`，默认为 **「无法在知识库中找到依据，建议
换个问法或先上传相关文档。」**。

## 前端架构

- 路由：`/chat`。
- 布局：三栏
  - 左侧 `chat-sidebar`：返回首页 / 知识库下拉 / 新建对话 / 历史会话列表。
  - 中间 `chat-main`：顶部状态条、消息滚动区、底部 `Composer`。
  - 右侧 `CitationPane`：实时证据面板，hover 可点开 `PreviewModal`。
- 引用交互：
  - 内容中的 `^[n]` 渲染为 `.cite-chip`（圆角胶囊）。
  - `hover` → `ElPopover` 展示紧凑 `CitationCard`。
  - `click` → `PreviewModal`，左侧复用 Stage 6 `PdfViewer`，按
    `page_start + bbox` 高亮原文；右侧展示文档、章节路径、页码、
    相关度、snippet、下载原文按钮。
- 状态管理：`stores/chat.ts`（Pinia），含
  `sessions/activeSessionId/activeKbId/messages/latestReferences/
  streaming/error/abortController`。`sendQuestion` 通过
  `@microsoft/fetch-event-source` 打开 SSE，支持 `stop` 中断。
- 视觉语言：白色/off-white 背景（`#FAFAF9` / `#FFFFFF`）、细灰边框
  `#E5E7EB`、主色 `#0F766E`（teal）、文字 `#111827`/`#6B7280`、
  克制阴影、不使用紫色 AI 渐变，移动端 `<880px` 退化为单列，
  隐藏右侧证据面板。

## 新增/变更环境变量

```
DASHSCOPE_CHAT_MODEL=qwen3.6-plus
DASHSCOPE_CHAT_MODEL_FALLBACK=qwen3-turbo
DASHSCOPE_NATIVE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_EMBEDDING_MODEL=qwen3-vl-embedding
DASHSCOPE_EMBEDDING_DIMENSION=1024
CHAT_HISTORY_LIMIT=50
CHAT_MIN_SCORE_THRESHOLD=0.05
CHAT_TOPK=6
CHAT_NO_HIT_MESSAGE=无法在知识库中找到依据，建议换个问法或先上传相关文档。
```

## 新增/变更依赖

- 后端：`sse-starlette` ^2.1,<3。
- 前端：`@microsoft/fetch-event-source` ^2.0.1、`markdown-it` ^14.1.0、
  `@types/markdown-it` ^14.1.2、`dompurify`。

> 未引入 LangGraph 运行时：Stage 7 使用手写的 async 节点 pipeline，
> `graph.py` 中保留了与 LangGraph 概念一致的可单测节点签名，便于后续
> 平滑迁移到 `langgraph` 包。

## 测试结果

- `backend/tests/test_chat_graph.py`：9 个节点级用例（plan_query、
  rrf_fusion、dedupe_citations、should_answer、rewrite_citations、
  build_reference_payload、SQLite fallback 引用、LLM 429 fallback、
  无命中兜底）全绿。
- `backend/tests/test_chat_api.py`：5 个 API 用例覆盖 SSE 事件顺序 +
  12 字段引用 payload、权限 403、无命中兜底、会话列表/详情 token
  重签、其他用户 404。
- `pytest backend/tests -q`：158 passed（SQLite fallback 下）。
- `npm run lint` / `npm run stylelint` / `npm run build`：通过。
- `npm audit --omit=dev`：0 vulnerabilities。
- `docker compose config --quiet`：通过。
- 容器 Alembic：`stage_7_rag_chat (head)`。
- DashScope 真实冒烟：`qwen3-vl-embedding` 返回 1024 维 embedding；
  `qwen3.6-plus` 流式响应可被解析为纯文本 delta。
- SeekDB 原生探针：`seekdb-v1.2.0.0` 下 `cosine_similarity`、
  `negative_inner_product`、`MATCH ... AGAINST` + NGRAM FULLTEXT 均可命中测试样本；
  `knowledge_chunks_v2` 已存在 `kcv_vec_native`、`kcv_sparse_native`、
  `kcv_content_ngram`。
- 前端构建产物 `dist/assets/ChatView-*.js ~149.61 kB`（gzip ~63.29 kB）。

## 评测目标与 Runbook

`eval/ragas_runbook.py` 用于离线评测：

```bash
python -m eval.ragas_runbook \
  --kb-id <kb_uuid> --user-id <user_uuid> \
  --golden eval/golden_cases.json --run-key stage7-smoke
```

- 启发式指标（默认启用）：关键字命中率、引用数、命中覆盖率，写入
  `rag_eval_runs.metrics_json`。
- 可选 ragas（`--ragas`）：调用 `faithfulness` / `answer_relevancy`，
  未安装 ragas 或无外部 LLM key 时自动跳过并在 `metrics.ragas.skipped`
  中标记。
- 目标：`faithfulness ≥ 0.75`、`answer_relevancy ≥ 0.8`。

## 剩余风险 / 待办

- DashScope 真实调用已通过最小冒烟；仍需用真实入库工程文档跑端到端问答，
  评估 `qwen3.6-plus` 在中文工程 prompt 下的引用遵循率和答案质量。
- SeekDB 原生向量/稀疏/全文检索已在当前本地镜像启用并通过函数探针；
  上生产前仍需对真实知识库规模验证查询计划、召回质量和索引资源占用。
- ragas 指标需外部 LLM key，当前仅作可选路径，未进 CI。
- 前端 Markdown 渲染已接入 DOMPurify；后续若开放更多 Markdown 插件或自定义
  HTML 白名单，需要重新做 XSS 回归。
- 会话标题目前取第一条用户消息前 30 字符，长期可考虑 LLM 摘要化。
