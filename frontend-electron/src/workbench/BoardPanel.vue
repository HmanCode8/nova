<template>
  <section class="board">
    <header class="pane-head">
      <span>看板</span>
      <div class="pane-head-actions">
        <button class="pane-btn" :disabled="loading" @click="load">{{ loading ? '…' : '刷新' }}</button>
        <button class="pane-btn" title="添加卡片" @click="pickerOpen = !pickerOpen">+</button>
        <button class="pane-btn pane-toggle" title="收起/展开" @click="$emit('collapse')">›</button>
      </div>
    </header>

    <div v-if="pickerOpen" class="board-picker">
      <button
        v-for="option in AVAILABLE"
        :key="option.type"
        class="board-pick"
        :disabled="hasCard(option.type)"
        @click="addCard(option.type)"
      >
        {{ option.label }}{{ hasCard(option.type) ? '（已添加）' : '' }}
      </button>
    </div>

    <div class="board-list">
      <article v-for="card in cards" :key="card.type" class="board-card">
        <header class="board-card-head">
          <span>{{ labelOf(card.type) }}</span>
          <button class="board-remove" title="移除卡片" @click="removeCard(card.type)">×</button>
        </header>

        <template v-if="card.type === 'trace_stats'">
          <div class="board-stats">
            <div class="board-stat"><b>{{ stats.total }}</b><span>工具调用</span></div>
            <div class="board-stat"><b>{{ stats.rate }}%</b><span>成功率</span></div>
            <div class="board-stat"><b>{{ stats.avg }}ms</b><span>平均耗时</span></div>
          </div>
        </template>

        <template v-else-if="card.type === 'tool_rank'">
          <div v-if="!stats.rank.length" class="board-empty">暂无调用记录</div>
          <div v-for="row in stats.rank" :key="row.name" class="board-rank">
            <span class="board-rank-name" :title="row.name">{{ row.name }}</span>
            <span class="board-rank-bar"><i :style="{ width: row.percent + '%' }"></i></span>
            <span class="board-rank-count">{{ row.count }}</span>
          </div>
        </template>

        <template v-else-if="card.type === 'project'">
          <div v-if="!project" class="board-empty">当前会话暂无项目计划</div>
          <template v-else>
            <p class="board-project-title">{{ project.title }}</p>
            <p class="board-project-meta">{{ project.done }}/{{ project.total }} 步完成</p>
            <div class="board-progress"><i :style="{ width: progress + '%' }"></i></div>
            <ul class="board-steps">
              <li v-for="(step, index) in (project.steps || []).slice(0, 5)" :key="index" :class="step.status">
                <span class="board-step-index">{{ index + 1 }}</span>{{ step.title || step.text || step }}
              </li>
            </ul>
          </template>
        </template>

        <template v-else-if="card.type === 'tasks'">
          <div v-if="!tasks.length" class="board-empty">暂无后台任务</div>
          <div v-for="task in tasks.slice(0, 4)" :key="task.task_id" class="board-task">
            <span class="board-task-title" :title="task.title">{{ task.title }}</span>
            <span class="board-task-status" :class="task.status">{{ statusLabel(task.status) }}</span>
          </div>
        </template>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../ws'

const props = defineProps({
  sessionId: { type: String, default: '' },
  tasks: { type: Array, default: () => [] }
})
defineEmits(['collapse'])

const AVAILABLE = [
  { type: 'trace_stats', label: '工具调用统计' },
  { type: 'tool_rank', label: '工具调用排行' },
  { type: 'project', label: '项目进度' },
  { type: 'tasks', label: '后台任务' }
]

const DEFAULT_CARDS = ['trace_stats', 'project']

const cards = ref(
  (JSON.parse(localStorage.getItem('nova_board_cards') || 'null') || DEFAULT_CARDS).map((type) => ({
    type
  }))
)
const traces = ref([])
const project = ref(null)
const loading = ref(false)
const pickerOpen = ref(false)

const stats = computed(() => {
  const rows = traces.value
  const total = rows.length
  const success = rows.filter((row) => row.status === 'success').length
  const avg = total
    ? Math.round(rows.reduce((sum, row) => sum + (Number(row.duration_ms) || 0), 0) / total)
    : 0
  const map = new Map()
  rows.forEach((row) => map.set(row.tool_name, (map.get(row.tool_name) || 0) + 1))
  const sorted = [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)
  const max = sorted[0]?.[1] || 1
  return {
    total,
    rate: total ? Math.round((success / total) * 100) : 0,
    avg,
    rank: sorted.map(([name, count]) => ({
      name,
      count,
      percent: Math.max(6, Math.round((count / max) * 100))
    }))
  }
})

const progress = computed(() => {
  const plan = project.value
  if (!plan || !plan.total) return 0
  return Math.round(((plan.done || 0) / plan.total) * 100)
})

const STATUS_LABELS = {
  pending: '排队',
  running: '执行中',
  success: '完成',
  failed: '失败',
  cancelled: '已停',
  timeout: '超时'
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

function labelOf(type) {
  return AVAILABLE.find((item) => item.type === type)?.label || type
}

function hasCard(type) {
  return cards.value.some((card) => card.type === type)
}

function persist() {
  localStorage.setItem('nova_board_cards', JSON.stringify(cards.value.map((card) => card.type)))
}

function addCard(type) {
  if (hasCard(type)) return
  cards.value.push({ type })
  persist()
  pickerOpen.value = false
}

function removeCard(type) {
  cards.value = cards.value.filter((card) => card.type !== type)
  persist()
}

async function load() {
  loading.value = true
  try {
    const data = await api.listTraces({ session_id: props.sessionId || '', limit: 200 })
    traces.value = data.traces || []
  } catch {
    traces.value = []
  }
  if (props.sessionId) {
    try {
      project.value = await api.getProject(props.sessionId)
    } catch {
      project.value = null
    }
  }
  loading.value = false
}

watch(() => props.sessionId, load)
onMounted(load)
</script>
