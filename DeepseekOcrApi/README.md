# DeepSeek OCR API 服务（已下线）

本项目已切换到 `../GlmOcrApi/`。旧 DeepSeek-OCR API 不再作为文档入库 OCR 服务启动。

当前 OCR 运行入口：

```bash
bash /home/ubuntu/jiang/ragproject3/GlmOcrApi/start.sh
```

GLM-OCR 服务对外继续提供兼容的 `:8899` 上传、轮询、Markdown、图片资产接口，并新增 layout JSON 输出。
