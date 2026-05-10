<script setup lang="ts">
import { Back, Delete, Edit, Plus, Refresh, Search, Setting } from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElCard from 'element-plus/es/components/card/index.mjs'
import ElDialog from 'element-plus/es/components/dialog/index.mjs'
import ElDrawer from 'element-plus/es/components/drawer/index.mjs'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'
import ElPagination from 'element-plus/es/components/pagination/index.mjs'
import ElSelect, { ElOption } from 'element-plus/es/components/select/index.mjs'
import ElTable, { ElTableColumn } from 'element-plus/es/components/table/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import ElEmpty from 'element-plus/es/components/empty/index.mjs'
import vLoading from 'element-plus/es/components/loading/src/directive.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-card.css'
import 'element-plus/theme-chalk/el-dialog.css'
import 'element-plus/theme-chalk/el-drawer.css'
import 'element-plus/theme-chalk/el-empty.css'
import 'element-plus/theme-chalk/el-form.css'
import 'element-plus/theme-chalk/el-form-item.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-input.css'
import 'element-plus/theme-chalk/el-loading.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'
import 'element-plus/theme-chalk/el-option.css'
import 'element-plus/theme-chalk/el-pagination.css'
import 'element-plus/theme-chalk/el-select.css'
import 'element-plus/theme-chalk/el-table.css'
import 'element-plus/theme-chalk/el-table-column.css'
import 'element-plus/theme-chalk/el-tag.css'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createKnowledgeBase,
  disableKnowledgeBase,
  listKnowledgeBases,
  listPermissionCandidates,
  listPermissions,
  updateKnowledgeBase,
  updatePermissions,
} from '@/api/knowledge'
import type {
  KnowledgeBaseOut,
  PermissionOut,
  PermissionUpdateItem,
  PermissionUserOut,
} from '@/api/types'

const router = useRouter()

// ── Knowledge base list state ───────────────────────────────────────
const kbs = ref<KnowledgeBaseOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const search = ref('')

// ── Create / Edit dialog ────────────────────────────────────────────
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingKb = ref<KnowledgeBaseOut | null>(null)
const dialogLoading = ref(false)
const dialogForm = reactive({
  name: '',
  description: '',
})

// ── Permission drawer ───────────────────────────────────────────────
const permDrawerVisible = ref(false)
const permKbId = ref('')
const permKbName = ref('')
const permissions = ref<PermissionOut[]>([])
const permLoading = ref(false)
const permSaving = ref(false)
const allUsers = ref<PermissionUserOut[]>([])
const permForm = ref<PermissionUpdateItem[]>([])

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

// ── Create / Edit ───────────────────────────────────────────────────
function openCreateDialog() {
  dialogMode.value = 'create'
  editingKb.value = null
  dialogForm.name = ''
  dialogForm.description = ''
  dialogVisible.value = true
}

function openEditDialog(kb: KnowledgeBaseOut) {
  dialogMode.value = 'edit'
  editingKb.value = kb
  dialogForm.name = kb.name
  dialogForm.description = kb.description
  dialogVisible.value = true
}

