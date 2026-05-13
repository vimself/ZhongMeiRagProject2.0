<script setup lang="ts">
import {
  CircleCheck,
  Edit,
  Key,
  Plus,
  Refresh,
  Search,
  View,
  Back,
  Warning,
} from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElCard from 'element-plus/es/components/card/index.mjs'
import ElDialog from 'element-plus/es/components/dialog/index.mjs'
import ElDrawer from 'element-plus/es/components/drawer/index.mjs'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index.mjs'
import ElIcon from 'element-plus/es/components/icon/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import ElPagination from 'element-plus/es/components/pagination/index.mjs'
import ElSelect, { ElOption } from 'element-plus/es/components/select/index.mjs'
import ElSwitch from 'element-plus/es/components/switch/index.mjs'
import ElTable, { ElTableColumn } from 'element-plus/es/components/table/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-card.css'
import 'element-plus/theme-chalk/el-dialog.css'
import 'element-plus/theme-chalk/el-drawer.css'
import 'element-plus/theme-chalk/el-form.css'
import 'element-plus/theme-chalk/el-form-item.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-input.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-option.css'
import 'element-plus/theme-chalk/el-pagination.css'
import 'element-plus/theme-chalk/el-select.css'
import 'element-plus/theme-chalk/el-switch.css'
import 'element-plus/theme-chalk/el-table.css'
import 'element-plus/theme-chalk/el-table-column.css'
import 'element-plus/theme-chalk/el-tag.css'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { createUser, listAuditLogs, listUsers, resetPassword, updateUser } from '@/api/admin'
import type { AdminUserOut, AuditLogOut } from '@/api/types'
import { formatBeijingDateTime } from '@/utils/time'

const router = useRouter()

// ── User list state ─────────────────────────────────────────────────
const users = ref<AdminUserOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const search = ref('')
const filterRole = ref('')
const filterActive = ref<boolean | undefined>(undefined)

// ── Dialog state ────────────────────────────────────────────────────
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingUser = ref<AdminUserOut | null>(null)
const dialogLoading = ref(false)
const dialogForm = reactive({
  username: '',
  display_name: '',
  password: '',
  role: 'user',
  is_active: true,
  require_password_change: false,
})

// ── Reset password dialog ───────────────────────────────────────────
const resetDialogVisible = ref(false)
const resetUserId = ref('')
const resetUserName = ref('')
const resetNewPassword = ref('')
const resetLoading = ref(false)

// ── Audit drawer ────────────────────────────────────────────────────
const auditDrawerVisible = ref(false)
const auditTargetId = ref('')
const auditTargetName = ref('')
const auditLogs = ref<AuditLogOut[]>([])
const auditTotal = ref(0)
const auditPage = ref(1)
const auditPageSize = ref(20)
const auditLoading = ref(false)

// ── Helpers ─────────────────────────────────────────────────────────
const formatDateTime = formatBeijingDateTime

