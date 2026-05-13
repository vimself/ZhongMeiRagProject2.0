<script setup lang="ts">
import { ArrowLeft, ChatLineRound, Delete, Plus, Refresh } from '@element-plus/icons-vue'
import ElButton from 'element-plus/es/components/button/index.mjs'
import ElIcon from 'element-plus/es/components/icon/index.mjs'
import ElSelect, { ElOption } from 'element-plus/es/components/select/index.mjs'
import ElEmpty from 'element-plus/es/components/empty/index.mjs'
import ElMessageBox from 'element-plus/es/components/message-box/index.mjs'
import ElMessage from 'element-plus/es/components/message/index.mjs'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-select.css'
import 'element-plus/theme-chalk/el-tag.css'
import 'element-plus/theme-chalk/el-empty.css'
import 'element-plus/theme-chalk/el-message-box.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-overlay.css'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { ChatCitation } from '@/api/chat'
import { listKnowledgeBases } from '@/api/knowledge'
import { pdfPreviewUrl, signPdfToken } from '@/api/pdfPreview'
import type { KnowledgeBaseOut } from '@/api/types'
import CitationPane from '@/features/chat/CitationPane.vue'
import Composer from '@/features/chat/Composer.vue'
import MessageList from '@/features/chat/MessageList.vue'
import { useChatStore } from '@/stores/chat'
import { formatBeijingDate } from '@/utils/time'

const router = useRouter()
const route = useRoute()
const chat = useChatStore()

const kbList = ref<KnowledgeBaseOut[]>([])
const loadingKb = ref(false)
const scrollerRef = ref<HTMLDivElement>()

const activeKbName = computed(() => {
  if (!chat.activeKbId) return ''
  return kbList.value.find((k) => k.id === chat.activeKbId)?.name || ''
})

const hasEvidence = computed(() => chat.latestReferences.length > 0)

const emptyHint = computed(() => {
  if (!chat.activeKbId) return '请先选择左上角的知识库，再开始提问。'
  if (chat.messages.length === 0) return '向当前知识库发起提问，回答完成后会展示可用依据。'
  return ''
})

async function loadKnowledgeBases() {
  loadingKb.value = true
  try {
    const resp = await listKnowledgeBases({ page: 1, page_size: 100 })
    kbList.value = resp.data.items
    // 若 query 指定 kb_id
    const kbFromQuery = String(route.query.kb_id || '').trim()
    if (kbFromQuery && kbList.value.some((k) => k.id === kbFromQuery)) {
      chat.setKb(kbFromQuery)
    } else if (!chat.activeKbId && kbList.value.length > 0) {
      chat.setKb(kbList.value[0].id)
    }
  } catch (err) {
    ElMessage.error('知识库列表加载失败：' + (err as Error).message)
  } finally {
    loadingKb.value = false
  }
}

async function scrollToBottom() {
  await nextTick()
  const el = scrollerRef.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
}

function handleKbChange(id: string) {
  chat.setKb(id)
  chat.resetConversation(id)
}

function handleNewChat() {
  chat.resetConversation(chat.activeKbId ?? undefined)
}

async function handleSelectSession(sessionId: string) {
  try {
    await chat.loadSession(sessionId)
    await scrollToBottom()
  } catch (err) {
    ElMessage.error('加载会话失败：' + (err as Error).message)
  }
}

