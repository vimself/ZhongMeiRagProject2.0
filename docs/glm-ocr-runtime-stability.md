# GLM-OCR Runtime Stability

更新时间：2026-05-16

## 背景

GLM-OCR 的 vLLM 运行日志中出现持续的 `ProcessGroupNCCL` / `TCPStore Broken pipe` 告警。现阶段先按“稳定性优先”收紧默认启动参数，降低多余的推理加速路径和通信复杂度。

这类日志通常来自 PyTorch 分布式通信后台心跳或诊断线程：TCPStore 已关闭或连接被断开后，线程仍尝试检查诊断开关，于是向 stderr 输出 `Broken pipe` 和 C++ 栈。它不直接参与 PDF 渲染、版面检测、区域识别或 Markdown/JSON 生成；只要 OCR session 正常 `completed` 且页数、Markdown、JSON、图片资产完整，就不代表 OCR 文本质量下降。若同时伴随 vLLM 退出、请求超时、session `failed` 或结果缺页，则按任务失败/服务稳定性问题处理。

## 默认策略

`GlmOcrApi/start.sh` 调整为以下保守默认值：

- `GLM_VLLM_ENFORCE_EAGER=1`
- `GLM_VLLM_DISABLE_CUSTOM_ALL_REDUCE=1`
- `GLM_VLLM_SPECULATIVE_CONFIG` 默认留空

现有保留项：

- `GLM_VLLM_MAX_NUM_SEQS=1`
- `GLM_VLLM_MAX_NUM_BATCHED_TOKENS=16384`
- `GLM_VLLM_LIMIT_MM_PER_PROMPT={"image":4}`

## 日志策略

`GlmOcrApi/start.sh` 默认将 vLLM 和 API 进程输出接入 `GlmOcrApi/log_filter.py` 后再写入 `ocr_log/`：

- `GLM_LOG_FILTER_NCCL_BROKEN_PIPE=1`：默认过滤 `ProcessGroupNCCL` / `TCPStore sendBytes failed` / `should dump` 的 `Broken pipe` 噪声及紧跟的 C++ 栈。
- `GLM_LOG_FILTER_SUMMARY_INTERVAL_SECONDS=600`：最多每 10 分钟输出一次过滤摘要，避免日志被摘要本身刷屏；设为 `0` 可关闭摘要。
- 普通 warning/error、OCR 任务排队、开始、完成、失败和 callback 失败日志不做过滤。

需要排查 PyTorch/vLLM 底层分布式通信时，临时设置 `GLM_LOG_FILTER_NCCL_BROKEN_PIPE=0` 后重启 `GlmOcrApi/start.sh`，即可保留完整原始日志。

2026-05-16 修复：日志过滤不能使用 Bash process substitution 启动。该方式会在 `start.sh` 退出后关闭过滤器进程，导致 API 进程后续 `tqdm` 写 stderr 时触发 `BrokenPipeError`，OCR session 直接失败。当前 `start.sh` 使用独立 `nohup bash` 管道 wrapper 持有服务进程和 `log_filter.py`，`stop.sh` 按进程组停止 wrapper、服务和过滤器。

## 调优原则

- 先看 OCR 任务成功率、耗时、结果完整性，再看吞吐。
- 需要恢复吞吐优化时，一次只放开一个开关，避免多变量叠加。
- 如果重新开启 speculative decoding，优先在压测环境验证，不直接回到生产默认值。
