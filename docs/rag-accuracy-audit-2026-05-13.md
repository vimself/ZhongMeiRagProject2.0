# 2026-05-13 RAG 准确度专项审查

## 审查目标

本次审查只围绕一个目标：提升“文档上传 → OCR → 解析 → 切片 → 入库 → Track A/B 检索 → RAG 生成 → 前端引用返回”整条链路的**答案准确度、证据可追溯性和用户信赖度**，并且**不脱离现有技术栈**：

- OCR 继续使用 `DeepSeek-OCR-2`
- 数据库继续使用 `SeekDB`
- Embedding 继续使用阿里 `qwen3-vl-embedding`
- Chat / Query Rewrite 继续使用阿里 `qwen3.6-plus`
- Rerank 使用阿里官方 `qwen3-rerank`

## 当日已落地修复

### 1. 生成阶段不再只吃 200 字摘要

此前 `backend/app/services/rag/graph.py` 在 `build_prompt()` 中把引用上下文压成 `snippet`，导致模型经常看不到真正约束条件、数值要求和否定语句。现在已改为优先注入 `section_text` 全量证据块，`snippet` 只作兜底。

影响：

- 明显降低“检索命中但回答答偏”的概率
- 对施工规范、参数阈值、例外条件这类长句约束更友好

### 2. 正式接入 `qwen3-rerank`

当前检索已在 `Retriever` 和 chat graph 中接入官方重排序能力：

- `backend/app/services/llm/client.py`
- `backend/app/services/rag/reranker.py`
- `backend/app/services/rag/retriever.py`
- `backend/app/services/rag/graph.py`

实现策略：

- 先做向量召回 + BM25/稀疏召回 + RRF
- 再把候选块送入 `qwen3-rerank`
- `rerank` 只负责**重排顺序**，不再覆盖原始融合分数，避免把“相对分数”误当成跨请求阈值使用

### 3. 多轮聊天开始具备历史感知检索改写

此前 `/api/v2/chat/stream` 的检索完全按当前这一问执行，`CHAT_HISTORY_LIMIT` 配了但没有进入检索链路。现在已补齐：

- `backend/app/api/chat.py` 会加载最近会话历史
- `backend/app/services/rag/graph.py` 新增最近对话驱动的独立检索问句改写
- 改写继续复用 `qwen3.6-plus`，不引入额外模型

效果：

- “那这个标准适用于哪里？”
- “上面这个材料还有温度要求吗？”
- “那人员配置要求呢？”

这类追问不再只按字面做单轮召回。

### 4. 聊天引用预览恢复到真实 `preview_url + bbox`

此前 `frontend/src/views/ChatView.vue` 点引用时重新走 `/pdf/sign` 并新开页，导致后端已生成的 `preview_url`、`#bbox=...` 和页内高亮能力被绕掉。现在已改为直接复用 `PreviewModal.vue` 和 `PdfViewer.vue` 现有链路。

效果：

- 引用点击与检索证据使用同一份定位信息
- 前端终于能消费后端已经签发的 `preview_url`

## 当前仍然存在的高风险缺口

### P0. 页码与 bbox grounding 仍然不够真实

这是当前最影响“用户能否 99% 信任系统”的问题。

现状：

- `backend/app/services/ingest/outline_parser.py` 通过 `<--- Page Split --->` 记录页边界
- `backend/app/services/ingest/chunker.py` 仍然按章节切块，块只继承 section 级 `page_start/page_end`
- `backend/app/services/ingest/track_a_indexer.py` 写入 `knowledge_chunks_v2` 时把 `bbox_json` 固定为 `None`
- `backend/app/services/ingest/track_b_indexer.py` 只是按 `chunk.page_start` 聚合页文本

后果：

- 回答看起来像“引用了第 37 页”，但模型实际吃到的是章节块，不一定真对应那一页
- bbox 高亮只在少数链路成立，chat 侧证据锚点并不稳定
- 表格、列表、跨页条款、图文混排内容最容易出现“答对了大意，点开对不上位置”

