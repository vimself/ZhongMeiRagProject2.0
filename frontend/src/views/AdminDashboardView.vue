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
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'

import type { DashboardStats, SystemStatus } from '@/api/dashboard'
import { fetchDashboardStats, fetchSystemStatus } from '@/api/dashboard'

use([CanvasRenderer, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent])

const router = useRouter()
const loading = ref(false)
const stats = ref<DashboardStats | null>(null)
const sysStatus = ref<SystemStatus | null>(null)

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

const docTypeChartOption = computed(() => {
  if (!stats.value) return {}
  const entries = Object.entries(stats.value.document_by_kind)
  return {
    tooltip: { trigger: 'item' },
    legend: { orient: 'vertical', right: 10, top: 'center' },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        data: entries.map(([name, value]) => ({ name, value })),
        label: { show: true, formatter: '{b}: {c}' },
      },
    ],
  }
})

const dbStatusClass = computed(() => {
  if (!sysStatus.value) return 'status-unknown'
  return sysStatus.value.database.status === 'ok' ? 'status-ok' : 'status-down'
})

const redisStatusClass = computed(() => {
  if (!sysStatus.value) return 'status-unknown'
  return sysStatus.value.redis.status === 'ok' ? 'status-ok' : 'status-down'
})

const dashscopeStatusClass = computed(() => {
  if (!sysStatus.value) return 'status-unknown'
  const s = sysStatus.value.dashscope.status
  if (s === 'ok') return 'status-ok'
  if (s === 'not_configured') return 'status-not-configured'
  return 'status-degraded'
})

const uptimeLabel = computed(() => {
  if (!sysStatus.value) return '—'
  const sec = sysStatus.value.uptime_seconds
  if (sec < 60) return `${Math.round(sec)}秒`
  if (sec < 3600) return `${Math.round(sec / 60)}分钟`
  return `${(sec / 3600).toFixed(1)}小时`
})

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

    <section class="charts-row">
      <article class="chart-card">
        <h3>近 7 天趋势</h3>
        <VChart :option="trendChartOption" autoresize style="height: 300px" />
      </article>
      <article class="chart-card">
        <h3>文档类型分布</h3>
        <VChart :option="docTypeChartOption" autoresize style="height: 300px" />
      </article>
    </section>

    <section class="status-section">
      <h2>系统状态</h2>
      <div class="status-lights">
        <div class="status-light" :class="dbStatusClass">
          <span class="status-dot" />
          <span>数据库</span>
          <span v-if="sysStatus" class="status-latency">{{ sysStatus.database.latency_ms }}ms</span>
        </div>
        <div class="status-light" :class="redisStatusClass">
          <span class="status-dot" />
          <span>Redis</span>
          <span v-if="sysStatus" class="status-latency">{{ sysStatus.redis.latency_ms }}ms</span>
        </div>
        <div class="status-light" :class="dashscopeStatusClass">
          <span class="status-dot" />
          <span>DashScope</span>
        </div>
        <div class="status-light status-ok">
          <span class="status-dot" />
          <span>运行时间: {{ uptimeLabel }}</span>
        </div>
      </div>
    </section>

    <section v-if="stats?.recent_activities?.length" class="activity-section">
      <h2>近期操作</h2>
      <ElTable :data="stats.recent_activities" stripe size="small" style="width: 100%">
        <ElTableColumn prop="action" label="操作" width="200" />
        <ElTableColumn prop="target_type" label="对象" width="150" />
        <ElTableColumn prop="ip_address" label="IP" width="140" />
        <ElTableColumn prop="created_at" label="时间" />
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

.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  max-width: 1080px;
  margin: 0 auto 24px;
}

.chart-card {
  padding: 20px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.chart-card h3 {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
  color: #111827;
}

.status-section {
  max-width: 1080px;
  margin: 0 auto 24px;
}

.status-section h2 {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 12px;
}

.status-lights {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.status-light {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
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

.activity-section h2 {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 12px;
}

@media (width <= 768px) {
  .shell {
    padding: 20px;
  }

  .charts-row {
    grid-template-columns: 1fr;
  }

  .page-header h1 {
    font-size: 20px;
  }
}
</style>
