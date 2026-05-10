<script setup lang="ts">
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElInputNumber from 'element-plus/es/components/input-number/index.mjs'
import ElEmpty from 'element-plus/es/components/empty/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-empty.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-input-number.css'
import { ArrowLeft, ArrowRight, RefreshRight, ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

interface BboxHighlight {
  page: number
  x: number
  y: number
  width: number
  height: number
}

const props = withDefaults(
  defineProps<{
    url: string
    initialPage?: number
    highlightBbox?: BboxHighlight | null
  }>(),
  {
    initialPage: 1,
    highlightBbox: null,
  },
)

const emit = defineEmits<{
  (e: 'page-change', page: number): void
  (e: 'total-pages', total: number): void
}>()

const containerRef = ref<HTMLDivElement>()
const canvasRef = ref<HTMLCanvasElement>()
const overlayRef = ref<HTMLCanvasElement>()

const pdfDoc = ref<PDFDocumentProxy | null>(null)
const currentPage = ref(props.initialPage)
const totalPages = ref(0)
const scale = ref(1.5)
const loading = ref(true)
const errorMsg = ref<string | null>(null)

const canPrev = computed(() => currentPage.value > 1)
const canNext = computed(() => currentPage.value < totalPages.value)

async function loadPdf(url: string) {
  loading.value = true
  errorMsg.value = null
  pdfDoc.value = null
  try {
    const doc = await pdfjsLib.getDocument(url).promise
    pdfDoc.value = doc
    totalPages.value = doc.numPages
    emit('total-pages', doc.numPages)
    currentPage.value = Math.min(props.initialPage, doc.numPages)
    await renderPage(currentPage.value)
  } catch (err: unknown) {
    if (err && typeof err === 'object' && 'name' in err && err.name === 'PasswordException') {
      errorMsg.value = '此 PDF 需要密码才能打开'
    } else {
      errorMsg.value = 'PDF 加载失败，请检查链接是否有效或已过期'
    }
  } finally {
    loading.value = false
  }
}

async function renderPage(pageNum: number) {
  if (!pdfDoc.value || !canvasRef.value) return
  loading.value = true
  try {
    const page: PDFPageProxy = await pdfDoc.value.getPage(pageNum)
    const viewport = page.getViewport({ scale: scale.value })
    const canvas = canvasRef.value
    const ctx = canvas.getContext('2d')!
    canvas.width = viewport.width
    canvas.height = viewport.height
    await page.render({ canvasContext: ctx, viewport }).promise
    renderOverlay(page, viewport)
    currentPage.value = pageNum
    emit('page-change', pageNum)
  } catch {
    errorMsg.value = '页面渲染失败'
  } finally {
    loading.value = false
  }
}

function renderOverlay(page: PDFPageProxy, viewport: { width: number; height: number }) {
  if (!overlayRef.value) return
  const overlay = overlayRef.value
  overlay.width = viewport.width
  overlay.height = viewport.height
  const ctx = overlay.getContext('2d')!
  ctx.clearRect(0, 0, overlay.width, overlay.height)

  if (props.highlightBbox && props.highlightBbox.page === currentPage.value) {
    const bbox = props.highlightBbox
    const pageViewport = page.getViewport({ scale: scale.value })
    // PDF coordinate system: origin at bottom-left
    // Canvas coordinate system: origin at top-left
    const x = bbox.x * scale.value
    const y = pageViewport.height - (bbox.y + bbox.height) * scale.value
    const w = bbox.width * scale.value
    const h = bbox.height * scale.value
    ctx.fillStyle = 'rgba(37, 99, 235, 0.15)'
    ctx.strokeStyle = 'rgba(37, 99, 235, 0.8)'
    ctx.lineWidth = 2
    ctx.fillRect(x, y, w, h)
    ctx.strokeRect(x, y, w, h)
  }
}

function goToPage(page: number) {
  if (!pdfDoc.value) return
  const target = Math.max(1, Math.min(page, totalPages.value))
  renderPage(target)
}

function prevPage() {
  if (canPrev.value) goToPage(currentPage.value - 1)
}

function nextPage() {
  if (canNext.value) goToPage(currentPage.value + 1)
}

function zoomIn() {
  scale.value = Math.min(scale.value + 0.25, 4)
  renderPage(currentPage.value)
}

function zoomOut() {
  scale.value = Math.max(scale.value - 0.25, 0.5)
  renderPage(currentPage.value)
}

function resetZoom() {
  scale.value = 1.5
  renderPage(currentPage.value)
}

function fitWidth() {
  if (!containerRef.value || !pdfDoc.value) return
  pdfDoc.value.getPage(currentPage.value).then((page) => {
    const viewport = page.getViewport({ scale: 1 })
    const containerWidth = containerRef.value!.clientWidth - 32
    scale.value = containerWidth / viewport.width
    renderPage(currentPage.value)
  })
}

watch(
  () => props.url,
  (newUrl) => {
    if (newUrl) {
      nextTick(() => loadPdf(newUrl))
    }
  },
  { immediate: true },
)

watch(
  () => props.highlightBbox,
  () => {
    if (pdfDoc.value) {
      renderPage(currentPage.value)
    }
  },
)

onBeforeUnmount(() => {
  if (pdfDoc.value) {
    pdfDoc.value.destroy()
  }
})
</script>

<template>
  <div ref="containerRef" class="pdf-viewer">
    <div class="pdf-toolbar">
      <div class="pdf-toolbar-group">
        <ElButton :icon="ArrowLeft" :disabled="!canPrev" text size="small" @click="prevPage" />
        <ElInputNumber
          :model-value="currentPage"
          :min="1"
          :max="totalPages"
          size="small"
          controls-position="right"
          class="page-input"
          @change="
            (val: number | undefined) => {
              if (val) goToPage(val)
            }
          "
        />
        <span class="page-label">/ {{ totalPages }}</span>
        <ElButton :icon="ArrowRight" :disabled="!canNext" text size="small" @click="nextPage" />
      </div>
      <div class="pdf-toolbar-group">
        <ElButton :icon="ZoomOut" text size="small" @click="zoomOut" />
        <span class="zoom-label">{{ Math.round(scale * 100) }}%</span>
        <ElButton :icon="ZoomIn" text size="small" @click="zoomIn" />
        <ElButton text size="small" @click="resetZoom">重置</ElButton>
        <ElButton text size="small" @click="fitWidth">适宽</ElButton>
        <ElButton :icon="RefreshRight" text size="small" @click="renderPage(currentPage)" />
      </div>
    </div>

    <div class="pdf-canvas-container">
      <div v-if="loading" class="pdf-loading">
        <div class="spinner" />
        <span>加载中...</span>
      </div>
      <div v-else-if="errorMsg" class="pdf-error">
        <ElEmpty :description="errorMsg" />
      </div>
      <div v-else class="pdf-canvas-wrapper">
        <canvas ref="canvasRef" class="pdf-canvas" />
        <canvas ref="overlayRef" class="pdf-overlay" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.pdf-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #f0f2f5;
}

.pdf-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #e5eaf1;
  flex-shrink: 0;
}

.pdf-toolbar-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.page-input {
  width: 72px;
}

.page-label {
  color: #64748b;
  font-size: 13px;
  min-width: 40px;
}

.zoom-label {
  color: #334155;
  font-size: 13px;
  min-width: 42px;
  text-align: center;
}

.pdf-canvas-container {
  flex: 1;
  overflow: auto;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 16px;
}

.pdf-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 300px;
  color: #64748b;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5eaf1;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.pdf-error {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 300px;
}

.pdf-canvas-wrapper {
  position: relative;
  box-shadow: 0 2px 12px rgb(0 0 0 / 8%);
  background: #fff;
}

.pdf-canvas {
  display: block;
}

.pdf-overlay {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
}
</style>
