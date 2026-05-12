import { fetchEventSource } from '@microsoft/fetch-event-source'

import { apiClient } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

export interface ChatCitation {
  id: string
  index: number
  chunk_id: string | null
  document_id: string
  document_title: string
  knowledge_base_id: string
  section_path: string[]
  section_text: string
  page_start: number | null
  page_end: number | null
  bbox: { x?: number; y?: number; width?: number; height?: number } | null
  snippet: string
  score: number
  preview_url: string
  download_url: string
}

export interface ChatMessageDTO {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  finish_reason: string | null
  model: string | null
  created_at: string
  citations: ChatCitation[]
}

export interface ChatSessionSummary {
  id: string
  title: string
  knowledge_base_id: string | null
  is_active: boolean
  message_count: number
  created_at: string
  updated_at: string
}

export interface ChatSessionDetail {
  id: string
  title: string
  knowledge_base_id: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  messages: ChatMessageDTO[]
}

export interface ChatSessionListResponse {
  items: ChatSessionSummary[]
  total: number
}

export interface ChatStreamRequestBody {
  kb_id: string
  question: string
  session_id?: string
  filters?: Record<string, unknown>
  k?: number
}

export interface ChatStreamReferencesEvent {
  session_id: string
  references: ChatCitation[]
}

export interface ChatStreamDoneEvent {
  session_id: string
  finish_reason: string
  model: string | null
  citations: number
  min_score_threshold: number
}

export interface ChatStreamStatusEvent {
  stage: string
  message: string
}

export interface ChatStreamHandlers {
  onReferences: (payload: ChatStreamReferencesEvent) => void
  onStatus?: (payload: ChatStreamStatusEvent) => void
  onReasoning?: (delta: string) => void
  onContent: (delta: string) => void
  onDone: (payload: ChatStreamDoneEvent) => void
  onError: (message: string) => void
  onOpen?: () => void
  signal?: AbortSignal
}

export function listChatSessions(params?: { page?: number; page_size?: number }) {
  return apiClient.get<ChatSessionListResponse>('/chat/sessions', { params })
}

export function getChatSession(sessionId: string) {
  return apiClient.get<ChatSessionDetail>(`/chat/sessions/${sessionId}`)
}

export function deleteChatSession(sessionId: string) {
  return apiClient.delete<{ status: string }>(`/chat/sessions/${sessionId}`)
}

export async function streamChat(
  body: ChatStreamRequestBody,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const auth = useAuthStore()
  const base = import.meta.env.VITE_API_BASE_URL ?? '/api/v2'
  const url = `${base}/chat/stream`
  await fetchEventSource(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      Authorization: `Bearer ${auth.accessToken ?? ''}`,
    },
    body: JSON.stringify(body),
    signal: handlers.signal,
    openWhenHidden: true,
    onopen: async (response) => {
      if (response.ok) {
        handlers.onOpen?.()
        return
      }
      if (response.status === 401 && (await auth.refresh())) {
        throw new Error('reauth-needed')
      }
      const text = await response.text().catch(() => '')
      throw new Error(text || `SSE 连接失败：${response.status}`)
    },
    onmessage(ev) {
      if (!ev.event) return
      try {
        const payload = JSON.parse(ev.data)
        if (ev.event === 'references') {
          handlers.onReferences(payload as ChatStreamReferencesEvent)
        } else if (ev.event === 'status') {
          handlers.onStatus?.(payload as ChatStreamStatusEvent)
        } else if (ev.event === 'reasoning') {
          handlers.onReasoning?.(String(payload.delta ?? ''))
        } else if (ev.event === 'content') {
          handlers.onContent(String(payload.delta ?? ''))
        } else if (ev.event === 'done') {
          handlers.onDone(payload as ChatStreamDoneEvent)
        } else if (ev.event === 'error') {
          handlers.onError(String(payload.message ?? 'LLM 错误'))
        }
      } catch (err) {
        handlers.onError(`解析 SSE 事件失败：${(err as Error).message}`)
      }
    },
    onerror(err) {
      handlers.onError(err instanceof Error ? err.message : String(err))
      throw err
    },
  })
}
