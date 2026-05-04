# Stage 1 基础设施与工程骨架进度报告

生成时间：2026-05-04

## 开发过程

1. 读取 `docs/ultimate-refactor.md`，定位 Stage 1 范围：
   - 仓库与规范
   - FastAPI / Celery 空骨架
   - 基础设施容器化
   - CI 流水线
2. 检查当前仓库，初始仅有 `AGENTS.md` 与 `docs/ultimate-refactor.md`。
3. 按 monorepo 结构创建：
   - `backend/`
   - `frontend/`
   - `docs/`
   - `ops/`
   - `docker/`
   - `.github/workflows/`
4. 实现后端空壳、前端空壳、Docker Compose、Nginx、Prometheus、Grafana provisioning、CI 与 pre-commit 钩子。
5. 安装本地依赖并执行可运行验证，修复过程中发现的依赖版本、mypy、Stylelint、Husky 跨平台脚本问题。

## 完成情况

### 1.1 仓库与规范

已完成。

- 新增根目录规范文件：
  - `.editorconfig`
  - `.gitattributes`
  - `.gitignore`
  - `.env.example`
  - `README.md`
  - `AGENTS.md`
- 建立 monorepo 目录：
  - `backend/`
  - `frontend/`
  - `docs/`
  - `ops/`
  - `docker/`
- 后端配置：
  - `backend/pyproject.toml`
  - `ruff`
  - `black`
  - `mypy`
  - `pytest`
  - `pytest-asyncio`
- 前端配置：
  - Vite 7
  - Vue 3
  - TypeScript strict
  - Pinia
  - Vue Router
  - Element Plus
  - ESLint 9 flat
  - Prettier
  - Stylelint
  - Husky
  - lint-staged
- pre-commit 入口：
  - `.husky/pre-commit`
  - 后端执行 `ruff`、`black --check`
  - 前端执行 `lint-staged`

### 1.2 FastAPI / Celery 空骨架

已完成。

- FastAPI 应用：
  - `backend/app/main.py`
  - `backend/app/api/health.py`
- 健康检查：
  - `GET /healthz`
  - `GET /readyz`
- 配置：
  - `backend/app/core/config.py`
  - 使用 `pydantic-settings`
  - `JWT_SECRET` 无业务默认值，由环境变量提供
- 日志：
  - `backend/app/core/logging.py`
  - loguru JSON sink
- trace id：
  - `backend/app/middleware/trace_id.py`
  - 响应头返回 `x-trace-id`
- 指标：
  - `/metrics`
  - `prometheus-fastapi-instrumentator`
- Celery：
  - `backend/app/celery_app.py`
  - 队列：`default`、`ingest`、`rag`、`plan`、`docx`
  - 任务：`default.ping`

### 1.3 基础设施容器化

已完成配置，受本机 Docker Desktop Linux engine 未启动影响，未能实际拉起容器。

- `docker-compose.yml` 包含：
  - `nginx`
  - `api`
  - `worker-default`
  - `worker-ingest`
  - `worker-rag`
  - `worker-plan`
  - `worker-docx`
  - `beat`
  - `flower`
  - `redis`
  - `seekdb`
  - `prometheus`
  - `grafana`
- Dockerfile：
  - `docker/Dockerfile.api`
  - `docker/Dockerfile.worker`
- 入口脚本：
  - `docker/entrypoint.sh`
  - 支持 `RUN_ALEMBIC=1` 时执行 `alembic upgrade head`
- Nginx：
  - `ops/nginx/nginx.conf`
  - 已关闭代理缓冲以支持 SSE
  - 透传 `Range` / `If-Range` 以支持后续 PDF 分片预览
- Prometheus：
  - `ops/prometheus/prometheus.yml`
  - 抓取 API `/metrics`
- Grafana：
  - Prometheus datasource provisioning
  - 默认 API Overview dashboard

说明：Stage 1 文档要求 SeekDB。当前已替换为真实 SeekDB 镜像 `docker.1ms.run/oceanbase/seekdb:latest`，对应官方镜像为 `oceanbase/seekdb:latest`。官方文档说明 SeekDB 容器对外提供 MySQL 协议端口 `2881` 与 obshell dashboard 端口 `2886`，本项目默认映射为：

- `127.0.0.1:12881 -> seekdb:2881`
- `http://localhost:12886 -> seekdb:2886`

官方镜像源依据：

- Docker Hub：`oceanbase/seekdb`
- 官方文档：`https://docs.seekdb.ai/seekdb/deploy-by-docker/`
- GitHub：`https://github.com/oceanbase/seekdb`

### 1.4 CI 流水线

已完成。

- 新增 `.github/workflows/ci.yml`
- 后端流水线：
  - Python 3.11
  - install
  - `ruff check`
  - `black --check`
  - `mypy`
  - `pytest`
