<script setup lang="ts">
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElTable, { ElTableColumn } from 'element-plus/es/components/table/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-table.css'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'

import type { DashboardActivity, DashboardStats, HealthStatus, SystemStatus } from '@/api/dashboard'
import { fetchDashboardStats, fetchSystemStatus } from '@/api/dashboard'
import { formatBeijingDateTime } from '@/utils/time'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const router = useRouter()
const loading = ref(false)
const stats = ref<DashboardStats | null>(null)
const sysStatus = ref<SystemStatus | null>(null)
const formatDateTime = formatBeijingDateTime

interface StatusItem {
  key: string
  label: string
  status: string
  detail: string
  latency?: number
  value?: string
}

type StatIconName = 'users' | 'knowledge' | 'documents' | 'chunks' | 'sessions' | 'messages'

interface StatCard {
  label: string
  value: number
  icon: StatIconName
}

const KB_ACTIVITY_LABELS: Record<string, string> = {
  'knowledge_base.create': '创建知识库',
  'knowledge_base.delete': '删除知识库',
  'knowledge_base.permissions.update': '修改权限',
}

const KB_ACTIVITY_ACTIONS = new Set(Object.keys(KB_ACTIVITY_LABELS))

const statCards = computed<StatCard[]>(() => {
  if (!stats.value) return []
  return [
    { label: '用户数', value: stats.value.user_count, icon: 'users' },
    {
      label: '活跃知识库',
      value: stats.value.kb_active_count,
      icon: 'knowledge',
    },
    { label: '文档总数', value: stats.value.document_total, icon: 'documents' },
    { label: '知识片段', value: stats.value.chunk_count, icon: 'chunks' },
    {
      label: '聊天会话',
      value: stats.value.chat_session_count,
      icon: 'sessions',
    },
    {
      label: '聊天消息',
      value: stats.value.chat_message_count,
      icon: 'messages',
    },
  ]
})

const recentActivities = computed<DashboardActivity[]>(() => {
  return (stats.value?.recent_activities ?? [])
    .map((item) => {
      const action = String(item.action ?? '')
      const actionLabel =
        typeof item.action_label === 'string' && item.action_label.trim()
          ? item.action_label.trim()
          : KB_ACTIVITY_LABELS[action]
      const actorUsername =
        typeof item.actor_username === 'string' ? item.actor_username.trim() : ''
      const knowledgeBaseName =
        typeof item.knowledge_base_name === 'string' ? item.knowledge_base_name.trim() : ''
      const createdAt = typeof item.created_at === 'string' ? item.created_at : ''

      if (
        !KB_ACTIVITY_ACTIONS.has(action) ||
        !actionLabel ||
        !actorUsername ||
        !knowledgeBaseName ||
        !createdAt
      ) {
        return null
      }

      return {
        ...item,
        action,
        action_label: actionLabel,
        actor_username: actorUsername,
        knowledge_base_name: knowledgeBaseName,
        created_at: createdAt,
      }
    })
    .filter((item): item is DashboardActivity => item !== null)
})

const trendChartOption = computed(() => {
  if (!stats.value) return {}
  const t = stats.value.trends_7d
  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#fff',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      textStyle: { color: '#0f172a', fontSize: 13 },
    },
    legend: {
      data: ['文档入库', '聊天会话'],
      bottom: 0,
      textStyle: { color: '#64748b', fontSize: 12 },
    },
    grid: { left: 48, right: 24, top: 16, bottom: 44 },
    xAxis: {
      type: 'category',
      data: t.dates,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
      axisLabel: { color: '#64748b', fontSize: 12 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
      axisLabel: { color: '#64748b', fontSize: 12 },
    },
    series: [
      {
        name: '文档入库',
        type: 'line',
        data: t.documents,
        smooth: true,
        color: '#0f766e',
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2.5 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgb(15 118 110 / 12%)' },
              { offset: 1, color: 'rgb(15 118 110 / 0%)' },
            ],
          },
        },
      },
      {
        name: '聊天会话',
        type: 'line',
        data: t.chat_sessions,
        smooth: true,
        color: '#64748b',
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2.5 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgb(100 116 139 / 10%)' },
              { offset: 1, color: 'rgb(100 116 139 / 0%)' },
            ],
          },
        },
      },
    ],
  }
})