async function submitDialog() {
  if (!dialogForm.name.trim()) {
    ElMessage.error('请输入知识库名称')
    return
  }
  dialogLoading.value = true
  try {
    if (dialogMode.value === 'create') {
      await createKnowledgeBase({
        name: dialogForm.name.trim(),
        description: dialogForm.description.trim(),
      })
      ElMessage.success('知识库已创建')
    } else if (editingKb.value) {
      await updateKnowledgeBase(editingKb.value.id, {
        name: dialogForm.name.trim(),
        description: dialogForm.description.trim(),
      })
      ElMessage.success('知识库已更新')
    }
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

// ── Disable knowledge base ──────────────────────────────────────────
async function handleDisable(kb: KnowledgeBaseOut) {
  try {
    await ElMessageBox.confirm(
      `确定要停用知识库 "${kb.name}" 吗？停用后将不可访问。`,
      '停用知识库',
      { confirmButtonText: '确定停用', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await disableKnowledgeBase(kb.id)
    ElMessage.success('知识库已停用')
    await loadKBs()
  } catch {
    ElMessage.error('操作失败')
  }
}

// ── Permission drawer ───────────────────────────────────────────────
async function openPermDrawer(kb: KnowledgeBaseOut) {
  permKbId.value = kb.id
  permKbName.value = kb.name
  permDrawerVisible.value = true
  try {
    await Promise.all([loadPermissions(), loadAllUsers()])
  } catch {
    ElMessage.error('权限信息加载失败')
  }
}

async function loadPermissions() {
  permLoading.value = true
  try {
    const resp = await listPermissions(permKbId.value)
    permissions.value = resp.data
    permForm.value = resp.data.map((p) => ({ user_id: p.user_id, role: p.role }))
  } finally {
    permLoading.value = false
  }
}

async function loadAllUsers() {
  const resp = await listPermissionCandidates(permKbId.value)
  allUsers.value = resp.data
}

function addPermRow() {
  permForm.value.push({ user_id: '', role: 'viewer' })
}

function removePermRow(index: number) {
  permForm.value.splice(index, 1)
}

async function savePermissions() {
  // Validate
  const validItems = permForm.value.filter((p) => p.user_id)
  const userIds = validItems.map((p) => p.user_id)
  if (new Set(userIds).size !== userIds.length) {
    ElMessage.error('不能重复添加同一用户')
    return
  }

  permSaving.value = true
  try {
    await updatePermissions(permKbId.value, { permissions: validItems })
    ElMessage.success('权限已更新')
    permDrawerVisible.value = false
    await loadKBs()
  } catch (err: unknown) {
    const msg =
      err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined
    ElMessage.error(msg || '操作失败')
  } finally {
    permSaving.value = false
  }
}

// Available users for a given perm row (exclude already selected in other rows)
function availableUsers(excludeIndex: number): PermissionUserOut[] {
  const selectedIds = new Set(
    permForm.value.filter((_, i) => i !== excludeIndex).map((p) => p.user_id),
  )
  return allUsers.value.filter((u) => !selectedIds.has(u.id))
}

onMounted(loadKBs)
</script>

<template>
  <main class="kb-page">
    <header class="page-header">
      <ElButton :icon="Back" text @click="router.push('/')">返回首页</ElButton>
      <h1>知识库管理</h1>
    </header>

    <!-- Toolbar -->
    <ElCard class="toolbar-card" shadow="never">
      <div class="toolbar">
        <ElInput
          v-model="search"
          placeholder="搜索知识库名称或描述"
          clearable
          :prefix-icon="Search"
          style="width: 280px"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <div class="toolbar-actions">
          <ElButton :icon="Refresh" @click="loadKBs">刷新</ElButton>
          <ElButton type="primary" :icon="Plus" @click="openCreateDialog">新建知识库</ElButton>
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
        @row-click="(row: KnowledgeBaseOut) => router.push(`/knowledge/${row.id}/documents`)"
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
        <ElTableColumn label="操作" width="240" fixed="right">
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
              <ElButton
                v-if="row.my_role === 'owner' || row.my_role === 'admin'"
                :icon="Setting"
                text
                size="small"
                @click.stop="openPermDrawer(row)"
              >
                权限
              </ElButton>
              <ElButton
                v-if="row.my_role === 'owner' || row.my_role === 'admin'"
                :icon="Delete"
                text
                size="small"
                type="danger"
                @click.stop="handleDisable(row)"
              >
                停用
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

    <!-- Create / Edit Dialog -->
    <ElDialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新建知识库' : '编辑知识库'"
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
        <ElButton type="primary" :loading="dialogLoading" @click="submitDialog">
          {{ dialogMode === 'create' ? '创建' : '保存' }}
        </ElButton>
      </template>
    </ElDialog>

    <!-- Permission Drawer -->
    <ElDrawer v-model="permDrawerVisible" :title="`权限管理 — ${permKbName}`" size="600px">
      <div v-loading="permLoading">
        <div v-if="permForm.length === 0 && !permLoading" class="perm-empty">暂无权限记录</div>
        <div v-else class="perm-list">
          <div v-for="(item, index) in permForm" :key="index" class="perm-row">
            <ElSelect v-model="item.user_id" filterable placeholder="选择用户" style="flex: 1">
              <ElOption
                v-for="u in availableUsers(index)"
                :key="u.id"
                :label="`${u.display_name} (${u.username})`"
                :value="u.id"
              />
            </ElSelect>
            <ElSelect v-model="item.role" style="width: 120px">
              <ElOption label="所有者" value="owner" />
              <ElOption label="编辑者" value="editor" />
              <ElOption label="查看者" value="viewer" />
            </ElSelect>
            <ElButton :icon="Delete" text type="danger" @click="removePermRow(index)" />
          </div>
        </div>
        <div class="perm-actions">
          <ElButton :icon="Plus" @click="addPermRow">添加用户</ElButton>
          <ElButton type="primary" :loading="permSaving" @click="savePermissions">
            保存权限
          </ElButton>
        </div>
      </div>
    </ElDrawer>
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

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
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

.perm-empty {
  padding: 40px 0;
  color: #8896a4;
  text-align: center;
  font-size: 14px;
}

.perm-list {
  display: grid;
  gap: 12px;
  margin-bottom: 16px;
}

.perm-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.perm-actions {
  display: flex;
  gap: 8px;
  padding-top: 16px;
  border-top: 1px solid #ebedf0;
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

  .action-btns {
    flex-direction: column;
  }

  .perm-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
