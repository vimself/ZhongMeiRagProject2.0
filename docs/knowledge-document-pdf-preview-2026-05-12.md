# 2026-05-12 知识库详情 PDF 预览跳转修正

## 背景

知识库详情页 `/knowledge/:kbId/documents` 的文档预览仍使用页面内抽屉和自定义 `PdfViewer`。智能问答证据文档已改为新标签页签发短时 PDF token 后打开原生 PDF 预览，两处交互不一致。

## 调整

- 文档列表行的“预览”按钮改为先打开空白新标签页，再调用 `/api/v2/pdf/sign` 签发短时 token。
- 签发成功后跳转到 `/api/v2/pdf/preview?document_id=...&token=...#page=1`，固定打开 PDF 第一页。
- 文档详情抽屉中的“预览 PDF”复用同一逻辑。
- 移除知识库详情页内嵌 PDF 抽屉与 `PdfViewer` 依赖，保持与智能问答证据文档预览方式一致。

## 验证

- 前端单文件样式检查：`npx stylelint src/views/KnowledgeDocumentsView.vue`
