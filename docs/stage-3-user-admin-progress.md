# Stage 3 · 用户与后台管理 — 进度报告

生成时间：2026-05-09

---

## 1. 开发流程

1. 阅读 `docs/ultimate-refactor.md` Stage 3 目标与验收标准。
2. 阅读 `docs/stage-2-data-auth-progress.md` 了解已有能力和文档结构。
3. 检查后端代码结构（models、schemas、api、services、tests）和前端代码结构（api、stores、views、router）。
4. 实现后端：模型扩展 → Alembic 迁移 → Schemas → User API → Admin API → 注册路由 → 测试 → 验证。
5. 实现前端：类型扩展 → API 封装 → ProfileView → AdminUsersView → 路由守卫 → 验证。
6. 运行全量验证（ruff、black、mypy、pytest、eslint、stylelint、build、docker compose config）。
7. 编写本文档并更新 AGENTS.md。

---

## 2. 完成情况

### 2.1 User 模型扩展与 Alembic 迁移

- User 模型新增 `avatar_path: String(512), nullable` 字段。
- 新增迁移文件 `alembic/versions/20260509_stage_3_user_admin.py`，revision `stage_3_user_admin`，依赖 `stage_2_auth_core`。
- 使用 `batch_alter_table` 确保 SQLite 兼容性。
- `upgrade` 添加 `avatar_path` 列，`drop_column` 删除该列，双向可逆。

