<script setup lang="ts">
import { Lock } from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElDialog from 'element-plus/es/components/dialog/index.mjs'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index.mjs'
import ElIcon from 'element-plus/es/components/icon/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-dialog.css'
import 'element-plus/theme-chalk/el-form.css'
import 'element-plus/theme-chalk/el-form-item.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-input.css'
import 'element-plus/theme-chalk/el-message.css'
import { reactive, ref } from 'vue'

import { useAuthStore } from '@/stores/auth'

const model = defineModel<boolean>({ required: true })
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

async function submit() {
  if (form.newPassword.length < 8) {
    ElMessage.error('新密码至少 8 位')
    return
  }
  if (form.newPassword !== form.confirmPassword) {
    ElMessage.error('两次输入的新密码不一致')
    return
  }
  loading.value = true
  try {
    await auth.changePassword(form.oldPassword, form.newPassword)
    ElMessage.success('密码已更新')
    form.oldPassword = ''
    form.newPassword = ''
    form.confirmPassword = ''
    model.value = false
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <ElDialog v-model="model" title="修改密码" width="420px" :close-on-click-modal="false">
    <ElForm label-position="top">
      <ElFormItem label="原密码">
        <ElInput
          v-model="form.oldPassword"
          type="password"
          show-password
          autocomplete="current-password"
        >
          <template #prefix>
            <ElIcon><Lock /></ElIcon>
          </template>
        </ElInput>
      </ElFormItem>
      <ElFormItem label="新密码">
        <ElInput
          v-model="form.newPassword"
          type="password"
          show-password
          autocomplete="new-password"
        >
          <template #prefix>
            <ElIcon><Lock /></ElIcon>
          </template>
        </ElInput>
      </ElFormItem>
      <ElFormItem label="确认新密码">
        <ElInput
          v-model="form.confirmPassword"
          type="password"
          show-password
          autocomplete="new-password"
        >
          <template #prefix>
            <ElIcon><Lock /></ElIcon>
          </template>
        </ElInput>
      </ElFormItem>
    </ElForm>
    <template #footer>
      <ElButton @click="model = false">取消</ElButton>
      <ElButton type="primary" :loading="loading" @click="submit">保存</ElButton>
    </template>
  </ElDialog>
</template>
