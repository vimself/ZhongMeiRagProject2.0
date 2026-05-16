# GLM-OCR API 服务

这是给 ZhongMei RAG 项目替换 DeepSeek-OCR API 的自托管 GLM-OCR 服务。外部 HTTP 协议保持兼容原 `DeepseekOcrApi`：RAG 后端仍可按上传、轮询、取 Markdown、取图片资产的方式调用；内部改为官方 `glmocr` self-hosted pipeline，经 vLLM OpenAI 兼容接口调用本地 `/home/ubuntu/jiang/glm-ocr` 模型。

官方 self-hosted pipeline 负责：

- PDF 渲染为页面图像
- PP-DocLayoutV3 版面检测
- 按版面区域并发识别文本、表格、公式
- 生成 Markdown、JSON 版面信息和图片裁剪集

## 目录结构与结果文件

`GlmOcrApi/` 当前按服务代码、启动脚本和 OCR 回归测试划分：

```text
GlmOcrApi/
├── app.py                         # 兼容 OCR API，负责上传、排队、状态、结果下载
├── config.py                      # 环境变量与默认配置
├── glm_processor.py               # 官方 glmocr self-hosted pipeline 包装与结果落盘
├── quality_repair.py              # OCR 后置质量修复：行级重识别、文本层对齐、公式/编号清洗
├── log_filter.py                  # vLLM/API 日志过滤器
├── start.sh                       # 启动 vLLM 与兼容 OCR API
├── stop.sh                        # 按进程组停止 vLLM/API/日志过滤器
├── example_client.py              # API 调用示例
├── requirements.txt               # Python 依赖
└── ocrtest/
    ├── run_glm_ocr_quality_test.py       # 单页/小范围质量回归
    ├── run_full_pdf_quality_audit.py     # 全 PDF 分批质量门禁
    ├── 泵站设计标准.pdf                  # 扫描水印 PDF 回归样本
    ├── DB32T 4077.1-2021 ... 通则.pdf    # 可抽取文本层 PDF 回归样本
    └── output/                           # 本地回归输出目录
```

`ocrtest/output/` 下每个 case 目录都是一次本地质量评测结果，例如：

- `db32t-textlayer-full/`：DB32T 4077.1-2021 目标 PDF 全量 98 页评测，当前质量分 99.64，阻断页 0，修复区域 214。
- `pump-full-quality-audit-v2/`：`泵站设计标准.pdf` 全量 117 页评测，当前质量分 98.77，阻断页 0，修复区域 673。
- `db32t-baseline-p001-012/`、`db32t-textlayer*-pXXX-YYY/`：本次文本层修复迭代的局部分段对比结果。
- `pump-audit-*`、`pump-page-*`、`repaired_*`、`diagnostics_*`：扫描水印 PDF 的问题页定位、修复验证和诊断结果。

典型 OCR session 或质量门禁 batch 的输出文件：

```text
case_or_batch/
├── result.md              # 修复后的 Markdown，RAG 入库优先使用
├── result.json            # 修复后的版面 JSON
├── result_raw.json        # 官方 pipeline 原始 JSON，便于对比定位
├── quality_report.json    # 修复明细：页码、bbox、原因、修复前后长度
├── metadata.json          # 模型、页数、图片/表格/公式数量、修复统计
├── images/                # 裁剪图片资产
├── layout_vis/            # 可选版面可视化图片
└── result_layout.pdf      # 可选版面可视化 PDF
```

全 PDF 质量门禁 case 还会输出：

- `quality_summary.json`：全量摘要、阻断页、警告页、空白页、修复数和质量分。
- `page_audit.json`：逐页字符量、文本层字符量、修复数、阻断/警告原因。
- `batch_audit.json`：每批页范围、耗时、修复数和问题页。
- `quality_report.md`：人工可读巡检报告。
- `batches/pages_xxx_yyy/`：每批切分页 PDF、OCR 结果和修复报告。

## 启动

```bash
cd /home/ubuntu/jiang/ragproject3/GlmOcrApi
pip install -r requirements.txt
bash start.sh
```