- 前端流水线：
  - Node 22
  - `npm install`
  - `npm run lint`
  - `npm run stylelint`
  - `npm run build`
- 镜像扫描：
  - 构建 API 镜像
  - Trivy 扫描 CRITICAL/HIGH 漏洞

## 本地验证结果

已通过：

- 后端依赖安装：
  - `python -m pip install -e ".[dev]"`
- 后端格式与静态检查：
  - `ruff check .` 通过
  - `black --check .` 通过
  - `mypy app` 通过
- 后端测试：
  - `pytest` 通过，2 个测试全部通过
- 前端依赖安装：
  - `npm install` 通过
  - 生成 `frontend/package-lock.json`
- 前端检查：
  - `npm run lint` 通过
  - `npm run stylelint` 通过
  - `npm run build` 通过
- Compose 静态校验：
  - `docker compose config` 通过

Docker Desktop 启动后的复验结果：

- `docker compose build api worker-default` 通过。
- `docker compose up -d --build` 通过。
- `docker compose ps` 显示全部 Stage 1 服务已启动：
  - `api` healthy
  - `nginx` healthy
  - `redis` healthy
  - `seekdb` healthy
  - `worker-default / worker-ingest / worker-rag / worker-plan / worker-docx` running
  - `beat` running
  - `flower` running
  - `prometheus` running
  - `grafana` running
- `http://localhost:8000/healthz` 返回 `{"status":"ok"}`。
- `http://localhost:8000/readyz` 返回 `{"status":"ready","app":"zhongmei-rag","environment":"local"}`。
- `http://localhost:8080/healthz` 经 Nginx 转发返回 `{"status":"ok"}`。
- `celery call default.ping` 成功，结果为 `{'status': 'pong'}`。
- Flower `http://localhost:5555` 返回 HTTP 200。
- Grafana `http://localhost:3000/api/health` 返回 HTTP 200。
- Prometheus `http://localhost:9090/-/healthy` 返回 HTTP 200。
- Prometheus active targets 中 `api:8000` 与 `localhost:9090` 均为 `up`。
- Grafana provisioning 已加载默认看板 `ZhongMei API Overview`。

本次复验中修复的问题：

- `seekdb` 原默认映射宿主 `3306`，与本机已有服务冲突；先临时改为 `13306`，后续替换真实 SeekDB 后最终改为 `${SEEKDB_PORT:-12881}:2881`，并新增 dashboard 映射 `${SEEKDB_DASHBOARD_PORT:-12886}:2886`。
- Nginx healthcheck 使用 `localhost` 时容器内连接被拒绝；已改为 `http://127.0.0.1/healthz`，复验为 healthy。

Git 仓库初始化后的复验结果：

- 已设置 `git config core.hooksPath .husky`。
- `git hook run pre-commit` 通过。
- pre-commit hook 已改为优先使用项目根目录 `.venv` 内的 Python，避免本机全局 Python 未安装 `ruff/black` 时误失败。
- 由于当前尚无远端 PR 事件，本地无法实际触发 GitHub/Gitea PR 流水线；但 `.github/workflows/ci.yml` 已纳入 Git 仓库工作区，且对应命令已在本地通过。

SeekDB 替换后的复验结果：

- `docker pull docker.1ms.run/oceanbase/seekdb:latest` 通过。
- `docker compose config` 通过。
- `docker compose up -d --build` 通过。
- `docker compose ps` 显示 `seekdb` 使用镜像 `docker.1ms.run/oceanbase/seekdb:latest`，状态为 healthy。
- `Test-NetConnection 127.0.0.1 -Port 12881` 通过，MySQL 协议端口连通。
- `http://localhost:12886` 返回 HTTP 200，SeekDB dashboard 可访问。

前端构建优化后的复验结果：

- 移除 Element Plus 全量注册，改为当前页面组件按需导入。
- `vite.config.ts` 增加 `manualChunks`。
- `npm run build` 通过，构建不再出现 chunk 超过 500KB 的警告。
- 当前主要 chunk：
  - `vue`：约 95.50KB，gzip 约 37.27KB
  - `element`：约 16.86KB，gzip 约 6.84KB

## 剩余问题

无 Stage 1 阻塞问题。

后续阶段注意事项：

1. 当前 SeekDB 镜像通过 `docker.1ms.run` 代理拉取；如部署环境可直连 Docker Hub，可将 `SEEKDB_IMAGE` 改回 `oceanbase/seekdb:latest`。
2. SeekDB 官方 Docker 文档标注该镜像适合测试环境，不建议直接作为生产部署形态；生产上线阶段需要重新评估部署方式、资源参数、备份策略与权限配置。
3. GitHub/Gitea PR 触发 CI 需要推送到远端后验证，本地已验证流水线中的核心命令和 pre-commit hook。

## 结论

Stage 1 的代码与配置交付已完成。当前已通过静态检查、后端测试、前端构建与 Docker Compose 容器级冒烟验收。
