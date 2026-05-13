<script setup lang="ts">
import {
  ArrowRight,
  ChatLineRound,
  Collection,
  Connection,
  Cpu,
  DataAnalysis,
  DocumentChecked,
  Files,
  Key,
  Monitor,
  Search,
  Setting,
  SwitchButton,
  TrendCharts,
  User as UserIcon,
} from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElIcon from 'element-plus/es/components/icon/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-tag.css'
import type { Component } from 'vue'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const passwordDialogVisible = ref(false)

interface ModuleCard {
  title: string
  description: string
  meta: string
  icon: Component
  route?: string
  badge?: string
}

const cards: ModuleCard[] = [
  {
    title: '知识库',
    description: '沉淀工程文档、OCR 解析结果与引用资产，统一管理知识入口。',
    meta: '文档入库 / 权限协作',
    icon: Files,
    route: '/knowledge',
  },
  {
    title: 'RAG 问答',
    description: '面向施工方案和技术资料进行可溯源问答，引用证据即时展开。',
    meta: '流式回答 / 引用追踪',
    icon: ChatLineRound,
    route: '/chat',
  },
  {
    title: '知识检索',
    description: '跨知识库聚合全文与语义召回结果，支持结构化导出。',
    meta: '全局搜索 / 异步导出',
    icon: Search,
    route: '/search',
  },
  {
    title: '方案编制',
    description: '围绕模板、参数与章节生成的专业编制作业区。',
    meta: '规划中',
    icon: Monitor,
    badge: '即将开放',
  },
]

const adminCards: ModuleCard[] = [
  {
    title: '系统仪表盘',
    description: '查看用户、知识库、入库、问答与基础服务运行状态。',
    meta: '运维总览 / 治理审计',
    icon: DataAnalysis,
    route: '/admin/dashboard',
    badge: 'Admin',
  },
]

const visibleCards = computed(() => (auth.isAdmin ? [...cards, ...adminCards] : cards))

const heroMetrics = computed(() => [
  { label: '当前阶段', value: 'Stage 8' },
  { label: '登录角色', value: auth.isAdmin ? '管理员' : '成员' },
  { label: '核心链路', value: 'OCR · RAG · Search' },
])

const workflowItems = [
  { title: '入库', description: '批量 PDF 入队，OCR 与切片任务自动流转。', icon: DocumentChecked },
  { title: '检索', description: 'Track A/B 召回经 RRF 融合后返回证据。', icon: Connection },
  { title: '问答', description: 'SSE 流式生成，引用面板保持可追踪。', icon: Cpu },
  { title: '治理', description: '后台聚合系统健康、审计与知识库操作。', icon: TrendCharts },
]

function openModule(card: ModuleCard) {
  if (card.route) {
    void router.push(card.route)
  }
}

