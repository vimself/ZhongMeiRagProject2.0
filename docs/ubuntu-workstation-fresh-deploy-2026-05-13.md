# Ubuntu 工作站全新环境上线说明（2026-05-13）

## 目标

本文档用于把当前 `ZhongMeiRagProject_v2.0` 部署到 Ubuntu 工作站，并使用**全新的数据库数据**启动系统。

本次目标不是迁移旧数据，而是让以下能力在工作站上跑起来：

- 前端 Web 页面
- FastAPI 后端
- Celery workers
- SeekDB 数据库
- Redis
- 已部署在该工作站上的 `DeepseekOcrApi`

## 先说结论

当前仓库已经具备后端、Worker、SeekDB、Redis、Nginx 的 Docker Compose 编排，但**前端生产托管还没接进现有 Compose/Nginx**。
因此，如果要在 Ubuntu 工作站上作为完整系统上线，至少需要处理这三类配置：

1. `.env`：改成工作站环境可用的生产参数。
2. `docker-compose.yml`：让容器能访问宿主机上的 OCR 服务，并把前端构建产物挂给 Nginx。
3. `ops/nginx/nginx.conf`：让 Nginx 同时提供前端静态站点、SPA 路由回退和大文件上传能力。

2026-05-13 本机实部署时还确认了两个细节：

- `location /api/` 代理到 FastAPI 时必须保留原始 `/api/v2/*` 路径，`proxy_pass` 不应写成带尾部 `/` 的形式。
- 如果 Docker Hub 匿名拉取触发限流，可以把基础服务镜像和 Python 基础镜像切到可用镜像代理，并给 pip 配置更长超时/重试和可用 PyPI 镜像。
- `docker.1ms.run/grafana/grafana:11.3.0` 在本机启动时会扫描到两个内置 `xychart` 插件目录；可通过只读挂载空目录屏蔽重复的 `v2` 插件目录，并挂载空 `plugins-bundled` 目录减少无效 warning。

## 当前仓库现状

基于当前代码，几个关键事实如下：

- 后端/Worker 使用 Docker 镜像启动，配置入口是根目录 `docker-compose.yml`。
- 前端当前只有开发态 `Vite` 配置，生产态没有被 Compose/Nginx 托管。
- OCR 服务默认假设部署在远端工作站 `222.195.4.65:8899`，但你现在要把业务系统也放到这台工作站。
- 后端 OCR 客户端当前**不支持给 OCR `/upload` 和 `/session/{id}` 自动带 `Authorization` header`**。
- API 容器当前默认 `SEED_DEFAULT_USERS=1`，这更适合本地开发，不适合长期生产启动。

## 推荐部署拓扑

推荐采用下面这个结构：

```text
Ubuntu 宿主机
├─ DeepseekOcrApi（宿主机进程，监听 8899）
└─ Docker Compose
   ├─ nginx            8080 -> 前端静态文件 + /api 反向代理
   ├─ api              FastAPI
   ├─ worker-*         Celery workers
   ├─ redis            broker / result backend
   └─ seekdb           业务数据库
```

这样做的原因：

- OCR 已经是这台工作站上的独立服务，继续跑在宿主机最省事。
- 业务系统仍复用现有 Compose，不需要再拆第二套部署方式。
- 前端直接由同一个 Nginx 提供静态文件，`VITE_API_BASE_URL=/api/v2` 可以保持不变。

## 必须修改的配置

### 1. `.env`

建议从 `.env.example` 复制一份新的工作站环境配置：

```bash
cp .env.example .env
```

至少修改为下面这种思路：

```env
APP_ENV=prod
JWT_SECRET=请替换为足够长的强随机字符串

ADMIN_SEED_USERNAME=admin
ADMIN_SEED_PASSWORD=Admin@123
USER_SEED_USERNAME=user
USER_SEED_PASSWORD=User@123
DEFAULT_USERS_RESET_PASSWORDS=false

REDIS_URL=redis://redis:6379/0
DATABASE_URL=mysql+asyncmy://root:zhongmei-root@seekdb:2881/zhongmei?charset=utf8mb4

VITE_API_BASE_URL=/api/v2

DASHSCOPE_API_KEY=你的DashScopeKey
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_NATIVE_BASE_URL=https://dashscope.aliyuncs.com/api/v1

OCR_BASE_URL=http://host.docker.internal:8899
OCR_CALLBACK_BASE_URL=http://127.0.0.1:8000
OCR_CALLBACK_TOKEN=请填写一个随机token，并与OCR服务端保持一致

UPLOAD_DIR=uploads/documents
EXPORT_DIR=uploads/exports
UPLOAD_MAX_MB=200
UPLOAD_MAX_FILES=50
```

这里有 4 个关键点：

1. `OCR_BASE_URL` 不要直接写 `http://127.0.0.1:8899`
   因为 `api` 和 `worker-ingest` 跑在容器里，容器里的 `127.0.0.1` 指向容器自己，不是 Ubuntu 宿主机。

