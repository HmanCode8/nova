<template>
  <section class="trace-panel">
    <header class="trace-toolbar">
      <div class="trace-title">
        <span>轨迹</span>
        <span class="trace-count">{{ traces.length }} 条</span>
      </div>

      <input
        v-model="search"
        class="trace-search"
        type="search"
        placeholder="搜索工具名 / 参数 / 返回内容"
        @input="onSearchInput"
      />

      <div class="trace-scope">
        <button
          class="scope-btn"
          :class="{ active: scope === 'session' }"
          @click="setScope('session')"
        >
          当前会话
        </button>
        <button class="scope-btn" :class="{ active: scope === 'all' }" @click="setScope('all')">
          全部
        </button>
      </div>

      <button class="trace-refresh" :disabled="loading" @click="reload">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </header>

    <div class="trace-list">
      <div v-if="!traces.length && !loading" class="trace-empty">
        <p>暂无调用记录</p>
        <p class="muted">让 Nova 读写文件、执行命令或联网搜索后，这里会记录每一次工具调用。</p>
      </div>

      <article
        v-for="item in traces"
        :key="item.id"
        class="trace-row"
        :class="[item.status, { open: expanded === item.id }]"
      >
        <button class="trace-summary" @click="toggle(item.id)">
          <span class="trace-dot" :class="item.status"></span>
          <span class="trace-name">{{ item.tool_name }}</span>
          <span class="trace-status">{{ statusLabel(item) }}</span>

          <span class="trace-bar-box">
            <span class="trace-bar" :style="{ width: barWidth(item) }"></span>
          </span>
          <span class="trace-duration">{{ formatDuration(item.duration_ms) }}</span>
          <span class="trace-time">{{ shortTime(item.created_at) }}</span>
          <span class="trace-caret">{{ expanded === item.id ? '▾' : '▸' }}</span>
        </button>

        <div v-if="expanded === item.id" class="trace-detail">
          <div class="trace-field">
            <span class="field-name">任务</span>
            <span class="field-value">{{ item.task_id || '（会话内直接调用）' }}</span>
          </div>
          <div class="trace-field">
            <span class="field-name">参数</span>
            <pre class="field-code">{{ pretty(item.params) }}</pre>
          </div>
          <div class="trace-field">
            <span class="field-name">返回</span>
            <pre class="field-code">{{ pretty(item.result) }}</pre>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../ws'

const props = defineProps({
  sessionId: { type: String, default: '' }
})

const traces = ref([])
const loading = ref(false)
const search = ref('')
const scope = ref('session')
const expanded = ref('')

let searchTimer = null

const maxDuration = computed(() =>
  traces.value.reduce((max, item) => Math.max(max, Number(item.duration_ms) || 0), 0)
)

const STATUS_LABELS = {
  success: '成功',
  failed: '失败',
  blocked: '已拦截',
  waiting_confirm: '待确认',
  cancelled: '已取消',
  running: '执行中'
}

function statusLabel(item) {
  const base = STATUS_LABELS[item.status] || item.status || ''
  return item.confirmed ? `${base} · 已确认` : base
}

function formatDuration(ms) {
  const value = Number(ms) || 0
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(1)} s`
}

function barWidth(item) {
  const total = maxDuration.value
  if (!total) return '4%'
  const ratio = (Number(item.duration_ms) || 0) / total
  return `${Math.max(4, Math.round(ratio * 100))}%`
}

function shortTime(value) {
  if (!value) return ''
  return String(value).slice(5, 16)
}

function pretty(value) {
  if (!value) return '（空）'
  const text = String(value)
  try {
    const parsed = JSON.parse(text)
    return JSON.stringify(parsed, null, 2)
  } catch {
    return text
  }
}

function toggle(id) {
  expanded.value = expanded.value === id ? '' : id
}

function setScope(value) {
  scope.value = value
  reload()
}

function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(reload, 300)
}

async function reload() {
  loading.value = true
  try {
    const params = { limit: 200 }
    if (scope.value === 'session' && props.sessionId) params.session_id = props.sessionId
    if (search.value.trim()) params.search = search.value.trim()
    const data = await api.listTraces(params)
    traces.value = data.traces || []
  } catch (err) {
    traces.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.sessionId,
  () => {
    if (scope.value === 'session') reload()
  }
)

onMounted(reload)
</script>
