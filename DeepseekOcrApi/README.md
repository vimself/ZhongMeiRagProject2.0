# DeepSeek OCR API 服务

基于 DeepSeek-OCR-2 的 PDF 识别 API 服务，支持多任务并发处理。

## 功能特性

- 上传 PDF 文件进行 OCR 识别
- 返回 Markdown 格式的识别结果
- 提取 PDF 中的图片内容
- 支持多任务并发处理
- 提供 RESTful API 接口

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动服务

```bash
bash start.sh
```

或者直接运行：

```bash
python3 -m uvicorn app:app --host 0.0.0.0 --port 8899 --workers 1
```

## API 接口

### 1. 上传 PDF

**接口**: `POST /upload`

**参数**:
- `file`: PDF 文件 (multipart/form-data)

**返回**:
```json
{
  "session_id": "uuid",
  "status": "processing",
  "message": "PDF uploaded successfully. Processing started."
}
```

### 2. 查询处理状态

**接口**: `GET /status/{session_id}`

**返回**:
```json
{
  "session_id": "uuid",
  "status": "completed",
  "is_completed": true,
  "is_failed": false
}
```

状态值：
- `processing`: 处理中
- `completed`: 完成
- `failed`: 失败

### 3. 下载完整结果

**接口**: `GET /result/{session_id}`

**返回**: ZIP 文件，包含：
- `result.md`: Markdown 结果
- `result_det.md`: 带检测标记的 Markdown
- `result_layout.pdf`: 带布局标注的 PDF
- `images/`: 提取的图片文件夹

### 4. 获取 Markdown 内容

**接口**: `GET /result/{session_id}/markdown`

**返回**:
```json
{
  "session_id": "uuid",
  "markdown": "# 文档内容..."
}
```

### 5. 下载所有图片

**接口**: `GET /result/{session_id}/images`

**返回**: ZIP 文件，包含所有提取的图片

### 6. 下载单张图片

**接口**: `GET /result/{session_id}/image/{image_name}`

**返回**: 图片文件

### 7. 删除会话

**接口**: `DELETE /session/{session_id}`

**返回**:
```json
{
  "session_id": "uuid",
  "message": "Session deleted successfully."
}
```

## 使用示例

### Python 示例

```python
import requests
import time

# 上传 PDF
url = "http://localhost:8000/upload"
with open("test.pdf", "rb") as f:
    response = requests.post(url, files={"file": f})
    session_id = response.json()["session_id"]
    print(f"Session ID: {session_id}")

# 轮询查询状态
status_url = f"http://localhost:8000/status/{session_id}"
while True:
    response = requests.get(status_url)
    status = response.json()["status"]
    print(f"Status: {status}")
    
    if status == "completed":
        break
    elif status.startswith("failed"):
        print(f"Processing failed: {status}")
        break
    
    time.sleep(5)

# 下载结果
result_url = f"http://localhost:8000/result/{session_id}"
response = requests.get(result_url)
with open("results.zip", "wb") as f:
    f.write(response.content)

# 获取 Markdown 内容
markdown_url = f"http://localhost:8000/result/{session_id}/markdown"
response = requests.get(markdown_url)
markdown = response.json()["markdown"]
print(markdown)
```

### cURL 示例

```bash
# 上传 PDF
curl -X POST -F "file=@test.pdf" http://localhost:8000/upload

# 查询状态
curl http://localhost:8000/status/{session_id}

# 下载结果
curl -O http://localhost:8000/result/{session_id}

# 获取 Markdown
curl http://localhost:8000/result/{session_id}/markdown

# 下载所有图片
curl -O http://localhost:8000/result/{session_id}/images

# 删除会话
curl -X DELETE http://localhost:8000/session/{session_id}
```

## 配置说明

在 `config.py` 中可以修改以下配置：

- `MODEL_PATH`: 模型路径
- `MAX_CONCURRENCY`: 最大并发数
- `NUM_WORKERS`: 图片预处理工作线程数
- `API_HOST`: API 服务监听地址
- `API_PORT`: API 服务端口
- `API_WORKERS`: API 工作进程数
- `TEMP_DIR`: 临时文件存储目录
- `MAX_FILE_SIZE`: 最大文件大小（字节）

## 注意事项

1. 首次启动会加载模型，需要较长时间
2. 确保模型路径正确，模型文件完整
3. 临时文件存储在 `/tmp/deepseek_ocr_uploads/` 目录
4. 建议定期清理临时文件以释放磁盘空间
5. 处理大文件时请确保有足够的内存和磁盘空间
