# Stage 2 数据层与认证内核进度报告

生成时间：2026-05-09

## 开发过程

1. 读取 `docs/ultimate-refactor.md`，定位 Stage 2 范围：
   - Alembic 初始化与基础表迁移
   - 密码哈希、JWT 签发与认证依赖
   - 登录失败限流与审计
   - 前端登录、刷新、登出与改密链路
2. 阅读 `docs/stage-1-infrastructure-progress.md`，沿用 Stage 1 的报告结构、验收记录方式和剩余问题格式。
3. 检查当前仓库骨架，确认 Stage 1 已提供 FastAPI、Celery、Vue、Pinia、Router、Docker Compose 与 CI 基础。
4. 实现后端数据层、认证安全层、认证 API、管理员种子脚本与测试。
5. 实现前端 axios 客户端、Pinia auth store、路由守卫、登录页、首页登录态和修改密码弹窗。
6. 安装依赖并执行后端静态检查、迁移升降级、单元测试、前端 lint/stylelint/build 与 Compose 静态校验。

## 完成情况

### 2.1 Alembic 初始化 & 基础表迁移

已完成。

- 新增 Alembic 配置：
  - `backend/alembic.ini`
  - `backend/alembic/env.py`
  - `backend/alembic/script.py.mako`
- 新增 Stage 2 迁移：
  - `backend/alembic/versions/20260509_stage_2_auth_core.py`
- 新增 SQLAlchemy 2.0 async 数据层：
  - `backend/app/db/base.py`
  - `backend/app/db/session.py`
- 新增认证相关 ORM 模型：
  - `users`
  - `login_records`
  - `auth_login_attempts`
  - `audit_logs`
- `docker-compose.yml` 中 API 服务已配置 `RUN_ALEMBIC=1`，容器启动时可自动执行 `alembic upgrade head`。

### 2.2 密码 + JWT + 依赖注入

已完成。

- 密码哈希：
  - `backend/app/security/password.py`
  - 使用 Python 标准库 `hashlib.scrypt`
  - 哈希格式包含 scrypt 参数、salt 与 digest
- JWT：
  - `backend/app/security/jwt.py`
  - access token 默认 30 分钟
  - refresh token 默认 7 天
  - 预留 `pdf_preview` token 签发与解析能力
- 认证依赖：
  - `backend/app/api/deps.py`
  - `current_user`
  - `require_admin`
  - `pdf_token_user`
- 认证路由：
  - `POST /api/v2/auth/login`
  - `POST /api/v2/auth/refresh`
  - `POST /api/v2/auth/logout`
  - `POST /api/v2/auth/change-password`
  - `GET /api/v2/auth/me`
  - `GET /api/v2/auth/config`
- 默认用户种子脚本：
  - `backend/app/cli/seed_default_users.py`
  - Docker API 容器迁移完成后通过 `SEED_DEFAULT_USERS=1` 自动执行。
  - 初始化并保留 `admin` 与 `user` 两个账号，清理其他无效用户记录；有文档或知识库外键引用时先转移到 `admin`。
  - 对历史脏数据中为空或不属于默认双账号的 `knowledge_bases.creator_id` 进行修复，统一绑定到当前 `admin` 用户 ID。
  - 手动执行时可加 `--reset-passwords`，按环境变量重置现有默认账号密码。
- 兼容脚本：
  - `backend/app/cli/seed_admin.py`
  - 继续支持手动重置默认账号密码。
  - 通过 `ADMIN_SEED_*`、`USER_SEED_*` 与 `DEFAULT_USERS_RESET_PASSWORDS` 配置。

### 2.3 登录限流 + 审计

已完成。

- 新增登录失败双桶限流：
  - `backend/app/security/login_limiter.py`
  - subject 维度：`auth:login-fail:subject:{username}`
  - ip 维度：`auth:login-fail:ip:{ip}`
  - 默认 5 次失败后锁定 15 分钟
  - 生产路径使用 Redis；测试环境使用内存 fallback
