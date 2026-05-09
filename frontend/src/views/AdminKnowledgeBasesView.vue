<script setup lang="ts">
import { Back, Refresh, Search, View } from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElCard from 'element-plus/es/components/card/index.mjs'
import ElDrawer from 'element-plus/es/components/drawer/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import ElPagination from 'element-plus/es/components/pagination/index.mjs'
import ElSelect, { ElOption } from 'element-plus/es/components/select/index.mjs'
import ElTable, { ElTableColumn } from 'element-plus/es/components/table/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import ElEmpty from 'element-plus/es/components/empty/index.mjs'
import vLoading from 'element-plus/es/components/loading/src/directive.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-card.css'
import 'element-plus/theme-chalk/el-drawer.css'
import 'element-plus/theme-chalk/el-empty.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-input.css'
import 'element-plus/theme-chalk/el-loading.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-option.css'
import 'element-plus/theme-chalk/el-pagination.css'
import 'element-plus/theme-chalk/el-select.css'
import 'element-plus/theme-chalk/el-table.css'
import 'element-plus/theme-chalk/el-table-column.css'
import 'element-plus/theme-chalk/el-tag.css'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { adminListKnowledgeBases, adminListPermissions } from '@/api/knowledge'
import type { KnowledgeBaseOut, PermissionOut } from '@/api/types'

const router = useRouter()

// ── List state ──────────────────────────────────────────────────────
const kbs = ref<KnowledgeBaseOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const search = ref('')
const filterActive = ref<boolean | undefined>(undefined)

// ── Permission drawer ───────────────────────────────────────────────
const permDrawerVisible = ref(false)
const permKbName = ref('')
const permissions = ref<PermissionOut[]>([])
const permLoading = ref(false)

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

function roleLabel(role: string): string {
  const map: Record<string, string> = {
    owner: '所有者',
    editor: '编辑者',
    viewer: '查看者',
  }
  return map[role] || role
}

function roleTagType(role: string): 'danger' | 'warning' | 'info' {
  const map: Record<string, 'danger' | 'warning' | 'info'> = {
    owner: 'danger',
    editor: 'warning',
    viewer: 'info',
  }
  return map[role] || 'info'
}

// ── Load ────────────────────────────────────────────────────────────
async function loadKBs() {
  loading.value = true
  try {
    const resp = await adminListKnowledgeBases({
      page: page.value,
      page_size: pageSize.value,
      search: search.value,
      is_active: filterActive.value,
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

// ── Permission drawer ───────────────────────────────────────────────
async function openPermDrawer(kb: KnowledgeBaseOut) {
  permKbName.value = kb.name
  permDrawerVisible.value = true
  permLoading.value = true
  try {
    const resp = await adminListPermissions(kb.id)
    permissions.value = resp.data
  } catch {
    ElMessage.error('权限信息加载失败')
  } finally {
    permLoading.value = false
  }
}

onMounted(loadKBs)
</script>

<template>
  <main class="admin-kb-page">
    <header class="page-header">
      <ElButton :icon="Back" text @click="router.push('/')">返回首页</ElButton>
      <h1>知识库管理（管理员）</h1>
    </header>

    <!-- Toolbar -->
    <ElCard class="toolbar-card" shadow="never">
      <div class="toolbar">
        <div class="toolbar-filters">
          <ElInput
            v-model="search"
            placeholder="搜索知识库名称或描述"
            clearable
            :prefix-icon="Search"
            style="width: 280px"
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          />
          <ElSelect
            v-model="filterActive"
            placeholder="状态筛选"
            clearable
            style="width: 140px"
            @change="handleSearch"
          >
            <ElOption label="启用" :value="true" />
            <ElOption label="停用" :value="false" />
          </ElSelect>
        </div>
        <ElButton :icon="Refresh" @click="loadKBs">刷新</ElButton>
      </div>
    </ElCard>

    <!-- Table -->
    <ElCard class="table-card" shadow="never">
      <ElTable v-loading="loading" :data="kbs" stripe style="width: 100%">
        <ElTableColumn prop="name" label="知识库名称" min-width="180" />
        <ElTableColumn prop="description" label="描述" min-width="240">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="desc-cell">{{ row.description || '—' }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="80">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <ElTag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '停用' }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="创建者" prop="creator_id" width="120">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="time-cell">{{ row.creator_id || '—' }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="创建时间" width="150">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="time-cell">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="120" fixed="right">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <ElButton :icon="View" text size="small" @click="openPermDrawer(row)"> 权限 </ElButton>
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

    <!-- Permission Drawer (read-only for admin) -->
    <ElDrawer v-model="permDrawerVisible" :title="`权限查看 — ${permKbName}`" size="560px">
      <div v-loading="permLoading">
        <div v-if="permissions.length === 0 && !permLoading" class="perm-empty">暂无权限记录</div>
        <div v-else class="perm-list">
          <div v-for="perm in permissions" :key="perm.id" class="perm-item">
            <div class="perm-item-main">
              <span class="perm-user">{{ perm.display_name }} ({{ perm.username }})</span>
              <ElTag :type="roleTagType(perm.role)" size="small">
                {{ roleLabel(perm.role) }}
              </ElTag>
            </div>
            <div class="perm-meta">
              <span>ID: {{ perm.user_id }}</span>
              <span>创建: {{ formatDateTime(perm.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </ElDrawer>
  </main>
</template>

<style scoped>
.admin-kb-page {
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

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.toolbar-filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
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

.empty-wrapper {
  padding: 40px 0;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  padding: 16px 20px;
}

.perm-empty {
  padding: 40px 0;
  color: #8896a4;
  text-align: center;
  font-size: 14px;
}

.perm-list {
  display: grid;
  gap: 12px;
}

.perm-item {
  padding: 12px 16px;
  background: #fafbfc;
  border: 1px solid #ebedf0;
  border-radius: 6px;
}

.perm-item-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.perm-user {
  font-weight: 600;
  color: #1f2937;
  font-size: 14px;
}

.perm-meta {
  display: flex;
  gap: 16px;
  color: #8896a4;
  font-size: 12px;
}

@media (width <= 768px) {
  .admin-kb-page {
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

  .toolbar-filters {
    flex-direction: column;
  }
}
</style>