async function handleDeleteSession(id: string) {
  try {
    await ElMessageBox.confirm('确定要删除该会话吗？删除后无法恢复。', '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await chat.removeSession(id)
    ElMessage.success('会话已删除')
  } catch (err) {
    ElMessage.error('删除失败：' + (err as Error).message)
  }
}

async function handleSubmit(question: string) {
  await chat.sendQuestion(question)
  await scrollToBottom()
  await chat.fetchSessions()
}

function withPdfPageHash(url: string, page?: number | null): string {
  if (!page || page < 1) return url
  return `${url}#page=${page}`
}

async function openCitation(citation: ChatCitation) {
  const previewWindow = window.open('about:blank', '_blank')
  if (previewWindow) {
    previewWindow.opener = null
  }
  try {
    const { data } = await signPdfToken(citation.document_id)
    const url = withPdfPageHash(pdfPreviewUrl(data.document_id, data.token), citation.page_start)
    if (previewWindow) {
      previewWindow.location.href = url
    } else {
      window.open(url, '_blank')
    }
  } catch (err) {
    previewWindow?.close()
    ElMessage.error('PDF 预览链接签发失败：' + (err as Error).message)
  }
}

watch(
  () => chat.messages.length,
  () => scrollToBottom(),
)

watch(
  () => chat.streaming,
  () => scrollToBottom(),
)

watch(
  () =>
    chat.messages.map((m) => `${m.content.length}:${m.reasoningContent?.length ?? 0}`).join('|'),
  () => scrollToBottom(),
)

onMounted(async () => {
  await loadKnowledgeBases()
  await chat.fetchSessions()
})
</script>

<template>
  <div class="chat-shell" :class="{ 'chat-shell--with-evidence': hasEvidence }">
    <aside class="chat-sidebar">
      <header class="chat-sidebar__head">
        <ElButton text size="small" :icon="ArrowLeft" @click="router.push('/')">返回首页</ElButton>
        <span class="chat-sidebar__brand">RAG 问答工作台</span>
      </header>

      <section class="chat-sidebar__kb">
        <label class="chat-sidebar__label">当前知识库</label>
        <ElSelect
          :model-value="chat.activeKbId"
          :disabled="loadingKb || chat.streaming"
          placeholder="选择知识库"
          size="default"
          class="chat-sidebar__select"
          @change="handleKbChange"
        >
          <ElOption v-for="kb in kbList" :key="kb.id" :label="kb.name" :value="kb.id" />
        </ElSelect>
      </section>

      <section class="chat-sidebar__actions">
        <ElButton
          type="primary"
          plain
          :icon="Plus"
          :disabled="!chat.activeKbId || chat.streaming"
          @click="handleNewChat"
        >
          新建对话
        </ElButton>
        <ElButton :icon="Refresh" :loading="chat.loadingList" @click="chat.fetchSessions()">
          刷新
        </ElButton>
      </section>

      <section class="chat-sidebar__sessions">
        <div class="chat-sidebar__section-title">历史会话</div>
        <div v-if="chat.loadingList && chat.sessions.length === 0" class="chat-sidebar__hint">
          加载中…
        </div>
        <ElEmpty
          v-else-if="chat.sessions.length === 0"
          description="暂无会话"
          :image-size="60"
          class="chat-sidebar__empty"
        />
        <ul v-else class="chat-sidebar__list">
          <li
            v-for="s in chat.sessions"
            :key="s.id"
            class="chat-sidebar__item"
            :class="{ active: s.id === chat.activeSessionId }"
          >
            <button type="button" class="chat-sidebar__item-btn" @click="handleSelectSession(s.id)">
              <ElIcon class="chat-sidebar__item-icon"><ChatLineRound /></ElIcon>
              <div class="chat-sidebar__item-body">
                <div class="chat-sidebar__item-title" :title="s.title">{{ s.title }}</div>
                <div class="chat-sidebar__item-meta">
                  {{ s.message_count }} 条 · {{ formatBeijingDate(s.updated_at) }}
                </div>
              </div>
            </button>
            <button
              type="button"
              class="chat-sidebar__item-del"
              title="删除会话"
              @click.stop="handleDeleteSession(s.id)"
            >
              <ElIcon><Delete /></ElIcon>
            </button>
          </li>
        </ul>
      </section>
    </aside>

    <main class="chat-main">
      <header class="chat-main__head">
        <div class="chat-main__head-title">
          <span class="chat-main__head-dot" />
          <span class="chat-main__head-text">
            {{ activeKbName ? activeKbName : '未选择知识库' }}
          </span>
          <span v-if="chat.activeSessionId" class="chat-main__head-meta">
            · 会话 {{ chat.activeSessionId.slice(0, 8) }}
          </span>
        </div>
        <div v-if="chat.streaming" class="chat-main__head-status">正在生成…</div>
      </header>

      <div ref="scrollerRef" class="chat-main__scroll">
        <div v-if="chat.messages.length === 0 && !chat.loadingDetail" class="chat-empty">
          <div class="chat-empty__title">工程 RAG 问答</div>
          <div class="chat-empty__subtitle">{{ emptyHint }}</div>
          <ul class="chat-empty__hints">
            <li>回答由所选知识库的检索结果生成，正文会优先展示可读结论。</li>
            <li>参考文档会在答案下方汇总，右侧证据面板可打开 PDF 预览。</li>
            <li>无依据时将返回「未找到依据」，不编造内容。</li>
          </ul>
        </div>
        <MessageList v-else :messages="chat.messages" :streaming="chat.streaming" />
        <div v-if="chat.error" class="chat-main__error">{{ chat.error }}</div>
      </div>

      <Composer
        :disabled="!chat.activeKbId"
        :streaming="chat.streaming"
        @submit="handleSubmit"
        @stop="chat.stop()"
      />
    </main>

    <CitationPane
      v-if="hasEvidence"
      class="chat-rightpane"
      :references="chat.latestReferences"
      :loading="false"
      @open="openCitation"
    />
  </div>
</template>

<style scoped>
.chat-shell {
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
  --zm-shadow: 0 18px 42px rgb(15 23 42 / 5%);
  --zm-shadow-strong: 0 24px 60px rgb(15 23 42 / 7%);

  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  height: 100vh;
  min-height: 600px;
  background: var(--zm-bg);
  color: var(--zm-text-strong);
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB',
    'Microsoft YaHei', sans-serif;
}

.chat-shell--with-evidence {
  grid-template-columns: 280px minmax(0, 1fr) 340px;
}

.chat-sidebar {
  display: flex;
  flex-direction: column;
  background: var(--zm-surface);
  border-right: 1px solid var(--zm-border-soft);
  min-width: 0;
}

.chat-sidebar__head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--zm-border-soft);
}

