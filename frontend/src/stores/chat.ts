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
  reasoningContent?: string
  progressText?: string
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

function isNoEvidenceAnswer(content: string): boolean {
  const normalized = content.replace(/\s+/g, '')
  return (
    normalized.includes('无法在知识库中找到依据') ||
    normalized.includes('未在知识库中找到依据') ||
    normalized.includes('没有在知识库中找到依据')
  )
}

function shouldExposeCitations(message: ChatMessageDTO | LocalChatMessage): boolean {
  if (message.role !== 'assistant') return false
  if (message.finish_reason === 'no_hit') return false
  return !isNoEvidenceAnswer(message.content)
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
        this.messages = resp.data.messages.map((m) => {
          const citations = shouldExposeCitations(m) ? (m.citations ?? []) : []
          return {
            ...m,
            citations,
            status: 'done',
            reasoningContent: '',
            progressText: '',
          }
        })
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
        reasoningContent: '',
        progressText: '正在连接问答服务',
      }
      this.messages.push(userMsg, assistantMsg)
      this.latestReferences = []
      const assistantId = assistantMsg.id
      let pendingReferences: ChatCitation[] = []
      const updateAssistant = (updater: (msg: LocalChatMessage) => void) => {
        const target = this.messages.find((m) => m.id === assistantId)
        if (target) updater(target)
      }
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
            onStatus: (payload) => {
              updateAssistant((msg) => {
                msg.progressText = payload.message
              })
            },
            onReferences: (payload) => {
              this.activeSessionId = payload.session_id
              pendingReferences = payload.references
            },
            onReasoning: (delta) => {
              updateAssistant((msg) => {
                msg.reasoningContent = `${msg.reasoningContent ?? ''}${delta}`
              })
            },
            onContent: (delta) => {
              updateAssistant((msg) => {
                msg.content += delta
              })
            },
            onDone: (payload: ChatStreamDoneEvent) => {
              const target = this.messages.find((m) => m.id === assistantId)
              const shouldShowReferences =
                pendingReferences.length > 0 &&
                shouldExposeCitations({
                  ...(target ?? assistantMsg),
                  content: target?.content ?? '',
                  finish_reason: payload.finish_reason,
                  citations: pendingReferences,
                })
              updateAssistant((msg) => {
                msg.finish_reason = payload.finish_reason
                msg.model = payload.model
                msg.status = 'done'
                msg.progressText = ''
                msg.citations = shouldShowReferences ? pendingReferences : []
              })
              this.latestReferences = shouldShowReferences ? pendingReferences : []
            },
            onError: (message) => {
              updateAssistant((msg) => {
                msg.status = 'error'
                msg.error = message
                msg.citations = []
              })
              this.latestReferences = []
              this.error = message
            },
          },
        )
      } catch (err) {
        const message = (err as Error).message || '网络错误'
        updateAssistant((msg) => {
          msg.status = 'error'
          msg.error = message
          msg.citations = []
        })
        this.latestReferences = []
        this.error = message
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
