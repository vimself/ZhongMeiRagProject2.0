<script setup lang="ts">
import { Back, Camera, Delete, Edit, Key } from '@element-plus/icons-vue'
import ElAvatar from 'element-plus/es/components/avatar/index.mjs'
import ElButton from 'element-plus/es/components/button/index.mjs'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index.mjs'
import ElIcon from 'element-plus/es/components/icon/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import { ElMessageBox } from 'element-plus/es/components/message-box/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import ElUpload from 'element-plus/es/components/upload/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-avatar.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-form.css'
import 'element-plus/theme-chalk/el-form-item.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-input.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'
import 'element-plus/theme-chalk/el-tag.css'
import 'element-plus/theme-chalk/el-upload.css'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { UserProfileDetail } from '@/api/types'
import { deleteAvatar, getProfile, updateProfile, uploadAvatar } from '@/api/user'
import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { formatBeijingFullDateTime } from '@/utils/time'

const auth = useAuthStore()
const router = useRouter()
const profile = ref<UserProfileDetail | null>(null)
const loading = ref(false)
const editMode = ref(false)
const passwordDialogVisible = ref(false)
const avatarUploading = ref(false)
const editForm = reactive({ display_name: '' })

const avatarSrc = computed(() => profile.value?.avatar_url || '')

const roleLabel = computed(() => (profile.value?.role === 'admin' ? '管理员' : '普通用户'))

const roleType = computed(() => (profile.value?.role === 'admin' ? 'danger' : 'info'))

const initials = computed(() => {
  const name = profile.value?.display_name || profile.value?.username || ''
  return name.slice(0, 1).toUpperCase()
})

async function loadProfile() {
  loading.value = true
  try {
    const resp = await getProfile()
    profile.value = resp.data
    editForm.display_name = resp.data.display_name
  } finally {
    loading.value = false
  }
}

function startEdit() {
  editMode.value = true
  editForm.display_name = profile.value?.display_name || ''
}

function cancelEdit() {
  editMode.value = false
  editForm.display_name = profile.value?.display_name || ''
}

async function saveProfile() {
  if (!editForm.display_name.trim()) {
    ElMessage.error('展示名不能为空')
    return
  }
  loading.value = true
  try {
    const resp = await updateProfile(editForm.display_name.trim())
    profile.value = resp.data
    editMode.value = false
    await auth.refreshProfile()
    ElMessage.success('资料已更新')
  } finally {
    loading.value = false
  }
}

async function handleAvatarUpload(options: { file: File }) {
  avatarUploading.value = true
  try {
    const resp = await uploadAvatar(options.file)
    profile.value = resp.data
    await auth.refreshProfile()
    ElMessage.success('头像已上传')
  } catch {
    ElMessage.error('头像上传失败，请检查文件类型和大小')
  } finally {
    avatarUploading.value = false
  }
}

