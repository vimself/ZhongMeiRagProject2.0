<script setup lang="ts">
import { Back, Edit, Refresh, Search, View } from '@element-plus/icons-vue'
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
function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

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
      <ElButton :icon="Back" text @click="router.push('/')">返回首页</ElButton>
      <h1>我的知识库</h1>
    </header>

    <!-- Toolbar -->
    <ElCard class="toolbar-card" shadow="never">
      <div class="toolbar">
        <ElInput
          v-model="search"
          class="knowledge-search"
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
        <ElTableColumn label="操作" width="190" fixed="right">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <div class="action-btns">
              <ElButton
                :icon="View"
                text
                size="small"
                type="primary"
                @click.stop="openDocuments(row)"
              >
                文档
              </ElButton>
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
  min-height: 100vh;
  padding: 32px;
  background: #f6f8fb;
  color: #1f2937;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 1200px;
  margin: 0 auto 24px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}

.toolbar-card :deep(.el-card__body) {
  padding: 16px 20px;
}

.toolbar-card {
  max-width: 1200px;
  margin: 0 auto;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.knowledge-search {
  width: min(100%, 360px);
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

.table-card {
  max-width: 1200px;
  margin: 0 auto;
}

.table-card :deep(.el-card__body) {
  padding: 0;
}

.desc-cell {
  color: #52616f;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 300px;
  display: inline-block;
}

.time-cell {
  color: #8896a4;
  font-size: 13px;
}

.action-btns {
  display: flex;
  gap: 0;
  flex-wrap: wrap;
}

.empty-wrapper {
  padding: 40px 0;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  padding: 16px 20px;
}

@media (width <= 768px) {
  .kb-page {
    padding: 20px;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .knowledge-search {
    width: 100%;
  }

  .action-btns {
    flex-direction: column;
  }
}
</style>
