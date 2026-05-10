import { defineStore } from 'pinia'

import {
  type ChatCitation,
  type ChatMessageDTO,
  type ChatSessionSummary,
  type ChatStreamDoneEvent,
  deleteChatSession,
  getChatSession,
  listChatSessions,
  streamChat,
} from '@/api/chat'

export interface LocalChatMessage extends Omit<ChatMessageDTO, 'citations'> {
  citations: ChatCitation[]
  /** 'streaming' | 'done' | 'error' */
  status: 'streaming' | 'done' | 'error'
  /** 流式过程中的错误信息 */
  error?: string | null
}

interface ChatStoreState {
  sessions: ChatSessionSummary[]
  activeSessionId: string | null
  activeKbId: string | null
  messages: LocalChatMessage[]
  /** 最近一次检索的引用（按 index 存） */
  latestReferences: ChatCitation[]
  loadingList: boolean
  loadingDetail: boolean
  streaming: boolean
  error: string | null
  abortController: AbortController | null
}

function now(): string {
  return new Date().toISOString()
}

function tempId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export const useChatStore = defineStore('chat', {
  state: (): ChatStoreState => ({
    sessions: [],
    activeSessionId: null,
    activeKbId: null,
    messages: [],
    latestReferences: [],
    loadingList: false,
    loadingDetail: false,
    streaming: false,
    error: null,
    abortController: null,
  }),
  getters: {
    hasActiveSession: (s) => Boolean(s.activeSessionId),
  },
  actions: {
    setKb(kbId: string | null) {
      this.activeKbId = kbId
    },
    async fetchSessions() {
      this.loadingList = true
      try {
        const resp = await listChatSessions({ page: 1, page_size: 50 })
        this.sessions = resp.data.items
      } finally {
        this.loadingList = false
      }
    },
    async loadSession(sessionId: string) {
      this.loadingDetail = true
      try {
        const resp = await getChatSession(sessionId)
        this.activeSessionId = sessionId
        this.activeKbId = resp.data.knowledge_base_id ?? this.activeKbId
        this.messages = resp.data.messages.map((m) => ({
          ...m,
          citations: m.citations ?? [],
          status: 'done',
        }))
        // 预填 latestReferences 为最新 assistant 消息的引用（便于右侧面板）
        const lastAssistant = [...this.messages].reverse().find((m) => m.role === 'assistant')
        this.latestReferences = lastAssistant?.citations ?? []
      } finally {
        this.loadingDetail = false
      }
    },
    resetConversation(kbId?: string) {
      this.activeSessionId = null
      if (kbId) this.activeKbId = kbId
      this.messages = []
      this.latestReferences = []
      this.error = null
    },
    async removeSession(sessionId: string) {
      await deleteChatSession(sessionId)
      this.sessions = this.sessions.filter((s) => s.id !== sessionId)
      if (this.activeSessionId === sessionId) {
        this.resetConversation(this.activeKbId ?? undefined)
      }
    },
    async sendQuestion(question: string, k?: number) {
      if (!this.activeKbId) {
        this.error = '请先在左侧选择知识库'
        return
      }
      if (this.streaming) return
      const trimmed = question.trim()
      if (!trimmed) return
      this.error = null
      const abort = new AbortController()
      this.abortController = abort

      const userMsg: LocalChatMessage = {
        id: tempId('u'),
        role: 'user',
        content: trimmed,
        finish_reason: null,
        model: null,
        created_at: now(),
        citations: [],
        status: 'done',
      }
      const assistantMsg: LocalChatMessage = {
        id: tempId('a'),
        role: 'assistant',
        content: '',
        finish_reason: null,
        model: null,
        created_at: now(),
        citations: [],
        status: 'streaming',
      }
      this.messages.push(userMsg, assistantMsg)
      this.streaming = true
      try {
        await streamChat(
          {
            kb_id: this.activeKbId,
            question: trimmed,
            session_id: this.activeSessionId ?? undefined,
            k,
          },
          {
            signal: abort.signal,
            onReferences: (payload) => {
              this.activeSessionId = payload.session_id
              this.latestReferences = payload.references
              assistantMsg.citations = payload.references
            },
            onContent: (delta) => {
              assistantMsg.content += delta
            },
            onDone: (payload: ChatStreamDoneEvent) => {
              assistantMsg.finish_reason = payload.finish_reason
              assistantMsg.model = payload.model
              assistantMsg.status = 'done'
            },
            onError: (message) => {
              assistantMsg.status = 'error'
              assistantMsg.error = message
              this.error = message
            },
          },
        )
      } catch (err) {
        assistantMsg.status = 'error'
        assistantMsg.error = (err as Error).message || '网络错误'
        this.error = assistantMsg.error
      } finally {
        this.streaming = false
        this.abortController = null
      }
    },
    stop() {
      this.abortController?.abort()
      this.streaming = false
    },
  },
})
