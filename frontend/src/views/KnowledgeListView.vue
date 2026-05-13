<script setup lang="ts">
import { ArrowLeft, Edit, Refresh, Search } from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElCard from 'element-plus/es/components/card/index.mjs'
import ElDialog from 'element-plus/es/components/dialog/index.mjs'
import ElEmpty from 'element-plus/es/components/empty/index.mjs'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import ElPagination from 'element-plus/es/components/pagination/index.mjs'
import ElTable, { ElTableColumn } from 'element-plus/es/components/table/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import vLoading from 'element-plus/es/components/loading/src/directive.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-card.css'
import 'element-plus/theme-chalk/el-dialog.css'
import 'element-plus/theme-chalk/el-empty.css'
import 'element-plus/theme-chalk/el-form.css'
import 'element-plus/theme-chalk/el-form-item.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-input.css'
import 'element-plus/theme-chalk/el-loading.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-pagination.css'
import 'element-plus/theme-chalk/el-table.css'
import 'element-plus/theme-chalk/el-table-column.css'
import 'element-plus/theme-chalk/el-tag.css'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { listKnowledgeBases, updateKnowledgeBase } from '@/api/knowledge'
import type { KnowledgeBaseOut } from '@/api/types'
import { formatBeijingDateTime } from '@/utils/time'

const router = useRouter()

// ── Knowledge base list state ───────────────────────────────────────
const kbs = ref<KnowledgeBaseOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const search = ref('')

// ── Edit dialog ─────────────────────────────────────────────────────
const dialogVisible = ref(false)
const editingKb = ref<KnowledgeBaseOut | null>(null)
const dialogLoading = ref(false)
const dialogForm = reactive({
  name: '',
  description: '',
})

// ── Helpers ─────────────────────────────────────────────────────────
const formatDateTime = formatBeijingDateTime

function roleLabel(role: string | null): string {
  const map: Record<string, string> = {
    owner: '所有者',
    editor: '编辑者',
    viewer: '查看者',
    admin: '管理员',
  }
  return role ? map[role] || role : '—'
}

function roleTagType(role: string | null): 'danger' | 'warning' | 'info' {
  const map: Record<string, 'danger' | 'warning' | 'info'> = {
    owner: 'danger',
    editor: 'warning',
    viewer: 'info',
    admin: 'danger',
  }
  return role ? map[role] || 'info' : 'info'
}