2. `OCR_BASE_URL` 推荐写成 `http://host.docker.internal:8899`
   但 Linux 下要配合 `docker-compose.yml` 里的 `extra_hosts` 一起用，否则这个域名默认不可解析。

3. `OCR_CALLBACK_BASE_URL` 可以写成 `http://127.0.0.1:8000`
   这是给**宿主机上的 OCR 服务**回调用的。OCR 进程跑在宿主机，访问宿主机暴露出来的 API 端口最直接。

4. `OCR_CALLBACK_TOKEN` 建议一定要启用
   后端 `POST /api/v2/ocr/callback` 已支持 Bearer Token 校验，工作站本机部署时没必要把回调口裸奔。

   如果工作站上现有 `DeepseekOcrApi` 进程没有配置 `OCR_CALLBACK_TOKEN`，后端也必须先保持为空；否则 OCR 回调会被后端拒绝。要启用时，需要两端使用同一个 token。

### 2. `docker-compose.yml`

建议做以下调整。

#### 2.1 让容器能访问宿主机 OCR

最少给 `api` 和 `worker-ingest` 加上：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

原因：

- `api` 需要探活 OCR 状态（仪表板接口会访问 OCR `/healthz`）。
- `worker-ingest` 需要上传 PDF 到 OCR，并轮询 OCR 结果。

#### 2.2 把前端构建产物挂到 Nginx

给 `nginx` 增加静态文件挂载：

```yaml
services:
  nginx:
    volumes:
      - ./ops/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/dist:/usr/share/nginx/html:ro
```

否则当前 Nginx 只会转发 `/api`，不会返回前端页面。

#### 2.3 不建议继续把默认用户初始化写死在长期启动流程里

当前 `api` 服务里写的是：

```yaml
environment:
  RUN_ALEMBIC: "1"
  SEED_DEFAULT_USERS: "1"
```

更稳妥的上线方式是改成：

```yaml
environment:
  RUN_ALEMBIC: "1"
  SEED_DEFAULT_USERS: "0"
```

然后在首次启动成功后，手动执行一次：

```bash
docker compose exec -T api python -m app.cli.seed_default_users
```

原因很直接：

- 当前 `seed_default_users` 脚本会把系统最终收敛为只保留 `admin` 和 `user` 两个用户。
- 全新环境首次启动时这样做没问题。
- 但如果你以后正式创建了更多用户，这个开关长期保持 `1` 会有风险。

#### 2.4 建议给 Redis 补持久化卷

当前 Compose 中 Redis 开了 `appendonly yes`，但**没有 volume**，容器重建后数据并不稳妥。

建议改成：

```yaml
services:
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data

volumes:
  seekdb-data:
  uploads-data:
  redis-data:
```

这不是系统跑起来的硬前提，但作为工作站部署，建议补上。

#### 2.5 Docker Hub 限流时的镜像代理

本机部署时遇到 Docker Hub 匿名拉取限流，已将 Compose 中的基础服务镜像改为镜像代理形式，例如：

```yaml
services:
  nginx:
    image: docker.1ms.run/nginx:1.27-alpine
  redis:
    image: docker.1ms.run/redis:7-alpine
  prometheus:
    image: docker.1ms.run/prom/prometheus:v2.55.1
  grafana:
    image: docker.1ms.run/grafana/grafana:11.3.0
    volumes:
      - ./ops/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./ops/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - ./ops/grafana/plugins-bundled:/usr/share/grafana/plugins-bundled:ro
      - ./ops/grafana/empty-plugin-dir:/usr/share/grafana/public/app/plugins/panel/xychart/v2:ro
```

同理，后端和 Worker Dockerfile 的基础镜像也可以切到：

```dockerfile
FROM docker.1ms.run/python:3.11-slim AS runtime
```

如果 pip 下载超时，可以在 Dockerfile 中设置：

```dockerfile
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
```

### 3. `ops/nginx/nginx.conf`

当前 Nginx 配置只有 `/api/` 反向代理，没有前端静态站点，也没有 SPA fallback。

建议至少补下面几项：

1. 设置静态站点根目录：

```nginx
root /usr/share/nginx/html;
index index.html;
```

2. 补首页和前端路由回退：

```nginx
location / {
  try_files $uri $uri/ /index.html;
}
```

3. 提高上传上限：

```nginx
client_max_body_size 10g;
```

这一项非常重要。
当前项目单文件上传上限是 `UPLOAD_MAX_MB=200`，并支持单次最多 `UPLOAD_MAX_FILES=50` 份 PDF。如果 Nginx 仍按单文件大小限制，批量上传时生产环境走 `/api` 很容易直接返回 `413 Request Entity Too Large`；默认应按 50 份 200MB 的批量请求总量放大到 `10g`。

一个更完整的参考结构如下：

