# DeepSeek OCR API 服务

这是 ZhongMei RAG v2.0 使用的自托管 DeepSeek-OCR-2 服务端。服务采用单例 vLLM、内部异步队列和持久化 `meta.json` 会话状态。Windows 本机开启校园网 VPN 后直接访问工作站 `http://222.195.4.65:8899`；工作站回调 Windows 本机通过 SSH 反向隧道访问 `http://127.0.0.1:18000`。

## 启动

```bash
pip install -r requirements.txt
bash start.sh
```

关键环境变量：

- `API_HOST` / `API_PORT`：默认 `0.0.0.0:8899`
- `API_TOKEN`：设置后，`POST /upload` 与 `DELETE /session/{sid}` 必须带 `Authorization: Bearer <token>`
- `DEFAULT_CALLBACK_URL`：默认 `http://127.0.0.1:18000/api/v2/ocr/callback`，用于工作站侧通过反向隧道回调 Windows 后端
- `OCR_CALLBACK_TOKEN`：回调时写入 `Authorization: Bearer <token>`，需与后端 `OCR_CALLBACK_TOKEN` 一致
- `CORS_ALLOW_ORIGINS`：逗号分隔白名单，默认 `*`
- `QUEUE_SIZE`：默认 `16`
- `MAX_FILE_SIZE`：默认 `200MB`
- `GENERATE_TIMEOUT_SECONDS`：默认 `50min`
- `TEMP_DIR`：默认 `/tmp/deepseek_ocr_uploads`

## API

### 健康检查

- `GET /healthz`：进程存活
- `GET /readyz`：模型加载和 GPU 可用性
- `GET /queue`：队列长度与活跃任务数

### 上传

`POST /upload`

表单字段：

- `file`：PDF 文件
- `priority`：整数，默认 `5`
- `callback_url`：可选；未传时使用 `DEFAULT_CALLBACK_URL`，处理完成或失败后 POST 回调

返回：

```json
{
  "session_id": "uuid",
  "status": "queued",
  "message": "PDF uploaded successfully. Processing queued."
}
```

### 状态

`GET /status/{session_id}`

返回包含 `status`、`progress`、`stage`、`started_at`、`updated_at`、`elapsed_ms`、结构化错误字段，并保留 `is_completed` / `is_failed` 兼容字段。

### 结果

- `GET /result/{session_id}/markdown`
- `GET /result/{session_id}/markdown?include_meta=true`
- `GET /result/{session_id}/assets`
- `GET /result/{session_id}/images/base64`
- `GET /result/{session_id}/images/list`
- `GET /result/{session_id}/image/{image_name}`
- `GET /result/{session_id}`：完整 ZIP

`include_meta=true` 时 markdown 接口返回：

```json
{
  "session_id": "uuid",
  "markdown": "# 文档内容",
  "page_count": 12,
  "outline": [{"level": 1, "title": "第一章 总则"}],
  "processed_at": "2026-05-09T00:00:00+00:00"
}
```

### 删除会话

`DELETE /session/{session_id}`

设置 `API_TOKEN` 后需要鉴权。服务端只删除一个明确 session 目录，并校验目录位于 `TEMP_DIR` 下。

## 运行模型

`PDFOCRProcessor` 保持单例 vLLM。`/upload` 只入队并立即返回，后台 worker 串行调用模型，避免高并发将 GPU 拉满。`meta.json` 会持久化上传时间、文件名、状态、阶段、进度、耗时、错误和资产元数据。后台清理协程每 30 分钟清理超过 24 小时未更新的 session。
