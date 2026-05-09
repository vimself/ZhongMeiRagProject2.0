## 用户要求

总是使用中文回答我。
禁止批量删除文件或目录。
不要使用：
- `del /s`
- `rd /s`
- `rmdir /s`
- `Remove-Item -Recurse`
- `rm -rf`
需要删除文件时，只能一次删除一个明确路径的文件。
正确示例：
`Remove-Item "C:\path\to\file.txt"`
如果需要批量删除文件，应停止操作，并询问用户，让用户手动删除。
完成任务后，你需要检查更新docs文件夹下的md文件，以及按情况去更新AGENTS.md文件内容。

## github远程仓库地址

origin=https://github.com/vimself/ZhongMeiRagProject2.0.git

## 工程约定

- 项目采用 monorepo：`backend/`、`frontend/`、`docs/`、`ops/`、`docker/`。
- 后端目标运行时为 Python 3.11 + FastAPI + Celery。
- 前端目标运行时为 Vue 3 + TypeScript + Vite。
- 基础设施通过 Docker Compose 启动，配置文件集中放在 `ops/` 和 `docker/`。

## 当前实现状态

- Stage 1 基础设施与工程骨架已完成，进度记录见 `docs/stage-1-infrastructure-progress.md`。
- Stage 2 数据层与认证内核已完成，进度记录见 `docs/stage-2-data-auth-progress.md`。
- Stage 3 用户与后台管理已完成，进度记录见 `docs/stage-3-user-admin-progress.md`。
- 后端认证入口统一位于 `/api/v2/auth/*`，包含登录、刷新、登出、改密与当前用户查询。
- 个人中心 API 位于 `/api/v2/user/*`，包含资料读取/更新、头像上传/删除、改密。
- 管理员 API 位于 `/api/v2/admin/*`，包含用户 CRUD、重置密码、停用、审计日志查询。
- 首次部署创建管理员账号时，在迁移完成后运行 `python -m app.cli.seed_admin`，并确保 `ADMIN_SEED_PASSWORD` 已配置为非示例值。
- 头像文件存储在 `uploads/avatars/{user_id}/` 目录，Docker Compose 通过 `uploads-data:/app/backend/uploads` 持久化。
- 前端 `.stylelintrc.json` 配置了 Vue `:deep` 伪类支持，修改样式时请注意。