const uptimeLabel = computed(() => {
  if (!sysStatus.value) return '未获取'
  const sec = sysStatus.value.uptime_seconds
  if (sec < 60) return `${Math.round(sec)} 秒`
  if (sec < 3600) return `${Math.round(sec / 60)} 分钟`
  return `${(sec / 3600).toFixed(1)} 小时`
})

const systemItems = computed<StatusItem[]>(() => {
  const status = sysStatus.value
  const missingBackendField = status
    ? ({ status: 'not_reported' } satisfies HealthStatus)
    : undefined
  return [
    toStatusItem('database', '数据库', status?.database, '业务数据读写'),
    toStatusItem('redis', 'Redis', status?.redis, '缓存与任务队列'),
    toStatusItem('ocr', 'OCR', status?.ocr ?? missingBackendField, '文档解析服务'),
    toStatusItem(
      'llm',
      'LLM',
      status?.llm ?? status?.dashscope ?? missingBackendField,
      '问答与向量模型服务',
    ),
    {
      key: 'uptime',
      label: '运行时间',
      status: status ? 'ok' : 'unknown',
      detail: 'API 服务进程',
      value: uptimeLabel.value,
    },
  ]
})

function toStatusItem(
  key: string,
  label: string,
  source: HealthStatus | undefined,
  detail: string,
): StatusItem {
  return {
    key,
    label,
    status: source?.status ?? 'unknown',
    detail,
    latency: source?.latency_ms,
  }
}

function statusClass(status: string) {
  if (status === 'ok') return 'status-ok'
  if (status === 'down') return 'status-down'
  if (status === 'not_configured') return 'status-not-configured'
  if (status === 'not_reported') return 'status-not-configured'
  if (status === 'degraded') return 'status-degraded'
  return 'status-unknown'
}

function statusText(status: string) {
  if (status === 'ok') return '正常'
  if (status === 'down') return '异常'
  if (status === 'not_configured') return '未配置'
  if (status === 'not_reported') return '未返回'
  if (status === 'degraded') return '受限'
  return '未知'
}

async function refreshAll() {
  loading.value = true
  try {
    const [s, st] = await Promise.all([fetchDashboardStats(), fetchSystemStatus()])
    stats.value = s.data
    sysStatus.value = st.data
  } catch {
    // keep previous data
  } finally {
    loading.value = false
  }
}

onMounted(refreshAll)
</script>

