# 2026-05-12 · 知识库生命周期与权限语义修正

## 背景

人工测试发现知识库和文档生命周期语义不清：

- 普通用户可以看到并调用创建知识库入口。
- `/admin/knowledge-bases` 页面只有列表和权限查看，缺少明确的治理用途。
- `/knowledge` 同时暴露新建、删除和权限设置入口，与管理员知识库治理页职责重叠。
- 文档与知识库早期使用“停用”表述，2026-05-13 已统一调整为不可恢复的物理删除。

## 调整后的产品语义

1. 知识库创建和删除属于全局生命周期操作，只允许管理员执行。
2. owner/editor/viewer 是知识库内角色：owner/editor 可编辑知识库基础信息并管理知识库内部文档，viewer 只读；普通 owner 不再能删除整个知识库，也不能设置知识库权限。
3. 面向用户的文案统一使用“删除文档”“删除知识库”。2026-05-13 后端改为物理删除：
   - 知识库删除：删除 `knowledge_bases`、权限、文档、OCR 解析、资产、向量/稀疏索引，并解除历史聊天会话绑定。
   - 文档删除：删除 `documents`、OCR 解析、资产、入库任务、Track A/B 索引，并清理历史聊天中指向该文档的 citation。
4. 当前版本不提供恢复入口。管理员知识库页定位为全局生命周期治理页，集中提供创建、删除、权限设置、规模盘点、权限快照和审计记录查看。
5. `/knowledge` 是可访问知识库列表和详情入口，负责查看有权限的知识库、进入具体知识库文档管理和编辑知识库基础信息。

## 后端变更

- `POST /api/v2/knowledge-bases` 增加 admin 校验，普通用户返回 403。
- `DELETE /api/v2/knowledge-bases/{id}` 增加 admin 校验，普通 owner 返回 403。
- `PUT /api/v2/knowledge-bases/{id}/permissions` 与 `/permission-candidates` 增加 admin 校验，普通 owner 不能再管理权限。
- 新增 `/api/v2/admin/knowledge-bases/{id}/permission-candidates` 与 `PUT /api/v2/admin/knowledge-bases/{id}/permissions`，管理员页通过管理员路由完成权限设置。
- `KnowledgeBaseOut` 新增 `creator_username`、`creator_name`、`document_count`、`active_document_count`、`permission_count`、`deleted_at`，管理员列表展示创建者唯一用户名、文档规模和成员数量，不再只显示 UUID；展示名允许重复，用户名保持唯一。
- `require_document_role()` 校验文档和所属知识库仍存在，知识库或文档物理删除后文档详情、PDF、资产入口均不可访问。
- `Retriever` 仍兼容过滤历史 `documents.status='disabled'` 旧数据；新删除流程会直接清空文档和向量数据。
- 知识库物理删除前会将关联 `chat_sessions.knowledge_base_id` 置空，并删除对应 `chat_message_citations`，保留历史问答文本但不再暴露已删除文档引用。

## 前端变更

- `/knowledge` 改为“我的知识库”，只保留搜索、刷新、进入文档和编辑知识库基础信息；新建、删除、权限设置入口均移除。
- `/admin/knowledge-bases` 改为“知识库治理”，管理员可在此创建知识库、删除知识库、设置权限、查看文档规模、成员数量、权限快照和知识库审计记录。
- `/admin/knowledge-bases` 不提供文档入口，文档增删改查统一通过 `/knowledge/:kbId/documents` 按授权角色进入。
- `/admin/knowledge-bases` 档案抽屉移除表格右侧固定操作列造成的跨层遮挡，并通过 `append-to-body` 将抽屉 Teleport 到 `body`，同时显式设置 `z-index`，为抽屉遮罩、抽屉本体和抽屉内容区补充层级与白底保护，避免打开档案后主页表格穿透到右侧信息面板。
- 文档页按当前用户在知识库中的角色隐藏上传、重试、删除按钮。
- 文档和知识库的危险操作文案改为“删除”，确认弹窗明确说明删除后无法找回，并会清空数据库记录、OCR 结果和向量数据。
- 首页管理员入口从“知识库管理”改为“知识库治理”，入口对应全局档案页。

## 验证

- `python -m pytest tests/test_knowledge_base.py -q`：35 passed。
- `ruff check app/api/knowledge_base.py tests/test_knowledge_base.py`：通过。
- `black --check app/api/knowledge_base.py tests/test_knowledge_base.py`：通过。
- `npm run lint -- --max-warnings=0`：通过。
- `npx stylelint "src/views/KnowledgeListView.vue" "src/views/AdminKnowledgeBasesView.vue"`：通过。
- `npm run build`：通过。

说明：全量 `npm run stylelint` 仍会在既有文件 `src/features/chat/CitationCard.vue:141` 报 `declaration-block-no-redundant-longhand-properties`，该文件不属于本次知识库生命周期修正范围。