async function logout() {
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <main class="shell">
    <section class="header">
      <div class="brand-block">
        <span class="brand-mark">ZM</span>
        <div>
          <p class="eyebrow">ZhongMei RAG v2.0</p>
          <h1>工程知识与施工方案智能编制平台</h1>
        </div>
      </div>
      <div class="account">
        <div class="identity">
          <span>{{ auth.user?.display_name }}</span>
          <ElTag class="stage-tag" effect="dark">Stage 8</ElTag>
        </div>
        <div class="actions">
          <ElButton :icon="UserIcon" plain @click="router.push('/profile')">个人中心</ElButton>
          <ElButton :icon="Key" @click="passwordDialogVisible = true">改密</ElButton>
          <ElButton :icon="SwitchButton" plain @click="logout">登出</ElButton>
        </div>
      </div>
    </section>

    <section class="hero">
      <div class="hero-copy">
        <p class="section-kicker">Enterprise RAG Workspace</p>
        <p class="hero-subtitle">把工程资料、检索证据、方案生成</p>
        <h2>组织在同一个工作台中</h2>
        <p class="hero-description">
          面向工程知识沉淀、施工资料检索和可追溯问答的统一入口，减少跨系统切换，让每一次回答都能回到原始文档证据。
        </p>
        <div class="hero-actions">
          <ElButton type="primary" size="large" @click="router.push('/chat')">
            开始问答
            <ElIcon class="button-icon">
              <ArrowRight />
            </ElIcon>
          </ElButton>
        </div>
      </div>

      <div class="hero-panel" aria-label="平台运行概览">
        <div class="panel-head">
          <span>工作台概览</span>
          <ElTag class="status-tag" effect="plain">运行中</ElTag>
        </div>
        <div class="metric-grid">
          <div v-for="item in heroMetrics" :key="item.label" class="metric-item">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
        <div v-if="auth.isAdmin" class="admin-shortcuts">
          <ElButton :icon="Setting" @click="router.push('/admin/users')">用户管理</ElButton>
          <ElButton :icon="Collection" @click="router.push('/admin/knowledge-bases')">
            知识库管理
          </ElButton>
        </div>
      </div>
    </section>

    <section class="section-heading">
      <div>
        <p class="section-kicker">Core Modules</p>
        <h2>选择你的下一步操作</h2>
      </div>
      <p>常用能力置顶，管理员能力按权限自动显示</p>
    </section>

    <section class="module-grid">
      <article
        v-for="card in visibleCards"
        :key="card.title"
        class="module-card"
        :class="{ clickable: card.route, disabled: !card.route }"
        @click="openModule(card)"
      >
        <div class="module-topline">
          <span class="module-icon">
            <ElIcon :size="22">
              <component :is="card.icon" />
            </ElIcon>
          </span>
          <ElTag v-if="card.badge" class="soft-tag" effect="plain">{{ card.badge }}</ElTag>
        </div>
        <h3>{{ card.title }}</h3>
        <p>{{ card.description }}</p>
        <div class="module-footer">
          <span>{{ card.meta }}</span>
          <ElIcon v-if="card.route" :size="18">
            <ArrowRight />
          </ElIcon>
        </div>
      </article>
    </section>

    <section class="workflow">
      <div class="section-heading compact">
        <div>
          <p class="section-kicker">Operating Flow</p>
          <h2>从资料入库到可追溯回答</h2>
        </div>
      </div>
      <div class="workflow-grid">
        <article v-for="item in workflowItems" :key="item.title" class="workflow-item">
          <ElIcon :size="20">
            <component :is="item.icon" />
          </ElIcon>
          <div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.description }}</p>
          </div>
        </article>
      </div>
    </section>

    <ChangePasswordDialog v-model="passwordDialogVisible" />
  </main>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  padding: 28px 32px 56px;
  background:
    linear-gradient(180deg, rgb(248 251 251 / 92%) 0%, rgb(244 247 249 / 100%) 100%), #f7fafc;
  color: #0f172a;
}

.header,
.hero,
.section-heading,
.module-grid,
.workflow {
  width: min(1180px, 100%);
  margin-right: auto;
  margin-left: auto;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 32px;
  margin-bottom: 28px;
}

.brand-block {
  display: flex;
  gap: 16px;
  align-items: center;
  min-width: 0;
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
  margin: 0 0 6px;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
}

h1 {
  margin: 0;
  font-size: clamp(24px, 3vw, 32px);
  line-height: 1.2;
  font-weight: 800;
}

.account {
  display: grid;
  flex: 0 0 auto;
  gap: 12px;
  justify-items: end;
}

.identity,
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}

.identity strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.identity span {
  color: #334155;
  font-size: 14px;
}

.stage-tag,
.status-tag,
.soft-tag {
  --el-tag-border-color: rgb(15 118 110 / 18%);
  --el-tag-text-color: #0f766e;
  --el-tag-bg-color: rgb(15 118 110 / 8%);
}

.stage-tag {
  --el-tag-bg-color: #0f766e;
  --el-tag-border-color: #0f766e;
  --el-tag-text-color: #fff;
}

.hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
  gap: 24px;
  align-items: stretch;
  margin-bottom: 34px;
}

.hero-copy,
.hero-panel {
  background: #fff;
  border: 1px solid rgb(203 213 225 / 80%);
  border-radius: 8px;
  box-shadow: 0 24px 60px rgb(15 23 42 / 7%);
}

