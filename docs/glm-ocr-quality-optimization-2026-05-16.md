# GLM-OCR 识别质量优化

日期：2026-05-16

## 背景

`GlmOcrApi/ocrtest/泵站设计标准.pdf` 是扫描版 PDF，页面带有浅灰水印，且无可抽取文本层。官方 GLM-OCR self-hosted pipeline 在第 16 页 `4.2.1` 多行条文区域出现明显重复循环和缺漏，例如第 2、3、4 条会把“水库调蓄性能”“重现期 5 年～10 年”等短语反复生成。

## 调整

- 官方 GLM-OCR pipeline 仍作为主流程，继续负责 PDF 渲染、PP-DocLayoutV3 版面检测、区域识别、Markdown/JSON、图片资产和版面可视化。
- 新增 `GlmOcrApi/quality_repair.py`：对文本区域做后置质量修复，发现长输出重复、公式标记异常、编号条文多行换行等情况时，按深色文字投影切分为文本行，逐行调用本地 vLLM `Text Recognition:`，再合并回原版面区域。
- 对目录类大块 `content` 区域保留行换行，避免行级修复后所有目录项挤在一行。
- `result.md` 与 `result.json` 使用修复后的文本；`result_raw.json` 保留官方 pipeline 原始识别结果；新增 `quality_report.json` 记录每个修复区域的页码、bbox、行数、原因和修复前后长度。
- 默认将区域 OCR 生成上限从 `8192` 降到 `2048`，图像编码改为 `PNG`，`repetition_penalty` 调整为 `1.2`，降低长区域生成循环概率。
- 增加章节号规范化，修正 `4. 2.1`、顺序上下文中误读为 `4.2.2.2` 等常见版面 OCR 后处理问题。

## 关键环境变量

- `GLM_TEXT_LINE_REPAIR_ENABLED=true`：启用质量修复；对比原始 pipeline 时可设为 `0`。
- `GLM_TEXT_LINE_REPAIR_POLICY=auto`：默认只修复疑似坏块和多行编号条文；可设 `always` 强制多行文本块逐行重识别，或 `off` 关闭。
- `GLM_TEXT_LINE_REPAIR_MAX_LINES=36`：单区域行级修复常规行数上限。
- `GLM_TEXT_LINE_REPAIR_MAX_REGIONS_PER_PAGE=24`：单页最多修复区域数。
- `GLM_TEXT_LINE_REPAIR_MAX_TOKENS=192`：单行 OCR 生成上限。
- `GLM_MAX_TOKENS=2048`、`GLM_IMAGE_FORMAT=PNG`、`GLM_REPETITION_PENALTY=1.2`：主 pipeline 质量优先默认值。

## 验证

新增本地回归脚本：

```bash
cd /home/ubuntu/jiang/ragproject3/GlmOcrApi
python ocrtest/run_glm_ocr_quality_test.py --page 16 --case-name pump-page16
python ocrtest/run_glm_ocr_quality_test.py --page 0 --max-pages 6 --case-name pump-first6
python ocrtest/run_glm_ocr_quality_test.py --page 16 --no-repair --case-name pump-page16-baseline
```

本次验证结果：

- `repaired_target_page16_v4`：第 16 页 `4.2.1` 共修复 6 个文本区域，大段重复循环消除，第 2、3、4、5、6 条恢复为完整条文结构。
- `repaired_first6`：前 6 页完成，修复 5 个区域，目录页不再出现基线中的大段重复循环。

## 注意

行级修复会增加 vLLM 调用次数，扫描件质量越差、触发修复区域越多，耗时越高。批量入库时仍建议保持 `worker-ingest-ocr` 单并发，优先保证 OCR 质量和稳定性。
