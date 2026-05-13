import { apiClient } from '@/api/client'

export interface DashboardActivity {
  action: string
  action_label: string
  actor_username: string
  knowledge_base_name: string
  target_id: string | null
  created_at: string
}

export interface DashboardStats {
  user_count: number
  kb_count: number
  kb_active_count: number
  document_total: number
  document_by_status: Record<string, number>
  document_by_kind: Record<string, number>
  chunk_count: number
  asset_count: number
  chat_session_count: number
  chat_message_count: number
  ingest_by_status: Record<string, number>
  recent_activities: DashboardActivity[]
  trends_7d: { dates: string[]; documents: number[]; chat_sessions: number[] }
  trends_14d: { dates: string[]; documents: number[]; chat_sessions: number[] }
}

export interface HealthStatus {
  status: 'ok' | 'down' | 'degraded' | 'not_configured' | string
  latency_ms?: number
  code?: number
}

export interface SystemStatus {
  database: HealthStatus
  redis: HealthStatus
  ocr?: HealthStatus
  llm?: HealthStatus
  dashscope?: HealthStatus
  uptime_seconds: number
}

export function fetchDashboardStats() {
  return apiClient.get<DashboardStats>('/dashboard/stats')
}

export function fetchSystemStatus() {
  return apiClient.get<SystemStatus>('/dashboard/system-status')
}
