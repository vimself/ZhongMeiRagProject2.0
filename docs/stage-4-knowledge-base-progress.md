# Stage 4 · 知识库骨架 — 进度报告

生成时间：2026-05-09

---

## 1. 开发流程

1. 阅读 `docs/ultimate-refactor.md` Stage 4 目标与验收标准。
2. 阅读 `docs/stage-3-user-admin-progress.md` 了解已有能力和文档结构。
3. 检查后端代码结构（models、schemas、api、tests）和前端代码结构（api、stores、views、router）。
4. 实现后端：新模型 → Alembic 迁移 → Schemas → 权限依赖 → KB API → Admin KB API → 测试 → 验证。
5. 实现前端：类型扩展 → API 封装 → KnowledgeListView → AdminKnowledgeBasesView → 路由守卫 → 验证。
6. 运行全量验证（ruff、black、mypy、pytest、eslint、stylelint、build、docker compose config）。
7. 编写本文档并更新 AGENTS.md。

---

## 2. 完成情况

### 2.1 新数据模型与 Alembic 迁移

新增两张表，使用 SQLAlchemy 2.0 `Mapped` / `mapped_column` 风格：

**`knowledge_bases` 表**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String(36) PK | UUID 主键 |
| `name` | String(256) | 知识库名称 |
| `description` | String(2048) | 描述，默认空串 |
| `creator_id` | String(36) FK → users | 创建者，SET NULL |
| `is_active` | Boolean | 兼容旧数据的可用标志，默认 True；新删除流程改为物理删除 |
| `created_at` | DateTime(tz) | 创建时间 |
| `updated_at` | DateTime(tz) | 更新时间 |

索引：`ix_knowledge_bases_creator_id`、`ix_knowledge_bases_is_active`。

**`knowledge_base_permissions` 表**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String(36) PK | UUID 主键 |
| `knowledge_base_id` | String(36) FK → knowledge_bases | CASCADE |
| `user_id` | String(36) FK → users | CASCADE |
| `role` | String(32) | owner/editor/viewer |
| `created_at` | DateTime(tz) | 创建时间 |
| `updated_at` | DateTime(tz) | 更新时间 |

唯一约束：`(knowledge_base_id, user_id)` — `uq_kb_permission_user`。
索引：`ix_kb_permissions_user_id`、`ix_kb_permissions_kb_id`。

**Alembic 迁移**

- 新增 `alembic/versions/20260509_stage_4_knowledge_base.py`。
- revision: `stage_4_knowledge_base`，依赖 `stage_3_user_admin`。
- `upgrade` 创建两张表及所有索引/约束。
- `downgrade` 按反序删除索引、约束、表，双向可逆。
- `alembic/env.py` 新增 `from app.models import knowledge_base` 注册。

### 2.2 权限语义

| 角色 | 查看 | 编辑基本信息 | 管理权限 | 删除 |
|------|------|-------------|---------|----------|
| admin | ✅ | ✅ | ✅ | ✅ |
| owner | ✅ | ✅ | ✅ | ✅ |
| editor | ✅ | ✅ | ❌ | ❌ |
| viewer | ✅ | ❌ | ❌ | ❌ |
| 无权限 | 403 | 403 | 403 | 403 |
| 未登录 | 401 | 401 | 401 | 401 |

- 创建知识库时，创建者自动成为 owner。
- 禁止移除最后一个 owner（返回 400）。
- 角色只能是 `owner`/`editor`/`viewer`，否则 Pydantic 校验返回 422。
- admin 用户跳过权限检查，拥有所有知识库的完全管理权限。

### 2.3 知识库 API 路由

**用户端路由（`/api/v2/knowledge-bases`）**

| 端点 | 方法 | 功能 | 最低权限 |
|------|------|------|---------|
| `/api/v2/knowledge-bases` | GET | 分页列表，支持搜索，仅返回有权限的 KB | 登录 |
| `/api/v2/knowledge-bases` | POST | 创建知识库，自动 owner | admin |
| `/api/v2/knowledge-bases/{id}` | GET | 获取详情 | viewer |
| `/api/v2/knowledge-bases/{id}` | PUT | 更新名称/描述 | editor |
| `/api/v2/knowledge-bases/{id}` | DELETE | 物理删除知识库及其文档、OCR、向量/稀疏索引和权限记录 | admin |
| `/api/v2/knowledge-bases/{id}/permissions` | GET | 查看权限列表 | viewer |
| `/api/v2/knowledge-bases/{id}/permissions` | PUT | 更新权限矩阵 | admin |
| `/api/v2/knowledge-bases/{id}/permission-candidates` | GET | 查询可授权用户候选 | admin |

