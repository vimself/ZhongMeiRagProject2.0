<script setup lang="ts">
import { ArrowLeft, Delete, Plus, Refresh, Search, Setting, View } from '@element-plus/icons-vue'
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

import { listAuditLogs } from '@/api/admin'
import {
  adminListPermissionCandidates,
  adminListKnowledgeBases,
  adminListPermissions,
  adminUpdatePermissions,
  createKnowledgeBase,
  deleteKnowledgeBase,
} from '@/api/knowledge'
import type {
  AuditLogOut,
  KnowledgeBaseOut,
  PermissionOut,
  PermissionUpdateItem,
  PermissionUserOut,
} from '@/api/types'
import { formatBeijingDateTime } from '@/utils/time'

const router = useRouter()

// ── List state ──────────────────────────────────────────────────────
const kbs = ref<KnowledgeBaseOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const search = ref('')

// ── Create dialog ───────────────────────────────────────────────────
const dialogVisible = ref(false)
const dialogLoading = ref(false)
const dialogForm = reactive({
  name: '',
  description: '',
})

// ── Archive drawer ─────────────────────────────────────────────────
const archiveDrawerVisible = ref(false)
const selectedKb = ref<KnowledgeBaseOut | null>(null)
const permissions = ref<PermissionOut[]>([])
const auditLogs = ref<AuditLogOut[]>([])
const archiveLoading = ref(false)

// ── Permission drawer ───────────────────────────────────────────────
const permDrawerVisible = ref(false)
const permKbId = ref('')
const permKbName = ref('')
const permLoading = ref(false)
const permSaving = ref(false)
const allUsers = ref<PermissionUserOut[]>([])
const permForm = ref<PermissionUpdateItem[]>([])

// ── Helpers ─────────────────────────────────────────────────────────
const formatDateTime = formatBeijingDateTime

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

function creatorLabel(row: KnowledgeBaseOut): string {
  if (row.creator_username) return row.creator_username
  if (row.creator_name) return row.creator_name
  return compactUserId(row.creator_id)
}

function compactUserId(userId: string | null): string {
  if (!userId) return '—'
  return `未知用户 ${userId.slice(0, 8)}`
}

function userOptionLabel(user: PermissionUserOut): string {
  const name = user.display_name || user.username
  return name ? `${name}（${user.username || user.id.slice(0, 8)}）` : compactUserId(user.id)
}

function permissionUserLabel(permission: PermissionOut): string {
  const name = permission.display_name || permission.username
  return name
    ? `${name}（${permission.username || permission.user_id.slice(0, 8)}）`
    : compactUserId(permission.user_id)
}

function lifecycleActionLabel(action: string): string {
  const map: Record<string, string> = {
    'knowledge_base.create': '创建知识库',
    'knowledge_base.update': '更新信息',
    'knowledge_base.delete': '删除知识库',
    'knowledge_base.disable': '删除知识库',
    'knowledge_base.permissions.update': '更新权限',
  }
  return map[action] || action
}

function resetDialog() {
  dialogForm.name = ''
  dialogForm.description = ''
}

