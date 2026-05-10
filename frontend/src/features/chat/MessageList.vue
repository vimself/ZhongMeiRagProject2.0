<script setup lang="ts">
import DOMPurify from 'dompurify'
import ElPopover from 'element-plus/es/components/popover/index.mjs'
import 'element-plus/theme-chalk/el-popover.css'
import MarkdownIt from 'markdown-it'
import { computed } from 'vue'

import type { ChatCitation } from '@/api/chat'
import type { LocalChatMessage } from '@/stores/chat'
import CitationCard from '@/features/chat/CitationCard.vue'

const props = defineProps<{
  messages: LocalChatMessage[]
  streaming?: boolean
}>()

const emit = defineEmits<{
  (e: 'open-citation', citation: ChatCitation): void
}>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

interface Segment {
  type: 'html' | 'cite'
  html?: string
  index?: number
}

function splitContent(content: string): Segment[] {
  if (!content) return []
  const segments: Segment[] = []
  const pattern = /\^\[(\d+)\]/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(content)) !== null) {
    if (match.index > lastIndex) {
      const chunk = content.slice(lastIndex, match.index)
      segments.push({ type: 'html', html: DOMPurify.sanitize(md.render(chunk)) })
    }
    segments.push({ type: 'cite', index: Number(match[1]) })
    lastIndex = pattern.lastIndex
  }
  if (lastIndex < content.length) {
    const chunk = content.slice(lastIndex)
    segments.push({ type: 'html', html: DOMPurify.sanitize(md.render(chunk)) })
  }
  return segments
}

function citationByIndex(msg: LocalChatMessage, index: number): ChatCitation | null {
  return msg.citations.find((c) => c.index === index) ?? null
}

const items = computed(() =>
  props.messages.map((m) => ({
    raw: m,
    segments: m.role === 'assistant' ? splitContent(m.content) : [],
  })),
)

function handleOpen(cite: ChatCitation | null) {
  if (cite) emit('open-citation', cite)
}
</script>

<template>
  <div class="message-list">
    <template v-for="{ raw: msg, segments } in items" :key="msg.id">
      <div class="message" :class="`message--${msg.role}`">
        <div class="message__meta">
          <span class="message__role">
            {{ msg.role === 'user' ? '你' : msg.role === 'assistant' ? '中煤 RAG' : '系统' }}
          </span>
          <span v-if="msg.model" class="message__model">{{ msg.model }}</span>
          <span v-if="msg.status === 'error'" class="message__status message__status--error">
            错误
          </span>
          <span v-else-if="msg.status === 'streaming'" class="message__status"> 生成中… </span>
        </div>

        <div v-if="msg.role === 'user'" class="message__bubble message__bubble--user">
          {{ msg.content }}
        </div>

        <div v-else class="message__bubble message__bubble--assistant">
          <div v-if="!msg.content && msg.status === 'streaming'" class="message__typing">
            <span class="dot" /><span class="dot" /><span class="dot" />
          </div>
          <div v-else class="markdown-body">
            <template v-for="(seg, i) in segments" :key="i">
              <!-- eslint-disable-next-line vue/no-v-html -->
              <span v-if="seg.type === 'html'" v-html="seg.html" />
              <ElPopover
                v-else
                :width="300"
                trigger="hover"
                placement="top"
                :show-arrow="true"
                :hide-after="120"
                :offset="6"
              >
                <template #reference>
                  <button
                    type="button"
                    class="cite-chip"
                    @click="handleOpen(citationByIndex(msg, seg.index!))"
                  >
                    ^[{{ seg.index }}]
                  </button>
                </template>
                <CitationCard
                  v-if="citationByIndex(msg, seg.index!)"
                  :citation="citationByIndex(msg, seg.index!)!"
                  compact
                />
                <p v-else class="cite-missing">该引用不存在或已失效</p>
              </ElPopover>
            </template>
          </div>

          <div v-if="msg.error" class="message__error">
            {{ msg.error }}
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.message-list {
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding: 24px 28px 140px;
}

.message {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: min(820px, 100%);
}

.message--user {
  align-self: flex-end;
  align-items: flex-end;
}

.message--assistant {
  align-self: flex-start;
}

.message__meta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #6b7280;
  font-size: 11px;
  letter-spacing: 0.04em;
}

.message__role {
  text-transform: uppercase;
  color: #111827;
  font-weight: 600;
}

.message__model {
  color: #9ca3af;
}

.message__status {
  color: #0f766e;
  font-weight: 500;
}

.message__status--error {
  color: #b91c1c;
}

.message__bubble {
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.75;
  color: #111827;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.message__bubble--user {
  background: #111827;
  color: #fafaf9;
  border-color: #111827;
  white-space: pre-wrap;
}

.message__bubble--assistant {
  background: #fff;
  color: #111827;
}

.message__typing {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  padding: 4px 0;
}

.message__typing .dot {
  width: 6px;
  height: 6px;
  background: #9ca3af;
  border-radius: 50%;
  animation: typing 1.2s infinite ease-in-out both;
}

.message__typing .dot:nth-child(2) {
  animation-delay: 0.15s;
}

.message__typing .dot:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes typing {
  0%,
  80%,
  100% {
    opacity: 0.3;
    transform: translateY(0);
  }

  40% {
    opacity: 1;
    transform: translateY(-2px);
  }
}

.message__error {
  margin-top: 10px;
  padding: 8px 10px;
  color: #b91c1c;
  font-size: 12.5px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
}

.cite-chip {
  all: unset;
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  margin: 0 2px;
  color: #0f766e;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 18px;
  cursor: pointer;
  border: 1px solid rgb(15 118 110 / 30%);
  border-radius: 999px;
  background: rgb(15 118 110 / 6%);
  transition:
    background 0.12s ease,
    border-color 0.12s ease;
  vertical-align: baseline;
  font-variant-numeric: tabular-nums;
}

.cite-chip:hover {
  background: rgb(15 118 110 / 12%);
  border-color: #0f766e;
}

.cite-chip:focus-visible {
  outline: 2px solid rgb(15 118 110 / 35%);
  outline-offset: 2px;
}

.cite-missing {
  margin: 0;
  color: #6b7280;
  font-size: 12px;
}

.markdown-body :deep(p) {
  margin: 0 0 8px;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 4px 0 8px;
  padding-left: 22px;
}

.markdown-body :deep(code) {
  padding: 1px 5px;
  background: #f5f5f4;
  border-radius: 4px;
  font-size: 12.5px;
}

.markdown-body :deep(pre) {
  margin: 8px 0;
  padding: 10px 12px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 6px;
  overflow-x: auto;
}

.markdown-body :deep(pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
}

.markdown-body :deep(a) {
  color: #0f766e;
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
}

.markdown-body :deep(blockquote) {
  margin: 6px 0;
  padding: 6px 10px;
  color: #4b5563;
  background: #fafaf9;
  border-left: 3px solid #e5e7eb;
  border-radius: 0 4px 4px 0;
}

.markdown-body :deep(table) {
  width: 100%;
  margin: 8px 0;
  border-collapse: collapse;
  font-size: 12.5px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 6px 8px;
  border: 1px solid #e5e7eb;
}

.markdown-body :deep(th) {
  background: #fafaf9;
  font-weight: 600;
}
</style>