.chat-sidebar__head :deep(.el-button) {
  color: var(--zm-text-muted);
  font-size: 13px;
  transition: color 0.15s ease;
}

.chat-sidebar__head :deep(.el-button:hover) {
  color: var(--zm-primary);
}

.chat-sidebar__brand {
  color: var(--zm-text-strong);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.chat-sidebar__kb {
  padding: 16px 16px 12px;
}

.chat-sidebar__label {
  display: block;
  margin-bottom: 8px;
  color: var(--zm-text-muted);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.chat-sidebar__select {
  width: 100%;
}

.chat-sidebar__actions {
  display: flex;
  gap: 8px;
  padding: 8px 16px 16px;
}

.chat-sidebar__actions :deep(.el-button) {
  flex: 1;
  height: 36px;
  border-radius: var(--zm-radius);
  font-weight: 500;
}

.chat-sidebar__sessions {
  flex: 1;
  min-height: 0;
  padding: 8px 12px 16px;
  overflow-y: auto;
  border-top: 1px solid var(--zm-border-soft);
}

.chat-sidebar__section-title {
  padding: 12px 4px 8px;
  color: var(--zm-text-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.chat-sidebar__hint {
  padding: 12px 4px;
  color: var(--zm-text-muted);
  font-size: 12px;
}

.chat-sidebar__empty {
  padding-top: 12px;
}

.chat-sidebar__list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.chat-sidebar__item {
  display: flex;
  position: relative;
  align-items: stretch;
  border-radius: var(--zm-radius);
  transition: background 0.15s ease;
}

.chat-sidebar__item:hover {
  background: var(--zm-bg-soft);
}

.chat-sidebar__item.active {
  background: var(--zm-teal-soft);
}

.chat-sidebar__item-btn {
  all: unset;
  display: flex;
  flex: 1;
  gap: 12px;
  align-items: flex-start;
  padding: 12px;
  cursor: pointer;
  border-radius: var(--zm-radius);
  min-width: 0;
  transition: background 0.15s ease;
  outline: none;
}

.chat-sidebar__item-btn:hover {
  background: transparent;
}

.chat-sidebar__item-btn:focus-visible {
  box-shadow: 0 0 0 2px var(--zm-primary);
  background: var(--zm-teal-soft);
}

.chat-sidebar__item-icon {
  margin-top: 2px;
  color: var(--zm-text-muted);
  font-size: 15px;
  transition: color 0.15s ease;
}

.chat-sidebar__item.active .chat-sidebar__item-icon {
  color: var(--zm-primary);
}

.chat-sidebar__item-body {
  flex: 1;
  min-width: 0;
}

.chat-sidebar__item-title {
  color: var(--zm-text-strong);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

.chat-sidebar__item.active .chat-sidebar__item-title {
  color: var(--zm-primary);
  font-weight: 600;
}

.chat-sidebar__item-meta {
  margin-top: 4px;
  color: var(--zm-text-muted);
  font-size: 11px;
  line-height: 1.3;
}

.chat-sidebar__item-del {
  all: unset;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  color: var(--zm-border);
  cursor: pointer;
  border-radius: 0 var(--zm-radius) var(--zm-radius) 0;
  opacity: 0;
  transition:
    opacity 0.15s ease,
    color 0.15s ease,
    background 0.15s ease;
  outline: none;
}

.chat-sidebar__item-del:hover {
  color: #b91c1c;
  background: #fef2f2;
}

.chat-sidebar__item-del:focus-visible {
  opacity: 1;
  box-shadow: 0 0 0 2px var(--zm-primary);
}

.chat-sidebar__item:hover .chat-sidebar__item-del {
  opacity: 1;
}

.chat-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--zm-bg);
}

.chat-main__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: var(--zm-surface);
  border-bottom: 1px solid var(--zm-border-soft);
}

.chat-main__head-title {
  display: inline-flex;
  gap: 12px;
  align-items: center;
  color: var(--zm-text-strong);
  font-size: 15px;
  font-weight: 600;
}

.chat-main__head-dot {
  width: 8px;
  height: 8px;
  background: var(--zm-primary);
  border-radius: 50%;
  box-shadow: 0 0 0 3px var(--zm-teal-soft);
}

.chat-main__head-meta {
  color: var(--zm-text-muted);
  font-weight: 400;
  font-size: 12px;
}

.chat-main__head-status {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  padding: 6px 14px;
  color: var(--zm-primary);
  font-size: 12px;
  font-weight: 500;
  background: var(--zm-teal-soft);
  border: 1px solid rgb(15 118 110 / 16%);
  border-radius: 999px;
}

.chat-main__head-status::before {
  content: '';
  width: 6px;
  height: 6px;
  background: var(--zm-primary);
  border-radius: 50%;
  animation: pulse 1.2s infinite ease-in-out;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.4;
  }

  50% {
    opacity: 1;
  }
}

.chat-main__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.chat-main :deep(.composer) {
  flex-shrink: 0;
}

.chat-empty {
  max-width: 560px;
  margin: 16vh auto 0;
  padding: 0 24px;
  text-align: center;
}

.chat-empty__title {
  margin-bottom: 12px;
  color: var(--zm-text-strong);
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
}

.chat-empty__subtitle {
  margin-bottom: 28px;
  color: var(--zm-text-muted);
  font-size: 14px;
  line-height: 1.6;
}

.chat-empty__hints {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 20px 24px;
  margin: 0 auto;
  max-width: 480px;
  color: var(--zm-text);
  font-size: 13px;
  line-height: 1.6;
  text-align: left;
  list-style: none;
  background: var(--zm-surface);
  border: 1px solid var(--zm-border-soft);
  border-radius: var(--zm-radius);
  box-shadow: var(--zm-shadow);
}

.chat-empty__hints li {
  padding-left: 20px;
  position: relative;
}

.chat-empty__hints li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  width: 6px;
  height: 6px;
  background: var(--zm-primary);
  border-radius: 50%;
}

.chat-main__error {
  margin: 0 24px 16px;
  padding: 12px 16px;
  color: #b91c1c;
  font-size: 13px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--zm-radius);
}

.chat-rightpane {
  min-width: 0;
  background: var(--zm-surface);
  border-left: 1px solid var(--zm-border-soft);
}

@media (width <= 1100px) {
  .chat-shell--with-evidence {
    grid-template-columns: 240px minmax(0, 1fr) 320px;
  }

  .chat-shell {
    grid-template-columns: 240px minmax(0, 1fr);
  }
}

@media (width <= 880px) {
  .chat-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
    height: auto;
  }

  .chat-sidebar {
    max-height: 280px;
    border-right: none;
    border-bottom: 1px solid var(--zm-border-soft);
  }

  .chat-rightpane {
    display: none;
  }
}
</style>
