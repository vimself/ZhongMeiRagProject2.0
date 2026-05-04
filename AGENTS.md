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

## 工程约定

- 项目采用 monorepo：`backend/`、`frontend/`、`docs/`、`ops/`、`docker/`。
- 后端目标运行时为 Python 3.11 + FastAPI + Celery。
- 前端目标运行时为 Vue 3 + TypeScript + Vite。
- 基础设施通过 Docker Compose 启动，配置文件集中放在 `ops/` 和 `docker/`。