- slowapi 已接入 FastAPI 应用：
  - `app.state.limiter`
  - `SlowAPIMiddleware`
  - `RateLimitExceeded` 异常处理器
- 登录失败记录落库：
  - `auth_login_attempts`
- 改密和登出审计落库：
  - `audit_logs`

说明：Stage 2 中“失败 5 次触发限流”的核心验收由 Redis 双桶逻辑完成。slowapi 目前作为入口限流基础设施接入应用，未对登录接口叠加固定 IP 限流装饰器，避免与“失败次数”语义混淆。

### 2.4 前端登录链路

已完成。

- 新增 API 客户端：
  - `frontend/src/api/client.ts`
  - axios baseURL 默认 `/api/v2`
  - 请求拦截器自动注入 Bearer token
  - 401 响应自动 refresh，失败后清理会话
- 新增类型定义：
  - `frontend/src/api/types.ts`
- 新增 Pinia auth store：
  - `frontend/src/stores/auth.ts`
  - 登录、刷新、登出、修改密码
  - localStorage 持久化 access token、refresh token 与用户信息
- 新增登录页：
  - `frontend/src/views/LoginView.vue`
- 更新首页：
  - `frontend/src/views/HomeView.vue`
  - 展示当前用户
  - 支持打开改密弹窗
  - 支持登出
- 新增改密弹窗：
  - `frontend/src/components/ChangePasswordDialog.vue`
- 更新路由守卫：
  - `frontend/src/router/index.ts`
  - 未登录访问受保护页面时跳转 `/login`
  - 存在 refresh token 时先尝试自动刷新

## 本地验证结果

已通过：

- 后端依赖安装：
  - `..\.venv\Scripts\python.exe -m pip install -e ".[dev]"`
  - 实际执行时使用项目根目录 `.venv`，因为系统默认 `python` 为 3.10，不满足后端 `>=3.11` 要求。
- Alembic 升降级：
  - `alembic upgrade head` 通过
  - `alembic downgrade base` 通过
  - 再次 `alembic upgrade head` 通过
- 后端格式与静态检查：
  - `ruff check .` 通过
  - `black --check .` 通过
  - `mypy app` 通过
- 后端测试：
  - `pytest` 通过，5 个测试全部通过
  - 覆盖登录、刷新、登出、改密审计、失败 5 次限流
- 前端依赖安装：
  - `npm install` 通过
  - 已更新 `frontend/package-lock.json`
- 前端检查：
  - `npm run lint` 通过
  - `npm run stylelint` 通过
  - `npm run build` 通过
- 前端生产依赖安全检查：
  - `npm audit --omit=dev` 通过，生产依赖 0 漏洞
- Compose 静态校验：
  - `docker compose config` 通过
- 前端页面冒烟：
  - 已启动 Vite dev server：`http://127.0.0.1:5173`
  - `GET /login` 返回 HTTP 200
  - `GET /` 返回 HTTP 200

本次验证中修复的问题：

- 系统默认 `python` 为 3.10，改用项目 `.venv` 中的 Python 执行后端依赖安装和检查。
- slowapi 装饰器会让登录接口请求体被 FastAPI 误判为 query 参数；已移除接口装饰器，保留 slowapi 应用级接入，登录失败限流由 Redis 双桶实现。
- Windows 下 Husky prepare 脚本使用 `shell: false` 直接执行 `.cmd` 会触发 `EINVAL`；已调整为仅 Windows 使用 shell 执行。
- Element Plus `form-item` 深路径没有类型声明；已改为从 `form/index.mjs` 同时导入 `ElForm` 与 `ElFormItem`。
- 避免从 Element Plus 根包导入导致构建 chunk 过大，最终 `element` chunk 约 127.63KB，gzip 约 44.82KB。
- axios 拦截器与 auth store 之间的动态导入提示已消除，改为在 `main.ts` 注入 auth 回调。