建议：

1. 在 OCR 解析阶段保留**页块级文本锚点**，而不是只保留 markdown 长文本。
2. 切片从“章节级 chunk”升级为“章节约束下的页块/语义块 chunk”，每个 chunk 必须带真实 `page_start/page_end`。
3. `bbox` 不应只有单框；对跨块内容建议存 `bbox_list` 或 `anchor_blocks`。
4. 表格块和段落块分流建模，避免把 OCR 表格压扁后再嵌入。

### P0. `knowledge_page_index_v2` 已写入，但没有进入检索闭环

现状：

- `backend/app/services/ingest/track_b_indexer.py` 已持续写 `knowledge_page_index_v2`
- 但 `backend/app/services/rag/retriever.py` 的原生查询仍然只查 `knowledge_chunks_v2`
- chat graph 中的 `Track B` 实际也还是 chunk 级 BM25/稀疏召回，不是设计文档里承诺的“页级检索”

后果：

- 页级结构索引花了入库成本，但召回时没有产出收益
- 对“第几页、哪个表、哪段说明”的问题，系统少了一层很重要的 recall expansion

建议：

1. 先在 `knowledge_page_index_v2` 上做页级 BM25 或 hybrid topN。
2. 再用 `section_map_json` 把命中页扩展回候选 chunk。
3. 最后让 `qwen3-rerank` 在“页候选扩展后的 chunk 集合”上做最终排序。

这是最符合当前 SeekDB 能力、同时收益最高的 Track B 补全方式。

### P1. 稀疏检索特征仍然过于原始

现状：

- `backend/app/services/rag/vector_utils.py` 的 `text_term_weights()` 主要依赖 ASCII token、中文单字和中文二元组

后果：

- 对规范编号、章节号、单位、缩写、型号、材料牌号、温度区间等工程问法不够敏感
- 会出现“语义像但关键词不准”或“关键词有但稀疏侧加权不够”的问题

建议：

1. 增加数字/单位归一化，如 `5℃`、`5°C`、`5 度` 统一。
2. 增加工程领域词项增强：标准号、图号、材料型号、章节编号、表号。
3. 对标题、章节路径、表头词给予更高 lexical boost。

### P1. 缺少检索质量纠偏器和回答可答性判断器

现状：

- `should_answer()` 仍以融合分数阈值为主
- 当前没有真正的“证据够不够回答这个问题”的判定节点

后果：

- 检索到了“相关但不充分”的块时，模型仍可能组织出貌似合理但其实证据不足的答案
- “无法在知识库中找到依据” 的触发条件仍然偏粗

建议：

1. 在 `dedupe_citations` 之后增加一个轻量 `evidence_judge` 节点。
2. 输入：用户问题 + top3 citations。
3. 输出：`answerable / partially_answerable / no_evidence`。
4. 该节点继续复用 `qwen3.6-plus` 即可，不需要换模型。

这一步本质上是把 CRAG / Self-RAG 里的“检索后自我反思”做成工程化简化版。

### P1. 缺少持续 RAG 评测集和 claim 级诊断

如果没有评测集，系统就只能凭体感优化。

建议至少建立三层评测：

1. `retrieval recall@k / MRR / citation hit`
2. `answer groundedness / no-answer precision`
3. `claim-level entailment`，专门检查回答中的每条断言是否真被引用支撑

建议覆盖的问题类型：

- 定义型
- 阈值/数值型
- 条件/例外型
- 多段汇总型
- 多轮追问型
- 表格定位型
- 页码定位型

## 与官方资料和一手论文的对照结论

### 阿里官方 `qwen3-rerank`

阿里官方文档明确把 `qwen3-rerank` 定位为文本搜索和 RAG 场景的重排序模型，并说明：

