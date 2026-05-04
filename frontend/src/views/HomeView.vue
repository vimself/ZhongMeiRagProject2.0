<script setup lang="ts">
import { Monitor, Service, Tickets } from '@element-plus/icons-vue'
import ElIcon from 'element-plus/es/components/icon/index.mjs'
import ElTag from 'element-plus/es/components/tag/index.mjs'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-tag.css'

const cards = [
  { title: '知识库', description: '文档入库、检索与引用预览骨架', icon: Tickets },
  { title: 'RAG 问答', description: 'SSE 流式回答与可溯源引用入口', icon: Service },
  { title: '方案编制', description: '模板、参数、章节生成工作台入口', icon: Monitor },
]
</script>

<template>
  <main class="shell">
    <section class="topbar">
      <div>
        <p class="eyebrow">ZhongMei RAG v2.0</p>
        <h1>工程知识与施工方案智能编制平台</h1>
      </div>
      <ElTag type="success" effect="dark">Stage 1</ElTag>
    </section>

    <section class="grid">
      <article v-for="card in cards" :key="card.title" class="module">
        <ElIcon :size="24">
          <component :is="card.icon" />
        </ElIcon>
        <div>
          <h2>{{ card.title }}</h2>
          <p>{{ card.description }}</p>
        </div>
      </article>
    </section>
  </main>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  padding: 32px;
  background: #f6f8fb;
  color: #1f2937;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1080px;
  margin: 0 auto 24px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #52616f;
  font-size: 14px;
}

h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  max-width: 1080px;
  margin: 0 auto;
}

.module {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  min-height: 120px;
  padding: 20px;
  background: #fff;
  border: 1px solid #d8dee8;
  border-radius: 8px;
}

.module h2 {
  margin: 0 0 8px;
  font-size: 18px;
}

.module p {
  margin: 0;
  color: #52616f;
  line-height: 1.6;
}

@media (width <= 640px) {
  .shell {
    padding: 20px;
  }

  .topbar {
    align-items: flex-start;
    gap: 16px;
  }

  h1 {
    font-size: 22px;
  }
}
</style>
