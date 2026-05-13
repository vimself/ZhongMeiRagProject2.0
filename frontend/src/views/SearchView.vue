<script setup lang="ts">
import { ArrowLeft, Document, Download, Loading, Search } from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElCard from 'element-plus/es/components/card/index.mjs'
import ElDialog from 'element-plus/es/components/dialog/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import ElPagination from 'element-plus/es/components/pagination/index.mjs'
import ElSelect, { ElOption } from 'element-plus/es/components/select/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-card.css'
import 'element-plus/theme-chalk/el-dialog.css'
import 'element-plus/theme-chalk/el-input.css'
import 'element-plus/theme-chalk/el-overlay.css'
import 'element-plus/theme-chalk/el-pagination.css'
import 'element-plus/theme-chalk/el-select.css'
import 'element-plus/theme-chalk/el-tag.css'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { SearchHit } from '@/api/search'
import { listKnowledgeBases } from '@/api/knowledge'
import PreviewModal from '@/features/chat/PreviewModal.vue'
import { useSearchStore } from '@/stores/search'

const store = useSearchStore()
const router = useRouter()

const kbList = ref<Array<{ id: string; name: string }>>([])

const previewVisible = ref(false)
const activeCitation = ref<SearchHit | null>(null)
const exportDialogVisible = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const downloadUrl = computed(() => {
  if (!store.exportDownloadUrl) return ''
  const base = import.meta.env.VITE_API_BASE_URL ?? '/api/v2'
  return store.exportDownloadUrl.startsWith('http')
    ? store.exportDownloadUrl
    : `${base.replace(/\/api\/v2$/, '')}${store.exportDownloadUrl}`
})

function doSearch() {
  store.page = 1
  store.search()
}

function handlePageChange(p: number) {
  store.page = p
  store.search()
}

function openPreview(hit: SearchHit) {
  activeCitation.value = hit
  previewVisible.value = true
}

