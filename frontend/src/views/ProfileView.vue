<script setup lang="ts">
import { Back, Camera, Delete, Edit, Key, User } from '@element-plus/icons-vue'
import ElAvatar from 'element-plus/es/components/avatar/index.mjs'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElCard from 'element-plus/es/components/card/index.mjs'
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
import 'element-plus/theme-chalk/el-card.css'
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

const avatarSrc = computed(() => {
  if (profile.value?.avatar_url) {
    return profile.value.avatar_url
  }
  return ''
})

const roleLabel = computed(() => {
  if (profile.value?.role === 'admin') return '管理员'
  return '普通用户'
})

const roleType = computed(() => {
  return profile.value?.role === 'admin' ? 'danger' : 'info'
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
    <header class="page-header">
      <ElButton :icon="Back" text @click="router.push('/')">返回首页</ElButton>
      <h1>个人中心</h1>
    </header>

    <div v-loading="loading" class="profile-layout">
      <!-- Avatar Section -->
      <ElCard class="avatar-card" shadow="never">
        <div class="avatar-section">
          <div class="avatar-wrapper">
            <ElAvatar :size="96" :src="avatarSrc" :icon="User" />
            <div class="avatar-actions">
              <ElUpload
                :show-file-list="false"
                :http-request="handleAvatarUpload"
                accept="image/jpeg,image/png,image/webp,image/gif"
              >
                <ElButton
                  :icon="Camera"
                  :loading="avatarUploading"
                  size="small"
                  type="primary"
                  plain
                >
                  上传头像
                </ElButton>
              </ElUpload>
              <ElButton
                v-if="profile?.avatar_url"
                :icon="Delete"
                size="small"
                plain
                @click="handleDeleteAvatar"
              >
                删除
              </ElButton>
            </div>
          </div>
          <p class="avatar-hint">支持 JPG / PNG / WebP / GIF，最大 5 MB</p>
        </div>
      </ElCard>

      <!-- Info Section -->
      <ElCard class="info-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span>基本资料</span>
            <ElButton v-if="!editMode" :icon="Edit" text size="small" @click="startEdit"
              >编辑</ElButton
            >
          </div>
        </template>

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
            <span class="value">{{ formatDate(profile?.last_login_at ?? null) }}</span>
          </div>
          <div class="info-row">
            <span class="label">创建时间</span>
            <span class="value">{{ formatDate(profile?.created_at ?? null) }}</span>
          </div>
        </div>

        <ElForm v-else label-position="top">
          <ElFormItem label="展示名">
            <ElInput v-model="editForm.display_name" maxlength="128" show-word-limit />
          </ElFormItem>
          <div class="edit-actions">
            <ElButton @click="cancelEdit">取消</ElButton>
            <ElButton type="primary" :loading="loading" @click="saveProfile">保存</ElButton>
          </div>
        </ElForm>
      </ElCard>

      <!-- Password Section -->
      <ElCard class="password-card" shadow="never">
        <template #header>
          <span>密码安全</span>
        </template>
        <div class="password-section">
          <div class="password-info">
            <ElIcon :size="20"><Key /></ElIcon>
            <span>定期修改密码可以提高账号安全性</span>
          </div>
          <ElButton type="primary" plain :icon="Key" @click="passwordDialogVisible = true">
            修改密码
          </ElButton>
        </div>
      </ElCard>
    </div>

    <ChangePasswordDialog v-model="passwordDialogVisible" />
  </main>
</template>

<style scoped>
.profile-page {
  min-height: 100vh;
  padding: 32px;
  background: #f6f8fb;
  color: #1f2937;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 720px;
  margin: 0 auto 24px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}

.profile-layout {
  display: grid;
  gap: 16px;
  max-width: 720px;
  margin: 0 auto;
}

.avatar-card :deep(.el-card__body) {
  padding: 24px;
}

.avatar-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.avatar-wrapper {
  display: flex;
  align-items: center;
  gap: 20px;
}

.avatar-actions {
  display: flex;
  gap: 8px;
}

.avatar-hint {
  margin: 0;
  color: #8896a4;
  font-size: 13px;
}

.info-card :deep(.el-card__header) {
  padding: 16px 24px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.info-rows {
  display: grid;
  gap: 0;
}

.info-row {
  display: flex;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid #f0f2f5;
}

.info-row:last-child {
  border-bottom: none;
}

.info-row .label {
  width: 100px;
  flex-shrink: 0;
  color: #8896a4;
  font-size: 14px;
}

.info-row .value {
  flex: 1;
  font-size: 14px;
  word-break: break-all;
}

.edit-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.password-card :deep(.el-card__header) {
  padding: 16px 24px;
  font-weight: 600;
}

.password-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.password-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #52616f;
  font-size: 14px;
}

@media (width <= 640px) {
  .profile-page {
    padding: 20px;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .avatar-wrapper {
    flex-direction: column;
    text-align: center;
  }

  .info-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }

  .info-row .label {
    width: auto;
  }

  .password-section {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
