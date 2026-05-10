<script setup lang="ts">
import { computed } from 'vue'

import type { ChatCitation } from '@/api/chat'

const props = defineProps<{ citation: ChatCitation; compact?: boolean }>()

const sectionLabel = computed(() =>
  props.citation.section_path?.length ? props.citation.section_path.join(' › ') : '（无章节）',
)
const pageLabel = computed(() => {
  const start = props.citation.page_start
  const end = props.citation.page_end
  if (start == null) return '—'
  if (end == null || end === start) return `p.${start}`
  return `p.${start}-${end}`
})
const scoreLabel = computed(() => `relevance ${props.citation.score.toFixed(3)}`)
</script>

<template>
  <article class="citation-card" :class="{ compact }">
    <header class="citation-card__head">
      <span class="citation-card__index">[{{ citation.index }}]</span>
      <span class="citation-card__title" :title="citation.document_title">
        {{ citation.document_title || '未命名文档' }}
      </span>
    </header>
    <dl class="citation-card__meta">
      <div>
        <dt>章节</dt>
        <dd :title="sectionLabel">{{ sectionLabel }}</dd>
      </div>
      <div>
        <dt>页码</dt>
        <dd>{{ pageLabel }}</dd>
      </div>
      <div>
        <dt>相关度</dt>
        <dd>{{ scoreLabel }}</dd>
      </div>
    </dl>
    <p v-if="citation.snippet" class="citation-card__snippet">{{ citation.snippet }}</p>
  </article>
</template>

<style scoped>
.citation-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 360px;
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  color: #111827;
  font-size: 13px;
  line-height: 1.55;
}

.citation-card.compact {
  max-width: 280px;
  padding: 10px 12px;
}

.citation-card__head {
  display: flex;
  gap: 6px;
  align-items: baseline;
  padding-bottom: 6px;
  border-bottom: 1px dashed #e5e7eb;
}

.citation-card__index {
  color: #0f766e;
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.02em;
}

.citation-card__title {
  font-weight: 600;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.citation-card__meta {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px 12px;
  margin: 0;
}

.citation-card__meta dt {
  color: #6b7280;
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.citation-card__meta dd {
  margin: 0;
  color: #111827;
  font-weight: 500;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.citation-card__snippet {
  margin: 0;
  padding: 8px 10px;
  color: #374151;
  font-size: 12px;
  background: #fafaf9;
  border-left: 2px solid #0f766e;
  border-radius: 0 4px 4px 0;
  max-height: 140px;
  overflow: auto;
}
</style>
