<script setup lang="ts">
import { ArrowLeft, Download, Search } from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElDialog from 'element-plus/es/components/dialog/index.mjs'
import ElEmpty from 'element-plus/es/components/empty/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import ElPagination from 'element-plus/es/components/pagination/index.mjs'
import ElSelect, { ElOption } from 'element-plus/es/components/select/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-dialog.css'
import 'element-plus/theme-chalk/el-empty.css'
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
  <main class="shell">
    <section class="page-header">
      <ElButton :icon="ArrowLeft" text @click="router.push('/')">返回</ElButton>
      <h1>知识检索</h1>
    </section>

    <section class="filter-bar">
      <ElInput
        v-model="store.query"
        placeholder="输入关键词..."
        clearable
        :prefix-icon="Search"
        @keyup.enter="doSearch"
      />
      <ElSelect v-model="store.kbId" placeholder="全部知识库" clearable>
        <ElOption v-for="kb in kbList" :key="kb.id" :label="kb.name" :value="kb.id" />
      </ElSelect>
      <ElSelect v-model="store.sortBy" style="width: 120px">
        <ElOption label="相关度" value="relevance" />
        <ElOption label="时间" value="date" />
      </ElSelect>
      <ElButton type="primary" :icon="Search" @click="doSearch">检索</ElButton>
      <ElButton :icon="Download" :loading="store.exportPolling" @click="doExport"
        >导出 ZIP</ElButton
      >
    </section>

    <section v-if="store.hotKeywords.length" class="quick-filters">
      <div v-if="store.hotKeywords.length" class="filter-group">
        <span class="filter-label">热词：</span>
        <ElTag
          v-for="kw in store.hotKeywords.slice(0, 10)"
          :key="kw.keyword"
          class="clickable-tag"
          @click="store.applyKeyword(kw.keyword)"
        >
          {{ kw.keyword }}
        </ElTag>
      </div>
    </section>

    <section v-loading="store.loading" class="results">
      <ElEmpty
        v-if="!store.loading && store.results.length === 0 && store.hasSearched"
        description="未找到匹配结果"
      />
      <article
        v-for="hit in store.results"
        :key="hit.id"
        class="result-card"
        @click="openPreview(hit)"
      >
        <header class="result-card__head">
          <span class="result-card__index">[{{ hit.index }}]</span>
          <span class="result-card__title">{{ hit.document_title || '未命名文档' }}</span>
          <span class="result-card__score">{{ hit.score.toFixed(3) }}</span>
        </header>
        <dl class="result-card__meta">
          <dt>章节</dt>
          <dd>{{ hit.section_path.length ? hit.section_path.join(' › ') : '—' }}</dd>
          <dt>页码</dt>
          <dd>{{ hit.page_start != null ? `p.${hit.page_start}` : '—' }}</dd>
        </dl>
        <p class="result-card__snippet">{{ hit.snippet }}</p>
      </article>
    </section>

    <div v-if="store.total > store.pageSize" class="pagination-wrapper">
      <ElPagination
        layout="total, prev, pager, next"
        :total="store.total"
        :page-size="store.pageSize"
        :current-page="store.page"
        @current-change="handlePageChange"
      />
    </div>

    <ElDialog
      v-model="exportDialogVisible"
      title="导出进度"
      width="400px"
      :close-on-click-modal="false"
    >
      <div
        v-if="store.exportStatus === 'pending' || store.exportStatus === 'running'"
        class="export-progress"
      >
        <p>正在生成导出文件...</p>
      </div>
      <div v-else-if="store.exportStatus === 'succeeded'" class="export-done">
        <p>导出完成！</p>
        <a :href="downloadUrl" target="_blank" rel="noopener" class="download-link">下载 ZIP</a>
      </div>
      <p v-else-if="store.exportStatus === 'failed'" class="error-text">导出失败</p>
    </ElDialog>

    <PreviewModal v-model="previewVisible" :citation="activeCitation" />
  </main>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  padding: 32px;
  background: #f6f8fb;
  color: #1f2937;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 1080px;
  margin: 0 auto 24px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  max-width: 1080px;
  margin: 0 auto 20px;
  padding: 16px 20px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.quick-filters {
  max-width: 1080px;
  margin: 0 auto 20px;
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.filter-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.filter-label {
  color: #6b7280;
  font-size: 13px;
  margin-right: 4px;
}

.clickable-tag {
  cursor: pointer;
  transition: border-color 0.2s;
}

.clickable-tag:hover {
  border-color: #0f766e;
}

.results {
  max-width: 1080px;
  margin: 0 auto;
  min-height: 200px;
}

.result-card {
  padding: 16px 20px;
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  cursor: pointer;
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}

.result-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgb(64 158 255 / 15%);
}

.result-card__head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}

.result-card__index {
  color: #0f766e;
  font-weight: 600;
  font-size: 13px;
  flex-shrink: 0;
}

.result-card__title {
  flex: 1;
  color: #111827;
  font-weight: 600;
  font-size: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-card__score {
  color: #6b7280;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.result-card__meta {
  display: flex;
  gap: 16px;
  margin: 0 0 8px;
  font-size: 13px;
}

.result-card__meta dt {
  color: #6b7280;
}

.result-card__meta dd {
  margin: 0;
  color: #374151;
}

.result-card__snippet {
  margin: 0;
  color: #374151;
  font-size: 13px;
  line-height: 1.7;
  background: #fafaf9;
  border: 1px solid #e5e7eb;
  border-left: 2px solid #0f766e;
  border-radius: 0 6px 6px 0;
  padding: 8px 12px;
  max-height: 120px;
  overflow: hidden;
  white-space: pre-wrap;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  max-width: 1080px;
  margin: 0 auto;
  padding: 16px 20px;
}

.export-progress p {
  color: #374151;
  font-size: 14px;
}

.export-done p {
  color: #0f766e;
  font-weight: 600;
  margin-bottom: 12px;
}

.download-link {
  color: #0f766e;
  font-weight: 600;
  text-decoration: underline;
}

.error-text {
  color: #b91c1c;
  font-size: 14px;
}

@media (width <= 768px) {
  .shell {
    padding: 20px;
  }

  .filter-bar {
    flex-direction: column;
  }

  .page-header h1 {
    font-size: 20px;
  }
}
</style>
