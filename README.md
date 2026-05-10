# ZhongMei RAG Project v2.0

中煤 RAG v2.0 是一个工程文档知识库与 RAG 问答系统。当前已完成 Stage 7：

- 后端：FastAPI、SeekDB、Redis、Celery、DashScope LLM/Embedding、DeepSeek-OCR 工作站接入。
- 前端：Vue 3、TypeScript、Vite、Pinia、Element Plus，包含知识库、文档入库、PDF 预览、RAG 问答工作台。
- 基础设施：Docker Compose 启动 API、Worker、Redis、SeekDB、Nginx、Flower、Prometheus、Grafana。

这份 README 按“小白也能跑起来”的方式写：照着做即可完成本地启动、创建管理员账号、打开浏览器登录测试。

## 1. 准备环境

请先安装：

1. Docker Desktop
2. Node.js 20+（建议 LTS）
3. Git

Windows 用户建议在 PowerShell 里执行命令。以下命令默认都在项目根目录执行：

```powershell
cd E:\ZhongMeiRagProject_v2.0
```

## 2. 配置环境变量

复制示例配置：

```powershell
Copy-Item .env.example .env
```

打开 `.env`，至少检查这些配置：

```env
ADMIN_SEED_USERNAME=admin
ADMIN_SEED_PASSWORD=Admin@123456
ADMIN_SEED_DISPLAY_NAME=系统管理员
DASHSCOPE_API_KEY=你的阿里云DashScopeKey
```

本地测试账号建议使用：

- 初始用户名：`admin`
- 初始密码：`Admin@123456`

说明：

- `ADMIN_SEED_PASSWORD` 是初始化管理员密码。你也可以改成自己的密码。
- `Admin@123456` 只用于本地测试；正式部署必须换成强密码。
- `DASHSCOPE_API_KEY` 用于 RAG 问答和 embedding。只测试登录、用户管理、知识库页面时可以先不填；要测试文档入库和问答，建议配置真实 key。
- `.env.example` 只是模板，Docker Compose 实际读取 `.env`。

## 3. 启动后端、数据库和队列

第一次启动会构建镜像，时间会比较久：

```powershell
docker compose up --build -d
```

等待服务启动：

```powershell
docker compose ps
```

看到 `api`、`redis`、`seekdb` 为 healthy，说明核心服务已起来。

也可以打开这些地址检查：

- API 健康检查：http://localhost:8000/healthz
- API 就绪检查：http://localhost:8000/readyz
- Nginx 健康检查：http://localhost:8080/healthz
- Flower 队列监控：http://localhost:5555
- Prometheus：http://localhost:9090
- Grafana：http://localhost:3000
- SeekDB Dashboard：http://localhost:12886

## 4. 创建初始管理员账号

后端容器启动后，执行：

```powershell
docker compose exec -T api python -m app.cli.seed_admin
```

这条命令会按 `.env` 里的配置创建或重置管理员账号。

默认测试登录信息：

- 用户名：`admin`
- 密码：`Admin@123456`

首次登录后系统可能要求修改密码，这是正常行为。

## 5. 启动前端页面

Docker Compose 当前不托管 Vue 前端静态页面，本地测试需要单独启动前端开发服务器。

进入前端目录并安装依赖：

```powershell
cd frontend
npm install
```

启动前端：

```powershell
npm run dev
```

看到 Vite 输出地址后，打开：

```text
http://localhost:5173
```

使用上面的管理员账号登录：

- 用户名：`admin`
- 密码：`Admin@123456`

前端请求会通过 Vite 代理转发到后端 `http://localhost:8000`，不需要手动改 API 地址。

## 6. 最简单的测试流程

登录后可以按这个顺序测试：

1. 打开首页，确认能看到系统入口。
2. 进入“知识库”，创建一个测试知识库。
3. 进入知识库文档页，上传 PDF。
4. 等待入库任务完成。
5. 打开“RAG 问答”，选择知识库，输入问题测试引用回答。
6. 点击回答里的引用，验证 PDF 预览和 bbox 高亮。

注意：

- 文档 OCR 使用校园网工作站 `222.195.4.65:8899` 上的 DeepSeek-OCR-2 服务。
- 如果你不在校园网或没有 VPN，上传 PDF 后 OCR 入库可能失败；登录、知识库管理、用户管理等功能仍可测试。
- 如果要让工作站回调本机 API，需要保持后端可被工作站访问，项目约定使用 SSH 反向隧道。

SSH 反向隧道示例：

```powershell
ssh -N -T -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:18000:127.0.0.1:8000 ubuntu@222.195.4.65
```

## 7. 常用命令

查看服务状态：

```powershell
docker compose ps
```

查看 API 日志：

```powershell
docker compose logs -f api
```

查看入库 Worker 日志：

```powershell
docker compose logs -f worker-ingest
```

停止所有容器：

```powershell
docker compose down
```

重新构建并启动：

```powershell
docker compose up --build -d
```

重新初始化管理员密码：

```powershell
docker compose exec -T api python -m app.cli.seed_admin
```

## 8. 本地开发验证

后端检查：

```powershell
cd E:\ZhongMeiRagProject_v2.0
.venv\Scripts\ruff.exe check backend eval
.venv\Scripts\mypy.exe backend\app
.venv\Scripts\pytest.exe backend\tests -q
```

前端检查：

```powershell
cd E:\ZhongMeiRagProject_v2.0\frontend
npm run lint
npm run stylelint
npm run build
```

## 9. 常见问题

### 访问 `http://localhost:5173` 打不开

确认前端开发服务器是否启动：

```powershell
cd E:\ZhongMeiRagProject_v2.0\frontend
npm run dev
```

### 登录提示账号不存在或密码错误

重新执行管理员初始化：

```powershell
cd E:\ZhongMeiRagProject_v2.0
docker compose exec -T api python -m app.cli.seed_admin
```

然后用 `.env` 里的 `ADMIN_SEED_USERNAME` 和 `ADMIN_SEED_PASSWORD` 登录。

### API 不健康

查看容器状态和日志：

```powershell
docker compose ps
docker compose logs -f api
```

常见原因是 SeekDB 还没完全启动。第一次启动 SeekDB 可能需要等 1 到 3 分钟。

### RAG 问答没有正常生成

检查：

1. `.env` 里是否配置了 `DASHSCOPE_API_KEY`。
2. 文档是否已经入库完成。
3. OCR 工作站是否能访问。
4. `worker-ingest` 日志是否有报错。

## 10. 目录说明

- `backend/`：FastAPI 后端、Celery 任务、Alembic 迁移、测试。
- `frontend/`：Vue 3 前端。
- `docs/`：各阶段进度文档和总体设计。
- `docker/`：API/Worker 镜像构建文件与入口脚本。
- `ops/`：Nginx、Prometheus、Grafana 配置。
- `DeepseekOcrApi/`：自托管 OCR 服务代码。