.hero-copy {
  padding: 32px 36px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.section-kicker {
  margin: 0 0 12px;
  color: #0f766e;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.hero-copy h2,
.section-heading h2,
.workflow h2 {
  margin: 0;
  color: #0f172a;
  line-height: 1.18;
}

.hero-copy h2 {
  max-width: 760px;
  font-size: clamp(38px, 5.5vw, 58px);
  font-weight: 800;
  line-height: 1.1;
}

.hero-subtitle {
  margin: 0 0 8px;
  color: #64748b;
  font-size: clamp(16px, 2vw, 20px);
  font-weight: 500;
  line-height: 1.4;
}

.hero-description {
  max-width: 680px;
  margin: 18px 0 0;
  color: #475569;
  font-size: 17px;
  line-height: 1.8;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 24px;
}

.button-icon {
  margin-left: 6px;
}

.hero-panel {
  display: grid;
  align-content: space-between;
  gap: 24px;
  padding: 28px;
}

.panel-head,
.module-topline,
.module-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-head span {
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
}

.metric-grid {
  display: grid;
  gap: 12px;
}

.metric-item {
  display: grid;
  gap: 6px;
  padding: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.metric-item span {
  color: #64748b;
  font-size: 13px;
}

.metric-item strong {
  color: #0f172a;
  font-size: 20px;
  font-weight: 800;
}

.admin-shortcuts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.section-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 16px;
}

.section-heading.compact {
  margin-bottom: 18px;
}

.section-heading h2 {
  font-size: 24px;
  font-weight: 800;
}

.section-heading > p {
  max-width: 380px;
  margin: 0;
  color: #64748b;
  line-height: 1.7;
  text-align: right;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 34px;
}

.module-card {
  display: grid;
  min-height: 238px;
  padding: 20px;
  background: #fff;
  border: 1px solid #dbe4ef;
  border-radius: 8px;
  box-shadow: 0 18px 42px rgb(15 23 42 / 5%);
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.module-card.clickable {
  cursor: pointer;
}

.module-card.clickable:hover {
  border-color: rgb(15 118 110 / 45%);
  box-shadow: 0 24px 60px rgb(15 118 110 / 11%);
  transform: translateY(-2px);
}

.module-card.disabled {
  color: #94a3b8;
  background: #fbfcfd;
}

.module-icon {
  display: inline-grid;
  place-items: center;
  width: 42px;
  height: 42px;
  color: #0f766e;
  background: rgb(15 118 110 / 8%);
  border: 1px solid rgb(15 118 110 / 12%);
  border-radius: 8px;
}

.module-card h3 {
  margin: 18px 0 10px;
  color: #0f172a;
  font-size: 19px;
  font-weight: 800;
}

.module-card p {
  margin: 0;
  color: #475569;
  line-height: 1.7;
}

.module-footer {
  align-self: end;
  margin-top: 24px;
  color: #0f766e;
  font-size: 13px;
  font-weight: 700;
}

.workflow {
  padding: 28px;
  background: #0f172a;
  border-radius: 8px;
}

.workflow .section-kicker,
.workflow .module-footer {
  color: #5eead4;
}

.workflow h2 {
  color: #f8fafc;
}

.workflow-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.workflow-item {
  display: flex;
  gap: 14px;
  min-height: 112px;
  padding: 18px;
  color: #cbd5e1;
  background: rgb(255 255 255 / 5%);
  border: 1px solid rgb(255 255 255 / 10%);
  border-radius: 8px;
}

.workflow-item > .el-icon {
  flex: 0 0 auto;
  color: #5eead4;
}

.workflow-item h3 {
  margin: 0 0 8px;
  color: #fff;
  font-size: 16px;
  font-weight: 800;
}

.workflow-item p {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
}

:deep(.el-button) {
  min-height: 36px;
  border-radius: 8px;
}

:deep(.el-button--large) {
  min-height: 44px;
  padding-right: 18px;
  padding-left: 18px;
}

:deep(.el-button--primary) {
  --el-button-bg-color: #0f766e;
  --el-button-border-color: #0f766e;
  --el-button-hover-bg-color: #115e59;
  --el-button-hover-border-color: #115e59;
  --el-button-active-bg-color: #134e4a;
  --el-button-active-border-color: #134e4a;
}

@media (width <= 1180px) {
  .module-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .workflow-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (width <= 900px) {
  .header,
  .hero,
  .section-heading {
    align-items: stretch;
    grid-template-columns: 1fr;
  }

  .header,
  .section-heading {
    flex-direction: column;
  }

  .account,
  .identity,
  .actions {
    justify-items: start;
    justify-content: flex-start;
  }

  .section-heading > p {
    max-width: none;
    text-align: left;
  }
}

@media (width <= 640px) {
  .shell {
    padding: 20px 16px 36px;
  }

  .brand-block {
    align-items: flex-start;
  }

  .brand-mark {
    width: 40px;
    height: 40px;
  }

  .hero-copy,
  .hero-panel,
  .workflow {
    padding: 22px;
  }

  .hero-copy {
    min-height: auto;
  }

  .hero-actions,
  .admin-shortcuts {
    grid-template-columns: 1fr;
  }

  .hero-actions {
    display: grid;
  }

  .module-grid,
  .workflow-grid {
    grid-template-columns: 1fr;
  }

  .module-card {
    min-height: 210px;
  }

  .actions {
    gap: 16px;
  }
}
</style>
