# 2026-05-13 · 知识库与文档物理删除改造

## 背景

原知识库和文档删除实际是软删除：知识库写 `is_active=false`，文档写 `status='disabled'`。这能隐藏业务入口，但旧 OCR 结果、向量数据和文档记录仍在数据库中，后续检索或历史引用处理容易产生过时数据风险。

本次将知识库和文档生命周期统一调整为物理删除。

## 删除策略

### 知识库删除

`DELETE /api/v2/knowledge-bases/{id}` 仅允许管理员执行。删除前后端会提醒用户“删除后无法找回”。

后端删除顺序：

1. 收集知识库下所有文档及文件资产路径。
2. 将关联 `chat_sessions.knowledge_base_id` 置空，保留用户历史问答文本。
3. 删除该知识库对应的 `chat_message_citations`，避免历史会话继续生成已删除文档的预览/下载引用。
4. 删除文档相关数据：`knowledge_chunks_v2`、`knowledge_page_index_v2`、`document_parse_results`、`document_assets`、`document_ingest_jobs`、`ingest_step_receipts` 和 `documents`。
5. 删除 `knowledge_base_permissions` 与 `knowledge_bases`。
6. 提交事务后，按数据库记录的单个文件路径逐个清理上传 PDF、markdown 和资产文件；不会递归删除目录。

这样不需要先通过 API 逐个删除文档，知识库删除服务会在同一事务中集中清理数据库依赖，避免中间状态残留。

### SeekDB 删除兼容

SeekDB/OceanBase 在 `documents`、`knowledge_bases` 这类带 `ON DELETE CASCADE` 外键的父表执行物理删除时，可能在已手动清空子表后仍返回 `4016 Internal error`。删除服务不会依赖数据库级联删除：应用层先显式删除 OCR、资产、入库任务、向量/稀疏索引、权限和 citation 等子表记录，然后仅在 MySQL/SeekDB 会话内短暂关闭 `FOREIGN_KEY_CHECKS` 执行父表删除，并在 `finally` 中恢复检查。

### 文档删除

`DELETE /api/v2/documents/{id}` 仍要求 owner/admin。删除文档会物理删除该文档的元数据、OCR 解析结果、资产登记、入库任务、Track A 向量/稀疏索引和 Track B 页索引，并清理历史聊天中指向该文档的 citation。

如果用户在文档入库途中删除文档，删除接口会先将文档标记为 `deleting`，并将未完成的入库任务标记为 `cancel_requested`，随后执行统一物理清理。Celery 入库任务在 OCR、解析、embedding、向量入库、资产登记和 finalize 等步骤边界都会重新检查文档/任务状态；如果发现文档已删除、正在删除或任务已请求取消，会停止后续写入，尽量清理 OCR session，并返回 `cancelled`，不会把该任务写入失败死信。列表、检索和搜索会排除 `deleting` 文档，避免删除中的文档继续进入 RAG 或知识检索。

新增批量删除接口：

`DELETE /api/v2/knowledge-bases/{kb_id}/documents`

请求体：

```json
{
  "document_ids": ["doc-id-1", "doc-id-2"]
}
```

接口按同一知识库校验所有文档 ID，任一 ID 不存在或不属于该知识库时返回 404，避免跨知识库误删。

## 聊天历史影响

知识库删除后，历史会话不会被删除，用户仍可查看问答文本；但会话不再绑定已删除知识库，历史 citation 会被清理，右侧证据面板和预览/下载链接不再指向已删除文档。

如果用户继续一个已解绑的历史会话，并选择了新的可访问知识库，后端会将该会话重新绑定到新的知识库；如果会话仍绑定其他知识库，则继续保持原有一致性校验。

## 前端变化

- `/admin/knowledge-bases` 删除确认文案改为明确说明不可恢复、会物理删除知识库/文档/OCR/向量数据，并解除历史会话绑定。
- 管理员知识库列表移除“已删除”状态筛选和删除时间列，因为删除后不再保留知识库档案行。
- `/knowledge/:kbId/documents` 单文档删除确认文案改为不可恢复说明。
- 文档列表新增多选列和“批量删除”按钮，批量删除前同样提示不可恢复。

## 审计 Action

- 知识库删除：`knowledge_base.delete`
- 单文档删除：`document.delete`
- 批量文档删除：`document.delete.batch`

旧 `knowledge_base.disable` / `document.disable` 不再由新删除流程写入；前端审计展示仍兼容历史日志。

## 验证

- `.venv\Scripts\python.exe -m pytest tests/test_documents_api.py tests/test_knowledge_base.py tests/test_chat_api.py`：68 passed
- `.venv\Scripts\ruff.exe check app/api/documents.py app/api/knowledge_base.py app/api/chat.py app/services/deletion.py tests/test_documents_api.py tests/test_knowledge_base.py`：All checks passed
- `npm run build`：通过
- 2026-05-13 修复 SeekDB 删除父表 `4016 Internal error` 后，补充验证：
  - `..\.venv\Scripts\python.exe -m pytest tests/test_documents_api.py tests/test_knowledge_base.py`：60 passed
  - `..\.venv\Scripts\python.exe -m ruff check app/services/deletion.py app/api/documents.py app/api/knowledge_base.py tests/test_documents_api.py tests/test_knowledge_base.py`：All checks passed
  - Docker API 上验证 `DELETE /api/v2/documents/{id}` 与 `DELETE /api/v2/knowledge-bases/{kb_id}/documents` 均返回 200，临时验证文档删除后数据库剩余数为 0。
- 2026-05-13 增加上传/入库途中删除的取消收敛逻辑后，补充验证：
  - `..\.venv\Scripts\python.exe -m pytest tests/test_ingest_task.py tests/test_documents_api.py tests/test_knowledge_base.py tests/test_retriever.py tests/test_search_dashboard.py`：95 passed
  - `..\.venv\Scripts\python.exe -m ruff check app/services/deletion.py app/tasks/ingest.py app/api/documents.py app/api/knowledge_base.py app/api/knowledge_base_deps.py app/services/rag/retriever.py app/services/rag/search_service.py tests/test_ingest_task.py`：All checks passed

本次未执行任何批量删除文件或目录命令。