<template>
  <main v-loading="loading" class="dashboard-page">
    <!-- Header -->
    <header class="page-header">
      <div class="page-header__left">
        <div class="brand-mark">ZM</div>
        <div class="page-header__titles">
          <span class="page-eyebrow">ADMIN</span>
          <h1 class="page-title">系统仪表盘</h1>
        </div>
      </div>
      <div class="page-header__actions">
        <ElButton :icon="ArrowLeft" text class="btn-back" @click="router.push('/')"
          >返回首页</ElButton
        >
        <ElButton :icon="Refresh" type="primary" class="btn-refresh" @click="refreshAll"
          >刷新数据</ElButton
        >
      </div>
    </header>

    <!-- Stat Cards -->
    <section class="stats-grid">
      <article v-for="card in statCards" :key="card.label" class="stat-card">
        <div class="stat-card__icon" :class="`stat-card__icon--${card.icon}`" aria-hidden="true">
          <svg
            class="stat-card__svg"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <g v-if="card.icon === 'users'">
              <path
                class="stat-card__svg-fill"
                d="M6.15 18.4c0.5-3.15 2.32-4.75 5.35-4.75s4.85 1.6 5.35 4.75"
              />
              <circle cx="11.5" cy="8.2" r="3.35" />
              <path d="M6.15 18.4c0.5-3.15 2.32-4.75 5.35-4.75s4.85 1.6 5.35 4.75" />
              <path class="stat-card__svg-muted" d="M17.05 6.65c1.25 0.38 2.15 1.52 2.15 2.9" />
              <path class="stat-card__svg-muted" d="M18.25 14.1c1.3 0.55 2.1 1.72 2.4 3.5" />
            </g>

            <g v-else-if="card.icon === 'knowledge'">
              <path
                class="stat-card__svg-fill"
                d="M5.4 6.2h10.2a3 3 0 0 1 3 3v8.6H8.4a3 3 0 0 1-3-3z"
              />
              <path d="M5.4 6.2h10.2a3 3 0 0 1 3 3v8.6H8.4a3 3 0 0 1-3-3z" />
              <path d="M8.4 9.6h6.9" />
              <path d="M8.4 12.65h5.1" />
              <path class="stat-card__svg-muted" d="M15.8 17.8V20" />
              <circle class="stat-card__svg-dot" cx="18.6" cy="6.45" r="1.15" />
            </g>

            <g v-else-if="card.icon === 'documents'">
              <path class="stat-card__svg-muted" d="M8.25 4.2h7.9a2.2 2.2 0 0 1 2.2 2.2v10.15" />
              <path class="stat-card__svg-fill" d="M5.65 6.75h8.6l4.1 4.1v8.95H5.65z" />
              <path d="M5.65 6.75h8.6l4.1 4.1v8.95H5.65z" />
              <path d="M14.25 6.75v4.1h4.1" />
              <path d="M8.55 14.25h6.9" />
              <path d="M8.55 17.05h4.65" />
            </g>

            <g v-else-if="card.icon === 'chunks'">
              <path class="stat-card__svg-muted" d="M8.2 8.1h7.6" />
              <path class="stat-card__svg-muted" d="M8.2 15.9h7.6" />
              <path class="stat-card__svg-muted" d="M8.2 8.1v7.8" />
              <path class="stat-card__svg-muted" d="M15.8 8.1v7.8" />
              <rect class="stat-card__svg-fill" x="4.6" y="4.7" width="7.1" height="6.8" rx="2" />
              <rect x="4.6" y="4.7" width="7.1" height="6.8" rx="2" />
              <rect x="12.3" y="12.5" width="7.1" height="6.8" rx="2" />
              <circle class="stat-card__svg-dot" cx="15.85" cy="8.1" r="1.25" />
              <circle class="stat-card__svg-dot" cx="8.2" cy="15.9" r="1.25" />
            </g>

            <g v-else-if="card.icon === 'sessions'">
              <path class="stat-card__svg-muted" d="M8 5.15h8.2a3.2 3.2 0 0 1 3.2 3.2v5.05" />
              <path
                class="stat-card__svg-fill"
                d="M4.8 7.55h10.05a3.2 3.2 0 0 1 3.2 3.2v3.5a3.2 3.2 0 0 1-3.2 3.2h-3.8L7.1 20v-2.55A3.2 3.2 0 0 1 4.8 14.4z"
              />
              <path
                d="M4.8 7.55h10.05a3.2 3.2 0 0 1 3.2 3.2v3.5a3.2 3.2 0 0 1-3.2 3.2h-3.8L7.1 20v-2.55A3.2 3.2 0 0 1 4.8 14.4z"
              />
              <path d="M8.2 11.2h6.3" />
              <path d="M8.2 14.05h4.15" />
            </g>

            <g v-else>
              <path
                class="stat-card__svg-fill"
                d="M5.2 5.9h13.6a2.9 2.9 0 0 1 2.9 2.9v7.25a2.9 2.9 0 0 1-2.9 2.9H9.9L5.2 21z"
              />
              <path
                d="M5.2 5.9h13.6a2.9 2.9 0 0 1 2.9 2.9v7.25a2.9 2.9 0 0 1-2.9 2.9H9.9L5.2 21z"
              />
              <path d="M8.65 9.7h6.9" />
              <path d="M8.65 12.65h8.25" />
              <path d="M8.65 15.6h4.25" />
              <circle class="stat-card__svg-dot" cx="18.1" cy="9.6" r="1" />
            </g>
          </svg>
        </div>
        <div class="stat-card__content">
          <div class="stat-card__value">{{ card.value }}</div>
          <div class="stat-card__label">{{ card.label }}</div>
        </div>
      </article>
    </section>

    <!-- Main Grid: Chart + Status -->
    <section class="dashboard-grid">
      <article class="panel chart-panel">
        <div class="panel-heading">
          <h2>近 7 天趋势</h2>
          <span class="panel-subtitle">文档入库与聊天会话量</span>
        </div>
        <VChart :option="trendChartOption" autoresize class="trend-chart" />
      </article>

      <article class="panel status-panel">
        <div class="panel-heading">
          <h2>系统状态</h2>
          <span class="panel-subtitle">核心服务健康度</span>
        </div>
        <div class="status-list">
          <div
            v-for="item in systemItems"
            :key="item.key"
            class="status-row"
            :class="statusClass(item.status)"
          >
            <span class="status-dot" />
            <div class="status-copy">
              <div class="status-title">
                <span>{{ item.label }}</span>
                <strong>{{ item.value || statusText(item.status) }}</strong>
              </div>
              <div class="status-detail">
                <span>{{ item.detail }}</span>
                <span v-if="item.latency !== undefined" class="status-latency">
                  {{ item.latency }}ms
                </span>
              </div>
            </div>
          </div>
        </div>
      </article>
    </section>

    <!-- Activity Table -->
    <section v-if="recentActivities.length" class="panel activity-panel">
      <div class="panel-heading">
        <h2>近期操作</h2>
        <span class="panel-subtitle">知识库创建、删除与权限修改</span>
      </div>
      <ElTable
        :data="recentActivities"
        stripe
        size="small"
        class="activity-table"
        style="width: 100%"
      >
        <ElTableColumn label="操作人" min-width="180">
          <template #default="{ row }">
            <span class="actor-name">{{ row.actor_username }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="knowledge_base_name" label="知识库" min-width="260" />
        <ElTableColumn prop="action_label" label="操作" min-width="180" />
        <ElTableColumn label="时间" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </ElTableColumn>
      </ElTable>
    </section>
  </main>
</template>

<style scoped>
.dashboard-page {
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
  padding: 28px 32px 56px;
  background:
    linear-gradient(180deg, rgb(248 251 251 / 92%) 0%, rgb(244 247 249 / 100%) 100%), var(--zm-bg);
  color: var(--zm-text);
  max-width: min(1200px, 100%);
  margin: 0 auto;
}

/* ── Header ── */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 28px;
}

