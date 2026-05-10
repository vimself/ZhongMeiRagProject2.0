<script setup lang="ts">
import ElDialog from 'element-plus/es/components/dialog/index.mjs'
import ElButton from 'element-plus/es/components/button/index.mjs'
import 'element-plus/theme-chalk/el-dialog.css'
import 'element-plus/theme-chalk/el-overlay.css'
import { computed } from 'vue'

import type { ChatCitation } from '@/api/chat'
import PdfViewer from '@/components/PdfViewer.vue'

const props = defineProps<{
  modelValue: boolean
  citation: ChatCitation | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const sectionLabel = computed(() =>
  props.citation?.section_path?.length ? props.citation.section_path.join(' › ') : '（无章节）',
)

const pageLabel = computed(() => {
  const c = props.citation
  if (!c || c.page_start == null) return '—'
  if (c.page_end == null || c.page_end === c.page_start) return `p.${c.page_start}`
  return `p.${c.page_start}-${c.page_end}`
})

const highlightBbox = computed(() => {
  const c = props.citation
  if (!c || !c.bbox || c.page_start == null) return null
  const { x, y, width, height } = c.bbox
  if (
    typeof x !== 'number' ||
    typeof y !== 'number' ||
    typeof width !== 'number' ||
    typeof height !== 'number'
  ) {
    return null
  }
  return { page: c.page_start, x, y, width, height }
})

function handleDownload() {
  if (!props.citation?.download_url) return
  const link = document.createElement('a')
  link.href = props.citation.download_url
  link.target = '_blank'
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

function handleClose() {
  emit('update:modelValue', false)
}
</script>

<template>
  <ElDialog
    v-model="visible"
    :show-close="true"
    :close-on-click-modal="false"
    :destroy-on-close="true"
    :append-to-body="true"
    top="6vh"
    width="min(1180px, 94vw)"
    class="citation-preview-dialog"
    align-center
  >
    <template #header>
      <div class="preview-modal__header">
        <span class="preview-modal__index">[{{ citation?.index ?? '—' }}]</span>
        <div class="preview-modal__title" :title="citation?.document_title">
          {{ citation?.document_title || '未命名文档' }}
        </div>
        <span class="preview-modal__page">{{ pageLabel }}</span>
      </div>
    </template>

    <div v-if="citation" class="preview-modal__body">
      <section class="preview-modal__viewer">
        <PdfViewer
          v-if="citation.preview_url"
          :url="citation.preview_url"
          :initial-page="citation.page_start ?? 1"
          :highlight-bbox="highlightBbox"
        />
        <div v-else class="preview-modal__placeholder">无可预览的 PDF 链接</div>
      </section>

      <aside class="preview-modal__meta">
        <div class="meta-block">
          <div class="meta-block__label">文档</div>
          <div class="meta-block__value" :title="citation.document_title">
            {{ citation.document_title }}
          </div>
        </div>
        <div class="meta-block">
          <div class="meta-block__label">章节路径</div>
          <div class="meta-block__value" :title="sectionLabel">{{ sectionLabel }}</div>
        </div>
        <div class="meta-block meta-block--grid">
          <div>
            <div class="meta-block__label">页码</div>
            <div class="meta-block__value">{{ pageLabel }}</div>
          </div>
          <div>
            <div class="meta-block__label">相关度</div>
            <div class="meta-block__value">{{ citation.score.toFixed(3) }}</div>
          </div>
        </div>
        <div v-if="citation.snippet" class="meta-block">
          <div class="meta-block__label">摘录</div>
          <p class="meta-block__snippet">{{ citation.snippet }}</p>
        </div>
        <div class="preview-modal__actions">
          <ElButton
            type="primary"
            :disabled="!citation.download_url"
            plain
            size="default"
            @click="handleDownload"
          >
            下载原文 PDF
          </ElButton>
          <ElButton size="default" @click="handleClose">关闭</ElButton>
        </div>
      </aside>
    </div>
  </ElDialog>
</template>

<style scoped>
.preview-modal__header {
  display: flex;
  gap: 12px;
  align-items: baseline;
  padding-right: 24px;
}

.preview-modal__index {
  color: #0f766e;
  font-weight: 600;
  font-size: 13px;
  letter-spacing: 0.04em;
}

.preview-modal__title {
  flex: 1;
  color: #111827;
  font-weight: 600;
  font-size: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.preview-modal__page {
  color: #6b7280;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.preview-modal__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  height: min(78vh, 760px);
  min-height: 480px;
  margin: -20px -24px -30px;
  border-top: 1px solid #e5e7eb;
  background: #fafaf9;
}

.preview-modal__viewer {
  min-width: 0;
  min-height: 0;
  background: #f0f2f5;
  border-right: 1px solid #e5e7eb;
}

.preview-modal__placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #9ca3af;
  font-size: 13px;
}

.preview-modal__meta {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 20px 22px;
  background: #fff;
  overflow-y: auto;
}

.meta-block__label {
  color: #6b7280;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 4px;
}

.meta-block__value {
  color: #111827;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.meta-block--grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.meta-block__snippet {
  margin: 0;
  padding: 10px 12px;
  color: #374151;
  font-size: 12.5px;
  line-height: 1.7;
  background: #fafaf9;
  border: 1px solid #e5e7eb;
  border-left: 2px solid #0f766e;
  border-radius: 0 6px 6px 0;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
}

.preview-modal__actions {
  margin-top: auto;
  display: flex;
  gap: 8px;
  padding-top: 16px;
  border-top: 1px solid #f3f4f6;
}

@media (width <= 900px) {
  .preview-modal__body {
    grid-template-columns: 1fr;
    height: auto;
  }

  .preview-modal__viewer {
    height: 50vh;
    border-right: none;
    border-bottom: 1px solid #e5e7eb;
  }
}
</style>