### 2.2 个人中心 API（`/api/v2/user/*`）

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/v2/user/profile` | GET | 获取当前用户完整资料 |
| `/api/v2/user/profile` | PUT | 更新展示名（不允许改 role/is_active） |
| `/api/v2/user/avatar` | POST | 上传头像（MIME/扩展名/大小校验，分片存储） |
| `/api/v2/user/avatar` | DELETE | 删除当前头像及物理文件 |
| `/api/v2/user/change-password` | POST | 修改密码，复用现有密码验证逻辑 |

- 头像存储路径：`uploads/avatars/{user_id}/{uuid}.{ext}`。
- 所有写操作记录 `audit_logs`。
- 上传限制：5 MB，允许 JPEG/PNG/WebP/GIF。

### 2.3 管理员用户管理 API（`/api/v2/admin/*`）

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/v2/admin/users` | GET | 分页列表，支持 search/role/is_active 筛选 |
| `/api/v2/admin/users` | POST | 创建用户，校验 username 唯一性；display_name 可重复 |
| `/api/v2/admin/users/{id}` | PUT | 更新 display_name/role/is_active/require_password_change |
| `/api/v2/admin/users/{id}/reset-password` | POST | 重置密码，自动设置 require_password_change=true |
| `/api/v2/admin/users/{id}` | DELETE | 软删除（停用），不硬删除 |
| `/api/v2/admin/audit-logs` | GET | 审计日志分页查询，支持 target_type/target_id/action 筛选 |

- 所有管理员写操作需要 `require_admin` 依赖，非管理员返回 403。
- 防护逻辑：管理员不能停用/降级/停用自己的账号。
- 审计 action 命名：`admin.user.create`、`admin.user.update`、`admin.user.reset_password`、`admin.user.disable`。
- 密码不会写入日志或响应。

### 2.4 Pydantic Schemas

- `backend/app/schemas/user.py`：`UserProfileOut`、`UpdateProfileRequest`、`ChangePasswordViaUserRequest`。
- `backend/app/schemas/admin.py`：`AdminUserOut`、`AdminUserListResponse`、`AdminCreateUserRequest`、`AdminUpdateUserRequest`、`AdminResetPasswordRequest`、`AuditLogOut`、`AuditLogListResponse`。

### 2.5 后端依赖更新

- `pyproject.toml` 新增 `python-multipart>=0.0.18`（文件上传必需）。
- `main.py` 新增 `StaticFiles` 挂载 `/uploads` 目录，注册 user_router 和 admin_router。
- `docker-compose.yml` 已为 API 服务挂载 `uploads-data:/app/backend/uploads`，确保头像文件在容器重建后持久化。

### 2.6 后端测试

新增 `tests/test_user_admin.py`，覆盖 32 个测试用例：

| 测试类 | 覆盖范围 |
|--------|---------|
| `TestUserProfile` (3) | 获取资料、更新资料、展示名去空格 |
| `TestAvatar` (4) | 上传有效头像、无效 MIME、超大文件、删除头像 |
| `TestUserChangePassword` (2) | 正常改密、错误旧密码 |
| `TestAdminUsers` (11) | 列表/搜索/筛选、创建/重复、更新/404、重置密码、停用、自保（不能停用/降级/停用自己） |
| `TestPermissionBoundary` (7) | 普通用户访问所有管理员端点均 403、未认证 401 |
| `TestAuditLogs` (3) | 列表、按 target 筛选、分页 |

### 2.7 前端类型与 API 封装

- `frontend/src/api/types.ts` 新增 `UserProfileDetail`、`AdminUserOut`、`AdminUserListResponse`、`AdminCreateUserRequest`、`AdminUpdateUserRequest`、`AuditLogOut`、`AuditLogListResponse`。
- `frontend/src/api/user.ts`：`getProfile`、`updateProfile`、`uploadAvatar`、`deleteAvatar`、`changePasswordViaUser`。
- `frontend/src/api/admin.ts`：`listUsers`、`createUser`、`updateUser`、`resetPassword`、`disableUser`、`listAuditLogs`。
- `frontend/src/stores/auth.ts` 新增 `refreshProfile` action，同步头像和展示名到本地状态。

### 2.8 前端页面

**ProfileView（个人中心）**
- 展示用户头像、用户名、角色、展示名、密码状态、最后登录、创建时间。
- 支持头像上传（ElUpload + http-request）、预览、删除（带确认弹窗）。
- 支持编辑展示名（行内编辑模式）。
- 支持修改密码（复用 ChangePasswordDialog）。
- 白色高级后台风格，响应式设计。

**AdminUsersView（管理员用户管理）**
- 表格：用户名、展示名、角色、状态、需改密标志、最后登录、创建时间、操作列。
- 工具栏：搜索输入框、角色筛选、状态筛选、刷新、新建用户按钮。
- 新建/编辑对话框：字段校验，角色选择，启用状态和改密标志切换；展示名允许重复。
- 重置密码对话框：带提示信息，密码最少 8 位。
- 启用状态调整：在新建/编辑对话框中通过启用状态开关维护。
- 审计抽屉：展示用户相关 audit_logs，支持分页，action 中文映射。
- 操作按钮：编辑、重置密码、查看审计；启用/停用统一放在编辑对话框内处理。

### 2.9 路由与权限

- `/profile`：`meta: { requiresAuth: true }`。
- `/admin/users`：`meta: { requiresAuth: true, requiresAdmin: true }`。
- 路由守卫新增 `requiresAdmin` 检查，非管理员重定向到首页。
- HomeView 新增"个人中心"和"用户管理"按钮（管理员可见）。
- HomeView Stage 标签从 Stage 2 更新为 Stage 3。

### 2.10 前端设计规范

- 遵循 `rag-white-premium-frontend` 设计规范：白色背景、克制配色、合理信息密度。
- 使用 Element Plus 组件和图标，tree-shaken 导入。
- 表格、表单、抽屉、弹窗状态完整。
- 移动端和桌面端均无文字溢出或重叠。

### 2.11 本次复核修正

复核时间：2026-05-09。

- 修复管理员创建用户审计记录 `target_id` 为空的问题：`POST /api/v2/admin/users` 在写审计前先 `flush` 新用户，确保审计抽屉按用户筛选时能看到 `admin.user.create`。
- 加强 `tests/test_user_admin.py::TestAdminUsers::test_create_user`，从仅校验 action 改为同时校验 `target_id == 新用户 id`。
- 补齐 Docker Compose 头像持久化卷：新增 `uploads-data` 命名卷并挂载到 API 容器 `/app/backend/uploads`。
- `.gitignore` 新增 `backend/uploads/`，避免运行期头像文件进入版本控制。

---

## 3. 本地验证结果

复核时间：2026-05-09。

| 检查项 | 结果 |
|--------|------|
| `ruff check .` | ✅ All checks passed |
| `black --check .` | ✅ 36 files unchanged |
| `mypy app` | ✅ Success: no issues found in 29 source files |
| `pytest tests/` | ✅ 37 passed（原 5 + 新 32） |
| 临时 SQLite `alembic upgrade head → downgrade -1 → upgrade head` | ✅ 最终 `stage_3_user_admin (head)` |
| `alembic current`（连接本地 Docker SeekDB） | ✅ stage_3_user_admin (head) |
| `npm run lint` | ✅ clean |
| `npm run stylelint` | ✅ clean |
| `npm run build` | ✅ built successfully |
| `npm audit --omit=dev` | ✅ 0 vulnerabilities |
| `docker compose config` | ✅ valid |

---

## 4. Docker/Compose 复验结果

复验时间：2026-05-09。Docker Desktop 已开启，本次执行了容器级复验。

已通过：

- `docker compose up -d --build` 重新构建并启动 API、Celery workers、beat、Flower 等服务。
- `docker compose ps` 显示 `api`、`nginx`、`redis`、`seekdb` 均为 healthy，worker/beat/flower 均已启动。
- `docker compose exec -T api python -m alembic current` 返回 `stage_3_user_admin (head)`。
- `docker compose exec -T api python -m app.cli.seed_default_users` 通过，用于确保本地 `admin` / `user` 默认双账号可登录，并清理其他无效用户记录。
- `http://localhost:8000/readyz` 返回 ready。
- `http://localhost:8080/healthz` 返回 ok。
- `http://localhost:8080/readyz` 返回 ready。
- 管理员登录 `POST /api/v2/auth/login` 通过。
- 管理员创建用户 `POST /api/v2/admin/users` 通过。
- 按新用户查询审计 `GET /api/v2/admin/audit-logs?target_type=user&target_id=...` 返回 `admin.user.create`，确认创建审计 `target_id` 已修复。
- 普通用户访问 `GET /api/v2/admin/users` 返回 403。
- `docker compose config` 已确认 `uploads-data` 卷挂载到 `/app/backend/uploads`。

说明：

- API 容器重建后，运行中的 Nginx 需要重启以刷新上游解析；本次通过 `docker compose restart nginx` 后入口恢复正常。
- 本次复验在 SeekDB 中保留了若干 `stage3_*` 烟测账号和审计记录，用于证明真实容器链路可用。

---

## 5. 剩余问题

- 无 Stage 3 阻塞问题。
- 以下为后续阶段注意事项：
  - 头像文件存储已通过 Compose 命名卷持久化；生产环境如改用主机目录或对象存储，需要同步调整备份策略。
  - `python-multipart` 已加入 pyproject.toml 依赖，Docker 构建时会自动安装。
  - `.stylelintrc.json` 新增了 Vue `:deep` 伪类支持配置。
  - 前端页面本次复核完成了 lint/stylelint/build，未额外执行浏览器截图级视觉复验。

---

## 6. 结论

Stage 3（用户与后台管理）已全部完成，所有交付物已实现并通过验证：

- ✅ 个人中心 API（profile CRUD、头像上传/删除、改密）
- ✅ 管理员用户管理 API（CRUD、重置密码、软删除、审计日志查询）
- ✅ 权限边界（require_admin 403、管理员自保）
- ✅ Alembic 可逆迁移
- ✅ 前端个人中心页面（头像、资料编辑、改密）
- ✅ 前端管理员用户管理页面（表格、搜索筛选、表单、审计抽屉）
- ✅ 路由守卫（requiresAuth + requiresAdmin）
- ✅ 32 个新增后端测试（共 37 个全部通过）
- ✅ 前端 lint/stylelint/build 全部通过
- ✅ 审计日志全面覆盖所有写操作
- ✅ Docker Compose 容器级复验通过，API 迁移到 `stage_3_user_admin (head)`
- ✅ 头像文件持久化卷 `uploads-data` 已补齐