.page-header__left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-mark {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--zm-primary);
  border-radius: 8px;
  box-shadow: 0 14px 26px rgb(15 118 110 / 18%);
  color: #fff;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.5px;
  flex-shrink: 0;
}

.page-header__titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.page-eyebrow {
  color: var(--zm-text-muted);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  line-height: 1;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--zm-text-strong);
  line-height: 1.3;
}

.page-header__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-back {
  color: var(--zm-text-muted) !important;
  font-size: 13px;
}

.btn-back:hover {
  color: var(--zm-primary) !important;
}

.btn-refresh {
  --el-button-bg-color: var(--zm-primary) !important;
  --el-button-border-color: var(--zm-primary) !important;
  --el-button-hover-bg-color: var(--zm-primary-hover) !important;
  --el-button-hover-border-color: var(--zm-primary-hover) !important;
  --el-button-active-bg-color: var(--zm-primary-active) !important;
  --el-button-active-border-color: var(--zm-primary-active) !important;
}

/* ── Stat Cards ── */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 16px;
  background: var(--zm-surface);
  border: 1px solid var(--zm-border-soft);
  border-radius: var(--zm-radius);
  transition:
    border-color 0.2s,
    box-shadow 0.2s,
    transform 0.2s;
  cursor: default;
}

.stat-card:hover {
  border-color: rgb(15 118 110 / 30%);
  box-shadow: 0 12px 32px rgb(15 23 42 / 6%);
  transform: translateY(-2px);
}

.stat-card__icon {
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--zm-teal-soft);
  border: 1px solid rgb(15 118 110 / 12%);
  border-radius: 8px;
  color: var(--zm-primary);
  flex-shrink: 0;
}

