# ZhongMei RAG Project v2.0

Stage 6 已完成文档预览与 RAG 元数据闭环（详见 `docs/stage-6-document-preview-rag-progress.md`），包含 PDF/资产短时签名 URL、HTTP Range 预览、bbox 高亮组件、RAG 检索引用元数据和 `retrieval/debug` 冒烟 API。

Stage 1 已建立基础工程骨架：

- `backend/`：FastAPI、Celery、pytest、ruff/black/mypy 配置。
- `frontend/`：Vite、Vue 3、TypeScript、Pinia、Element Plus 配置。
- `docker/`：API/Worker 镜像与入口脚本。
- `ops/`：Nginx、Prometheus、Grafana 默认配置。
- `.github/workflows/ci.yml`：lint、test、build、Trivy 扫描流水线。
- `DeepseekOcrApi/`：自托管 DeepSeek-OCR-2 API 服务代码，部署在校园网工作站 `222.195.4.65:8899`。

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
- PDF preview sign: `POST http://localhost:8000/api/v2/pdf/sign`
- PDF preview: `GET http://localhost:8000/api/v2/pdf/preview?document_id=...&token=...`

## 外部依赖：自托管 OCR 服务

文档识别使用校园网工作站部署的 DeepSeek-OCR-2 API 服务（非阿里云 DashScope OCR）：

- **工作站地址**：`222.195.4.65:8899`（已部署运行）
- **连接方式**：校园网 VPN 或 SSH 反向隧道（`ssh -R`）
    ssh -N -T -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:18000:127.0.0.1:8000 ubuntu@222.195.4.65
- **服务代码**：`DeepseekOcrApi/` 目录
- **API 协议**：异步模式（`POST /upload` → 轮询 `GET /status/{id}` → `GET /result/{id}/markdown`）
- **Stage 6 连通验证**：`GET /healthz` 返回 `{"status":"ok"}`，`GET /queue` 返回当前队列状态。

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
