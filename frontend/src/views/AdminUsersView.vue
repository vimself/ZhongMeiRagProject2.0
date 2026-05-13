<script setup lang="ts">
import {
  ArrowLeft,
  CircleCheck,
  CloseBold,
  Edit,
  Key,
  Plus,
  Refresh,
  Search,
  View,
  Warning,
} from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
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
import { computed, onMounted, reactive, ref } from 'vue'
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

const activeCount = computed(() => users.value.filter((u) => u.is_active).length)
const adminCount = computed(() => users.value.filter((u) => u.role === 'admin').length)

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
      if (!dialogForm.display_name.trim()) {
        ElMessage.error('请填写展示名')
        return
      }
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
  <main class="shell">
    <!-- ── Header ──────────────────────────────────────────────── -->
    <section class="page-header">
      <div class="header-left">
        <span class="brand-mark">ZM</span>
        <div>
          <p class="eyebrow">Administration</p>
          <h1>用户管理</h1>
        </div>
      </div>
      <ElButton :icon="ArrowLeft" text @click="router.push('/')">返回首页</ElButton>
    </section>

    <!-- ── Stats strip ─────────────────────────────────────────── -->
    <section class="stats-strip">
      <div class="stat-pill">
        <span class="stat-label">总用户</span>
        <span class="stat-value">{{ total }}</span>
      </div>
      <div class="stat-pill">
        <span class="stat-label">当启用</span>
        <span class="stat-value accent">{{ activeCount }}</span>
      </div>
      <div class="stat-pill">
        <span class="stat-label">当前管理员</span>
        <span class="stat-value">{{ adminCount }}</span>
      </div>
    </section>

    <!-- ── Toolbar ─────────────────────────────────────────────── -->
    <section class="toolbar-panel">
      <div class="toolbar">
        <div class="toolbar-filters">
          <ElInput
            v-model="search"
            class="search-input"
            placeholder="搜索用户名或展示名…"
            clearable
            :prefix-icon="Search"
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          />
          <ElSelect
            v-model="filterRole"
            placeholder="角色"
            clearable
            class="filter-select"
            @change="handleSearch"
          >
            <ElOption label="管理员" value="admin" />
            <ElOption label="普通用户" value="user" />
          </ElSelect>
          <ElSelect
            v-model="filterActive"
            placeholder="状态"
            clearable
            class="filter-select"
            @change="handleSearch"
          >
            <ElOption label="启用" :value="true" />
            <ElOption label="停用" :value="false" />
          </ElSelect>
        </div>
        <div class="toolbar-actions">
          <ElButton :icon="Refresh" text @click="loadUsers">刷新</ElButton>
          <ElButton type="primary" :icon="Plus" @click="openCreateDialog">新建用户</ElButton>
        </div>
      </div>
    </section>

    <!-- ── User Table ──────────────────────────────────────────── -->
    <section class="table-panel">
      <ElTable
        v-loading="loading"
        :data="users"
        :row-class-name="() => 'user-row'"
        style="width: 100%"
      >
        <ElTableColumn prop="username" label="用户名" min-width="140">
          <template #default="{ row }: { row: AdminUserOut }">
            <div class="user-cell">
              <span class="user-avatar">{{ row.username.charAt(0).toUpperCase() }}</span>
              <div class="user-info">
                <span class="user-name">{{ row.username }}</span>
                <span class="user-display">{{ row.display_name }}</span>
              </div>
            </div>
          </template>
        </ElTableColumn>
        <ElTableColumn label="角色" width="110" align="center">
          <template #default="{ row }: { row: AdminUserOut }">
            <ElTag
              :type="row.role === 'admin' ? 'danger' : 'info'"
              size="small"
              effect="plain"
              class="role-tag"
            >
              {{ row.role === 'admin' ? '管理员' : '用户' }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="90" align="center">
          <template #default="{ row }: { row: AdminUserOut }">
            <span class="status-indicator" :class="row.is_active ? 'active' : 'inactive'">
              <span class="status-dot" />
              {{ row.is_active ? '启用' : '停用' }}
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="密码状态" width="100" align="center">
          <template #default="{ row }: { row: AdminUserOut }">
            <span v-if="row.require_password_change" class="pwd-warn">
              <ElIcon :size="14"><Warning /></ElIcon>
              需改密
            </span>
            <span v-else class="pwd-ok">
              <ElIcon :size="14"><CircleCheck /></ElIcon>
              正常
            </span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="最后登录" width="160">
          <template #default="{ row }: { row: AdminUserOut }">
            <span class="time-cell">{{ formatDateTime(row.last_login_at) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="创建时间" width="160">
          <template #default="{ row }: { row: AdminUserOut }">
            <span class="time-cell">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="240" fixed="right" align="right">
          <template #default="{ row }: { row: AdminUserOut }">
            <div class="action-btns">
              <ElButton :icon="Edit" text size="small" @click="openEditDialog(row)">
                编辑
              </ElButton>
              <ElButton :icon="Key" text size="small" @click="openResetDialog(row)">
                改密
              </ElButton>
              <ElButton :icon="View" text size="small" @click="openAuditDrawer(row)">
                审计
              </ElButton>
            </div>
          </template>
        </ElTableColumn>

        <!-- Empty state -->
        <template #empty>
          <div class="empty-state">
            <ElIcon :size="48" class="empty-icon"><Search /></ElIcon>
            <p class="empty-title">暂无用户数据</p>
            <p class="empty-desc">当前筛选条件下没有匹配的用户，尝试调整搜索条件或创建新用户。</p>
          </div>
        </template>
      </ElTable>

      <div class="pagination-bar">
        <span class="pagination-info">共 {{ total }} 位用户</span>
        <ElPagination
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          @current-change="handlePageChange"
        />
      </div>
    </section>

    <!-- ── Create / Edit Dialog ────────────────────────────────── -->
    <ElDialog
      v-model="dialogVisible"
      width="520px"
      :close-on-click-modal="false"
      :show-close="false"
      class="premium-dialog user-dialog"
    >
      <!-- Visual header -->
      <div class="dialog-hero">
        <div>
          <h3 class="dialog-hero-title">
            {{ dialogMode === 'create' ? '新建用户' : '编辑用户' }}
          </h3>
          <p class="dialog-hero-desc">
            {{
              dialogMode === 'create'
                ? '填写以下信息创建一个新的系统用户'
                : `修改 ${editingUser?.username ?? ''} 的账户信息`
            }}
          </p>
        </div>
        <button class="dialog-close-btn" @click="dialogVisible = false">
          <ElIcon :size="18"><CloseBold /></ElIcon>
        </button>
      </div>

      <ElForm label-position="top" class="dialog-form">
        <!-- Section: account info -->
        <div class="form-section">
          <p class="form-section-label">账户信息</p>
          <ElFormItem v-if="dialogMode === 'create'" label="用户名" required>
            <ElInput
              v-model="dialogForm.username"
              maxlength="128"
              placeholder="登录用户名，创建后不可修改"
            />
          </ElFormItem>
          <ElFormItem label="展示名" required>
            <ElInput v-model="dialogForm.display_name" maxlength="128" placeholder="用户显示名称" />
          </ElFormItem>
          <ElFormItem v-if="dialogMode === 'create'" label="密码" required>
            <ElInput
              v-model="dialogForm.password"
              type="password"
              show-password
              minlength="8"
              placeholder="至少 8 位，建议包含字母和数字"
            />
            <p class="password-hint">密码不少于 8 位，创建后用户可自行修改</p>
          </ElFormItem>
        </div>

        <!-- Section: permissions -->
        <div class="form-section">
          <p class="form-section-label">权限设置</p>
          <ElFormItem label="用户角色">
            <ElSelect v-model="dialogForm.role" style="width: 100%">
              <ElOption label="普通用户" value="user" />
              <ElOption label="管理员" value="admin" />
            </ElSelect>
            <p class="role-hint">
              {{
                dialogForm.role === 'admin'
                  ? '管理员可管理所有用户和知识库'
                  : '普通用户可使用知识库和 RAG 问答'
              }}
            </p>
          </ElFormItem>
        </div>

        <!-- Section: status (edit mode only) -->
        <template v-if="dialogMode === 'edit'">
          <div class="form-section">
            <p class="form-section-label">账户状态</p>
            <div class="switch-group">
              <div class="switch-row">
                <div class="switch-label">
                  <span class="switch-label-text">启用状态</span>
                  <span class="switch-label-desc">停用后用户将无法登录系统</span>
                </div>
                <ElSwitch v-model="dialogForm.is_active" />
              </div>
              <div class="switch-row">
                <div class="switch-label">
                  <span class="switch-label-text">强制修改密码</span>
                  <span class="switch-label-desc">用户下次登录时需设置新密码</span>
                </div>
                <ElSwitch v-model="dialogForm.require_password_change" />
              </div>
            </div>
          </div>
        </template>
      </ElForm>

      <template #footer>
        <div class="dialog-footer">
          <ElButton @click="dialogVisible = false">取消</ElButton>
          <ElButton type="primary" :loading="dialogLoading" @click="submitDialog">
            {{ dialogMode === 'create' ? '创建用户' : '保存更改' }}
          </ElButton>
        </div>
      </template>
    </ElDialog>

    <!-- ── Reset Password Dialog ───────────────────────────────── -->
    <ElDialog
      v-model="resetDialogVisible"
      width="440px"
      :close-on-click-modal="false"
      :show-close="false"
      class="premium-dialog"
    >
      <div class="dialog-hero">
        <div>
          <h3 class="dialog-hero-title">重置密码</h3>
          <p class="dialog-hero-desc">为用户 {{ resetUserName }} 设置新密码</p>
        </div>
        <button class="dialog-close-btn" @click="resetDialogVisible = false">
          <ElIcon :size="18"><CloseBold /></ElIcon>
        </button>
      </div>
      <div class="dialog-form">
        <div class="reset-hint">
          <ElIcon :size="16" class="reset-hint-icon"><Warning /></ElIcon>
          <p>重置后用户下次登录时需强制修改密码。</p>
        </div>
        <ElForm label-position="top">
          <ElFormItem label="新密码" required>
            <ElInput
              v-model="resetNewPassword"
              type="password"
              show-password
              minlength="8"
              placeholder="至少 8 位，建议包含字母和数字"
            />
          </ElFormItem>
        </ElForm>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <ElButton @click="resetDialogVisible = false">取消</ElButton>
          <ElButton type="primary" :loading="resetLoading" @click="submitReset">
            确认重置
          </ElButton>
        </div>
      </template>
    </ElDialog>

    <!-- ── Audit Drawer ────────────────────────────────────────── -->
    <ElDrawer v-model="auditDrawerVisible" :title="`审计日志`" size="560px" class="premium-drawer">
      <template #header>
        <div class="drawer-header">
          <div>
            <h3 class="drawer-title">审计日志</h3>
            <p class="drawer-subtitle">用户：{{ auditTargetName }}</p>
          </div>
        </div>
      </template>
      <div v-loading="auditLoading" class="audit-container">
        <div v-if="auditLogs.length === 0" class="empty-state">
          <ElIcon :size="48" class="empty-icon"><View /></ElIcon>
          <p class="empty-title">暂无审计记录</p>
          <p class="empty-desc">该用户暂无操作记录。</p>
        </div>
        <div v-else class="audit-list">
          <div v-for="log in auditLogs" :key="log.id" class="audit-item">
            <div class="audit-item-top">
              <ElTag size="small" effect="plain" class="audit-action-tag">
                {{ actionLabel(log.action) }}
              </ElTag>
              <span class="audit-time">{{ formatDateTime(log.created_at) }}</span>
            </div>
            <div class="audit-meta">
              <span class="audit-ip">IP: {{ log.ip_address || '—' }}</span>
            </div>
            <div v-if="Object.keys(log.details).length > 0" class="audit-details">
              <code>{{ JSON.stringify(log.details, null, 2) }}</code>
            </div>
          </div>
        </div>
        <div v-if="auditTotal > auditPageSize" class="pagination-bar">
          <span class="pagination-info">共 {{ auditTotal }} 条记录</span>
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
/* ── Design tokens ─────────────────────────────────────────────── */
:root {
  --surface-0: #fff;
  --surface-1: #f8fafb;
  --surface-2: #f1f4f7;
  --border-light: #e5e7eb;
  --border-subtle: #eef0f2;
  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-muted: #8896a4;
  --accent: #0f766e;
  --accent-light: #ecfdf5;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
}

/* ── Shell ──────────────────────────────────────────────────────── */
.shell {
  min-height: 100vh;
  padding: 28px 32px 56px;
  background:
    linear-gradient(180deg, rgb(248 251 251 / 92%) 0%, rgb(244 247 249 / 100%) 100%), #f7fafc;
  color: var(--text-primary);
}

/* ── Page header ────────────────────────────────────────────────── */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: min(1200px, 100%);
  margin: 0 auto 24px;
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
  background: #0f766e;
  border-radius: 8px;
  box-shadow: 0 14px 26px rgb(15 118 110 / 18%);
}

.eyebrow {
  margin: 0 0 2px;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.page-header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.3;
}

/* ── Stats strip ────────────────────────────────────────────────── */
.stats-strip {
  display: flex;
  gap: 12px;
  width: min(1200px, 100%);
  margin: 0 auto 20px;
}

.stat-pill {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 16px 24px;
  background: linear-gradient(145deg, rgb(15 118 110 / 5%) 0%, rgb(16 185 129 / 3%) 100%);
  border: none;
  border-radius: var(--radius-lg);
  box-shadow:
    0 1px 2px rgb(15 118 110 / 4%),
    inset 0 1px 0 rgb(255 255 255 / 60%);
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #0f766e;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}

.stat-value.accent {
  color: #059669;
}

.stat-label {
  font-size: 13px;
  font-weight: 500;
  color: #6b7280;
}

/* ── Toolbar ────────────────────────────────────────────────────── */
.toolbar-panel {
  width: min(1200px, 100%);
  margin: 0 auto 16px;
  padding: 14px 20px;
  background: var(--surface-0);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
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
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.search-input {
  width: 280px;
}

.search-input :deep(.el-input__wrapper) {
  border-radius: var(--radius-sm);
  box-shadow: 0 0 0 1px var(--border-light);
  transition: box-shadow 0.2s ease;
}

.search-input :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c0c4cc;
}

.search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgb(15 118 110 / 20%);
}

.filter-select {
  width: 130px;
}

.filter-select :deep(.el-input__wrapper) {
  border-radius: var(--radius-sm);
}

.toolbar-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* ── Table panel ────────────────────────────────────────────────── */
.table-panel {
  width: min(1200px, 100%);
  margin: 0 auto;
  background: var(--surface-0);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.table-panel :deep(.el-table) {
  --el-table-border-color: var(--border-subtle);
  --el-table-header-bg-color: var(--surface-1);
  --el-table-row-hover-bg-color: #f8fafb;

  font-size: 14px;
}

.table-panel :deep(.el-table th.el-table__cell) {
  font-weight: 600;
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: var(--surface-1);
}

.table-panel :deep(.el-table td.el-table__cell) {
  padding: 14px 0;
}

.table-panel :deep(.el-table--enable-row-hover .el-table__body tr:hover > td) {
  background: #f8fafb;
}

/* User cell */
.user-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-avatar {
  display: inline-grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.user-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.user-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}

.user-display {
  font-size: 12px;
  color: var(--text-muted);
}

/* Role tag */
.role-tag {
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
}

/* Status indicator */
.status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-indicator.active {
  color: #059669;
}

.status-indicator.active .status-dot {
  background: #10b981;
  box-shadow: 0 0 0 3px rgb(16 185 129 / 15%);
}

.status-indicator.inactive {
  color: var(--text-muted);
}

.status-indicator.inactive .status-dot {
  background: #d1d5db;
}

/* Password status */
.pwd-warn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #d97706;
  font-size: 13px;
  font-weight: 500;
}

.pwd-ok {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #059669;
  font-size: 13px;
}

/* Time cells */
.time-cell {
  color: var(--text-muted);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

/* Action buttons */
.action-btns {
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: flex-end;
}

.action-btns :deep(.el-button) {
  margin-left: 0;
  padding-inline: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  transition:
    color 0.15s ease,
    background 0.15s ease;
}

.action-btns :deep(.el-button:hover) {
  color: var(--accent);
  background: var(--accent-light);
}

/* ── Pagination ─────────────────────────────────────────────────── */
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-top: 1px solid var(--border-subtle);
}

.pagination-info {
  font-size: 13px;
  color: var(--text-muted);
}

.pagination-bar :deep(.el-pagination) {
  --el-pagination-bg-color: transparent;
  --el-pagination-hover-color: var(--accent);
}

/* ── Teal primary button ──────────────────────────────────────── */
:deep(.el-button--primary) {
  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #115e59;
  --el-button-hover-border-color: #115e59;
  --el-button-active-bg-color: #134e4a;
  --el-button-active-border-color: #134e4a;
}

/* ── Empty state ────────────────────────────────────────────────── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 48px 24px;
  text-align: center;
}

.empty-icon {
  color: #d1d5db;
  margin-bottom: 16px;
}

.empty-title {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.empty-desc {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
  max-width: 320px;
  line-height: 1.6;
}

/* ── Dialogs ────────────────────────────────────────────────────── */
.premium-dialog :deep(.el-dialog) {
  box-shadow: 0 24px 48px rgb(0 0 0 / 8%);
}

.premium-dialog :deep(.el-dialog__header) {
  display: none;
}

.premium-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.premium-dialog :deep(.el-dialog__footer) {
  padding: 0 28px 24px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 20px;
}

/* Dialog hero header */
.dialog-hero {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 28px 28px 24px;
  background: linear-gradient(180deg, rgb(15 118 110 / 4%) 0%, transparent 100%);
  border-bottom: 1px solid var(--border-subtle);
  position: relative;
  border-radius: 15px 15px 0 0;
}

.dialog-hero-icon {
  display: inline-grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 12px;
  background: #0f766e;
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 8px 20px rgb(15 118 110 / 20%);
}

.dialog-hero-title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.3;
}

.dialog-hero-desc {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.5;
}

.dialog-close-btn {
  position: absolute;
  top: 20px;
  right: 20px;
  display: inline-grid;
  place-items: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.dialog-close-btn:hover {
  background: rgb(0 0 0 / 5%);
  color: var(--text-primary);
}

/* Form sections */
.dialog-form {
  padding: 24px 28px 4px;
}

.form-section {
  margin-bottom: 20px;
}

.form-section:last-child {
  margin-bottom: 0;
}

.form-section-label {
  margin: 0 0 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.dialog-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.dialog-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

.dialog-form :deep(.el-form-item__label) {
  font-weight: 600;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.4;
}

.dialog-form :deep(.el-input__wrapper) {
  border-radius: var(--radius-sm);
  transition: box-shadow 0.2s ease;
}

.dialog-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c0c4cc;
}

.dialog-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgb(15 118 110 / 20%);
}

.dialog-form :deep(.el-select) {
  width: 100%;
}

.password-hint,
.role-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.role-hint {
  padding: 8px 12px;
  background: var(--surface-1);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
}

/* Switch group */
.switch-group {
  display: flex;
  flex-direction: column;
  gap: 0;
  background: var(--surface-1);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  overflow: hidden;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
}

.switch-row + .switch-row {
  border-top: 1px solid var(--border-subtle);
}

.switch-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.switch-label-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.switch-label-desc {
  font-size: 12px;
  color: var(--text-muted);
}

/* Dialog footer */
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.dialog-footer :deep(.el-button) {
  min-width: 96px;
  font-weight: 500;
}

/* Reset hint */
.reset-hint {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  background: #fffbeb;
  border: 1px solid #fef3c7;
  border-radius: var(--radius-sm);
  margin-bottom: 20px;
}

.reset-hint-icon {
  color: #d97706;
  flex-shrink: 0;
  margin-top: 1px;
}

.reset-hint p {
  margin: 0;
  font-size: 13px;
  color: #92400e;
  line-height: 1.5;
}

/* ── Audit drawer ───────────────────────────────────────────────── */
.premium-drawer :deep(.el-drawer__header) {
  padding: 20px 24px;
  margin-bottom: 0;
  border-bottom: 1px solid var(--border-subtle);
}

.premium-drawer :deep(.el-drawer__body) {
  padding: 20px 24px;
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.drawer-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
}

.drawer-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

.audit-container {
  min-height: 200px;
}

.audit-list {
  display: grid;
  gap: 10px;
}

.audit-item {
  padding: 14px 16px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  transition: border-color 0.15s ease;
}

.audit-item:hover {
  border-color: var(--border-light);
}

.audit-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.audit-action-tag {
  border-radius: 20px;
  font-size: 12px;
}

.audit-time {
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.audit-meta {
  margin-bottom: 8px;
}

.audit-ip {
  color: var(--text-muted);
  font-size: 12px;
  font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace;
}

.audit-details code {
  display: block;
  padding: 10px 12px;
  background: var(--surface-0);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-secondary);
  font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace;
  line-height: 1.6;
}

/* ── Responsive ─────────────────────────────────────────────────── */
@media (width <= 768px) {
  .shell {
    padding: 20px 16px 40px;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .stats-strip {
    flex-direction: column;
    gap: 8px;
  }

  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-filters {
    flex-direction: column;
  }

  .search-input {
    width: 100%;
  }

  .filter-select {
    width: 100%;
  }

  .toolbar-actions {
    justify-content: flex-end;
  }

  .table-panel :deep(.el-table) {
    font-size: 13px;
  }

  .pagination-bar {
    flex-direction: column;
    gap: 12px;
    align-items: center;
  }

  .switch-group {
    flex-direction: column;
    gap: 12px;
  }
}

@media (width <= 480px) {
  .page-header h1 {
    font-size: 19px;
  }

  .stat-pill {
    padding: 10px 14px;
  }

  .stat-value {
    font-size: 18px;
  }
}
</style>

<style>
/* Unscoped – override Element Plus dialog root border-radius */
.premium-dialog .el-dialog,
.premium-dialog.el-dialog__wrapper .el-dialog {
  --el-dialog-border-radius: 15px;

  border-radius: 15px !important;
  overflow: hidden;
}
</style>
