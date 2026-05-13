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
    <!-- Left: Brand & Features -->
    <section class="brand-panel">
      <div class="brand-content">
        <div class="brand-header">
          <span class="brand-mark">ZM</span>
          <span class="brand-name">ZhongMei RAG v2.0</span>
        </div>

        <h1 class="brand-title">工程知识与施工方案<br />智能编制平台</h1>
        <p class="brand-subtitle">
          面向工程知识沉淀、施工资料检索和可追溯问答的统一入口<br />让每一次回答都能回到原始文档证据
        </p>

        <div class="brand-footer">
          <span class="stage-badge">Stage 8</span>
          <span class="footer-divider" />
          <span>OCR · RAG · Search</span>
        </div>
      </div>
    </section>

    <!-- Right: Login Form -->
    <section class="form-panel">
      <div class="form-wrapper">
        <div class="form-header">
          <h2>登录</h2>
          <p>输入你的账号信息以访问工作台</p>
        </div>

        <ElForm class="login-form" label-position="top" @submit.prevent="submit">
          <ElFormItem label="用户名">
            <ElInput
              v-model="form.username"
              size="large"
              placeholder="请输入用户名"
              autocomplete="username"
              @keyup.enter="submit"
            >
              <template #prefix>
                <ElIcon><User /></ElIcon>
              </template>
            </ElInput>
          </ElFormItem>
          <ElFormItem label="密码">
            <ElInput
              v-model="form.password"
              size="large"
              type="password"
              show-password
              placeholder="请输入密码"
              autocomplete="current-password"
              @keyup.enter="submit"
            >
              <template #prefix>
                <ElIcon><Lock /></ElIcon>
              </template>
            </ElInput>
          </ElFormItem>
          <ElButton
            class="submit-btn"
            type="primary"
            size="large"
            :loading="loading"
            @click="submit"
          >
            登录工作台
          </ElButton>
        </ElForm>

        <p class="form-hint">仅限授权人员访问，如需账号请联系管理员。</p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  display: flex;
  min-height: 100vh;
  min-height: 100dvh;
}

/* ── Left Brand Panel ── */
.brand-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  width: 52%;
  padding: 56px 64px;
  background: linear-gradient(168deg, rgb(15 118 110 / 6%) 0%, rgb(248 251 251 / 0%) 60%), #f7fafc;
  border-right: 1px solid #e2e8f0;
}

.brand-content {
  width: 100%;
  max-width: 560px;
}

.brand-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 40px;
}

.brand-mark {
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  width: 52px;
  height: 52px;
  color: #fff;
  font-size: 18px;
  font-weight: 800;
  background: #0f766e;
  border-radius: 10px;
  box-shadow: 0 16px 32px rgb(15 118 110 / 22%);
}

.brand-name {
  color: #475569;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.brand-title {
  margin: 0 0 22px;
  color: #0f172a;
  font-size: clamp(32px, 4vw, 44px);
  font-weight: 800;
  line-height: 1.2;
}

.brand-subtitle {
  max-width: 500px;
  margin: 0 0 44px;
  color: #475569;
  font-size: 17px;
  line-height: 1.85;
}

.brand-footer {
  display: flex;
  align-items: center;
  gap: 14px;
  color: #64748b;
  font-size: 14px;
  font-weight: 500;
}

.stage-badge {
  display: inline-flex;
  align-items: center;
  height: 26px;
  padding: 0 10px;
  color: #0f766e;
  font-size: 12px;
  font-weight: 700;
  background: rgb(15 118 110 / 8%);
  border: 1px solid rgb(15 118 110 / 15%);
  border-radius: 6px;
}

.footer-divider {
  width: 1px;
  height: 12px;
  background: #e2e8f0;
}

/* ── Right Form Panel ── */
.form-panel {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  padding: 56px 40px;
  background: #fff;
}

.form-wrapper {
  width: 100%;
  max-width: 380px;
}

.form-header {
  margin-bottom: 32px;
}

.form-header h2 {
  margin: 0 0 8px;
  color: #0f172a;
  font-size: 26px;
  font-weight: 800;
  line-height: 1.2;
}

.form-header p {
  margin: 0;
  color: #64748b;
  font-size: 14px;
  line-height: 1.6;
}

.login-form {
  margin-bottom: 0;
}

.login-form :deep(.el-form-item__label) {
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.login-form :deep(.el-input__wrapper) {
  border-radius: 8px;
  box-shadow: 0 0 0 1px #dbe4ef;
  transition:
    box-shadow 0.2s ease,
    border-color 0.2s ease;
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #94a3b8;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgb(15 118 110 / 25%);
}

.login-form :deep(.el-input__inner) {
  color: #0f172a;
  font-size: 14px;
}

.login-form :deep(.el-input__inner::placeholder) {
  color: #94a3b8;
}

.login-form :deep(.el-input__prefix) {
  color: #94a3b8;
}

.submit-btn {
  width: 100%;
  height: 44px;
  margin-top: 8px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 8px;

  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #115e59;
  --el-button-hover-border-color: #115e59;
  --el-button-active-bg-color: #134e4a;
  --el-button-active-border-color: #134e4a;
}

.form-hint {
  margin: 24px 0 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

/* ── Responsive ── */
@media (width <= 900px) {
  .login-page {
    flex-direction: column;
  }

  .brand-panel {
    width: 100%;
    padding: 36px 28px;
    border-right: none;
    border-bottom: 1px solid #e2e8f0;
  }

  .brand-content {
    max-width: none;
  }

  .brand-title {
    font-size: 30px;
  }

  .brand-subtitle {
    font-size: 15px;
  }

  .form-panel {
    padding: 36px 28px;
  }
}

@media (width <= 540px) {
  .brand-panel {
    padding: 28px 20px;
  }

  .form-panel {
    padding: 28px 20px;
  }

  .form-wrapper {
    max-width: none;
  }
}
</style>
