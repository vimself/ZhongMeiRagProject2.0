<script setup lang="ts">
import { Lock, User } from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index.mjs'
import ElIcon from 'element-plus/es/components/icon/index.mjs'
import ElInput from 'element-plus/es/components/input/index.mjs'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-form.css'
import 'element-plus/theme-chalk/el-form-item.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-input.css'
import 'element-plus/theme-chalk/el-message.css'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.error('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch {
    ElMessage.error('登录失败，请检查用户名或密码')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="brand">
        <p>ZhongMei RAG v2.0</p>
        <h1>工程知识与施工方案智能编制平台</h1>
      </div>
      <ElForm label-position="top" @submit.prevent="submit">
        <ElFormItem label="用户名">
          <ElInput v-model="form.username" autocomplete="username" @keyup.enter="submit">
            <template #prefix>
              <ElIcon><User /></ElIcon>
            </template>
          </ElInput>
        </ElFormItem>
        <ElFormItem label="密码">
          <ElInput
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
            @keyup.enter="submit"
          >
            <template #prefix>
              <ElIcon><Lock /></ElIcon>
            </template>
          </ElInput>
        </ElFormItem>
        <ElButton class="submit" type="primary" :loading="loading" @click="submit">登录</ElButton>
      </ElForm>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 24px;
  background: #eef2f7;
  color: #1f2937;
}

.login-panel {
  width: min(100%, 420px);
  padding: 28px;
  background: #fff;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  box-shadow: 0 16px 40px rgb(31 41 55 / 10%);
}

.brand {
  margin-bottom: 22px;
}

.brand p {
  margin: 0 0 8px;
  color: #52616f;
  font-size: 14px;
}

.brand h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.35;
}

.submit {
  width: 100%;
}
</style>