// ── Load knowledge bases ────────────────────────────────────────────
async function loadKBs() {
  loading.value = true
  try {
    const resp = await listKnowledgeBases({
      page: page.value,
      page_size: pageSize.value,
      search: search.value,
    })
    kbs.value = resp.data.items
    total.value = resp.data.total
  } catch {
    ElMessage.error('知识库列表加载失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  loadKBs()
}

function handlePageChange(newPage: number) {
  page.value = newPage
  loadKBs()
}

// ── Edit ────────────────────────────────────────────────────────────
function openEditDialog(kb: KnowledgeBaseOut) {
  editingKb.value = kb
  dialogForm.name = kb.name
  dialogForm.description = kb.description
  dialogVisible.value = true
}

function openDocuments(kb: KnowledgeBaseOut) {
  router.push(`/knowledge/${kb.id}/documents`)
}

async function submitDialog() {
  if (!dialogForm.name.trim()) {
    ElMessage.error('请输入知识库名称')
    return
  }
  dialogLoading.value = true
  try {
    if (!editingKb.value) return
    await updateKnowledgeBase(editingKb.value.id, {
      name: dialogForm.name.trim(),
      description: dialogForm.description.trim(),
    })
    ElMessage.success('知识库已更新')
    dialogVisible.value = false
    await loadKBs()
  } catch (err: unknown) {
    const msg =
      err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined
    ElMessage.error(msg || '操作失败')
  } finally {
    dialogLoading.value = false
  }
}

onMounted(loadKBs)
</script>

<template>
  <main class="kb-page">
    <header class="page-header">
      <div class="header-left">
        <span class="brand-mark">ZM</span>
        <div>
          <p class="eyebrow">Knowledge</p>
          <h1>我的知识库</h1>
        </div>
      </div>
      <ElButton :icon="ArrowLeft" text @click="router.push('/')">返回首页</ElButton>
    </header>

    <!-- Toolbar -->
    <ElCard class="toolbar-card" shadow="never">
      <div class="toolbar">
        <ElInput
          v-model="search"
          class="kb-search"
          placeholder="搜索知识库名称或描述"
          clearable
          :prefix-icon="Search"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <div class="toolbar-actions">
          <ElButton :icon="Refresh" @click="loadKBs">刷新</ElButton>
        </div>
      </div>
    </ElCard>

    <!-- Knowledge Base Table -->
    <ElCard class="table-card" shadow="never">
      <ElTable
        v-loading="loading"
        class="kb-table"
        :data="kbs"
        stripe
        style="width: 100%"
        @row-click="openDocuments"
      >
        <ElTableColumn prop="name" label="知识库名称" min-width="180" />
        <ElTableColumn prop="description" label="描述" min-width="240">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="desc-cell">{{ row.description || '—' }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="我的角色" width="120">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <ElTag :type="roleTagType(row.my_role)" size="small">
              {{ roleLabel(row.my_role) }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="创建时间" width="150">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="time-cell">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="100" fixed="right">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <div class="action-btns">
              <ElButton
                v-if="
                  row.my_role === 'owner' || row.my_role === 'editor' || row.my_role === 'admin'
                "
                :icon="Edit"
                text
                size="small"
                @click.stop="openEditDialog(row)"
              >
                编辑
              </ElButton>
            </div>
          </template>
        </ElTableColumn>
      </ElTable>

      <div v-if="total === 0 && !loading" class="empty-wrapper">
        <ElEmpty description="暂无知识库" />
      </div>

      <div v-if="total > pageSize" class="pagination-wrapper">
        <ElPagination
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="handlePageChange"
        />
      </div>
    </ElCard>

    <!-- Edit Dialog -->
    <ElDialog
      v-model="dialogVisible"
      title="编辑知识库"
      width="520px"
      append-to-body
      class="edit-kb-dialog"
      modal-class="edit-kb-dialog-modal"
      :z-index="3200"
      :close-on-click-modal="false"
    >
      <ElForm label-position="top">
        <ElFormItem label="知识库名称" required>
          <ElInput v-model="dialogForm.name" maxlength="256" placeholder="输入知识库名称" />
        </ElFormItem>
        <ElFormItem label="描述">
          <ElInput
            v-model="dialogForm.description"
            type="textarea"
            :rows="3"
            maxlength="2048"
            placeholder="知识库描述（可选）"
          />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="dialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="dialogLoading" @click="submitDialog">保存</ElButton>
      </template>
    </ElDialog>
  </main>
</template>

<style scoped>
.kb-page {
  --zm-primary: #0f766e;
  --zm-primary-hover: #115e59;
  --zm-primary-active: #134e4a;
  --zm-text-strong: #0f172a;
  --zm-text: #334155;
  --zm-text-muted: #64748b;
  --zm-bg: #f7fafc;
  --zm-bg-soft: #f8fafc;
  --zm-surface: #fff;
  --zm-border: #dbe4ef;
  --zm-border-soft: #e2e8f0;
  --zm-teal-soft: rgb(15 118 110 / 8%);
  --zm-radius: 8px;

  min-height: 100vh;
  padding: 36px 48px 48px;
  background: var(--zm-bg);
  color: var(--zm-text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', sans-serif;
}

/* ── Page header ─────────────────────────────────────────────────── */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 1200px;
  margin: 0 auto 28px;
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

/* ── Toolbar ─────────────────────────────────────────────────────── */
.toolbar-card {
  max-width: 1200px;
  margin: 0 auto;
  border-radius: var(--zm-radius);
  border: 1px solid var(--zm-border-soft);
  background: var(--zm-surface);
  box-shadow: none;
}

.toolbar-card :deep(.el-card__body) {
  padding: 16px 20px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.kb-search {
  width: 280px;
}

.kb-search :deep(.el-input__wrapper) {
  border-radius: var(--zm-radius);
  box-shadow: none;
  border: 1px solid var(--zm-border-soft);
  transition: border-color 0.2s ease;
}

.kb-search :deep(.el-input__wrapper:hover),
.kb-search :deep(.el-input__wrapper.is-focus) {
  border-color: var(--zm-primary);
  box-shadow: 0 0 0 2px var(--zm-teal-soft);
}

.toolbar-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-actions :deep(.el-button) {
  border-radius: var(--zm-radius);
  font-weight: 500;
  height: 36px;
  transition: all 0.2s ease;
}

.toolbar-actions :deep(.el-button--default) {
  border-color: var(--zm-border-soft);
  color: var(--zm-text);
}

.toolbar-actions :deep(.el-button--default:hover) {
  background: var(--zm-bg-soft);
  border-color: var(--zm-border);
  color: var(--zm-text-strong);
}

/* ── Table ───────────────────────────────────────────────────────── */
.table-card {
  max-width: 1200px;
  margin: 0 auto;
  border-radius: var(--zm-radius);
  border: 1px solid var(--zm-border-soft);
  background: var(--zm-surface);
  box-shadow: none;
}

.table-card :deep(.el-card__body) {
  padding: 0;
}

.kb-table :deep(.el-table__header th) {
  background: var(--zm-bg-soft);
  color: var(--zm-text-muted);
  font-size: 11.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--zm-border-soft);
}

.kb-table :deep(.el-table__row td) {
  border-bottom: 1px solid var(--zm-border-soft);
  color: var(--zm-text);
  font-size: 13.5px;
  padding: 12px 0;
}

.kb-table :deep(.el-table__row:hover td) {
  background: var(--zm-bg-soft);
}

.desc-cell {
  color: var(--zm-text-muted);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 300px;
  display: inline-block;
}

.time-cell {
  color: var(--zm-text-muted);
  font-size: 12.5px;
}

.action-btns {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
  flex-wrap: nowrap;
}

.kb-table .action-btns :deep(.el-button) {
  margin-left: 0;
  padding: 4px 10px;
  font-size: 13px;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.kb-table .action-btns :deep(.el-button--text) {
  color: var(--zm-text-muted);
}

.kb-table .action-btns :deep(.el-button--text:hover) {
  color: var(--zm-text-strong);
  background: var(--zm-bg-soft);
}

/* ── Empty & Pagination ──────────────────────────────────────────── */
.empty-wrapper {
  padding: 64px 0;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  padding: 14px 20px;
  border-top: 1px solid var(--zm-border-soft);
}

.pagination-wrapper :deep(.el-pagination) {
  font-size: 13px;
}

.pagination-wrapper :deep(.el-pager li) {
  border-radius: 6px;
  font-weight: 400;
  min-width: 32px;
  height: 32px;
  line-height: 32px;
}

.pagination-wrapper :deep(.el-pager li.is-active) {
  background: var(--zm-primary);
}

/* ── Responsive ──────────────────────────────────────────────────── */
@media (width <= 768px) {
  .kb-page {
    padding: 20px 16px 40px;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .kb-search {
    width: 100%;
  }

  .toolbar-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .action-btns {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (width <= 480px) {
  .page-header h1 {
    font-size: 19px;
  }
}
</style>

<style>
.edit-kb-dialog-modal {
  z-index: 3200 !important;
}

.edit-kb-dialog {
  z-index: 3201 !important;
  overflow: hidden;
  background: #fff;
  border-radius: 12px;
}

.edit-kb-dialog .el-dialog__header {
  padding: 20px 24px 16px;
  margin-right: 0;
  border-bottom: 1px solid #e2e8f0;
}

.edit-kb-dialog .el-dialog__title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.edit-kb-dialog .el-dialog__body {
  position: relative;
  z-index: 1;
  padding: 20px 24px;
  background: #fff;
}

.edit-kb-dialog .el-dialog__footer {
  position: relative;
  z-index: 1;
  padding: 14px 24px;
  border-top: 1px solid #e2e8f0;
}

.edit-kb-dialog .el-form-item__label {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}

.edit-kb-dialog .el-input__wrapper,
.edit-kb-dialog .el-textarea__inner {
  border-radius: 8px;
  box-shadow: none;
  border: 1px solid #e2e8f0;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}

.edit-kb-dialog .el-input__wrapper:hover,
.edit-kb-dialog .el-textarea__inner:hover {
  border-color: #cbd5e1;
}

.edit-kb-dialog .el-input__wrapper.is-focus,
.edit-kb-dialog .el-textarea__inner:focus {
  border-color: #0f766e;
  box-shadow: 0 0 0 2px rgb(15 118 110 / 8%);
}

.edit-kb-dialog .el-button {
  border-radius: 8px;
  font-weight: 500;
  height: 36px;
  transition: all 0.2s ease;
}

.edit-kb-dialog .el-button--default {
  border-color: #e2e8f0;
  color: #334155;
}

.edit-kb-dialog .el-button--default:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.edit-kb-dialog .el-button--primary {
  background: #0f766e;
  border-color: #0f766e;
}

.edit-kb-dialog .el-button--primary:hover {
  background: #115e59;
  border-color: #115e59;
}
</style>
