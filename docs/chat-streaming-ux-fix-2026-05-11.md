# Chat Streaming UX Fix - 2026-05-11

## 背景

用户在智能问答界面提问后，出现首字节等待时间长、答案不实时流式渲染、回答结束后页面空白且刷新后才显示的问题。

## 根因

- 后端在返回 `EventSourceResponse` 前先执行 query embedding、RAG 检索和引用构建，导致浏览器迟迟收不到 SSE 首个事件。
- `qwen3.6-plus` 开启思考模式时会先返回 `reasoning_content`，旧客户端只解析 `content`，用户只能看到空白等待。
- 前端 Pinia store 将临时 assistant message push 到响应式数组后，继续修改原始对象引用，部分增量没有触发界面更新。
- Prompt 对 Markdown 结构限制过强，回答更像纯文本段落；同时会把 `[cite:N]`
  和 OCR/LaTeX 片段直接带到正文，影响普通用户阅读。

## 修复

- `/api/v2/chat/stream` 先下发 `status` 事件，再进行检索；后续继续下发 `references`、可选 `reasoning`、`content`、`done`。
- DashScope 客户端新增 `stream_chat_events()`，同时解析 `reasoning_content` 和 `content`；`reasoning_content` 会转为 SSE `reasoning` 事件。
- 前端 `streamChat()` 支持 `status` 和 `reasoning` 事件。
- 前端 chat store 改为按 message id 更新 Pinia 响应式数组内的 assistant message，保证思考过程和正文都实时渲染。
- `MessageList` 新增思考过程折叠区；答案正文不再展示 `^[n]` 角标或悬浮引用卡片。
- 回答完成后，`MessageList` 在答案下方展示按文档去重的“参考文档”文件名，点击可打开 PDF 原文预览。
- 前端对常见 OCR/LaTeX 片段做可读化处理，例如 `$5^{\circ}C \sim 35^{\circ}C$`
  展示为 `5°C 至 35°C`。
- RAG prompt 改为更适合阅读的 Markdown 输出：先给直接结论，再给要点或表格；
  明确禁止输出引用编号、脚注和“引用依据/引用内容”段落。

## 配置

`DASHSCOPE_CHAT_ENABLE_THINKING=false` 仍为默认值，以保证最快正文输出。如需开启思考模式，可设置为 `true`；前端会展示思考过程，不再让用户空白等待。

## 验证

- `python -m pytest backend/tests/test_chat_graph.py backend/tests/test_chat_api.py -q`
- `python -m ruff check backend/app/services/llm/client.py backend/app/services/rag/graph.py backend/app/api/chat.py backend/tests/test_chat_graph.py backend/tests/test_chat_api.py`
- `npm run build`
