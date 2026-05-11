import { apiClient } from '@/api/client'

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
  recent_activities: Array<Record<string, unknown>>
  trends_7d: { dates: string[]; documents: number[]; chat_sessions: number[] }
  trends_14d: { dates: string[]; documents: number[]; chat_sessions: number[] }
}

export interface SystemStatus {
  database: { status: string; latency_ms: number }
  redis: { status: string; latency_ms: number }
  dashscope: { status: string }
  uptime_seconds: number
}

export function fetchDashboardStats() {
  return apiClient.get<DashboardStats>('/dashboard/stats')
}

export function fetchSystemStatus() {
  return apiClient.get<SystemStatus>('/dashboard/system-status')
}
