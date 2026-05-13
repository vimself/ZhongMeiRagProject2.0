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

const KB_ACTIVITY_LABELS: Record<string, string> = {
  'knowledge_base.create': '创建知识库',
  'knowledge_base.delete': '删除知识库',
  'knowledge_base.permissions.update': '修改权限',
}

const KB_ACTIVITY_ACTIONS = new Set(Object.keys(KB_ACTIVITY_LABELS))

const statCards = computed(() => {
  if (!stats.value) return []
  return [
    { label: '用户数', value: stats.value.user_count },
    { label: '活跃知识库', value: stats.value.kb_active_count },
    { label: '文档总数', value: stats.value.document_total },
    { label: '知识片段', value: stats.value.chunk_count },
    { label: '聊天会话', value: stats.value.chat_session_count },
    { label: '聊天消息', value: stats.value.chat_message_count },
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
    tooltip: { trigger: 'axis' },
    legend: { data: ['文档入库', '聊天会话'], bottom: 0 },
    grid: { left: 40, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: t.dates },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      { name: '文档入库', type: 'line', data: t.documents, smooth: true, color: '#0f766e' },
      { name: '聊天会话', type: 'line', data: t.chat_sessions, smooth: true, color: '#409eff' },
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
  <main v-loading="loading" class="shell">
    <section class="page-header">
      <ElButton :icon="ArrowLeft" text @click="router.push('/')">返回</ElButton>
      <h1>系统仪表盘</h1>
      <ElButton :icon="Refresh" @click="refreshAll">刷新</ElButton>
    </section>

    <section class="stats-grid">
      <article v-for="card in statCards" :key="card.label" class="stat-card">
        <div class="stat-card__value">{{ card.value }}</div>
        <div class="stat-card__label">{{ card.label }}</div>
      </article>
    </section>

    <section class="dashboard-grid">
      <article class="panel chart-panel">
        <div class="panel-heading">
          <h2>近 7 天趋势</h2>
        </div>
        <VChart :option="trendChartOption" autoresize class="trend-chart" />
      </article>

      <article class="panel status-panel">
        <div class="panel-heading">
          <h2>系统状态</h2>
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

    <section v-if="recentActivities.length" class="activity-section panel">
      <div class="panel-heading">
        <h2>近期操作</h2>
        <span>知识库创建、删除与权限修改</span>
      </div>
      <ElTable :data="recentActivities" stripe size="small" style="width: 100%">
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
.shell {
  min-height: 100vh;
  padding: 32px;
  background: #f6f8fb;
  color: #1f2937;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 1080px;
  margin: 0 auto 24px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  flex: 1;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  max-width: 1080px;
  margin: 0 auto 24px;
}

.stat-card {
  padding: 20px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  text-align: center;
}

.stat-card__value {
  font-size: 28px;
  font-weight: 700;
  color: #0f766e;
  margin-bottom: 6px;
}

.stat-card__label {
  font-size: 13px;
  color: #6b7280;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
  gap: 16px;
  max-width: 1080px;
  margin: 0 auto 24px;
}

.panel {
  padding: 20px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.panel-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel-heading h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #111827;
}

.panel-heading span {
  color: #6b7280;
  font-size: 12px;
}

.trend-chart {
  height: 320px;
}

.status-list {
  display: grid;
  gap: 10px;
}

.status-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.status-dot {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 50%;
  flex-shrink: 0;
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
  margin-bottom: 4px;
  color: #111827;
  font-size: 14px;
  font-weight: 600;
}

.status-title strong {
  color: #374151;
  font-size: 12px;
  font-weight: 600;
}

.status-detail {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #6b7280;
  font-size: 12px;
}

.status-ok .status-dot {
  background: #10b981;
}

.status-down .status-dot {
  background: #ef4444;
}

.status-degraded .status-dot {
  background: #f59e0b;
}

.status-not-configured .status-dot {
  background: #9ca3af;
}

.status-unknown .status-dot {
  background: #d1d5db;
}

.status-latency {
  color: #6b7280;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.activity-section {
  max-width: 1080px;
  margin: 0 auto;
}

.actor-name {
  color: #111827;
  font-weight: 600;
}

@media (width <= 768px) {
  .shell {
    padding: 20px;
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .page-header h1 {
    font-size: 20px;
  }
}
</style>
