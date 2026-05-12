<script setup lang="ts">
import ElButton from 'element-plus/es/components/button/index.mjs'
import 'element-plus/theme-chalk/el-button.css'
import { computed, ref } from 'vue'

defineOptions({ name: 'ChatComposer' })

const props = defineProps<{
  disabled?: boolean
  streaming?: boolean
  placeholder?: string
  hint?: string
}>()

const emit = defineEmits<{
  (e: 'submit', value: string): void
  (e: 'stop'): void
}>()

const input = ref('')
const textareaRef = ref<HTMLTextAreaElement>()
const MAX_LEN = 2000

const canSubmit = computed(
  () => !props.disabled && !props.streaming && input.value.trim().length > 0,
)

function autoGrow() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 220) + 'px'
}

function handleKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
    ev.preventDefault()
    submit()
  }
}

function submit() {
  if (!canSubmit.value) return
  const value = input.value.trim()
  emit('submit', value)
  input.value = ''
  autoGrow()
}

function handleStop() {
  emit('stop')
}
</script>

<template>
  <div class="composer">
    <div class="composer__wrap" :class="{ 'is-disabled': disabled }">
      <textarea
        ref="textareaRef"
        v-model="input"
        class="composer__input"
        rows="1"
        :maxlength="MAX_LEN"
        :placeholder="placeholder || '就选中的知识库进行提问…（Enter 发送，Shift+Enter 换行）'"
        :disabled="disabled"
        @input="autoGrow"
        @keydown="handleKeydown"
      />
      <div class="composer__toolbar">
        <span class="composer__hint">{{ hint || 'Enter 发送 · Shift+Enter 换行' }}</span>
        <div class="composer__actions">
          <span class="composer__counter" :class="{ danger: input.length > MAX_LEN - 100 }">
            {{ input.length }} / {{ MAX_LEN }}
          </span>
          <ElButton v-if="streaming" size="default" plain @click="handleStop">停止</ElButton>
          <ElButton v-else type="primary" size="default" :disabled="!canSubmit" @click="submit">
            发送
          </ElButton>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.composer {
  position: sticky;
  bottom: 0;
  z-index: 5;
  flex-shrink: 0;
  padding: 14px 20px 18px;
  background: linear-gradient(180deg, rgb(250 250 249 / 0%) 0%, #fafaf9 45%);
}

.composer__wrap {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  transition:
    border-color 0.14s ease,
    box-shadow 0.14s ease;
}

.composer__wrap:focus-within {
  border-color: #0f766e;
  box-shadow: 0 0 0 3px rgb(15 118 110 / 8%);
}

.composer__wrap.is-disabled {
  background: #fafaf9;
  border-color: #e5e7eb;
}

.composer__input {
  width: 100%;
  min-height: 60px;
  max-height: 220px;
  padding: 4px 2px;
  color: #111827;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.65;
  border: none;
  outline: none;
  background: transparent;
  resize: none;
}

.composer__input::placeholder {
  color: #9ca3af;
}

.composer__toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e5e7eb;
}

.composer__hint {
  color: #9ca3af;
  font-size: 11px;
  letter-spacing: 0.02em;
}

.composer__actions {
  display: inline-flex;
  gap: 10px;
  align-items: center;
}

.composer__counter {
  color: #9ca3af;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.composer__counter.danger {
  color: #b45309;
}

@media (width <= 640px) {
  .composer {
    padding: 10px 12px 14px;
  }

  .composer__hint {
    display: none;
  }
}
</style>