## 剩余问题

无 Stage 2 阻塞问题。

后续阶段注意事项：

1. API 容器启动时会在 Alembic 迁移后自动执行默认用户初始化：
   - `python -m app.cli.seed_default_users`
   - 数据库最终只保留 `admin` 与 `user` 两个用户。
2. `.env.example` 中的 `ADMIN_SEED_PASSWORD`、`USER_SEED_PASSWORD` 与 `JWT_SECRET` 仅为本地示例值，生产环境必须替换。
3. SQLite 单元测试与 SeekDB/MySQL 协议容器级复验均已通过；后续修改迁移或认证链路时需要同步覆盖两类验证。
4. slowapi 已作为入口限流基础设施接入，但登录失败次数语义由 Redis 双桶实现。后续如需全局 IP QPS 限制，可在路由层增加独立规则。

## Docker Desktop 复验结果

复验时间：2026-05-09

已通过：

- Docker Engine：
  - `docker info --format "{{.ServerVersion}}"` 返回 `29.4.1`
- Compose 构建与启动：
  - `docker compose up -d --build` 通过
  - `docker compose ps` 显示 `api`、`nginx`、`redis`、`seekdb` 均为 healthy
  - Celery `worker-default / worker-ingest / worker-rag / worker-plan / worker-docx`、`beat`、`flower` 均已启动
  - Prometheus 与 Grafana 已启动
- SeekDB / MySQL 协议：
  - `Test-NetConnection 127.0.0.1 -Port 12881` 通过
  - `seekdb` 容器镜像为 `docker.1ms.run/oceanbase/seekdb:latest`
- Alembic：
  - `docker compose exec -T api python -m alembic current` 返回 `stage_2_auth_core (head)`
  - Alembic 使用 `MySQLImpl` 连接 SeekDB
- API / Nginx 健康检查：
  - `http://localhost:8000/healthz` 返回 `{"status":"ok"}`
  - `http://localhost:8000/readyz` 返回 `{"status":"ready","app":"zhongmei-rag","environment":"local"}`
  - `http://localhost:8080/healthz` 返回 `{"status":"ok"}`
- 容器级认证链路：
  - 创建独立烟测账号 `stage2_smoke`
  - `POST /api/v2/auth/login` 通过
  - `GET /api/v2/auth/me` 通过，角色返回 `admin`
  - `POST /api/v2/auth/refresh` 通过，返回新的 access token
  - `POST /api/v2/auth/change-password` 通过
  - 使用新密码重新登录通过
  - `POST /api/v2/auth/logout` 通过
  - 登出后再次 refresh 返回 401
- 登录失败限流：
  - 创建独立限流烟测账号 `stage2_limit`
  - 失败登录状态序列为 `401, 401, 401, 401, 429`
  - 触发限流后使用正确密码登录仍返回 429
- SeekDB 落库验证：
  - `stage2_smoke` 登录尝试记录：2 条
  - `stage2_limit` 登录尝试记录：5 条
  - `stage2_smoke` 登录记录：2 条
  - `auth.change_password` 审计记录：1 条
  - `auth.logout` 审计记录：1 条

说明：

- 本次复验没有执行镜像、容器或卷删除操作。
- 本次复验在 SeekDB 中保留了 `stage2_smoke` 与 `stage2_limit` 两个烟测账号及对应登录/审计记录，用于证明真实 MySQL 协议链路可用。

## 结论

Stage 2 的数据层与认证内核开发已完成。当前已具备基础用户表、登录记录、登录失败审计、操作审计、scrypt 密码哈希、JWT access/refresh、认证依赖、管理员种子脚本，以及前端完整登录、刷新、登出和修改密码链路。代码已通过后端静态检查、迁移升降级、单元测试、前端 lint/stylelint/build、Docker Compose 静态校验，以及 Docker Desktop + SeekDB/MySQL 协议容器级认证链路复验。
