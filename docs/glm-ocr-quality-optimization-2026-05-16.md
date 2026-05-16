# GLM-OCR 识别质量优化

日期：2026-05-16

## 背景

`GlmOcrApi/ocrtest/泵站设计标准.pdf` 是扫描版 PDF，页面带有浅灰水印，且无可抽取文本层。官方 GLM-OCR self-hosted pipeline 在第 16 页 `4.2.1` 多行条文区域出现明显重复循环和缺漏，例如第 2、3、4 条会把“水库调蓄性能”“重现期 5 年～10 年”等短语反复生成。

## 调整

- 官方 GLM-OCR pipeline 仍作为主流程，继续负责 PDF 渲染、PP-DocLayoutV3 版面检测、区域识别、Markdown/JSON、图片资产和版面可视化。
- 新增 `GlmOcrApi/quality_repair.py`：对文本区域做后置质量修复，发现长输出重复、百分比数字失控、公式标记异常、编号条文多行换行等情况时，按深色文字投影切分为文本行，逐行调用本地 vLLM `Text Recognition:`，再合并回原版面区域。
- 对带可抽取文本层的 PDF 增加保守文本层对齐修复：仍以 GLM-OCR 的版面区域和 bbox 为准，只在同一区域文本层可可靠抽取，且 GLM 输出存在章节号漂移、重复循环、明显语义扩写或与文本层同长度显著差异时，使用文本层内容替换该区域；API 入参和返回规范不变。
- 文本层修复会识别并压缩重复小节号，例如 `9.4.1.1.1.1.1.1`→`9.4.1.1`、`9.4.4.4.4.1`→`9.4.4.1`，并容忍 OCR 原始结果中 `9. 4.1.1` 这类编号内部空格。
- 对 `97%～9999%`、`97\% \sim 99999999\%` 这类由 OCR 生成循环导致的百分比范围高端数字，增加窄规则规范化：只在同一百分比范围内把重复同一数字的异常高端值压缩为两位数，例如 `99%`；普通数字和非范围百分比不盲改。
- 对已判定为 `runaway_generation`、`raw_runaway_generation`、`repeated_text_loop`、`repeated_formula_token`、`percent_digit_run` 的坏块，验收逐行修复结果时不再使用坏块长度的 25% 作为最低长度阈值，避免 1000+ 字幻觉文本拒绝 100+ 字有效条文。
- 对目录类大块 `content` 区域保留行换行，避免行级修复后所有目录项挤在一行；对 `1111111 电气`、`111.1`、`11.1.1.1 2`、`11.111.18.2`、`12.12.`、`1011` 等目录和正文章节号粘连增加确定性规范化。
- 在 `result.md`/`result.json` 落盘前增加最终 text 区域章节号收口，兜住行级修复后重新出现的 `11.111.17.1 17.1`、`11.11.17` 等畸形编号，同时避免改写 `1110V`、`1110kV` 等工程数值。
- 对工程公式页增加确定性清洗，修复 `\mathrm{左}`、破损 `\sqrt{}`、`0.6m/s～0.8m/s`、`K_c`、`\sum G`、`\phi_0` 等常见 LaTeX 噪声，避免 RAG 入库正文携带未闭合公式标记。
- `result.md` 与 `result.json` 使用修复后的文本；`result_raw.json` 保留官方 pipeline 原始识别结果；新增 `quality_report.json` 记录每个修复区域的页码、bbox、行数、原因和修复前后长度。
- 默认将区域 OCR 生成上限从 `8192` 降到 `2048`，图像编码改为 `PNG`，`repetition_penalty` 调整为 `1.2`，降低长区域生成循环概率。
- 增加章节号规范化，修正 `4. 2.1`、顺序上下文中误读为 `4.2.2.2`、`4.3.1` 误读为 `4.4.3.1`、章节 11 扫描件中 `111/11.111` 重复等常见版面 OCR 后处理问题。

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

新增全 PDF 质量门禁脚本：

```bash
cd /home/ubuntu/jiang/ragproject3/GlmOcrApi
python ocrtest/run_full_pdf_quality_audit.py --case-name pump-full-quality-audit-v2 --batch-size 6
```