// ── Load users ──────────────────────────────────────────────────────
async function loadUsers() {
  loading.value = true
  try {
    const resp = await listUsers({
      page: page.value,
      page_size: pageSize.value,
      search: search.value,
      role: filterRole.value,
      is_active: filterActive.value,
    })
    users.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  loadUsers()
}

function handlePageChange(newPage: number) {
  page.value = newPage
  loadUsers()
}

// ── Create / Edit ───────────────────────────────────────────────────
function openCreateDialog() {
  dialogMode.value = 'create'
  editingUser.value = null
  dialogForm.username = ''
  dialogForm.display_name = ''
  dialogForm.password = ''
  dialogForm.role = 'user'
  dialogForm.is_active = true
  dialogForm.require_password_change = false
  dialogVisible.value = true
}

function openEditDialog(user: AdminUserOut) {
  dialogMode.value = 'edit'
  editingUser.value = user
  dialogForm.username = user.username
  dialogForm.display_name = user.display_name
  dialogForm.password = ''
  dialogForm.role = user.role
  dialogForm.is_active = user.is_active
  dialogForm.require_password_change = user.require_password_change
  dialogVisible.value = true
}

async function submitDialog() {
  dialogLoading.value = true
  try {
    if (dialogMode.value === 'create') {
      if (!dialogForm.username.trim() || !dialogForm.display_name.trim() || !dialogForm.password) {
        ElMessage.error('请填写所有必填字段')
        return
      }
      await createUser({
        username: dialogForm.username.trim(),
        display_name: dialogForm.display_name.trim(),
        password: dialogForm.password,
        role: dialogForm.role,
      })
      ElMessage.success('用户已创建')
    } else if (editingUser.value) {
      await updateUser(editingUser.value.id, {
        display_name: dialogForm.display_name.trim(),
        role: dialogForm.role,
        is_active: dialogForm.is_active,
        require_password_change: dialogForm.require_password_change,
      })
      ElMessage.success('用户已更新')
    }
    dialogVisible.value = false
    await loadUsers()
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

// ── Reset password ──────────────────────────────────────────────────
function openResetDialog(user: AdminUserOut) {
  resetUserId.value = user.id
  resetUserName.value = user.username
  resetNewPassword.value = ''
  resetDialogVisible.value = true
}

async function submitReset() {
  if (resetNewPassword.value.length < 8) {
    ElMessage.error('新密码至少 8 位')
    return
  }
  resetLoading.value = true
  try {
    await resetPassword(resetUserId.value, resetNewPassword.value)
    ElMessage.success('密码已重置，用户下次登录需修改密码')
    resetDialogVisible.value = false
    await loadUsers()
  } finally {
    resetLoading.value = false
  }
}

// ── Audit drawer ────────────────────────────────────────────────────
function openAuditDrawer(user: AdminUserOut) {
  auditTargetId.value = user.id
  auditTargetName.value = user.username
  auditPage.value = 1
  auditDrawerVisible.value = true
  loadAuditLogs()
}

async function loadAuditLogs() {
  auditLoading.value = true
  try {
    const resp = await listAuditLogs({
      page: auditPage.value,
      page_size: auditPageSize.value,
      target_type: 'user',
      target_id: auditTargetId.value,
    })
    auditLogs.value = resp.data.items
    auditTotal.value = resp.data.total
  } finally {
    auditLoading.value = false
  }
}

function handleAuditPageChange(newPage: number) {
  auditPage.value = newPage
  loadAuditLogs()
}

function actionLabel(action: string): string {
  const map: Record<string, string> = {
    'admin.user.create': '创建用户',
    'admin.user.update': '更新用户',
    'admin.user.reset_password': '重置密码',
    'admin.user.disable': '停用用户',
    'user.update_profile': '更新资料',
    'user.upload_avatar': '上传头像',
    'user.delete_avatar': '删除头像',
    'user.change_password': '修改密码',
    'auth.change_password': '修改密码',
    'auth.logout': '登出',
  }
  return map[action] || action
}

onMounted(loadUsers)
</script>

<template>
  <main class="admin-page">
    <header class="page-header">
      <ElButton :icon="Back" text @click="router.push('/')">返回首页</ElButton>
      <h1>用户管理</h1>
    </header>

    <!-- Toolbar -->
    <ElCard class="toolbar-card" shadow="never">
      <div class="toolbar">
        <div class="toolbar-filters">
          <ElInput
            v-model="search"
            class="user-search"
            placeholder="搜索用户名或展示名"
            clearable
            :prefix-icon="Search"
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          />
          <ElSelect
            v-model="filterRole"
            placeholder="角色筛选"
            clearable
            style="width: 140px"
            @change="handleSearch"
          >
            <ElOption label="管理员" value="admin" />
            <ElOption label="普通用户" value="user" />
          </ElSelect>
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
        <div class="toolbar-actions">
          <ElButton :icon="Refresh" @click="loadUsers">刷新</ElButton>
          <ElButton type="primary" :icon="Plus" @click="openCreateDialog">新建用户</ElButton>
        </div>
      </div>
    </ElCard>

    <!-- User Table -->
    <ElCard class="table-card" shadow="never">
      <ElTable v-loading="loading" :data="users" stripe style="width: 100%">
        <ElTableColumn prop="username" label="用户名" min-width="120" />
        <ElTableColumn prop="display_name" label="展示名" min-width="120" />
        <ElTableColumn label="角色" width="100">
          <template #default="{ row }: { row: AdminUserOut }">
            <ElTag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '用户' }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="80">
          <template #default="{ row }: { row: AdminUserOut }">
            <ElTag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '停用' }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="需改密" width="80">
          <template #default="{ row }: { row: AdminUserOut }">
            <ElIcon v-if="row.require_password_change" :size="16" style="color: #e6a23c">
              <Warning />
            </ElIcon>
            <ElIcon v-else :size="16" style="color: #67c23a">
              <CircleCheck />
            </ElIcon>
          </template>
        </ElTableColumn>
        <ElTableColumn label="最后登录" width="140">
          <template #default="{ row }: { row: AdminUserOut }">
            <span class="time-cell">{{ formatDateTime(row.last_login_at) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="创建时间" width="140">
          <template #default="{ row }: { row: AdminUserOut }">
            <span class="time-cell">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="270" fixed="right">
          <template #default="{ row }: { row: AdminUserOut }">
            <div class="action-btns">
              <ElButton :icon="Edit" text size="small" @click="openEditDialog(row)">编辑</ElButton>
              <ElButton :icon="Key" text size="small" @click="openResetDialog(row)"
                >重置密码</ElButton
              >
              <ElButton :icon="View" text size="small" @click="openAuditDrawer(row)">审计</ElButton>
            </div>
          </template>
        </ElTableColumn>
      </ElTable>

      <div class="pagination-wrapper">
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
      :title="dialogMode === 'create' ? '新建用户' : '编辑用户'"
      width="480px"
      :close-on-click-modal="false"
    >
      <ElForm label-position="top">
        <ElFormItem v-if="dialogMode === 'create'" label="用户名" required>
          <ElInput v-model="dialogForm.username" maxlength="128" placeholder="登录用户名" />
        </ElFormItem>
        <ElFormItem label="展示名" required>
          <ElInput v-model="dialogForm.display_name" maxlength="128" placeholder="显示名称" />
        </ElFormItem>
        <ElFormItem v-if="dialogMode === 'create'" label="密码" required>
          <ElInput
            v-model="dialogForm.password"
            type="password"
            show-password
            minlength="8"
            placeholder="至少 8 位"
          />
        </ElFormItem>
        <ElFormItem label="角色">
          <ElSelect v-model="dialogForm.role" style="width: 100%">
            <ElOption label="普通用户" value="user" />
            <ElOption label="管理员" value="admin" />
          </ElSelect>
        </ElFormItem>
        <template v-if="dialogMode === 'edit'">
          <ElFormItem label="启用状态">
            <ElSwitch v-model="dialogForm.is_active" active-text="启用" inactive-text="停用" />
          </ElFormItem>
          <ElFormItem label="下次登录需改密">
            <ElSwitch v-model="dialogForm.require_password_change" />
          </ElFormItem>
        </template>
      </ElForm>
      <template #footer>
        <ElButton @click="dialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="dialogLoading" @click="submitDialog">
          {{ dialogMode === 'create' ? '创建' : '保存' }}
        </ElButton>
      </template>
    </ElDialog>

    <!-- Reset Password Dialog -->
    <ElDialog
      v-model="resetDialogVisible"
      title="重置密码"
      width="420px"
      :close-on-click-modal="false"
    >
      <p class="reset-hint">
        为用户 <strong>{{ resetUserName }}</strong> 设置新密码。重置后用户下次登录需修改密码。
      </p>
      <ElForm label-position="top">
        <ElFormItem label="新密码">
          <ElInput
            v-model="resetNewPassword"
            type="password"
            show-password
            minlength="8"
            placeholder="至少 8 位"
          />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="resetDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="resetLoading" @click="submitReset">确认重置</ElButton>
      </template>
    </ElDialog>

    <!-- Audit Drawer -->
    <ElDrawer v-model="auditDrawerVisible" :title="`审计日志 — ${auditTargetName}`" size="560px">
      <div v-loading="auditLoading">
        <div v-if="auditLogs.length === 0" class="audit-empty">暂无审计记录</div>
        <div v-else class="audit-list">
          <div v-for="log in auditLogs" :key="log.id" class="audit-item">
            <div class="audit-item-header">
              <ElTag size="small" type="info">{{ actionLabel(log.action) }}</ElTag>
              <span class="audit-time">{{ formatDateTime(log.created_at) }}</span>
            </div>
            <div class="audit-meta">
              <span>IP: {{ log.ip_address || '—' }}</span>
            </div>
            <div v-if="Object.keys(log.details).length > 0" class="audit-details">
              <code>{{ JSON.stringify(log.details, null, 2) }}</code>
            </div>
          </div>
        </div>
        <div v-if="auditTotal > auditPageSize" class="pagination-wrapper">
          <ElPagination
            :current-page="auditPage"
            :page-size="auditPageSize"
            :total="auditTotal"
            layout="prev, pager, next"
            @current-change="handleAuditPageChange"
          />
        </div>
      </div>
    </ElDrawer>
  </main>
</template>

<style scoped>
.admin-page {
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

.toolbar-filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.user-search {
  width: 260px;
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

.time-cell {
  color: #8896a4;
  font-size: 13px;
}

.action-btns {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.action-btns :deep(.el-button) {
  margin-left: 0;
  padding-inline: 0;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  padding: 16px 20px;
}

.reset-hint {
  margin: 0 0 16px;
  color: #52616f;
  font-size: 14px;
  line-height: 1.6;
}

.audit-empty {
  padding: 40px 0;
  color: #8896a4;
  text-align: center;
  font-size: 14px;
}

.audit-list {
  display: grid;
  gap: 12px;
}

.audit-item {
  padding: 12px 16px;
  background: #fafbfc;
  border: 1px solid #ebedf0;
  border-radius: 6px;
}

.audit-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.audit-time {
  color: #8896a4;
  font-size: 13px;
}

.audit-meta {
  color: #8896a4;
  font-size: 13px;
  margin-bottom: 8px;
}

.audit-details code {
  display: block;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  color: #52616f;
}

@media (width <= 768px) {
  .admin-page {
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

  .user-search {
    width: 100%;
  }

  .toolbar-actions {
    justify-content: flex-end;
  }

  .action-btns {
    justify-content: flex-start;
  }
}
</style>
