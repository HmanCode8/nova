<template>
  <section class="radar">
    <header class="pane-head">
      <span>资讯雷达</span>
      <div class="pane-head-actions">
        <button class="pane-btn" :disabled="loading" title="刷新" @click="load">
          {{ loading ? '…' : '刷新' }}
        </button>
        <button class="pane-btn pane-toggle" title="收起/展开" @click="$emit('collapse')">‹</button>
      </div>
    </header>

    <div class="radar-sources">
      <span
        v-for="source in sources"
        :key="source.name"
        class="radar-source"
        :class="{ ok: source.ok }"
        :title="source.message"
      >
        {{ shortName(source.name) }} · {{ source.ok ? source.count : '不可用' }}
      </span>
      <span v-if="!sources.length" class="radar-source">未接入数据源</span>
    </div>

    <div class="radar-list">
      <p v-if="!items.length && !loading" class="radar-empty">
        暂无资讯。<br />
        安装邮件 / RSS 类 MCP 后，这里会自动汇总条目。
      </p>

      <article v-for="item in items" :key="item.title + item.source" class="radar-item">
        <div class="radar-item-head">
          <button
            class="star"
            :class="{ on: starred.has(item.title) }"
            :title="starred.has(item.title) ? '取消星标' : '星标收藏'"
            @click="toggleStar(item.title)"
          >
            ★
          </button>
          <span class="radar-item-title" :title="item.title">{{ item.title }}</span>
        </div>
        <p class="radar-item-summary">{{ item.summary || '（无摘要）' }}</p>
        <div class="radar-item-foot">
          <span class="radar-meta">{{ item.time || item.source }}</span>
          <button class="radar-ask" @click="$emit('ask', buildQuestion(item))">放入问题</button>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../ws'

defineEmits(['ask', 'collapse'])

const items = ref([])
const sources = ref([])
const loading = ref(false)
const starred = ref(new Set(JSON.parse(localStorage.getItem('nova_radar_stars') || '[]')))

function shortName(name) {
  return String(name || '')
    .replace(/^mcp_/, '')
    .split('_')[0]
    .slice(0, 12)
}

function buildQuestion(item) {
  const summary = item.summary ? `\n摘要：${item.summary}` : ''
  return `帮我分析一下这条资讯：${item.title}${summary}`
}

function toggleStar(title) {
  const next = new Set(starred.value)
  if (next.has(title)) next.delete(title)
  else next.add(title)
  starred.value = next
  localStorage.setItem('nova_radar_stars', JSON.stringify([...next]))
}

async function load() {
  loading.value = true
  try {
    const data = await api.getRadar()
    items.value = data.items || []
    sources.value = data.sources || []
  } catch {
    items.value = []
    sources.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>
