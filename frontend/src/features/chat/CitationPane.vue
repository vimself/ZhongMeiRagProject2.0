<script setup lang="ts">
import { computed } from 'vue'

import type { ChatCitation } from '@/api/chat'
import CitationCard from '@/features/chat/CitationCard.vue'

const props = defineProps<{
  references: ChatCitation[]
  loading?: boolean
  emptyHint?: string
}>()

const emit = defineEmits<{
  (e: 'open', citation: ChatCitation): void
}>()

const items = computed(() => props.references ?? [])
</script>

<template>
  <aside class="citation-pane">
    <header class="citation-pane__head">
      <div class="citation-pane__title">
        <span class="dot" />
        证据面板
      </div>
      <span class="count">{{ items.length }} 条引用</span>
    </header>
    <div class="citation-pane__body">
      <template v-if="loading">
        <p class="citation-pane__placeholder">正在检索相关证据…</p>
      </template>
      <template v-else-if="items.length === 0">
        <p class="citation-pane__placeholder">
          {{ emptyHint || '尚未产生引用。提问后将在这里展示检索依据。' }}
        </p>
      </template>
      <template v-else>
        <button
          v-for="c in items"
          :key="c.id"
          type="button"
          class="citation-pane__item"
          @click="emit('open', c)"
        >
          <CitationCard :citation="c" compact />
        </button>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.citation-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #fff;
  border-left: 1px solid #e5e7eb;
}

.citation-pane__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #e5e7eb;
}

.citation-pane__title {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  color: #111827;
  font-weight: 600;
  font-size: 13px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.dot {
  width: 6px;
  height: 6px;
  background: #0f766e;
  border-radius: 50%;
}

.count {
  color: #6b7280;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.citation-pane__body {
  flex: 1;
  padding: 16px 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.citation-pane__placeholder {
  margin: 0;
  padding: 24px 12px;
  color: #6b7280;
  font-size: 13px;
  line-height: 1.7;
  text-align: center;
  border: 1px dashed #e5e7eb;
  border-radius: 8px;
  background: #fafaf9;
}

.citation-pane__item {
  all: unset;
  display: block;
  cursor: pointer;
  transition: transform 0.12s ease;
}

.citation-pane__item:hover :deep(.citation-card) {
  border-color: #0f766e;
}

.citation-pane__item:focus-visible :deep(.citation-card) {
  border-color: #0f766e;
  outline: 2px solid rgb(15 118 110 / 18%);
  outline-offset: 2px;
}
</style>