默认端口：

- GLM-OCR vLLM：`127.0.0.1:18080`
- 兼容 OCR API：`0.0.0.0:8899`

## 关键环境变量

- `GLM_MODEL_PATH`：默认 `/home/ubuntu/jiang/glm-ocr`
- `GLM_MODEL_NAME`：默认 `glm-ocr`，需与 vLLM `--served-model-name` 一致
- `GLM_VLLM_PORT`：默认 `18080`，避免和 RAG 前端 nginx 默认 `8080` 冲突
- `API_PORT`：默认 `8899`
- `GLM_LAYOUT_DEVICE`：默认 `cpu`，单 GPU 时避免和 vLLM 抢显存；多 GPU 可设为 `cuda:1`
- `GLM_LAYOUT_MODEL_DIR`：默认 `PaddlePaddle/PP-DocLayoutV3_safetensors`
- `GLM_MAX_WORKERS`：区域 OCR 并发，默认 `1`；批量入库优先稳定性，确认 GPU 余量后再调大
- `GLM_PDF_DPI`：PDF 渲染 DPI，默认 `200`
- `GLM_MAX_TOKENS`：单个版面区域生成上限，默认 `2048`，降低长段落进入重复循环的概率
- `GLM_REPETITION_PENALTY`：默认 `1.2`
- `GLM_IMAGE_FORMAT`：官方 pipeline 传给 vLLM 的区域图像格式，默认 `PNG`，优先保留扫描件细节
- `GLM_TEXT_LINE_REPAIR_ENABLED`：默认 `true`，开启 OCR 质量修复
- `GLM_TEXT_LINE_REPAIR_POLICY`：默认 `auto`；可设 `always` 强制多行文本块逐行重识别，或设 `off` 关闭
- `GLM_TEXT_LINE_REPAIR_MAX_LINES`：默认 `36`，单区域行级修复的常规行数上限
- `GLM_TEXT_LINE_REPAIR_MAX_REGIONS_PER_PAGE`：默认 `24`，单页最多修复区域数
- `GLM_TEXT_LINE_REPAIR_MAX_TOKENS`：默认 `192`，单行重识别生成上限
- `GLM_VLLM_LIMIT_MM_PER_PROMPT`：默认 `{"image":4}`，用于提高 vLLM 多模态 encoder cache 上限，避免大页面图片 token 超过默认缓存
- `GLM_VLLM_MAX_NUM_BATCHED_TOKENS`：默认 `16384`，直接决定 vLLM 多模态 encoder cache 的基础上限
- `GLM_VLLM_MAX_NUM_SEQS`：默认 `1`，批量入库时限制 vLLM 同时处理的请求数
- `GLM_VLLM_ENFORCE_EAGER`：默认 `1`，稳定性优先，关闭 CUDA graph/`torch.compile` 相关激进路径；确认运行稳定后再考虑设为 `0`
- `GLM_VLLM_DISABLE_CUSTOM_ALL_REDUCE`：默认 `1`，单机 OCR 服务优先避免额外通信路径；确认多卡收益后再考虑设为 `0`
- `GLM_VLLM_SPECULATIVE_CONFIG`：默认空，即默认关闭 speculative decoding；多模态 OCR 默认不建议开启，确需启用时显式传 JSON，例如 `{"method":"mtp","num_speculative_tokens":3}`
- `GLM_VLLM_DISABLE_LOG_REQUESTS`：默认 `1`，关闭 vLLM 请求详情和 uvicorn access log
- `GLM_VLLM_DISABLE_LOG_STATS`：默认 `1`，关闭 vLLM 周期 stats log
- `VLLM_LOGGING_LEVEL`：默认 `WARNING`，只保留 vLLM warning/error 等关键日志
- `API_LOG_LEVEL`：默认 `info`，保留 OCR 任务级关键日志
- `API_ACCESS_LOG`：默认 `0`，关闭 API 高频 access log；调试 HTTP 请求时可设为 `1`
- `GLM_LOG_FILTER_NCCL_BROKEN_PIPE`：默认 `1`，过滤 PyTorch/NCCL TCPStore 心跳 `Broken pipe` 噪声；排查底层分布式通信时可设为 `0`
- `GLM_LOG_FILTER_SUMMARY_INTERVAL_SECONDS`：默认 `600`，日志过滤器最多每 10 分钟输出一次累计过滤摘要；设为 `0` 可关闭摘要
- `GLM_VLLM_MAX_MODEL_LEN`：默认 `32768`
- `GLM_VLLM_GPU_MEMORY_UTILIZATION`：默认 `0.78`
- `GLM_PRELOAD_PIPELINE`：默认 `false`，设为 `true` 时 API 启动后预加载 layout pipeline
- `TEMP_DIR`：默认 `/tmp/glm_ocr_uploads`
- `DEFAULT_CALLBACK_URL`：默认 `http://127.0.0.1:18000/api/v2/ocr/callback`