async function doExport() {
  exportDialogVisible.value = true
  await store.startExport('json')
  if (store.exportPolling) {
    pollTimer = setInterval(() => {
      store.pollExportStatus()
      if (!store.exportPolling && pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
    }, 2000)
  }
}

onMounted(async () => {
  store.loadHotKeywords()
  try {
    const { data } = await listKnowledgeBases({ page: 1, page_size: 100 })
    kbList.value = data.items
  } catch {
    kbList.value = []
  }
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <main class="search-page">
    <!-- Page header -->
    <header class="page-header">
      <div class="header-left">
        <span class="brand-mark">ZM</span>
        <div>
          <p class="eyebrow">SEARCH</p>
          <h1>知识检索</h1>
        </div>
      </div>
      <ElButton :icon="ArrowLeft" text @click="router.push('/')">返回首页</ElButton>
    </header>

    <!-- Toolbar card -->
    <ElCard class="toolbar-card" shadow="never">
      <div class="toolbar-row">
        <ElInput
          v-model="store.query"
          placeholder="输入关键词，按 Enter 检索..."
          clearable
          class="search-input"
          :prefix-icon="Search"
          @keyup.enter="doSearch"
        />
        <ElButton type="primary" :loading="store.loading" class="search-btn" @click="doSearch">
          检索
        </ElButton>
        <ElButton
          :icon="Download"
          :loading="store.exportPolling"
          class="action-btn"
          @click="doExport"
        >
          导出
        </ElButton>
      </div>

      <div class="filter-row">
        <div class="filter-group">
          <label class="filter-label">知识库</label>
          <ElSelect v-model="store.kbId" placeholder="全部知识库" clearable class="filter-select">
            <ElOption v-for="kb in kbList" :key="kb.id" :label="kb.name" :value="kb.id" />
          </ElSelect>
        </div>
        <div class="filter-group">
          <label class="filter-label">排序</label>
          <ElSelect v-model="store.sortBy" class="filter-select filter-select--narrow">
            <ElOption label="按相关度" value="relevance" />
            <ElOption label="按时间" value="date" />
          </ElSelect>
        </div>
      </div>

      <div v-if="store.hotKeywords.length" class="hot-keywords-row">
        <span class="hot-label">热词</span>
        <div class="hot-tags">
          <ElTag
            v-for="kw in store.hotKeywords.slice(0, 10)"
            :key="kw.keyword"
            class="hot-tag"
            effect="plain"
            @click="store.applyKeyword(kw.keyword)"
          >
            {{ kw.keyword }}
          </ElTag>
        </div>
      </div>
    </ElCard>

    <!-- Results -->
    <section v-loading="store.loading" class="results-area">
      <div
        v-if="!store.loading && store.results.length === 0 && store.hasSearched"
        class="empty-state"
      >
        <h3 class="empty-title">未找到匹配结果</h3>
        <p class="empty-desc">尝试调整关键词或更换知识库范围重新检索</p>
      </div>

      <div v-if="!store.loading && !store.hasSearched" class="empty-state">
        <h3 class="empty-title">输入关键词开始检索</h3>
        <p class="empty-desc">支持搜索文档标题、章节内容、关键技术信息</p>
      </div>

      <article
        v-for="(hit, idx) in store.results"
        :key="hit.id"
        class="result-card"
        :style="{ '--card-delay': `${idx * 40}ms` }"
        @click="openPreview(hit)"
      >
        <div class="result-card__head">
          <span class="result-card__idx">{{ hit.index }}</span>
          <span class="result-card__title">{{ hit.document_title || '未命名文档' }}</span>
          <span class="result-card__score">{{ hit.score.toFixed(3) }}</span>
        </div>

        <div class="result-card__meta">
          <span class="meta-item">
            <span class="meta-k">章节</span>
            <span class="meta-v">{{
              hit.section_path.length ? hit.section_path.join(' › ') : '—'
            }}</span>
          </span>
          <span class="meta-item">
            <span class="meta-k">页码</span>
            <span class="meta-v">{{ hit.page_start != null ? `p.${hit.page_start}` : '—' }}</span>
          </span>
        </div>

        <div class="result-card__snippet">{{ hit.snippet }}</div>
      </article>
    </section>

    <!-- Pagination -->
    <div v-if="store.total > store.pageSize" class="pagination-bar">
      <span class="pagination-info">共 {{ store.total }} 条结果</span>
      <ElPagination
        layout="prev, pager, next"
        :total="store.total"
        :page-size="store.pageSize"
        :current-page="store.page"
        @current-change="handlePageChange"
      />
    </div>

    <!-- Export dialog -->
    <ElDialog
      v-model="exportDialogVisible"
      title="导出进度"
      width="420px"
      :close-on-click-modal="false"
    >
      <div
        v-if="store.exportStatus === 'pending' || store.exportStatus === 'running'"
        class="export-state"
      >
        <div class="export-spinner">
          <el-icon :size="28" class="spin-icon"><Loading /></el-icon>
        </div>
        <p class="export-state__text">正在生成导出文件...</p>
        <p class="export-state__hint">文件打包完成后将自动提供下载</p>
      </div>
      <div v-else-if="store.exportStatus === 'succeeded'" class="export-state">
        <div class="export-success-icon">
          <el-icon :size="28"><Document /></el-icon>
        </div>
        <p class="export-state__text export-state__text--success">导出完成</p>
        <a :href="downloadUrl" target="_blank" rel="noopener" class="download-link">
          <ElButton type="primary" :icon="Download">下载 ZIP 文件</ElButton>
        </a>
      </div>
      <div v-else-if="store.exportStatus === 'failed'" class="export-state">
        <p class="export-state__text export-state__text--error">导出失败，请稍后重试</p>
      </div>
    </ElDialog>

    <PreviewModal v-model="previewVisible" :citation="activeCitation" />
  </main>
</template>

<style scoped>
/* ── Tokens ── */
.search-page {
  --zm-primary: #0f766e;
  --zm-primary-hover: #115e59;
  --zm-primary-active: #134e4a;
  --zm-teal-soft: rgb(15 118 110 / 8%);
  --zm-teal-border: rgb(15 118 110 / 18%);
  --zm-text-strong: #0f172a;
  --zm-text: #334155;
  --zm-text-muted: #64748b;
  --zm-bg: #f7fafc;
  --zm-bg-soft: #f8fafc;
  --zm-surface: #fff;
  --zm-border: #dbe4ef;
  --zm-border-soft: #e2e8f0;
  --zm-radius: 8px;
  --zm-shadow-hover: 0 24px 60px rgb(15 118 110 / 11%);

  min-height: 100vh;
  padding: 0 36px 48px;
  background: var(--zm-bg);
  color: var(--zm-text);
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB',
    'Microsoft YaHei', sans-serif;
}

/* ── Page header ── */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 0 24px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-mark {
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  width: 44px;
  height: 44px;
  color: #fff;
  font-size: 15px;
  font-weight: 800;
  background: var(--zm-primary);
  border-radius: 8px;
  box-shadow: 0 14px 26px rgb(15 118 110 / 18%);
}

.eyebrow {
  margin: 0 0 2px;
  color: var(--zm-text-muted);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--zm-text-strong);
  line-height: 1.3;
}

/* ── Toolbar card ── */
.toolbar-card {
  max-width: 1100px;
  margin: 0 auto 20px;
  border-radius: var(--zm-radius);
  border: 1px solid var(--zm-border-soft);
  background: var(--zm-surface);
  box-shadow: none;
}

.toolbar-card :deep(.el-card__body) {
  padding: 20px 24px;
}

/* ── Search input row ── */
.toolbar-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.search-input {
  flex: 1;
}

.search-input :deep(.el-input__wrapper) {
  border-radius: var(--zm-radius);
  box-shadow: 0 0 0 1px var(--zm-border);
  transition:
    box-shadow 0.2s ease,
    border-color 0.2s ease;
}

.search-input :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--zm-text-muted);
}