async function handleDeleteAvatar() {
  try {
    await ElMessageBox.confirm('确定要删除当前头像吗？', '删除头像', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  loading.value = true
  try {
    const resp = await deleteAvatar()
    profile.value = resp.data
    await auth.refreshProfile()
    ElMessage.success('头像已删除')
  } finally {
    loading.value = false
  }
}

const formatDate = formatBeijingFullDateTime

onMounted(loadProfile)
</script>

<template>
  <main class="profile-page">
    <!-- Back navigation -->
    <div class="nav-bar">
      <ElButton :icon="Back" text class="back-btn" @click="router.push('/')"> 返回首页 </ElButton>
    </div>

    <div v-loading="loading" class="profile-container">
      <!-- Hero Card: Avatar + Identity -->
      <section class="hero-card">
        <div class="hero-bg"></div>
        <div class="hero-content">
          <div class="avatar-block">
            <div class="avatar-ring">
              <ElAvatar v-if="avatarSrc" :size="108" :src="avatarSrc" class="avatar-img" />
              <div v-else class="avatar-fallback">
                <span>{{ initials }}</span>
              </div>
              <ElUpload
                class="avatar-upload-trigger"
                :show-file-list="false"
                :http-request="handleAvatarUpload"
                accept="image/jpeg,image/png,image/webp,image/gif"
              >
                <div class="avatar-overlay" :class="{ uploading: avatarUploading }">
                  <ElIcon :size="18"><Camera /></ElIcon>
                  <span>{{ avatarUploading ? '上传中...' : '更换头像' }}</span>
                </div>
              </ElUpload>
            </div>
            <div class="avatar-actions-row">
              <ElUpload
                :show-file-list="false"
                :http-request="handleAvatarUpload"
                accept="image/jpeg,image/png,image/webp,image/gif"
              >
                <ElButton
                  :icon="Camera"
                  :loading="avatarUploading"
                  size="small"
                  class="btn-primary-teal"
                >
                  上传头像
                </ElButton>
              </ElUpload>
              <ElButton
                v-if="profile?.avatar_url"
                :icon="Delete"
                size="small"
                class="btn-ghost"
                @click="handleDeleteAvatar"
              >
                删除
              </ElButton>
            </div>
            <p class="avatar-hint">支持 JPG / PNG / WebP / GIF，最大 5 MB</p>
          </div>

          <div class="hero-identity">
            <h1 class="profile-name">{{ profile?.display_name || profile?.username }}</h1>
            <p class="profile-username">@{{ profile?.username }}</p>
            <div class="hero-tags">
              <ElTag :type="roleType" size="small" class="role-tag">{{ roleLabel }}</ElTag>
              <ElTag
                v-if="profile?.require_password_change"
                type="warning"
                size="small"
                class="status-tag"
              >
                需要修改密码
              </ElTag>
              <ElTag v-else type="success" size="small" class="status-tag"> 账号正常 </ElTag>
            </div>
          </div>
        </div>
      </section>

      <!-- Info Card -->
      <section class="info-card">
        <div class="card-head">
          <span class="kicker">ACCOUNT DETAILS</span>
          <div class="card-head-row">
            <h2>基本资料</h2>
            <ElButton v-if="!editMode" :icon="Edit" text class="edit-btn" @click="startEdit">
              编辑
            </ElButton>
          </div>
        </div>

        <div v-if="!editMode" class="info-rows">
          <div class="info-row">
            <span class="label">用户名</span>
            <span class="value">{{ profile?.username }}</span>
          </div>
          <div class="info-row">
            <span class="label">展示名</span>
            <span class="value">{{ profile?.display_name }}</span>
          </div>
          <div class="info-row">
            <span class="label">角色</span>
            <span class="value">
              <ElTag :type="roleType" size="small">{{ roleLabel }}</ElTag>
            </span>
          </div>
          <div class="info-row">
            <span class="label">密码状态</span>
            <span class="value">
              <ElTag v-if="profile?.require_password_change" type="warning" size="small">
                需要修改密码
              </ElTag>
              <ElTag v-else type="success" size="small">正常</ElTag>
            </span>
          </div>
          <div class="info-row">
            <span class="label">最后登录</span>
            <span class="value text-muted">{{ formatDate(profile?.last_login_at ?? null) }}</span>
          </div>
          <div class="info-row">
            <span class="label">创建时间</span>
            <span class="value text-muted">{{ formatDate(profile?.created_at ?? null) }}</span>
          </div>
        </div>

        <ElForm v-else label-position="top" class="edit-form">
          <ElFormItem label="展示名">
            <ElInput v-model="editForm.display_name" maxlength="128" show-word-limit />
          </ElFormItem>
          <div class="edit-actions">
            <ElButton class="btn-ghost" @click="cancelEdit">取消</ElButton>
            <ElButton class="btn-primary-teal" :loading="loading" @click="saveProfile">
              保存修改
            </ElButton>
          </div>
        </ElForm>
      </section>

      <!-- Security Card -->
      <section class="security-card">
        <div class="card-head">
          <span class="kicker">SECURITY</span>
          <h2>密码安全</h2>
        </div>
        <div class="security-body">
          <div class="security-icon-box">
            <ElIcon :size="22"><Key /></ElIcon>
          </div>
          <div class="security-text">
            <p class="security-title">修改密码</p>
            <p class="security-desc">定期修改密码可以提高账号安全性，建议每 90 天更换一次</p>
          </div>
          <ElButton class="btn-primary-teal" :icon="Key" @click="passwordDialogVisible = true">
            修改密码
          </ElButton>
        </div>
      </section>
    </div>

    <ChangePasswordDialog v-model="passwordDialogVisible" />
  </main>
</template>

<style scoped>
/* ── Page ── */
.profile-page {
  min-height: 100vh;
  padding: 24px 32px 64px;
  background: linear-gradient(180deg, rgb(248 251 251) 0%, #f4f7f9 100%);
  color: #0f172a;
}

.nav-bar {
  max-width: 780px;
  margin: 0 auto 20px;
}

.back-btn {
  color: #64748b;
  font-size: 14px;
  transition: color 0.2s;
}

.back-btn:hover {
  color: #0f766e;
}

.profile-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 780px;
  margin: 0 auto;
}

/* ── Hero Card ── */
.hero-card {
  position: relative;
  background: linear-gradient(135deg, #f0fdfa 0%, #e6f7f5 40%, #f0f9ff 100%);
  border: 1px solid #dbe4ef;
  border-radius: 8px;
  overflow: hidden;
}

.hero-bg {
  display: none;
}

.hero-content {
  display: flex;
  align-items: flex-end;
  gap: 28px;
  padding: 28px 32px;
}

.avatar-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.avatar-ring {
  position: relative;
  width: 108px;
  height: 108px;
  border-radius: 50%;
  border: 3px solid #e6f7f5;
  box-shadow: 0 4px 16px rgb(15 23 42 / 8%);
  overflow: hidden;
  cursor: pointer;
}

.avatar-img {
  display: block;
}

.avatar-fallback {
  width: 108px;
  height: 108px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f766e, #0d9488);
  color: #fff;
  font-size: 40px;
  font-weight: 700;
  letter-spacing: -1px;
}

.avatar-upload-trigger {
  display: block;
}

.avatar-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background: rgb(15 23 42 / 55%);
  color: #fff;
  font-size: 12px;
  opacity: 0;
  transition: opacity 0.2s;
  border-radius: 50%;
  backdrop-filter: blur(2px);
}

.avatar-overlay.uploading {
  opacity: 1;
}

.avatar-ring:hover .avatar-overlay {
  opacity: 1;
}

.avatar-actions-row {
  display: flex;
  gap: 8px;
}

.avatar-hint {
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
  text-align: center;
}

.hero-identity {
  flex: 1;
  padding-bottom: 4px;
}

.profile-name {
  margin: 0;
  font-size: clamp(22px, 3vw, 28px);
  font-weight: 800;
  color: #0f172a;
  line-height: 1.2;
}

.profile-username {
  margin: 4px 0 12px;
  color: #64748b;
  font-size: 14px;
}

.hero-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.role-tag,
.status-tag {
  --el-tag-border-color: transparent;
}

/* ── Shared Card Styles ── */
.info-card,
.security-card {
  background: #fff;
  border: 1px solid #dbe4ef;
  border-radius: 8px;
  padding: 28px 32px;
  transition:
    box-shadow 0.25s,
    transform 0.25s;
}

.info-card:hover,
.security-card:hover {
  box-shadow: 0 12px 32px rgb(15 23 42 / 6%);
  transform: translateY(-1px);
}

.card-head {
  margin-bottom: 24px;
}

.kicker {
  display: block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #0f766e;
  margin-bottom: 6px;
}

.card-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-head h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.edit-btn {
  color: #0f766e;
  font-size: 13px;
  font-weight: 500;
  transition: color 0.2s;
}

.edit-btn:hover {
  color: #115e59;
}

/* ── Info Rows ── */
.info-rows {
  display: flex;
  flex-direction: column;
}

.info-row {
  display: flex;
  align-items: center;
  padding: 14px 0;
  border-bottom: 1px solid #f1f5f9;
}

.info-row:last-child {
  border-bottom: none;
}

.info-row .label {
  width: 100px;
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 500;
  color: #94a3b8;
}

.info-row .value {
  flex: 1;
  font-size: 14px;
  color: #0f172a;
  word-break: break-all;
}

.text-muted {
  color: #64748b;
}

/* ── Edit Form ── */
.edit-form {
  padding-top: 4px;
}

.edit-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 8px;
}

/* ── Security Card ── */
.security-body {
  display: flex;
  align-items: center;
  gap: 20px;
}

.security-icon-box {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  background: rgb(15 118 110 / 8%);
  color: #0f766e;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.security-text {
  flex: 1;
}

.security-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.security-desc {
  margin: 4px 0 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

/* ── Shared Button Styles ── */
.btn-primary-teal {
  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #115e59;
  --el-button-hover-border-color: #115e59;
  --el-button-active-bg-color: #134e4a;
  --el-button-active-border-color: #134e4a;
  --el-button-text-color: #fff;

  border-radius: 8px;
  font-weight: 500;
}

.btn-ghost {
  --el-button-bg-color: #fff;
  --el-button-border-color: #dbe4ef;
  --el-button-text-color: #475569;
  --el-button-hover-bg-color: #f8fafc;
  --el-button-hover-border-color: #cbd5e1;
  --el-button-hover-text-color: #0f172a;

  border-radius: 8px;
  font-weight: 500;
}

/* ── Responsive ── */
@media (width <= 640px) {
  .profile-page {
    padding: 16px 16px 48px;
  }

  .hero-content {
    flex-direction: column;
    align-items: center;
    text-align: center;
    padding: 0 20px 24px;
    gap: 16px;
  }

  .hero-identity {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .hero-tags {
    justify-content: center;
  }

  .info-card,
  .security-card {
    padding: 20px;
  }

  .info-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }

  .info-row .label {
    width: auto;
    font-size: 12px;
  }

  .security-body {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }
}

@media (width <= 480px) {
  .avatar-actions-row {
    flex-direction: column;
    width: 100%;
  }

  .avatar-actions-row .el-button {
    width: 100%;
  }
}
</style>