质量门禁会按批切分 PDF 并输出：

- `quality_summary.json`：全量摘要、阻断页、警告页、修复数。
- `page_audit.json`：逐页字符量、修复数、阻断/警告原因。
- `quality_report.md`：人工可读报告。
- `batches/pages_xxx_yyy/`：每批 OCR 结果、原始结果和质量修复报告。

当前阻断项包括长文本循环、百分比数字失控、公式标记不闭合、LaTeX 噪声混入正文、空页和明显畸形章节号等；目录页重复模式、正常术语重复、少量修复拒绝项作为警告保留，用于后续人工巡检和持续优化。

本次验证结果：

- `repaired_target_page16_v4`：第 16 页 `4.2.1` 共修复 6 个文本区域，大段重复循环消除，第 2、3、4、5、6 条恢复为完整条文结构。
- `repaired_first6`：前 6 页完成，修复 5 个区域，目录页不再出现基线中的大段重复循环。
- `codex-page18-final`：第 18 页 `4.2.5` 第 2 条由 1068 字重复循环收敛为 154 字完整条文，质量修复区域数 4，`quality_report.json` 不再出现拒绝项。
- `codex-page19-section-fixed`：第 19 页 `4.2.5` 第 4 条 `97%～9999%` 修正为 `97%～99%`，`4.4.3.1`/`4.4.3.2` 章节号修正为 `4.3.1`/`4.3.2`。
- `pump-full-quality-audit-v2`：完整 117 页分 20 批完成，质量分 98.77，阻断页 0，警告页 47，修复区域 673，修复拒绝 9。首轮阻断页 34、102、104 已通过公式/工程符号清洗修复，复跑后无 `percent_digit_run`、`repeated_text_loop`、`latex_noise_in_text`、`unbalanced_formula_marker` 阻断项。
- `db32t-textlayer-full`：`DB32T 4077.1-2021 矿山生态修复工程技术规程1+通则.pdf` 完整 98 页分 17 批完成，质量分 99.64，阻断页 0，警告页 13，修复区域 214，修复拒绝 0，空白页识别为第 2、6 页；典型修复包括第 8 页定义段落重复扩写、第 10 页 `3.222`/`3.23.23` 编号漂移、第 11 页正文语义扩写、第 22 页 `9.4.1.1.1.1.1.1`/`9.4.2.2.3` 编号重复、第 23 页 `9.4.4.4.4.1` 编号重复。
- `pump-section11-codex-v3`：`泵站设计标准.pdf` 第 76-78 页章节 11 开头质量分 100.0，阻断页 0，警告页 0；用户反馈中的 `1111111 电气`、`111.1 供电系统`、`11.1.1.1 2`、`111.11. 11.3` 已规范为 `11`、`11.1`、`11.1.2`、`11.3`。
- `pump-page97-codex-v4` / `pump-section11-late-codex-v5`：第 97 页单页质量分 100.0；第 97-102 页质量分 99.67，阻断页 0，警告页 1。`11.11.17`、`11.111.17.1 17.1`、`11.111.18.2`、`12.12.` 已规范为 `11.17`、`11.17.1`、`11.18.2`、`12.2`。
- `db32t-section-regression-codex-v3`：DB32T 第 20-23 页文本层样本阻断页 0，未出现新增章节号阻断；剩余 warning 是既有重复短语/重复章节巡检项。

## 注意

行级修复会增加 vLLM 调用次数，扫描件质量越差、触发修复区域越多，耗时越高。批量入库时仍建议保持 `worker-ingest-ocr` 单并发，优先保证 OCR 质量和稳定性。
对含文本层 PDF，文本层修复只作为 GLM-OCR 版面区域内的质量兜底，不替代版面检测；剩余 `quality_report.md` warning 主要用于人工巡检，例如标准条款中的正常重复短语、少量修复拒绝项等，不作为阻断项。明显畸形章节号已升级为 blocker，避免章节顺序和条文号错误被平均分掩盖。
