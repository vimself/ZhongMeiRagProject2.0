<script setup lang="ts">
import {
  Collection,
  Key,
  Monitor,
  Setting,
  Service,
  SwitchButton,
  Tickets,
  User as UserIcon,
} from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElIcon from 'element-plus/es/components/icon/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-tag.css'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const passwordDialogVisible = ref(false)

const cards = [
  { title: '知识库', description: '文档入库、检索与引用预览', icon: Tickets, route: '/knowledge' },
  { title: 'RAG 问答', description: 'SSE 流式回答与可溯源引用', icon: Service, route: '' },
  { title: '方案编制', description: '模板、参数、章节生成工作台', icon: Monitor, route: '' },
]

async function logout() {
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <main class="shell">
    <section class="topbar">
      <div>
        <p class="eyebrow">ZhongMei RAG v2.0</p>
        <h1>工程知识与施工方案智能编制平台</h1>
      </div>
      <div class="account">
        <div class="identity">
          <span>{{ auth.user?.display_name }}</span>
          <ElTag type="success" effect="dark">Stage 5</ElTag>
        </div>
        <div class="actions">
          <ElButton :icon="UserIcon" @click="router.push('/profile')">个人中心</ElButton>
          <ElButton v-if="auth.isAdmin" :icon="Setting" @click="router.push('/admin/users')">
            用户管理
          </ElButton>
          <ElButton
            v-if="auth.isAdmin"
            :icon="Collection"
            @click="router.push('/admin/knowledge-bases')"
          >
            知识库管理
          </ElButton>
          <ElButton :icon="Key" @click="passwordDialogVisible = true">改密</ElButton>
          <ElButton :icon="SwitchButton" @click="logout">登出</ElButton>
        </div>
      </div>
    </section>

    <section class="grid">
      <article
        v-for="card in cards"
        :key="card.title"
        class="module"
        :class="{ clickable: card.route }"
        @click="card.route ? router.push(card.route) : undefined"
      >
        <ElIcon :size="24">
          <component :is="card.icon" />
        </ElIcon>
        <div>
          <h2>{{ card.title }}</h2>
          <p>{{ card.description }}</p>
        </div>
      </article>
    </section>
    <ChangePasswordDialog v-model="passwordDialogVisible" />
  </main>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  padding: 32px;
  background: #f6f8fb;
  color: #1f2937;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  max-width: 1080px;
  margin: 0 auto 24px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #52616f;
  font-size: 14px;
}

h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
}

.account {
  display: grid;
  gap: 10px;
  justify-items: end;
}

.identity,
.actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.identity span {
  color: #334155;
  font-size: 14px;
  font-weight: 600;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  max-width: 1080px;
  margin: 0 auto;
}

.module {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  min-height: 120px;
  padding: 20px;
  background: #fff;
  border: 1px solid #d8dee8;
  border-radius: 8px;
}

.module.clickable {
  cursor: pointer;
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}

.module.clickable:hover {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgb(64 158 255 / 15%);
}

.module h2 {
  margin: 0 0 8px;
  font-size: 18px;
}

.module p {
  margin: 0;
  color: #52616f;
  line-height: 1.6;
}

@media (width <= 640px) {
  .shell {
    padding: 20px;
  }

  .topbar {
    align-items: flex-start;
    flex-direction: column;
    gap: 16px;
  }

  .account {
    justify-items: start;
    width: 100%;
  }

  h1 {
    font-size: 22px;
  }
}
</style>
