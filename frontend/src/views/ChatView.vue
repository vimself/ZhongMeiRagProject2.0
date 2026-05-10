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
import type { KnowledgeBaseOut } from '@/api/types'
import CitationPane from '@/features/chat/CitationPane.vue'
import Composer from '@/features/chat/Composer.vue'
import MessageList from '@/features/chat/MessageList.vue'
import PreviewModal from '@/features/chat/PreviewModal.vue'
import { useChatStore } from '@/stores/chat'

const router = useRouter()
const route = useRoute()
const chat = useChatStore()

const kbList = ref<KnowledgeBaseOut[]>([])
const loadingKb = ref(false)
const scrollerRef = ref<HTMLDivElement>()

const activeCitation = ref<ChatCitation | null>(null)
const previewVisible = ref(false)

const activeKbName = computed(() => {
  if (!chat.activeKbId) return ''
  return kbList.value.find((k) => k.id === chat.activeKbId)?.name || ''
})

const emptyHint = computed(() => {
  if (!chat.activeKbId) return '请先选择左上角的知识库，再开始提问。'
  if (chat.messages.length === 0) return '向当前知识库发起提问，右侧会展示检索到的引用。'
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

function openCitation(citation: ChatCitation) {
  activeCitation.value = citation
  previewVisible.value = true
}

watch(
  () => chat.messages.length,
  () => scrollToBottom(),
)

watch(
  () => chat.streaming,
  () => scrollToBottom(),
)

onMounted(async () => {
  await loadKnowledgeBases()
  await chat.fetchSessions()
})
</script>

<template>
  <div class="chat-shell">
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
                  {{ s.message_count }} 条 · {{ new Date(s.updated_at).toLocaleDateString() }}
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
            <li>回答由所选知识库的检索结果生成，每个结论都带有可追溯引用。</li>
            <li>点击 ^[n] 角标可查看证据并高亮原文位置。</li>
            <li>无依据时将返回「未找到依据」，不编造内容。</li>
          </ul>
        </div>
        <MessageList
          v-else
          :messages="chat.messages"
          :streaming="chat.streaming"
          @open-citation="openCitation"
        />
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
      class="chat-rightpane"
      :references="chat.latestReferences"
      :loading="chat.streaming && chat.latestReferences.length === 0"
      @open="openCitation"
    />

    <PreviewModal v-model="previewVisible" :citation="activeCitation" />
  </div>
</template>

<style scoped>
.chat-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 360px;
  height: 100vh;
  min-height: 600px;
  background: #fafaf9;
  color: #111827;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB',
    'Microsoft YaHei', sans-serif;
}

.chat-sidebar {
  display: flex;
  flex-direction: column;
  background: #fff;
  border-right: 1px solid #e5e7eb;
  min-width: 0;
}

.chat-sidebar__head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid #f3f4f6;
}

.chat-sidebar__brand {
  color: #111827;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.chat-sidebar__kb {
  padding: 16px 16px 8px;
}

.chat-sidebar__label {
  display: block;
  margin-bottom: 6px;
  color: #6b7280;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.chat-sidebar__select {
  width: 100%;
}

.chat-sidebar__actions {
  display: flex;
  gap: 8px;
  padding: 8px 16px 12px;
}

.chat-sidebar__actions :deep(.el-button) {
  flex: 1;
}

.chat-sidebar__sessions {
  flex: 1;
  min-height: 0;
  padding: 6px 10px 14px;
  overflow-y: auto;
  border-top: 1px solid #f3f4f6;
}

.chat-sidebar__section-title {
  padding: 8px 6px;
  color: #6b7280;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.chat-sidebar__hint {
  padding: 12px 6px;
  color: #9ca3af;
  font-size: 12px;
}

.chat-sidebar__empty {
  padding-top: 8px;
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
  border-radius: 8px;
  transition: background 0.12s ease;
}

.chat-sidebar__item:hover {
  background: #fafaf9;
}

.chat-sidebar__item.active {
  background: #f0fdf9;
}

.chat-sidebar__item-btn {
  all: unset;
  display: flex;
  flex: 1;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 10px 10px 12px;
  cursor: pointer;
  border-radius: 8px;
  min-width: 0;
}

.chat-sidebar__item-icon {
  margin-top: 2px;
  color: #6b7280;
  font-size: 14px;
}

.chat-sidebar__item.active .chat-sidebar__item-icon {
  color: #0f766e;
}

.chat-sidebar__item-body {
  flex: 1;
  min-width: 0;
}

.chat-sidebar__item-title {
  color: #111827;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-sidebar__item-meta {
  margin-top: 3px;
  color: #9ca3af;
  font-size: 11px;
}

.chat-sidebar__item-del {
  all: unset;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  color: #d1d5db;
  cursor: pointer;
  border-radius: 0 8px 8px 0;
  opacity: 0;
  transition:
    opacity 0.12s ease,
    color 0.12s ease;
}

.chat-sidebar__item-del:hover {
  color: #b91c1c;
}

.chat-sidebar__item:hover .chat-sidebar__item-del {
  opacity: 1;
}

.chat-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fafaf9;
}

.chat-main__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 22px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
}

.chat-main__head-title {
  display: inline-flex;
  gap: 10px;
  align-items: center;
  color: #111827;
  font-size: 14px;
  font-weight: 600;
}

.chat-main__head-dot {
  width: 6px;
  height: 6px;
  background: #0f766e;
  border-radius: 50%;
}

.chat-main__head-meta {
  color: #9ca3af;
  font-weight: 400;
  font-size: 12px;
}

.chat-main__head-status {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  padding: 4px 10px;
  color: #0f766e;
  font-size: 12px;
  background: #f0fdf9;
  border: 1px solid rgb(15 118 110 / 24%);
  border-radius: 999px;
}

.chat-main__head-status::before {
  content: '';
  width: 6px;
  height: 6px;
  background: #0f766e;
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

.chat-empty {
  max-width: 620px;
  margin: 14vh auto 0;
  padding: 0 24px;
  text-align: center;
}

.chat-empty__title {
  margin-bottom: 10px;
  color: #111827;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.chat-empty__subtitle {
  margin-bottom: 22px;
  color: #6b7280;
  font-size: 13.5px;
  line-height: 1.7;
}

.chat-empty__hints {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 20px;
  margin: 0 auto;
  max-width: 520px;
  color: #374151;
  font-size: 12.5px;
  line-height: 1.7;
  text-align: left;
  list-style: disc;
  padding-left: 40px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.chat-empty__hints li::marker {
  color: #0f766e;
}

.chat-main__error {
  margin: 0 28px 16px;
  padding: 10px 12px;
  color: #b91c1c;
  font-size: 12.5px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
}

.chat-rightpane {
  min-width: 0;
}

@media (width <= 1100px) {
  .chat-shell {
    grid-template-columns: 240px minmax(0, 1fr) 320px;
  }
}

@media (width <= 880px) {
  .chat-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
    height: auto;
  }

  .chat-sidebar {
    max-height: 260px;
    border-right: none;
    border-bottom: 1px solid #e5e7eb;
  }

  .chat-rightpane {
    display: none;
  }
}
</style>
