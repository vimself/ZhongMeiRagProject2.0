<script setup lang="ts">
import DOMPurify from 'dompurify'
import katex from 'katex'
import MarkdownIt from 'markdown-it'
import { computed } from 'vue'
import 'katex/dist/katex.min.css'

import { formatCitationReference, orderedCitations } from '@/features/chat/citationDisplay'
import type { LocalChatMessage } from '@/stores/chat'

const props = defineProps<{
  messages: LocalChatMessage[]
  streaming?: boolean
}>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

interface MathToken {
  block: boolean
  content: string
  map: [number, number] | null
  markup: string
  meta?: {
    displayMode?: boolean
  }
}

interface MathInlineState {
  pos: number
  src: string
  push(type: string, tag: string, nesting: number): MathToken
}

interface MathBlockState {
  bMarks: number[]
  eMarks: number[]
  line: number
  src: string
  tShift: number[]
  push(type: string, tag: string, nesting: number): MathToken
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function isEscaped(src: string, index: number): boolean {
  let slashCount = 0
  for (let cursor = index - 1; cursor >= 0 && src[cursor] === '\\'; cursor -= 1) {
    slashCount += 1
  }
  return slashCount % 2 === 1
}

function findClosingDollar(src: string, from: number): number {
  for (let cursor = from; cursor < src.length; cursor += 1) {
    if (src[cursor] === '$' && src[cursor + 1] !== '$' && !isEscaped(src, cursor)) {
      return cursor
    }
  }
  return -1
}

function findClosingSequence(src: string, delimiter: string): number {
  let cursor = 0
  while (cursor < src.length) {
    const found = src.indexOf(delimiter, cursor)
    if (found < 0) return -1
    if (delimiter !== '$$' || !isEscaped(src, found)) return found
    cursor = found + delimiter.length
  }
  return -1
}

function hasLikelyMathContent(expr: string): boolean {
  const content = expr.trim()
  return (
    content.length > 0 &&
    /\\[a-zA-Z]+|[=<>^_{}]|[+\-*/×÷]|[≤≥≈≠∑∫√]|[A-Za-z]\s*\(|\d\s*[A-Za-z%°]/.test(content)
  )
}

function renderMath(expr: string, displayMode: boolean): string {
  const content = expr.trim()
  try {
    return katex.renderToString(content, {
      displayMode,
      output: 'html',
      strict: 'ignore',
      throwOnError: false,
      trust: false,
    })
  } catch {
    return `<code class="math-fallback">${escapeHtml(content)}</code>`
  }
}

function pushMathToken(
  state: MathInlineState,
  expr: string,
  displayMode: boolean,
  markup: string,
): void {
  const token = state.push('math_inline', 'math', 0)
  token.content = expr
  token.markup = markup
  token.meta = { displayMode }
}

function mathInlineRule(state: MathInlineState, silent: boolean): boolean {
  const start = state.pos
  const src = state.src

  if (src.startsWith('\\(', start) || src.startsWith('\\[', start)) {
    const displayMode = src.startsWith('\\[', start)
    const close = displayMode ? '\\]' : '\\)'
    const end = src.indexOf(close, start + 2)
    if (end < 0) return false
    const expr = src.slice(start + 2, end)
    if (!hasLikelyMathContent(expr)) return false
    if (!silent) pushMathToken(state, expr, displayMode, displayMode ? '\\[\\]' : '\\(\\)')
    state.pos = end + close.length
    return true
  }

  if (src[start] !== '$' || src[start + 1] === '$' || isEscaped(src, start)) return false
  if (!src[start + 1] || /\s/.test(src[start + 1])) return false
  const end = findClosingDollar(src, start + 1)
  if (end < 0 || /\s/.test(src[end - 1])) return false
  const expr = src.slice(start + 1, end)
  if (!hasLikelyMathContent(expr)) return false
  if (!silent) pushMathToken(state, expr, false, '$')
  state.pos = end + 1
  return true
}

function mathBlockRule(
  state: MathBlockState,
  startLine: number,
  endLine: number,
  silent: boolean,
): boolean {
  const start = state.bMarks[startLine] + state.tShift[startLine]
  const max = state.eMarks[startLine]
  const firstLine = state.src.slice(start, max).trim()
  const delimiter = firstLine.startsWith('$$') ? '$$' : firstLine.startsWith('\\[') ? '\\]' : ''
  if (!delimiter) return false

  const openLength = delimiter === '$$' ? 2 : 2
  const contentLines: string[] = []
  const firstContent = firstLine.slice(openLength)
  const firstClose = findClosingSequence(firstContent, delimiter)
  let nextLine = startLine + 1
  let foundClose = firstClose >= 0

  if (foundClose) {
    contentLines.push(firstContent.slice(0, firstClose))
  } else {
    contentLines.push(firstContent)
    for (; nextLine < endLine; nextLine += 1) {
      const lineStart = state.bMarks[nextLine] + state.tShift[nextLine]
      const lineMax = state.eMarks[nextLine]
      const line = state.src.slice(lineStart, lineMax)
      const closeIndex = findClosingSequence(line, delimiter)
      if (closeIndex >= 0) {
        contentLines.push(line.slice(0, closeIndex))
        nextLine += 1
        foundClose = true
        break
      }
      contentLines.push(line)
    }
  }

  const expr = contentLines.join('\n').trim()
  if (!foundClose || !hasLikelyMathContent(expr)) return false
  if (silent) return true

  const token = state.push('math_block', 'math', 0)
  token.block = true
  token.content = expr
  token.markup = delimiter === '$$' ? '$$' : '\\[\\]'
  token.map = [startLine, nextLine]
  state.line = nextLine
  return true
}

md.inline.ruler.before('text', 'math_inline', mathInlineRule)
md.block.ruler.before('fence', 'math_block', mathBlockRule, {
  alt: ['paragraph', 'reference', 'blockquote', 'list'],
})
md.renderer.rules.math_inline = (tokens, idx) => {
  const displayMode = Boolean(tokens[idx].meta?.displayMode)
  const className = displayMode ? 'math-display math-display--inline' : 'math-inline'
  return `<span class="${className}">${renderMath(tokens[idx].content, displayMode)}</span>`
}
md.renderer.rules.math_block = (tokens, idx) =>
  `<div class="math-display">${renderMath(tokens[idx].content, true)}</div>\n`

function stripReferenceSection(content: string): string {
  const lines = content.split(/\r?\n/)
  const marker =
    /^(#{1,6}\s*)?(\*\*)?\s*(引用依据|引用内容|参考文档|参考资料|参考来源|References)\s*[:：]?\s*(\*\*)?\s*$/i
  const index = lines.findIndex((line) => marker.test(line.trim()))
  return index >= 0 ? lines.slice(0, index).join('\n') : content
}

function normalizeAnswerContent(content: string): string {
  return stripReferenceSection(content)
    .replace(/\[cite:\d+\]/g, '')
    .replace(/\^\[\d+\]/g, '')
    .replace(/\[\^\d+\]/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function renderContent(content: string): string {
  return DOMPurify.sanitize(md.render(normalizeAnswerContent(content)))
}

const items = computed(() =>
  props.messages.map((m) => ({
    raw: m,
    html: m.role === 'assistant' ? renderContent(m.content) : '',
    sources: orderedCitations(m.citations),
  })),
)
</script>

<template>
  <div class="message-list">
    <template v-for="{ raw: msg, html, sources } in items" :key="msg.id">
      <div class="message" :class="`message--${msg.role}`">
        <div class="message__meta">
          <span class="message__role">
            {{ msg.role === 'user' ? '用户' : msg.role === 'assistant' ? '中煤 RAG' : '系统' }}
          </span>
          <span v-if="msg.status === 'error'" class="message__status message__status--error">
            错误
          </span>
          <span v-else-if="msg.status === 'streaming'" class="message__status">
            {{ msg.progressText || '生成中…' }}
          </span>
        </div>

        <div v-if="msg.role === 'user'" class="message__bubble message__bubble--user">
          {{ msg.content }}
        </div>

        <div v-else class="message__bubble message__bubble--assistant">
          <details
            v-if="msg.reasoningContent"
            class="message__reasoning"
            :open="msg.status === 'streaming' && !msg.content"
          >
            <summary>
              <span>思考过程</span>
              <small>
                {{ msg.status === 'streaming' && !msg.content ? '实时生成' : '已完成' }}
              </small>
            </summary>
            <div class="message__reasoning-body">{{ msg.reasoningContent }}</div>
          </details>

          <div v-if="!msg.content && msg.status === 'streaming'" class="message__typing">
            <span class="dot" /><span class="dot" /><span class="dot" />
          </div>
          <!-- eslint-disable-next-line vue/no-v-html -->
          <div v-else-if="msg.content" class="markdown-body" v-html="html" />

          <div
            v-if="msg.status === 'done' && sources.length > 0 && msg.content"
            class="answer-sources"
          >
            <div class="answer-sources__head">参考文档</div>
            <div v-for="source in sources" :key="source.id" class="answer-source">
              <span class="answer-source__mark" aria-hidden="true" />
              <span class="answer-source__title">{{ formatCitationReference(source) }}</span>
            </div>
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
  background: #fff;
  color: #111827;
  border-color: #e5e7eb;
  white-space: pre-wrap;
}

.message__bubble--assistant {
  background: #fff;
  color: #111827;
  min-width: min(620px, 100%);
}

.message__reasoning {
  margin-bottom: 12px;
  color: #4b5563;
  background: #fafaf9;
  border: 1px solid #e7e5e4;
  border-radius: 8px;
}

.message__reasoning summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  cursor: pointer;
  color: #374151;
  font-size: 12px;
  font-weight: 600;
  list-style: none;
}

.message__reasoning summary::-webkit-details-marker {
  display: none;
}

.message__reasoning small {
  color: #0f766e;
  font-size: 11px;
  font-weight: 500;
}

.message__reasoning-body {
  max-height: 180px;
  padding: 0 10px 10px;
  overflow-y: auto;
  white-space: pre-wrap;
  color: #6b7280;
  font-size: 12.5px;
  line-height: 1.65;
  border-top: 1px solid #e7e5e4;
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

.answer-sources {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #f0f0ef;
}

.answer-sources__head {
  color: #6b7280;
  font-size: 12px;
  font-weight: 600;
}

.answer-source {
  display: grid;
  grid-template-columns: 7px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 6px;
  background: #f8faf9;
}

.answer-source__mark {
  width: 7px;
  height: 7px;
  background: #0f766e;
  border-radius: 50%;
}

.answer-source__title {
  color: #111827;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.7;
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

.markdown-body :deep(.math-inline) {
  display: inline-block;
  max-width: 100%;
  overflow: auto hidden;
  vertical-align: -0.08em;
  white-space: nowrap;
}

.markdown-body :deep(.math-display) {
  display: block;
  max-width: 100%;
  margin: 10px 0;
  padding: 10px 12px;
  overflow: auto hidden;
  background: #f8faf9;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.markdown-body :deep(.math-display--inline) {
  margin: 8px 0;
}

.markdown-body :deep(.math-display .katex-display) {
  margin: 0;
  text-align: left;
}

.markdown-body :deep(.math-fallback) {
  white-space: pre-wrap;
}
</style>