**管理员路由（`/api/v2/admin/knowledge-bases`）**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/v2/admin/knowledge-bases` | GET | 查看现存知识库，支持搜索 |
| `/api/v2/admin/knowledge-bases/{id}/permissions` | GET | 查看现存知识库权限记录 |
| `/api/v2/admin/knowledge-bases/{id}/permissions` | PUT | 更新活跃知识库权限矩阵 |
| `/api/v2/admin/knowledge-bases/{id}/permission-candidates` | GET | 查询可授权用户候选 |

### 2.4 审计日志

所有写操作记录 `audit_logs`：

| action | 说明 |
|--------|------|
| `knowledge_base.create` | 创建知识库 |
| `knowledge_base.update` | 更新知识库信息 |
| `knowledge_base.delete` | 物理删除知识库 |
| `knowledge_base.permissions.update` | 更新权限矩阵 |

日志中不记录敏感信息。

### 2.5 Pydantic Schemas

`backend/app/schemas/knowledge_base.py`：

- `KnowledgeBaseCreate`：name（必填）、description（可选）
- `KnowledgeBaseUpdate`：name、description（均可选）
- `KnowledgeBaseOut`：完整输出，含 `my_role`、`creator_id`、`creator_username`、`creator_name` 字段；创建者展示优先使用唯一用户名，展示名允许重复。
- `KnowledgeBaseListResponse`：分页列表
- `PermissionOut`：含 username、display_name 展示
- `PermissionUpdateItem`：user_id + role
- `PermissionUpdateRequest`：权限列表

### 2.6 后端依赖

- `backend/app/api/knowledge_base_deps.py`：权限检查依赖
  - `get_kb_or_404`：获取 KB 或 404
  - `_get_user_kb_role`：查询用户在某 KB 的角色
  - `require_viewer`/`require_editor`/`require_owner`：三级权限依赖
  - admin 用户自动通过所有权限检查
- `GET /api/v2/knowledge-bases/{id}/permission-candidates`：仅 admin 可查询可授权用户候选列表，普通 owner 不再具备权限设置能力。
- `GET /api/v2/admin/knowledge-bases/{id}/permissions`：管理员可查看现存知识库的权限记录；知识库物理删除后权限记录同步删除。
- `PUT /api/v2/admin/knowledge-bases/{id}/permissions`：管理员更新活跃知识库权限矩阵。

### 2.7 后端测试

新增 `tests/test_knowledge_base.py`，覆盖 32 个测试用例：

| 测试类 | 覆盖范围 |
|--------|---------|
| `TestKnowledgeBaseCRUD` (9) | 创建自动 owner、审计日志、列表、搜索、获取详情、更新、物理删除、404 |
| `TestKnowledgeBasePermissionBoundary` (7) | owner 可编辑删除、editor 可编辑不可删除、viewer 只读、无权限 403、未认证 401、admin 全权限、普通用户只能看到有权限的 KB |
| `TestKnowledgeBasePermissionManagement` (10) | 列表权限、添加 editor、即时生效、不能移除最后 owner、非法角色 422、权限更新审计、拒绝不存在用户、拒绝重复用户、owner 查询授权候选用户 |
| `TestAdminKnowledgeBase` (5) | 管理员列表现存 KB、搜索、删除后不再出现、删除后权限记录不可访问、普通用户 403 |
| `TestAlembicMigration` (1) | 表存在性验证 |

### 2.8 前端类型与 API 封装

- `frontend/src/api/types.ts` 新增：`KnowledgeBaseOut`、`KnowledgeBaseListResponse`、`KnowledgeBaseCreateRequest`、`KnowledgeBaseUpdateRequest`、`PermissionOut`、`PermissionUpdateItem`、`PermissionUpdateRequest`。
- `frontend/src/api/types.ts` 新增 `PermissionUserOut` 用于权限候选用户。
- `frontend/src/api/knowledge.ts`：`listKnowledgeBases`、`createKnowledgeBase`、`getKnowledgeBase`、`updateKnowledgeBase`、`deleteKnowledgeBase`、`listPermissions`、`listPermissionCandidates`、`updatePermissions`、`adminListKnowledgeBases`、`adminListPermissions`、`adminListPermissionCandidates`、`adminUpdatePermissions`。

### 2.9 前端页面

**KnowledgeListView（知识库列表）**

- 表格：知识库名称、描述、我的角色、创建时间、操作。
- 工具栏：搜索输入框、刷新。
- 编辑对话框：名称（必填）、描述（选填）。
- 点击知识库表格行进入对应文档列表；操作按钮根据 `my_role` 动态显示，owner/editor/admin 可编辑基础信息；不再提供单独文档按钮、新建、删除和权限设置。
- 空状态展示。

**AdminKnowledgeBasesView（管理员知识库管理）**

- 表格：知识库名称、描述、文档规模、成员数、创建者、创建时间、操作。
- 工具栏：搜索输入框、刷新、新建知识库。
- 权限设置抽屉：查看/添加/修改/删除权限，角色选择（owner/editor/viewer）。
- 档案抽屉：查看生命周期、规模快照、权限快照和审计记录。
- 空状态展示。

### 2.10 路由与权限

- `/knowledge`：`meta: { requiresAuth: true }`。
- `/admin/knowledge-bases`：`meta: { requiresAuth: true, requiresAdmin: true }`。
- HomeView Stage 标签从 Stage 3 更新为 Stage 4。
- 知识库卡片可点击，跳转 `/knowledge`。
- 首页新增"知识库管理"按钮（管理员可见），跳转 `/admin/knowledge-bases`。

### 2.11 前端设计规范

- 遵循 `rag-white-premium-frontend` 设计规范：白色背景、克制配色、合理信息密度。
- 使用 Element Plus 组件和图标，tree-shaken 导入。
- 表格、表单、抽屉、弹窗、空状态完整。
- 移动端和桌面端均无文字溢出或重叠。

### 2.12 本次复核修正

复核时间：2026-05-09。

- 修复知识库更新、删除、权限变更审计日志 `actor_user_id` 为空的问题，现在统一记录当前操作者。
- 权限矩阵更新前新增用户存在性校验，避免不存在的 `user_id` 触发数据库外键异常。
- 权限矩阵更新前新增重复用户校验，避免同一用户重复写入导致唯一约束异常。
- 新增 `GET /api/v2/knowledge-bases/{id}/permission-candidates`，使普通 owner 不依赖管理员用户列表接口也能在前端权限抽屉中选择授权用户。
- 新增 `GET /api/v2/admin/knowledge-bases/{id}/permissions`，管理员可查看现存知识库权限记录。
- 前端权限抽屉改为调用知识库授权候选用户接口；管理员知识库页面改为调用管理员权限查看接口。
- 前端知识库页和管理员知识库页局部注册 Element Plus `v-loading` 指令，修复运行时加载态指令未解析警告。
- 前端列表与权限抽屉补充 API 异常处理，避免接口失败时抛出未处理的 mounted hook 异常。
- 补充后端测试覆盖：审计操作者、缺失用户、重复用户、授权候选用户、知识库删除后权限记录不可访问。

---

## 3. 本次不迁移旧数据说明

Stage 4 不迁移旧 RAG 项目数据。所有测试数据均为本项目内新建的 `stage4_*` 测试数据。旧 RAG 项目数据全部废弃，不需要兼容、不需要导入、不需要转换。

---

## 4. 本地验证结果

验证时间：2026-05-09。

| 检查项 | 结果 |
|--------|------|
| `.venv\Scripts\ruff.exe check .` | ✅ All checks passed |
| `.venv\Scripts\black.exe --check .` | ✅ 42 files unchanged |
| `.venv\Scripts\mypy.exe app` | ✅ Success: no issues found in 33 source files |
| `.venv\Scripts\pytest.exe tests/` | ✅ 69 passed |
| 临时 SQLite `alembic upgrade head → downgrade -1 → upgrade head` | ✅ 最终 `stage_4_knowledge_base (head)` |
| `npm run lint` | ✅ clean |
| `npm run stylelint` | ✅ clean |
| `npm run build` | ✅ built successfully |
| `docker compose config` | ✅ valid |
| 浏览器页面冒烟 | ✅ `/knowledge`、`/admin/knowledge-bases` 页面可渲染；本地未重建的旧 API 容器返回 404 时页面已能提示错误而非崩溃 |

说明：本次 Alembic 验证使用临时 SQLite 数据库和临时 `JWT_SECRET`，仅验证迁移链路可逆性，不迁移旧 RAG 数据，不写入生产/容器 SeekDB。

---

## 5. 剩余问题

- 无 Stage 4 阻塞问题。
- 以下为后续阶段注意事项：
  - Stage 5 将在此基础上实现 PDF 上传、OCR、切片、Embedding、向量索引、RAG 检索。
  - 知识库中的文档管理、向量存储等能力将在 Stage 5 实现。
  - 前端知识库详情页（文档列表、上传界面）将在 Stage 5 实现。

---

## 6. 结论

Stage 4（知识库骨架）已全部完成，所有交付物已实现并通过验证：

- ✅ 知识库治理与用户侧访问入口分离（管理员创建/删除/权限设置，用户侧列表/详情/基础信息编辑）
- ✅ 权限矩阵 owner/editor/viewer 三级权限
- ✅ admin 可查询授权候选用户并更新权限矩阵
- ✅ 普通 owner 不能进行权限设置或删除知识库
- ✅ admin 删除知识库后同步清理权限记录
- ✅ 创建知识库自动 owner
- ✅ 禁止移除最后一个 owner
- ✅ 非法角色 Pydantic 校验
- ✅ 不存在用户、重复用户权限更新被明确拒绝
- ✅ Alembic 可逆迁移
- ✅ 审计日志覆盖所有写操作并记录操作者
- ✅ 前端知识库列表页（行点击进入文档、基础信息编辑）
- ✅ 前端管理员知识库治理页（新建、删除、权限设置、档案审计）
- ✅ 路由守卫（requiresAuth + requiresAdmin）
- ✅ 首页入口与 Stage 标识更新
- ✅ 前端 lint/stylelint/build 全部通过
- ✅ 不迁移旧数据，所有测试使用新建数据
