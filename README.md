# ZhongMei RAG Project v2.0

Stage 1 已建立基础工程骨架：

- `backend/`：FastAPI、Celery、pytest、ruff/black/mypy 配置。
- `frontend/`：Vite、Vue 3、TypeScript、Pinia、Element Plus 配置。
- `docker/`：API/Worker 镜像与入口脚本。
- `ops/`：Nginx、Prometheus、Grafana 默认配置。
- `.github/workflows/ci.yml`：lint、test、build、Trivy 扫描流水线。

## 快速开始

1. 复制环境变量：

```bash
cp .env.example .env
```

2. 启动基础服务：

```bash
docker compose up --build
```

3. 访问：

- API health: `http://localhost:8000/healthz`
- API ready: `http://localhost:8000/readyz`
- Nginx: `http://localhost:8080`
- Flower: `http://localhost:5555`
- Grafana: `http://localhost:3000`
- SeekDB MySQL protocol: `127.0.0.1:12881`
- SeekDB dashboard: `http://localhost:12886`

## 本地开发

后端：

```bash
cd backend
python -m pip install -e ".[dev]"
pytest
```

前端：

```bash
cd frontend
npm install
npm run build
```