.search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px var(--zm-primary),
    0 0 0 3px var(--zm-teal-soft);
}

.search-btn {
  border-radius: var(--zm-radius) !important;
  font-weight: 600;
  min-width: 80px;
}

.action-btn {
  border-radius: var(--zm-radius) !important;
  font-weight: 500;
  border-color: var(--zm-border-soft);
  color: var(--zm-text);
}

.action-btn:hover {
  background: var(--zm-bg-soft);
  border-color: var(--zm-border);
  color: var(--zm-text-strong);
}

/* ── Filter row ── */
.filter-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--zm-text-muted);
  white-space: nowrap;
}

.filter-select {
  width: 180px;
}

.filter-select--narrow {
  width: 120px;
}

.filter-select :deep(.el-input__wrapper) {
  border-radius: var(--zm-radius);
  box-shadow: 0 0 0 1px var(--zm-border-soft);
}

/* ── Hot keywords ── */
.hot-keywords-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--zm-border-soft);
  flex-wrap: wrap;
}

.hot-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--zm-text-muted);
  white-space: nowrap;
}

.hot-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.hot-tag {
  cursor: pointer;
  border-radius: 6px !important;
  font-size: 12px;
  font-weight: 500;
  color: var(--zm-primary) !important;
  background: var(--zm-teal-soft) !important;
  border-color: var(--zm-teal-border) !important;
  height: 26px;
  line-height: 24px;
  transition: all 0.15s ease;
}

.hot-tag:hover {
  background: rgb(15 118 110 / 14%) !important;
  border-color: var(--zm-primary) !important;
  transform: translateY(-1px);
}

/* ── Results ── */
.results-area {
  max-width: 1100px;
  margin: 0 auto;
  min-height: 180px;
}

/* ── Empty state ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 72px 24px;
  text-align: center;
}

.empty-title {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 600;
  color: var(--zm-text-strong);
}

.empty-desc {
  margin: 0;
  font-size: 15px;
  color: var(--zm-text-muted);
}

/* ── Result cards ── */
.result-card {
  background: var(--zm-surface);
  border: 1px solid var(--zm-border-soft);
  border-radius: var(--zm-radius);
  padding: 18px 22px;
  margin-bottom: 10px;
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
  animation: card-enter 0.3s ease both;
  animation-delay: var(--card-delay, 0ms);
}