- 适用于 RAG
- 单次最多 500 文档
- 单条文档最多 4,000 tokens
- 分数是**当前请求内的相对分数**，不适合作为跨请求绝对阈值

因此本次实现里把 rerank 用作**排序器**而不是**绝对分数判定器**，这是正确方向。

### SeekDB 官方 hybrid search

SeekDB 官方文档强调 hybrid search 的价值在于：

- 向量召回补语义
- 全文检索补精确关键词、数字、专有名词
- 可以调权重，不应只停留在静态等权融合

这意味着你当前的 `RRF + chunk 级 lexical` 只是合格基线，还不是终态。后续要么做 `page index -> chunk expand -> rerank`，要么做 query-aware boost。

### DeepSeek-OCR-2 官方论文

DeepSeek-OCR-2 的核心价值是复杂版面下的语义感知视觉顺序建模。换句话说，它的优势本来就在**布局理解**。如果入库阶段最后只保留“长 markdown 文本 + 粗页码”，那就把 OCR 模型最宝贵的布局能力在数据层面丢掉了。

### Self-RAG / CRAG / RAG-Fusion / RAGChecker

这些一手论文给当前系统的直接启示不是“照论文抄一套大系统”，而是四件非常务实的事：

1. 多轮和复杂问题要做 query rewrite 或多视角 query expansion。
2. 检索后必须有 evidence quality check，不能只靠原始召回分。
3. 混合检索要和 rerank 配合，不能停留在单次静态融合。
4. 必须建设细粒度评测，否则优化无法闭环。

## 推荐落地顺序

### 第一优先级

1. 把 chunk/page/bbox 锚点做真实。
2. 让 `knowledge_page_index_v2` 真正参与 Track B。
3. 保证表格、列表、跨页条款都能稳定落到证据锚点。

### 第二优先级

1. 对 Track A/B 融合后的候选做 `qwen3-rerank`。
2. 在 rerank 后补 `evidence_judge`。
3. 把多轮历史改写扩展到搜索接口和检索调试接口。

### 第三优先级

1. 建立 100~200 条工程问题黄金集。
2. 每次改 chunking / retrieval / prompt / OCR parser 都跑回归。
3. 把“答案正确率、引用命中率、无依据拒答准确率”做成 dashboard。

## 当日验证

- `pytest backend/tests/test_dashscope_client.py backend/tests/test_chat_graph.py backend/tests/test_retriever.py backend/tests/test_chat_api.py`：`34 passed`
- `npm run build`：通过

## 参考资料

- 阿里云 Model Studio `qwen3-rerank` 官方文档：[重排序 Reranking API](https://help.aliyun.com/zh/model-studio/rerank)
- 阿里云 Model Studio OpenAI 兼容 rerank 接口：[通用文本排序模型 API 使用详情](https://help.aliyun.com/zh/model-studio/text-rerank-api)
- 阿里云 Model Studio 向量与重排序模型概览：[向量与重排序](https://help.aliyun.com/zh/model-studio/embedding-rerank-model)
- SeekDB 官方说明：[seekdb 官网](https://www.seekdb.ai/)
- SeekDB 官方 hybrid search 文档：[Hybrid search with vector indexes](https://www.oceanbase.ai/docs/vector-index-hybrid-search/)
- SeekDB hybrid 参数调优示例：[Experience hybrid search](https://www.oceanbase.ai/docs/V1.0.0/experience-hybrid-search/)
- DeepSeek-OCR-2 官方论文：[DeepSeek-OCR 2: Visual Causal Flow](https://arxiv.org/abs/2601.20552)
- Self-RAG 论文：[Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511)
- CRAG 论文：[Corrective Retrieval Augmented Generation](https://arxiv.org/abs/2401.15884)
- RAG-Fusion 论文：[RAG-Fusion: a New Take on Retrieval-Augmented Generation](https://arxiv.org/abs/2402.03367)
- RAGChecker 论文：[RAGCHECKER: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation](https://arxiv.org/abs/2408.08067)