## 稳定性优先默认值

`start.sh` 当前默认按单卡 OCR 稳定性优先启动 vLLM：

- 默认开启 `--enforce-eager`
- 默认开启 `--disable-custom-all-reduce`
- 默认不传 `--speculative-config`

如果要恢复更激进的吞吐调优，建议一次只打开一项，并单独观察 `ocr_log/` 中是否重新出现 NCCL/TCPStore 异常日志。

## 日志降噪与 OCR 质量判断

日志中反复出现的 `ProcessGroupNCCL` / `TCPStore sendBytes failed` / `Failed to check the "should dump" flag on TCPStore` 通常来自 PyTorch 分布式通信的后台心跳或诊断线程：TCPStore 已关闭、连接被断开，后台线程仍在尝试检查诊断开关，所以持续向 stderr 打出 `Broken pipe` 和 C++ 栈。

这些提醒本身不参与 GLM-OCR 的版面检测、页面渲染、区域识别或 Markdown/JSON 生成。判断是否影响 OCR 质量时以任务结果为准：

- 如果 `/status/{session_id}` 为 `completed`，页数、Markdown、JSON 版面信息和图片资产完整，这类日志只属于运行时噪声，不代表 OCR 文本质量下降。
- 如果同时出现 vLLM 进程退出、请求超时、session `failed`、页数缺失或结果文件不完整，则影响的是 OCR 任务可用性/完整性，需要按失败任务排查；此时可临时设置 `GLM_LOG_FILTER_NCCL_BROKEN_PIPE=0` 保留完整底层日志。

`start.sh` 默认让 vLLM 和 API 日志先经过 `log_filter.py`，只过滤上述已知噪声及紧跟的 C++ 栈；普通 warning/error、OCR 任务排队、开始、完成、失败和 callback 失败日志会继续写入 `ocr_log/`。

注意：日志过滤器由 `start.sh` 的独立 `nohup bash` 管道 wrapper 持有，`stop.sh` 会按进程组停止 wrapper、服务进程和过滤器。不要改回 Bash process substitution，否则 `start.sh` 退出后过滤器可能先关闭，API 进程后续写 stderr 会触发 `BrokenPipeError` 并导致 OCR session 失败。

## OCR 质量修复

针对扫描版规范 PDF 中常见的水印干扰和多行正文重复循环，服务在官方 GLM-OCR self-hosted pipeline 后增加一次轻量质量修复：