.result-card:hover {
  border-color: rgb(15 118 110 / 45%);
  box-shadow: var(--zm-shadow-hover);
  transform: translateY(-2px);
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.result-card__head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}

.result-card__idx {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 20px;
  padding: 0 5px;
  background: var(--zm-teal-soft);
  border: 1px solid var(--zm-teal-border);
  border-radius: 4px;
  color: var(--zm-primary);
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.result-card__title {
  flex: 1;
  font-size: 15px;
  font-weight: 600;
  color: var(--zm-text-strong);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

.result-card__score {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--zm-primary);
  background: var(--zm-teal-soft);
  border: 1px solid var(--zm-teal-border);
  border-radius: 4px;
  padding: 1px 7px;
  line-height: 1.6;
}

.result-card__meta {
  display: flex;
  gap: 18px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
}

.meta-k {
  color: var(--zm-text-muted);
  font-weight: 500;
}

.meta-v {
  color: var(--zm-text);
}

.result-card__snippet {
  font-size: 13px;
  line-height: 1.7;
  color: var(--zm-text);
  background: var(--zm-bg-soft);
  border: 1px solid var(--zm-border-soft);
  border-left: 2px solid var(--zm-primary);
  border-radius: 0 var(--zm-radius) var(--zm-radius) 0;
  padding: 10px 14px;
  max-height: 100px;
  overflow: hidden;
  white-space: pre-wrap;
}

/* ── Pagination ── */
.pagination-bar {
  max-width: 1100px;
  margin: 0 auto;
  padding: 16px 0 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pagination-info {
  font-size: 12px;
  color: var(--zm-text-muted);
  font-variant-numeric: tabular-nums;
}

.pagination-bar :deep(.el-pager li.is-active) {
  background: var(--zm-primary);
  color: #fff;
  border-radius: 6px;
}

.pagination-bar :deep(.el-pager li) {
  border-radius: 6px;
}

/* ── Export dialog ── */
:deep(.el-dialog) {
  border-radius: 12px;
}

:deep(.el-dialog__header) {
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--zm-border-soft);
  margin: 0;
}

:deep(.el-dialog__title) {
  font-size: 15px;
  font-weight: 600;
  color: var(--zm-text-strong);
}

:deep(.el-dialog__body) {
  padding: 28px 24px;
}

.export-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
}

.export-spinner {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--zm-teal-soft);
  border-radius: 50%;
  color: var(--zm-primary);
}

.spin-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.export-success-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgb(5 150 105 / 8%);
  border: 1px solid rgb(5 150 105 / 18%);
  border-radius: 50%;
  color: #059669;
}

.export-state__text {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--zm-text-strong);
}

.export-state__text--success {
  color: #059669;
}

.export-state__text--error {
  color: #b91c1c;
}

.export-state__hint {
  margin: 0;
  font-size: 12px;
  color: var(--zm-text-muted);
}

.download-link {
  text-decoration: none;
  margin-top: 4px;
}

/* ── Responsive ── */
@media (width <= 768px) {
  .search-page {
    padding: 0 16px 32px;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
    padding: 20px 0 16px;
  }

  .page-header h1 {
    font-size: 19px;
  }

  .toolbar-card :deep(.el-card__body) {
    padding: 16px;
  }

  .toolbar-row {
    flex-direction: column;
  }

  .search-btn,
  .action-btn {
    width: 100%;
  }

  .filter-row {
    flex-direction: column;
    align-items: stretch;
  }

  .filter-group {
    justify-content: space-between;
  }

  .filter-select,
  .filter-select--narrow {
    width: 100%;
  }

  .result-card {
    padding: 14px 16px;
  }

  .result-card__meta {
    flex-direction: column;
    gap: 4px;
  }

  .pagination-bar {
    flex-direction: column;
    gap: 12px;
  }
}
</style>