.stat-card__svg {
  width: 24px;
  height: 24px;
  display: block;
  stroke: currentcolor;
  stroke-width: 1.65;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.stat-card__svg-fill {
  fill: rgb(15 118 110 / 9%);
}

.stat-card__content {
  min-width: 0;
}

.stat-card__value {
  font-size: 24px;
  font-weight: 700;
  color: var(--zm-text-strong);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
  margin-bottom: 2px;
}

.stat-card__label {
  font-size: 12px;
  color: var(--zm-text-muted);
  font-weight: 500;
  white-space: nowrap;
}

/* ── Dashboard Grid ── */
.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

/* ── Panel ── */
.panel {
  padding: 24px;
  background: var(--zm-surface);
  border: 1px solid var(--zm-border-soft);
  border-radius: var(--zm-radius);
}

.panel-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 16px;
}

.panel-heading h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--zm-text-strong);
}

.panel-subtitle {
  color: var(--zm-text-muted);
  font-size: 12px;
  font-weight: 400;
}

/* ── Chart ── */
.trend-chart {
  height: 300px;
}

/* ── Status Panel ── */
.status-list {
  display: grid;
  gap: 8px;
}

.status-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  background: var(--zm-bg-soft);
  border: 1px solid var(--zm-border-soft);
  border-radius: 6px;
  transition: background 0.15s;
}

.status-row:hover {
  background: #f1f5f9;
}

.status-dot {
  width: 10px;
  height: 10px;
  margin-top: 4px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 0 3px transparent;
  transition: box-shadow 0.2s;
}

.status-ok .status-dot {
  background: #10b981;
  box-shadow: 0 0 0 3px rgb(16 185 129 / 15%);
}

.status-down .status-dot {
  background: #ef4444;
  box-shadow: 0 0 0 3px rgb(239 68 68 / 15%);
}

.status-degraded .status-dot {
  background: #f59e0b;
  box-shadow: 0 0 0 3px rgb(245 158 11 / 15%);
}

.status-not-configured .status-dot {
  background: #9ca3af;
}

.status-unknown .status-dot {
  background: #d1d5db;
}

.status-copy {
  min-width: 0;
  flex: 1;
}

.status-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 2px;
  color: var(--zm-text-strong);
  font-size: 14px;
  font-weight: 600;
}

.status-title strong {
  color: var(--zm-text);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.status-detail {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--zm-text-muted);
  font-size: 12px;
}

.status-latency {
  font-variant-numeric: tabular-nums;
}

/* ── Activity Panel ── */
.activity-panel {
  margin-bottom: 0;
}

.actor-name {
  color: var(--zm-text-strong);
  font-weight: 600;
}

/* Element Plus table overrides */
:deep(.el-table) {
  --el-table-border-color: var(--zm-border-soft);
  --el-table-header-bg-color: var(--zm-bg-soft);
  --el-table-header-text-color: var(--zm-text-muted);
  --el-table-text-color: var(--zm-text);
  --el-table-row-hover-bg-color: #f8fafc;

  font-size: 13px;
}

:deep(.el-table th.el-table__cell) {
  font-weight: 600;
  font-size: 12px;
  text-transform: none;
}

/* ── Responsive ── */
@media (width <= 1024px) {
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (width <= 768px) {
  .dashboard-page {
    padding: 20px 16px 40px;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .page-header__actions {
    width: 100%;
  }

  .page-title {
    font-size: 20px;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .stat-card {
    padding: 14px 12px;
    gap: 10px;
  }

  .stat-card__icon {
    width: 36px;
    height: 36px;
  }

  .stat-card__svg {
    width: 22px;
    height: 22px;
  }

  .stat-card__value {
    font-size: 20px;
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .panel {
    padding: 18px;
  }

  .trend-chart {
    height: 240px;
  }
}

@media (width <= 480px) {
  .dashboard-page {
    padding: 16px 12px 32px;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }

  .stat-card {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    padding: 12px;
  }

  .stat-card__value {
    font-size: 18px;
  }

  .brand-mark {
    width: 38px;
    height: 38px;
    font-size: 13px;
  }
}
</style>