// ── Load ────────────────────────────────────────────────────────────
async function loadKBs() {
  loading.value = true
  try {
    const resp = await adminListKnowledgeBases({
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

// ── Create ──────────────────────────────────────────────────────────
function openCreateDialog() {
  resetDialog()
  dialogVisible.value = true
}

async function submitCreate() {
  if (!dialogForm.name.trim()) {
    ElMessage.error('请输入知识库名称')
    return
  }
  dialogLoading.value = true
  try {
    await createKnowledgeBase({
      name: dialogForm.name.trim(),
      description: dialogForm.description.trim(),
    })
    ElMessage.success('知识库已创建')
    dialogVisible.value = false
    await loadKBs()
  } catch (err: unknown) {
    const msg =
      err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined
    ElMessage.error(msg || '创建失败')
  } finally {
    dialogLoading.value = false
  }
}

async function handleDelete(kb: KnowledgeBaseOut) {
  try {
    await ElMessageBox.confirm(
      `确定要删除知识库 "${kb.name}" 吗？删除后无法找回，后端会物理删除该知识库、文档、OCR 结果和向量数据，并解除历史会话绑定。`,
      '删除知识库',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await deleteKnowledgeBase(kb.id)
    ElMessage.success('知识库已删除')
    await loadKBs()
  } catch {
    ElMessage.error('删除失败')
  }
}

// ── Permission management ───────────────────────────────────────────
async function openPermDrawer(kb: KnowledgeBaseOut) {
  permKbId.value = kb.id
  permKbName.value = kb.name
  permissions.value = []
  permForm.value = []
  allUsers.value = []
  permDrawerVisible.value = true
  await Promise.all([loadPermissions(), loadPermissionCandidates()])
}

async function loadPermissions() {
  permLoading.value = true
  try {
    const resp = await adminListPermissions(permKbId.value)
    permissions.value = resp.data
    permForm.value = resp.data.map((p) => ({ user_id: p.user_id, role: p.role }))
    mergePermissionUsers(
      resp.data.map((permission) => ({
        id: permission.user_id,
        username: permission.username,
        display_name: permission.display_name,
      })),
    )
  } catch {
    ElMessage.error('权限信息加载失败')
  } finally {
    permLoading.value = false
  }
}

async function loadPermissionCandidates() {
  try {
    const resp = await adminListPermissionCandidates(permKbId.value)
    mergePermissionUsers(resp.data)
  } catch {
    ElMessage.warning('候选用户列表加载失败，已保留当前权限成员')
  }
}

function mergePermissionUsers(users: PermissionUserOut[]) {
  const userMap = new Map(allUsers.value.map((user) => [user.id, user]))
  users.forEach((user) => {
    userMap.set(user.id, {
      id: user.id,
      username: user.username,
      display_name: user.display_name,
    })
  })
  allUsers.value = Array.from(userMap.values())
}

function addPermRow() {
  permForm.value.push({ user_id: '', role: 'viewer' })
}

function removePermRow(index: number) {
  permForm.value.splice(index, 1)
}

async function savePermissions() {
  const validItems = permForm.value.filter((p) => p.user_id)
  const userIds = validItems.map((p) => p.user_id)
  if (new Set(userIds).size !== userIds.length) {
    ElMessage.error('不能重复添加同一用户')
    return
  }

  permSaving.value = true
  try {
    await adminUpdatePermissions(permKbId.value, { permissions: validItems })
    ElMessage.success('权限已更新')
    permDrawerVisible.value = false
    await loadKBs()
  } catch (err: unknown) {
    const msg =
      err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined
    ElMessage.error(msg || '权限更新失败')
  } finally {
    permSaving.value = false
  }
}

function availableUsers(excludeIndex: number): PermissionUserOut[] {
  const selectedIds = new Set(
    permForm.value.filter((_, i) => i !== excludeIndex).map((p) => p.user_id),
  )
  return allUsers.value.filter((u) => !selectedIds.has(u.id))
}

// ── Archive drawer ─────────────────────────────────────────────────
async function openArchiveDrawer(kb: KnowledgeBaseOut) {
  selectedKb.value = kb
  archiveDrawerVisible.value = true
  archiveLoading.value = true
  try {
    const [permissionResp, auditResp] = await Promise.all([
      adminListPermissions(kb.id),
      listAuditLogs({
        page: 1,
        page_size: 20,
        target_type: 'knowledge_base',
        target_id: kb.id,
      }),
    ])
    permissions.value = permissionResp.data
    auditLogs.value = auditResp.data.items
  } catch {
    ElMessage.error('档案信息加载失败')
  } finally {
    archiveLoading.value = false
  }
}

onMounted(loadKBs)
</script>

<template>
  <main class="admin-kb-page">
    <header class="page-header">
      <div class="header-left">
        <span class="brand-mark">ZM</span>
        <div>
          <p class="eyebrow">Administration</p>
          <h1>知识库管理</h1>
        </div>
      </div>
      <ElButton :icon="ArrowLeft" text @click="router.push('/')">返回首页</ElButton>
    </header>

    <!-- Toolbar -->
    <ElCard class="toolbar-card" shadow="never">
      <div class="toolbar">
        <div class="toolbar-filters">
          <ElInput
            v-model="search"
            class="kb-search"
            placeholder="搜索知识库名称或描述"
            clearable
            :prefix-icon="Search"
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          />
        </div>
        <div class="toolbar-actions">
          <ElButton :icon="Refresh" @click="loadKBs">刷新</ElButton>
          <ElButton type="primary" :icon="Plus" @click="openCreateDialog">新建知识库</ElButton>
        </div>
      </div>
    </ElCard>

    <!-- Table -->
    <ElCard class="table-card" shadow="never">
      <ElTable v-loading="loading" class="admin-kb-table" :data="kbs" stripe style="width: 100%">
        <ElTableColumn prop="name" label="知识库名称" min-width="150" />
        <ElTableColumn prop="description" label="描述" min-width="180">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="desc-cell">{{ row.description || '—' }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="文档规模" width="100">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="metric-cell"
              >{{ row.active_document_count }} / {{ row.document_count }}</span
            >
          </template>
        </ElTableColumn>
        <ElTableColumn label="成员" width="70">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="metric-cell">{{ row.permission_count }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="创建者" prop="creator_username" width="150">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="time-cell">{{ creatorLabel(row) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="创建时间" width="150">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <span class="time-cell">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="210" align="right">
          <template #default="{ row }: { row: KnowledgeBaseOut }">
            <div class="action-btns">
              <ElButton :icon="View" text size="small" @click="openArchiveDrawer(row)">
                档案
              </ElButton>
              <ElButton
                v-if="row.is_active"
                :icon="Setting"
                text
                size="small"
                type="primary"
                @click="openPermDrawer(row)"
              >
                权限
              </ElButton>
              <ElButton
                v-if="row.is_active"
                :icon="Delete"
                text
                size="small"
                type="danger"
                @click="handleDelete(row)"
              >
                删除
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

    <ElDialog
      v-model="dialogVisible"
      title="新建知识库"
      width="520px"
      append-to-body
      class="create-kb-dialog"
      modal-class="create-kb-dialog-modal"
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
        <ElButton type="primary" :loading="dialogLoading" @click="submitCreate">创建</ElButton>
      </template>
    </ElDialog>

    <ElDrawer
      v-model="permDrawerVisible"
      :title="`权限设置 — ${permKbName}`"
      size="600px"
      append-to-body
      class="archive-drawer"
      modal-class="archive-drawer-modal"
      :z-index="3000"
    >
      <div v-loading="permLoading">
        <div v-if="permForm.length === 0 && !permLoading" class="perm-empty">暂无权限记录</div>
        <div v-else class="perm-list">
          <div v-for="(item, index) in permForm" :key="index" class="perm-row">
            <ElSelect
              v-model="item.user_id"
              :teleported="false"
              filterable
              placeholder="选择用户"
              style="flex: 1"
            >
              <ElOption
                v-for="u in availableUsers(index)"
                :key="u.id"
                :label="userOptionLabel(u)"
                :value="u.id"
              />
            </ElSelect>
            <ElSelect v-model="item.role" :teleported="false" style="width: 120px">
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

    <ElDrawer
      v-model="archiveDrawerVisible"
      :title="`知识库档案 — ${selectedKb?.name || ''}`"
      size="640px"
      append-to-body
      class="archive-drawer"
      modal-class="archive-drawer-modal"
      :z-index="3000"
    >
      <div v-loading="archiveLoading" class="archive">
        <template v-if="selectedKb">
          <section class="archive-section">
            <h2>生命周期</h2>
            <div class="archive-grid">
              <div>
                <span>创建者</span>
                <strong>{{ creatorLabel(selectedKb) }}</strong>
              </div>
              <div>
                <span>创建时间</span>
                <strong>{{ formatDateTime(selectedKb.created_at) }}</strong>
              </div>
            </div>
          </section>

          <section class="archive-section">
            <h2>规模快照</h2>
            <div class="archive-grid">
              <div>
                <span>文档总数</span>
                <strong>{{ selectedKb.active_document_count }}</strong>
              </div>
              <div>
                <span>数据库记录</span>
                <strong>{{ selectedKb.document_count }}</strong>
              </div>
              <div>
                <span>成员记录</span>
                <strong>{{ selectedKb.permission_count }}</strong>
              </div>
            </div>
          </section>

          <section class="archive-section">
            <h2>权限快照</h2>
            <div v-if="permissions.length === 0 && !archiveLoading" class="archive-empty">
              暂无权限记录
            </div>
            <div v-for="perm in permissions" :key="perm.id" class="perm-item">
              <div class="perm-item-main">
                <span class="perm-user">{{ permissionUserLabel(perm) }}</span>
                <ElTag :type="roleTagType(perm.role)" size="small">
                  {{ roleLabel(perm.role) }}
                </ElTag>
              </div>
              <div class="perm-meta">
                <span>ID: {{ perm.user_id }}</span>
                <span>创建: {{ formatDateTime(perm.created_at) }}</span>
              </div>
            </div>
          </section>

          <section class="archive-section">
            <h2>审计记录</h2>
            <div v-if="auditLogs.length === 0 && !archiveLoading" class="archive-empty">
              暂无审计记录
            </div>
            <div v-for="log in auditLogs" :key="log.id" class="audit-item">
              <div class="audit-item-top">
                <strong>{{ lifecycleActionLabel(log.action) }}</strong>
                <span>{{ formatDateTime(log.created_at) }}</span>
              </div>
              <small>操作者：{{ log.actor_user_id || '—' }}</small>
            </div>
          </section>
        </template>
      </div>
    </ElDrawer>
  </main>
</template>

<style scoped>
.admin-kb-page {
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

.toolbar-filters {
  display: flex;
  gap: 12px;
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

.toolbar-actions :deep(.el-button--primary) {
  background: var(--zm-primary);
  border-color: var(--zm-primary);
}

.toolbar-actions :deep(.el-button--primary:hover) {
  background: var(--zm-primary-hover);
  border-color: var(--zm-primary-hover);
}

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

.admin-kb-table :deep(.el-table__header th) {
  background: var(--zm-bg-soft);
  color: var(--zm-text-muted);
  font-size: 11.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--zm-border-soft);
}

.admin-kb-table :deep(.el-table__row td) {
  border-bottom: 1px solid var(--zm-border-soft);
  color: var(--zm-text);
  font-size: 13.5px;
  padding: 12px 0;
}

.admin-kb-table :deep(.el-table__row:hover td) {
  background: var(--zm-bg-soft);
}

.action-btns {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
  flex-wrap: nowrap;
}

.admin-kb-table .action-btns :deep(.el-button) {
  margin-left: 0;
  padding: 4px 10px;
  font-size: 13px;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.admin-kb-table .action-btns :deep(.el-button--text) {
  color: var(--zm-text-muted);
}

.admin-kb-table .action-btns :deep(.el-button--text:hover) {
  color: var(--zm-text-strong);
  background: var(--zm-bg-soft);
}

.admin-kb-table .action-btns :deep(.el-button--primary.is-text) {
  color: var(--zm-primary);
}

.admin-kb-table .action-btns :deep(.el-button--primary.is-text:hover) {
  color: var(--zm-primary-hover);
  background: var(--zm-teal-soft);
}

.admin-kb-table .action-btns :deep(.el-button--danger.is-text) {
  color: var(--zm-text-muted);
}

.admin-kb-table .action-btns :deep(.el-button--danger.is-text:hover) {
  color: #dc2626;
  background: #fef2f2;
}

.desc-cell {
  color: var(--zm-text-muted);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 260px;
  display: inline-block;
}

.time-cell {
  color: var(--zm-text-muted);
  font-size: 12.5px;
}

.metric-cell {
  color: var(--zm-text);
  font-size: 13.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

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

.archive {
  display: grid;
  gap: 24px;
}

.archive-section {
  display: grid;
  gap: 12px;
}

.archive-section h2 {
  margin: 0;
  color: var(--zm-text-strong);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--zm-border-soft);
}

.archive-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.archive-grid div {
  display: grid;
  gap: 5px;
  padding: 12px 14px;
  background: var(--zm-bg-soft);
  border: 1px solid var(--zm-border-soft);
  border-radius: var(--zm-radius);
  transition: border-color 0.2s ease;
}

.archive-grid div:hover {
  border-color: var(--zm-border);
}

.archive-grid span {
  color: var(--zm-text-muted);
  font-size: 11.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.archive-empty {
  color: var(--zm-text-muted);
  font-size: 13px;
  padding: 16px 0;
}

.archive-grid strong {
  color: var(--zm-text-strong);
  font-size: 15px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.perm-item {
  padding: 12px 14px;
  background: var(--zm-bg-soft);
  border: 1px solid var(--zm-border-soft);
  border-radius: var(--zm-radius);
  transition: border-color 0.2s ease;
}

.perm-item:hover {
  border-color: var(--zm-border);
}

.perm-item-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.perm-user {
  font-weight: 600;
  color: var(--zm-text-strong);
  font-size: 13.5px;
}

.perm-meta {
  display: flex;
  gap: 16px;
  color: var(--zm-text-muted);
  font-size: 12px;
}

.perm-empty {
  padding: 64px 0;
  color: var(--zm-text-muted);
  text-align: center;
  font-size: 13.5px;
}

.perm-list {
  display: grid;
  gap: 10px;
  margin-bottom: 16px;
}

.perm-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.perm-row :deep(.el-select) {
  flex: 1;
}

.perm-row :deep(.el-input__wrapper) {
  border-radius: var(--zm-radius);
  box-shadow: none;
  border: 1px solid var(--zm-border-soft);
  transition: border-color 0.2s ease;
}

.perm-row :deep(.el-input__wrapper:hover),
.perm-row :deep(.el-input__wrapper.is-focus) {
  border-color: var(--zm-primary);
  box-shadow: 0 0 0 2px var(--zm-teal-soft);
}

.perm-actions {
  display: flex;
  gap: 10px;
  padding-top: 16px;
  border-top: 1px solid var(--zm-border-soft);
}

.perm-actions :deep(.el-button) {
  border-radius: var(--zm-radius);
  font-weight: 500;
  height: 36px;
  transition: all 0.2s ease;
}

.perm-actions :deep(.el-button--default) {
  border-color: var(--zm-border-soft);
  color: var(--zm-text);
}

.perm-actions :deep(.el-button--default:hover) {
  background: var(--zm-bg-soft);
  border-color: var(--zm-border);
}

.perm-actions :deep(.el-button--primary) {
  background: var(--zm-primary);
  border-color: var(--zm-primary);
}

.perm-actions :deep(.el-button--primary:hover) {
  background: var(--zm-primary-hover);
  border-color: var(--zm-primary-hover);
}

.audit-item {
  display: grid;
  gap: 6px;
  padding: 12px 0;
  border-bottom: 1px solid var(--zm-border-soft);
}

.audit-item:last-child {
  border-bottom: none;
}

.audit-item-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.audit-item strong {
  color: var(--zm-text-strong);
  font-size: 13.5px;
  font-weight: 500;
}

.audit-item span {
  color: var(--zm-text-muted);
  font-size: 12.5px;
}

.audit-item small {
  color: var(--zm-text-muted);
  font-size: 12px;
}

@media (width <= 768px) {
  .admin-kb-page {
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

  .toolbar-filters {
    flex-direction: column;
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

  .archive-grid {
    grid-template-columns: 1fr;
  }

  .perm-row {
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
.create-kb-dialog-modal {
  z-index: 3200 !important;
}

.create-kb-dialog {
  z-index: 3201 !important;
  overflow: hidden;
  background: #fff;
  border-radius: 12px;
}

.create-kb-dialog .el-dialog__header {
  padding: 20px 24px 16px;
  margin-right: 0;
  border-bottom: 1px solid #e2e8f0;
}

.create-kb-dialog .el-dialog__title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.create-kb-dialog .el-dialog__body {
  position: relative;
  z-index: 1;
  padding: 20px 24px;
  background: #fff;
}

.create-kb-dialog .el-dialog__footer {
  position: relative;
  z-index: 1;
  padding: 14px 24px;
  border-top: 1px solid #e2e8f0;
}

.create-kb-dialog .el-form-item__label {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}

.create-kb-dialog .el-input__wrapper,
.create-kb-dialog .el-textarea__inner {
  border-radius: 8px;
  box-shadow: none;
  border: 1px solid #e2e8f0;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}

.create-kb-dialog .el-input__wrapper:hover,
.create-kb-dialog .el-textarea__inner:hover {
  border-color: #cbd5e1;
}

.create-kb-dialog .el-input__wrapper.is-focus,
.create-kb-dialog .el-textarea__inner:focus {
  border-color: #0f766e;
  box-shadow: 0 0 0 2px rgb(15 118 110 / 8%);
}

.create-kb-dialog .el-button {
  border-radius: 8px;
  font-weight: 500;
  height: 36px;
  transition: all 0.2s ease;
}

.create-kb-dialog .el-button--default {
  border-color: #e2e8f0;
  color: #334155;
}

.create-kb-dialog .el-button--default:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.create-kb-dialog .el-button--primary {
  background: #0f766e;
  border-color: #0f766e;
}

.create-kb-dialog .el-button--primary:hover {
  background: #115e59;
  border-color: #115e59;
}

.archive-drawer-modal {
  z-index: 3000 !important;
}

.archive-drawer {
  z-index: 3001 !important;
  background: #fff;
}

.archive-drawer .el-drawer__header {
  padding: 20px 24px;
  margin-bottom: 0;
  border-bottom: 1px solid #e2e8f0;
  background: #fff;
}

.archive-drawer .el-drawer__title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.archive-drawer .el-drawer__body {
  padding: 20px 24px;
  background: #fff;
  overflow: auto;
}
</style>