- 官方 pipeline 仍负责 PDF 渲染、PP-DocLayoutV3 版面检测、区域 OCR、表格/公式/图片资产输出。
- 修复器只处理文本区域：发现长输出重复、百分比数字失控、公式标记异常、编号条文多行换行等情况时，按深色文字投影把区域切成文本行，逐行调用 vLLM `Text Recognition:`，再合并为段落。
- 对带可抽取文本层的 PDF，新增保守文本层对齐修复：仍以 GLM-OCR 的版面区域和 bbox 为准，只在同一区域文本层可可靠抽取，且 GLM 输出存在章节号漂移、重复小节号、长段语义扩写或明显重复循环时，才使用文本层内容替换该区域。API 入参、状态轮询和结果返回规范不变。
- 文本层修复可纠正常见重复编号，例如 `3.222` -> `3.22`、`3.23.23` -> `3.23`、`9.4.1.1.1.1.1.1` -> `9.4.1.1`、`9.4.4.4.4.1` -> `9.4.4.1`，并容忍 OCR 原始结果中 `9. 4.1.1` 这类编号内部空格。
- 对目录类大块 `content` 区域保留行换行，避免所有目录项挤成一行；对 `1111111 电气`、`111.1`、`11.1.1.1 2`、`11.111.18.2`、`12.12.` 等章节号重复/粘连做最终落盘前规范化，同时保留 `1110V`、`1110kV` 等工程数值原文，避免把普通数值误当章节号。
- 质量门禁会把明显畸形章节号、重复章节尾号纳入问题检测；扫描件章节主线错误不再只作为低权重 warning 掩盖。
- 对标准条文中正常重复的术语和资质描述，质量门禁仍按 warning 处理，不作为阻断项。
- 对工程公式和单位文本增加窄规则清洗，修复破损 `\mathrm{左}`、`\sqrt{}`、`\sum G`、`\phi_0`、`97%～9999%` 等高确定性 OCR 噪声，避免 RAG 入库正文携带未闭合公式标记或明显生成循环。
- 每个 session 输出 `quality_report.json`，记录修复页码、区域、行数、原因和修复前后长度；`metadata.json` 增加 `quality_repair_enabled` 与 `quality_repair_count`。
- 如果需要对比官方原始效果，可临时设置 `GLM_TEXT_LINE_REPAIR_ENABLED=0` 后重启服务。

## API

兼容原服务：

- `GET /healthz`
- `GET /readyz`
- `GET /queue`
- `POST /upload`
- `GET /status/{session_id}`
- `GET /result/{session_id}/markdown`
- `GET /result/{session_id}/markdown?include_meta=true`
- `GET /result/{session_id}/assets`
- `GET /result/{session_id}/images/base64`
- `GET /result/{session_id}/images/list`
- `GET /result/{session_id}/image/{image_name}`
- `GET /result/{session_id}`
- `DELETE /session/{session_id}`

新增：

- `GET /result/{session_id}/json`
- `GET /result/{session_id}/layout`

`/result/{session_id}/assets` 会返回图片、表格、公式和 JSON 版面结果入口。

## 测试案例

```bash
curl -F "file=@/home/ubuntu/jiang/ocrtest/DB32T 4077.1-2021  矿山生态修复工程技术规程1+通则.pdf" \
  http://127.0.0.1:8899/upload
```

轮询 `/status/{session_id}` 到 `completed` 后：

```bash
curl "http://127.0.0.1:8899/result/${session_id}/markdown?include_meta=true" \
  -o /home/ubuntu/jiang/ocrtest/output/glm_result.json
curl "http://127.0.0.1:8899/result/${session_id}" \
  -o /home/ubuntu/jiang/ocrtest/output/glm_result.zip
```

本地质量回归脚本：

```bash
cd /home/ubuntu/jiang/ragproject3/GlmOcrApi
python ocrtest/run_glm_ocr_quality_test.py --page 16 --case-name pump-page16
python ocrtest/run_glm_ocr_quality_test.py --page 0 --max-pages 6 --case-name pump-first6
python ocrtest/run_glm_ocr_quality_test.py --page 16 --no-repair --case-name pump-page16-baseline
```

全 PDF 分批质量门禁脚本：

```bash
cd /home/ubuntu/jiang/ragproject3/GlmOcrApi
python ocrtest/run_full_pdf_quality_audit.py \
  --pdf "ocrtest/DB32T 4077.1-2021  矿山生态修复工程技术规程1+通则.pdf" \
  --output-dir ocrtest/output \
  --case-name db32t-textlayer-full \
  --batch-size 6
```

