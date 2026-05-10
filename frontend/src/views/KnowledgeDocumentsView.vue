<script setup lang="ts">
import {
  Back,
  Delete,
  Document as DocumentIcon,
  Refresh,
  Search,
  UploadFilled,
  View,
  Monitor,
} from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElDrawer from 'element-plus/es/components/drawer/index.mjs'
import ElEmpty from 'element-plus/es/components/empty/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'
import ElPagination from 'element-plus/es/components/pagination/index.mjs'
import ElProgress from 'element-plus/es/components/progress/index.mjs'
import ElSelect, { ElOption } from 'element-plus/es/components/select/index.mjs'
import ElTable, { ElTableColumn } from 'element-plus/es/components/table/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import ElUpload from 'element-plus/es/components/upload/index.mjs'
import vLoading from 'element-plus/es/components/loading/src/directive.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-drawer.css'
import 'element-plus/theme-chalk/el-empty.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-input.css'
import 'element-plus/theme-chalk/el-loading.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'
import 'element-plus/theme-chalk/el-option.css'
import 'element-plus/theme-chalk/el-pagination.css'
import 'element-plus/theme-chalk/el-progress.css'
import 'element-plus/theme-chalk/el-select.css'
import 'element-plus/theme-chalk/el-table.css'
import 'element-plus/theme-chalk/el-table-column.css'
import 'element-plus/theme-chalk/el-tag.css'
import 'element-plus/theme-chalk/el-upload.css'
import type { UploadRequestOptions } from 'element-plus'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  disableDocument,
  getDocument,
  getIngestProgress,
  listDocuments,
  retryDocument,
  uploadDocument,
} from '@/api/document'
import { getKnowledgeBase } from '@/api/knowledge'
import { signAssetToken } from '@/api/pdfPreview'
import type { AssetOut, DocumentDetailResponse, DocumentOut, IngestJobProgress } from '@/api/types'
import PdfViewer from '@/components/PdfViewer.vue'
import { usePdfPreview } from '@/composables/usePdfPreview'

const route = useRoute()
const router = useRouter()
type UploadAjaxLikeError = Error & { status: number; method: string; url: string }
const kbId = computed(() => String(route.params.kbId))
const kbName = ref('')

const docs = ref<DocumentOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const search = ref('')
const statusFilter = ref('')
const uploadPercent = ref(0)

const progressMap = reactive<Record<string, IngestJobProgress>>({})
const timers = new Map<string, number>()

const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<DocumentDetailResponse | null>(null)

const pdfDrawerVisible = ref(false)
const pdfPreview = usePdfPreview()

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '排队', value: 'pending' },
  { label: 'OCR', value: 'ocr' },
  { label: '解析', value: 'parsing' },
  { label: '索引', value: 'indexing' },
  { label: '完成', value: 'ready' },
  { label: '失败', value: 'failed' },
]

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatSize(size: number): string {
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '排队',
    ocr: 'OCR',
    parsing: '解析',
    indexing: '索引',
    ready: '完成',
    failed: '失败',
    disabled: '停用',
  }
  return map[status] || status
}

function statusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ready') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'disabled') return 'info'
  return 'warning'
}

function docKindLabel(kind: string): string {
  const map: Record<string, string> = {
    plan: '方案',
    spec: '规范',
    drawing: '图纸',
    quantity: '工程量',
    other: '其他',
  }
  return map[kind] || kind
}

function progressOf(row: DocumentOut): number {
  if (row.status === 'ready') return 100
  return progressMap[row.id]?.progress ?? 0
}

async function loadKnowledgeBase() {
  const resp = await getKnowledgeBase(kbId.value)
  kbName.value = resp.data.name
}