```nginx
events {
  worker_connections 1024;
}

http {
  include /etc/nginx/mime.types;
  default_type application/octet-stream;

  sendfile on;
  keepalive_timeout 65;
  client_max_body_size 10g;

  map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
  }

  upstream api_upstream {
    server api:8000;
  }

  server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location /healthz {
      proxy_pass http://api_upstream/healthz;
    }

    location /readyz {
      proxy_pass http://api_upstream/readyz;
    }

    location /api/ {
      proxy_pass http://api_upstream;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_set_header Range $http_range;
      proxy_set_header If-Range $http_if_range;
      proxy_buffering off;
      proxy_cache off;
      chunked_transfer_encoding off;
    }

    location / {
      try_files $uri $uri/ /index.html;
    }
  }
}
```

注意这里的 `proxy_pass http://api_upstream;` 不能写成 `proxy_pass http://api_upstream/;`。
当前前端请求路径是 `/api/v2/*`，而 FastAPI 路由也注册在 `/api/v2/*`。
如果 `proxy_pass` 带尾部 `/`，Nginx 会把 `/api/v2/auth/login` 改写成 `/v2/auth/login`，导致接口 404。

## OCR 服务端需要同步确认的配置

`DeepseekOcrApi` 跑在工作站宿主机时，建议确认这几个环境变量：

```bash
export API_HOST=0.0.0.0
export API_PORT=8899
export DEFAULT_CALLBACK_URL=http://127.0.0.1:8000/api/v2/ocr/callback
export OCR_CALLBACK_TOKEN=与后端OCR_CALLBACK_TOKEN一致
```

注意一个非常关键的限制：

- `DeepseekOcrApi` 支持 `API_TOKEN`，但当前仓库里的后端 OCR 客户端**没有**给 `/upload` 和 `/session/{id}` 自动附带 Bearer Token。
- 也就是说，**在你不改后端代码的前提下，OCR 服务端的 `API_TOKEN` 现在必须留空**。
- 如果你后面确实想给 OCR 上传接口加鉴权，需要先改 `backend/app/services/ocr/client.py`，再上线。

## 推荐上线步骤

### 1. 准备 Ubuntu 环境

至少确保这些组件可用：

- Docker Engine
- Docker Compose Plugin
- Git
- Node.js 20+
- npm

### 2. 拉取代码

```bash
git clone https://github.com/vimself/ZhongMeiRagProject2.0.git
cd ZhongMeiRagProject2.0
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

然后按上面的说明修改 `.env`。

### 4. 修改 Compose 和 Nginx

至少完成这几项：

- `api`、`worker-ingest` 增加 `extra_hosts`
- `nginx` 挂载 `./frontend/dist`
- Nginx 配置增加静态站点、SPA fallback、`client_max_body_size 10g`
- `api` 的 `SEED_DEFAULT_USERS` 改为 `0`
- Redis 增加持久化卷（推荐）

### 5. 构建前端生产产物

```bash
cd frontend
npm ci
npm run build
cd ..
```

构建成功后，应当生成 `frontend/dist/`。

### 6. 确保宿主机 OCR 服务可用

在工作站上先确认：

```bash
curl http://127.0.0.1:8899/healthz
```

如果 OCR 未启动，再按 `DeepseekOcrApi` 的启动方式拉起来。

### 7. 启动整套系统

```bash
docker compose up -d --build
```

### 8. 首次手动初始化默认用户

因为上面建议你把 `SEED_DEFAULT_USERS` 设成 `0`，所以首次启动后手动执行一次：

```bash
docker compose exec -T api python -m app.cli.seed_default_users
```

### 9. 检查运行状态

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f worker-ingest
```

再检查接口：

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
curl http://127.0.0.1/healthz
curl http://127.0.0.1:8899/healthz
```

## Fresh DB 场景下的说明

这次你明确说了**不迁移旧数据**，所以这里直接使用新的数据库即可。

这意味着：

- `seekdb-data` 直接让新环境自己初始化。
- `uploads-data` 也不需要从旧环境拷贝。
- 只要 `.env`、Compose、Nginx、OCR 回调关系配置正确，系统就能在空库上自动建表并启动。

## 上线后建议立即做的 5 件事

1. 用初始化的 `admin` 账号登录后，立刻改密码。
2. 上传一份小 PDF，验证 OCR 入库链路。
3. 在管理后台检查数据库、Redis、OCR、LLM 状态是否正常。
4. 确认前端上传 50MB 以上 PDF 时不会被 Nginx 直接拦成 `413`。
5. 如果工作站要对公网或更大内网开放，再补 HTTPS、端口暴露收敛和防火墙规则。

## 一句话版本

这次不是“迁库上线”，而是“在 OCR 工作站上起一套全新的业务环境”。
真正必须处理的点只有 4 个：**前端静态托管、容器访问宿主机 OCR、OCR 回调地址、Nginx 上传上限**。把这 4 个点配对了，系统就在空库上跑起来。