质量门禁会输出：

- `quality_summary.json`：全量摘要、阻断页、警告页、空白页、修复数和质量分。
- `page_audit.json`：逐页字符量、文本层字符量、修复数、阻断/警告原因。
- `quality_report.md`：人工可读巡检报告。
- `batches/pages_xxx_yyy/`：每批 OCR 结果、原始结果、质量修复报告和切分页 PDF。

当前 DB32T 4077.1-2021 目标 PDF 验证结果：

- 文件：`ocrtest/DB32T 4077.1-2021  矿山生态修复工程技术规程1+通则.pdf`
- 页数：98 页，真实空白页为第 2、6 页。
- 质量分：99.64。
- 阻断页：0。
- 警告页：13，主要是标准条款中的正常重复短语、附录编号粘连等人工巡检项。
- 修复区域：214。
- 修复拒绝：0。
- 典型修复：第 8 页定义段落重复扩写、第 10 页 `3.222`/`3.23.23` 编号漂移、第 11 页正文语义扩写、第 22 页 `9.4.1.1.1.1.1.1`/`9.4.2.2.3` 编号重复、第 23 页 `9.4.4.4.4.1` 编号重复。

章节号专项回归结果：

- `pump-section11-codex-v3`：`泵站设计标准.pdf` 第 76-78 页章节 11 开头，质量分 100.0，阻断页 0，警告页 0；`1111111 电气`、`111.1 供电系统`、`11.1.1.1 2`、`111.11. 11.3` 已规范为 `11`、`11.1`、`11.1.2`、`11.3`。
- `pump-section11-late-codex-v5`：`泵站设计标准.pdf` 第 97-102 页章节 11 后半段，质量分 99.67，阻断页 0，警告页 1；`11.11.17`、`11.111.17.1 17.1`、`11.111.18.2`、`12.12.` 已规范为 `11.17`、`11.17.1`、`11.18.2`、`12.2`。
- `db32t-section-regression-codex-v3`：DB32T 第 20-23 页文本层样本，阻断页 0，未发现新增章节号阻断；剩余 warning 为既有重复短语/重复章节巡检项。

## 注意事项

- API 协议保持兼容原 OCR 服务。质量修复只改变内部结果质量，不改变上传参数、状态轮询方式或结果接口字段规范。
- `start.sh` 默认使用 `glm-ocr` conda 环境，并同时启动 vLLM 与 API；如果只改 Python 代码，需要重启服务后才会影响 HTTP API 任务。
- vLLM/API 日志写入 `/home/ubuntu/jiang/ragproject3/ocr_log/`，测试长篇 PDF 时建议同步 `tail -F` 当前 `glm-api-*.log` 和 `glm-vllm-*.log`，重点看 session failed、请求超时、vLLM 退出等真实异常。
- `ocrtest/output/` 是本地回归结果目录，可能包含大量中间 PDF、图片和 JSON。需要清理时只删除明确确认的单个文件或单个 case 路径，避免误删仍要对比的基线结果。
- 全 PDF 质量门禁耗时较长，建议用 `--batch-size 4/6` 分批跑；中断后可用 `--resume` 复用已完成 batch，也可用 `--audit-only` 只重新审计已有结果。
- `quality_report.md` 中 warning 不等同于阻断。当前 warning 主要用于人工巡检，例如标准条款中的正常重复短语、少量修复拒绝项；生产入库更关注 `blocker_pages` 是否为空、畸形章节号是否清零、`skipped_repair_count` 是否异常、页数和资产是否完整。
- 对扫描件 PDF，文本层通常不可用，质量修复主要依赖深色文字投影切行和逐行重识别；对可复制文本 PDF，文本层修复只作为 GLM-OCR 版面 bbox 内的兜底，不替代版面检测。
- 不要把 `start.sh` 的日志过滤恢复成 Bash process substitution；当前 `nohup bash` 管道 wrapper 是为了避免父脚本退出后过滤器关闭，导致 API 写 stderr 时触发 `BrokenPipeError`。