async function loadDocuments() {
  loading.value = true
  try {
    const resp = await listDocuments(kbId.value, {
      page: page.value,
      page_size: pageSize.value,
      search: search.value,
      status: statusFilter.value || undefined,
    })
    docs.value = resp.data.items
    total.value = resp.data.total
    docs.value.forEach((doc) => {
      if (!['ready', 'failed', 'disabled'].includes(doc.status)) {
        startPolling(doc.id)
      }
    })
  } catch {
    ElMessage.error('文档列表加载失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  loadDocuments()
}

async function uploadRequest(options: UploadRequestOptions) {
  uploadPercent.value = 0
  try {
    const rawFile = options.file as File
    await uploadDocument(
      kbId.value,
      {
        file: rawFile,
        title: rawFile.name.replace(/\.pdf$/i, ''),
        doc_kind: 'other',
      },
      (percent) => {
        uploadPercent.value = percent
      },
    )
    options.onSuccess?.({})
    ElMessage.success('文档已入队')
    await loadDocuments()
  } catch (error) {
    const uploadError = (
      error instanceof Error ? error : new Error('上传失败')
    ) as UploadAjaxLikeError
    uploadError.status = uploadError.status ?? 0
    uploadError.method = uploadError.method ?? 'POST'
    uploadError.url = uploadError.url ?? ''
    options.onError?.(uploadError)
    ElMessage.error('上传失败')
  } finally {
    uploadPercent.value = 0
  }
}

async function openDetail(row: DocumentOut) {
  drawerVisible.value = true
  detailLoading.value = true
  try {
    const resp = await getDocument(row.id)
    detail.value = resp.data
  } catch {
    ElMessage.error('详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

async function openPdfPreview(row: DocumentOut, page?: number) {
  pdfDrawerVisible.value = true
  await pdfPreview.openPreview(row.id, page)
}

async function openDetailPdfPreview() {
  if (!detail.value) return
  pdfDrawerVisible.value = true
  await pdfPreview.openPreview(detail.value.id)
}

async function openAssetPreview(asset: AssetOut) {
  try {
    const url = asset.url || (await signAssetToken(String(asset.id))).data.url
    window.open(url, '_blank', 'noopener,noreferrer')
  } catch {
    ElMessage.error('资产预览链接签发失败')
  }
}

async function handleRetry(row: DocumentOut) {
  try {
    await retryDocument(row.id)
    ElMessage.success('文档已重新入队')
    await loadDocuments()
  } catch {
    ElMessage.error('重试失败')
  }
}

async function handleDisable(row: DocumentOut) {
  try {
    await ElMessageBox.confirm(`确定停用文档 "${row.title}" 吗？`, '停用文档', {
      confirmButtonText: '确定停用',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await disableDocument(row.id)
    ElMessage.success('文档已停用')
    await loadDocuments()
  } catch {
    ElMessage.error('停用失败')
  }
}

function startPolling(documentId: string) {
  if (timers.has(documentId)) return
  const tick = async () => {
    try {
      const resp = await getIngestProgress(documentId)
      progressMap[documentId] = resp.data
      if (['ready', 'failed', 'disabled'].includes(resp.data.document_status)) {
        stopPolling(documentId)
        await loadDocuments()
      }
    } catch {
      stopPolling(documentId)
    }
  }
  tick()
  timers.set(documentId, window.setInterval(tick, 2000))
}

function stopPolling(documentId: string) {
  const timer = timers.get(documentId)
  if (timer) {
    window.clearInterval(timer)
    timers.delete(documentId)
  }
}

function outlineItems(): Array<Record<string, unknown>> {
  const result = detail.value?.parse_result?.outline
  if (!result || typeof result !== 'object' || !('outline' in result)) return []
  const outline = (result as { outline?: unknown }).outline
  return Array.isArray(outline) ? (outline as Array<Record<string, unknown>>) : []
}

function statsText(): string {
  const stats = detail.value?.parse_result?.stats
  if (!stats || typeof stats !== 'object') return '暂无统计'
  const chunkCount = (stats as { chunk_count?: unknown }).chunk_count ?? 0
  const assetCount = (stats as { asset_count?: unknown }).asset_count ?? 0
  return `切片 ${chunkCount} 个，资产 ${assetCount} 个`
}

onMounted(async () => {
  await loadKnowledgeBase()
  await loadDocuments()
})

onUnmounted(() => {
  Array.from(timers.keys()).forEach(stopPolling)
})
</script>

<template>
  <main class="doc-page">
    <header class="page-header">
      <ElButton :icon="Back" text @click="router.push('/knowledge')">返回知识库</ElButton>
      <div>
        <h1>{{ kbName || '知识库文档' }}</h1>
        <p>入库文档、解析进度与结构化资产</p>
      </div>
    </header>

    <section class="toolbar">
      <ElUpload
        drag
        accept="application/pdf,.pdf"
        :show-file-list="false"
        :http-request="uploadRequest"
      >
        <div class="upload-inline">
          <UploadFilled />
          <span>拖拽 PDF 或点击上传</span>
        </div>
      </ElUpload>
      <div class="filters">
        <ElInput
          v-model="search"
          placeholder="搜索文件名或标题"
          clearable
          :prefix-icon="Search"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <ElSelect v-model="statusFilter" @change="handleSearch">
          <ElOption
            v-for="item in statusOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </ElSelect>
        <ElButton :icon="Refresh" @click="loadDocuments">刷新</ElButton>
      </div>
    </section>

    <ElProgress v-if="uploadPercent > 0" :percentage="uploadPercent" class="upload-progress" />

    <section class="table-shell">
      <ElTable v-loading="loading" :data="docs" stripe style="width: 100%">
        <ElTableColumn label="文件名" min-width="220">
          <template #default="{ row }: { row: DocumentOut }">
            <div class="file-cell">
              <DocumentIcon />
              <div>
                <strong>{{ row.title }}</strong>
                <span>{{ row.filename }}</span>
              </div>
            </div>
          </template>
        </ElTableColumn>
        <ElTableColumn label="大小" width="110">
          <template #default="{ row }: { row: DocumentOut }">
            {{ formatSize(row.size_bytes) }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="类型" width="110">
          <template #default="{ row }: { row: DocumentOut }">
            {{ docKindLabel(row.doc_kind) }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="110">
          <template #default="{ row }: { row: DocumentOut }">
            <ElTag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="进度" min-width="160">
          <template #default="{ row }: { row: DocumentOut }">
            <ElProgress :percentage="progressOf(row)" :stroke-width="8" />
          </template>
        </ElTableColumn>
        <ElTableColumn label="上传者" width="120" prop="uploader_name" />
        <ElTableColumn label="创建时间" width="150">
          <template #default="{ row }: { row: DocumentOut }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="270" fixed="right">
          <template #default="{ row }: { row: DocumentOut }">
            <div class="action-btns">
              <ElButton :icon="View" text size="small" @click="openDetail(row)">详情</ElButton>
              <ElButton
                v-if="row.status === 'ready'"
                :icon="Monitor"
                text
                size="small"
                type="primary"
                @click="openPdfPreview(row)"
              >
                预览
              </ElButton>
              <ElButton
                v-if="row.status === 'failed'"
                text
                size="small"
                type="warning"
                @click="handleRetry(row)"
              >
                重试
              </ElButton>
              <ElButton :icon="Delete" text size="small" type="danger" @click="handleDisable(row)">
                停用
              </ElButton>
            </div>
          </template>
        </ElTableColumn>
      </ElTable>

      <div v-if="total === 0 && !loading" class="empty-wrapper">
        <ElEmpty description="暂无入库文档" />
      </div>

      <div v-if="total > pageSize" class="pagination-wrapper">
        <ElPagination
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="
            (value: number) => {
              page = value
              loadDocuments()
            }
          "
        />
      </div>
    </section>

    <ElDrawer v-model="drawerVisible" title="文档详情" size="560px">
      <div v-loading="detailLoading" class="detail">
        <template v-if="detail">
          <div class="detail-header">
            <h2>{{ detail.title }}</h2>
            <ElButton
              v-if="detail.status === 'ready'"
              :icon="Monitor"
              type="primary"
              size="small"
              @click="openDetailPdfPreview"
            >
              预览 PDF
            </ElButton>
          </div>
          <p class="detail-sub">{{ detail.filename }} · {{ statsText() }}</p>
          <section>
            <h3>章节结构</h3>
            <ul v-if="outlineItems().length" class="outline">
              <li v-for="item in outlineItems()" :key="String(item.section_path)">
                <span :style="{ paddingLeft: `${(Number(item.level) - 1) * 14}px` }">
                  {{ item.title }}
                </span>
              </li>
            </ul>
            <ElEmpty v-else description="暂无章节结构" />
          </section>
          <section>
            <h3>资产</h3>
            <div v-if="detail.assets.length" class="asset-grid">
              <div v-for="asset in detail.assets" :key="String(asset.id)" class="asset-item">
                <span>{{ asset.kind }}</span>
                <small>第 {{ asset.page_no || '—' }} 页</small>
                <ElButton text size="small" type="primary" @click="openAssetPreview(asset)">
                  查看
                </ElButton>
              </div>
            </div>
            <ElEmpty v-else description="暂无资产" />
          </section>
        </template>
      </div>
    </ElDrawer>

    <ElDrawer
      v-model="pdfDrawerVisible"
      title="PDF 预览"
      size="80%"
      :before-close="
        () => {
          pdfPreview.closePreview()
          pdfDrawerVisible = false
        }
      "
    >
      <div v-if="pdfPreview.loading.value" class="pdf-drawer-loading">加载中...</div>
      <div v-else-if="pdfPreview.error.value" class="pdf-drawer-error">
        {{ pdfPreview.error.value }}
      </div>
      <PdfViewer
        v-else-if="pdfPreview.pdfUrl.value"
        :url="pdfPreview.pdfUrl.value"
        :initial-page="pdfPreview.currentPage.value"
        :highlight-bbox="pdfPreview.highlightBbox.value"
        @page-change="pdfPreview.onPageChange"
      />
    </ElDrawer>
  </main>
</template>

<style scoped>
.doc-page {
  min-height: 100vh;
  padding: 32px;
  background: #f6f8fb;
  color: #1f2937;
}

.page-header,
.toolbar,
.table-shell {
  max-width: 1240px;
  margin-right: auto;
  margin-left: auto;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 22px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}

.page-header p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}

.toolbar {
  display: grid;
  grid-template-columns: minmax(260px, 360px) 1fr;
  gap: 16px;
  align-items: stretch;
  margin-bottom: 14px;
}

.upload-inline {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: center;
  min-height: 72px;
  color: #334155;
  font-weight: 600;
}

.upload-inline svg {
  width: 24px;
  height: 24px;
}

.filters {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 160px auto;
  gap: 10px;
  align-content: center;
  padding: 14px;
  background: #fff;
  border: 1px solid #dbe3ee;
  border-radius: 8px;
}

.upload-progress {
  max-width: 1240px;
  margin: 0 auto 14px;
}

.table-shell {
  overflow: hidden;
  background: #fff;
  border: 1px solid #dbe3ee;
  border-radius: 8px;
}

.file-cell {
  display: flex;
  gap: 10px;
  align-items: center;
}

.file-cell svg {
  flex: 0 0 auto;
  width: 20px;
  height: 20px;
  color: #2563eb;
}

.file-cell strong,
.file-cell span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-cell strong {
  max-width: 320px;
  font-size: 14px;
}

.file-cell span {
  max-width: 320px;
  color: #64748b;
  font-size: 12px;
}

.action-btns {
  display: flex;
  gap: 0;
  flex-wrap: wrap;
}

.empty-wrapper {
  padding: 44px 0;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  padding: 16px;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.detail-header h2 {
  margin: 0;
}

.detail h2,
.detail h3 {
  margin: 0 0 10px;
}

.detail h2 {
  font-size: 20px;
}

.detail h3 {
  font-size: 15px;
}

.detail section {
  padding: 18px 0;
  border-top: 1px solid #e5eaf1;
}

.detail-sub {
  margin: 0 0 18px;
  color: #64748b;
}

.outline {
  display: grid;
  gap: 8px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.outline li {
  color: #334155;
  font-size: 14px;
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 10px;
}

.asset-item {
  display: grid;
  gap: 4px;
  padding: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.asset-item span {
  font-weight: 600;
}

.asset-item small {
  color: #64748b;
}

.pdf-drawer-loading,
.pdf-drawer-error {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 300px;
  color: #64748b;
  font-size: 15px;
}

@media (width <= 860px) {
  .doc-page {
    padding: 20px;
  }

  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar,
  .filters {
    grid-template-columns: 1fr;
  }
}
</style>
