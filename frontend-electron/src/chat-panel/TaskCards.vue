<template>
  <div class="task-stack">
    <article v-for="task in tasks" :key="task.task_id" class="task-card" :class="task.status">
      <header class="task-head">
        <span class="task-title">{{ task.title || '后台任务' }}</span>
        <span class="task-badge" :class="task.status">{{ statusLabel(task.status) }}</span>
        <button
          v-if="task.status === 'running' || task.status === 'pending'"
          class="task-stop"
          title="停止任务"
          @click="$emit('stop', task.task_id)"
        >
          停止
        </button>
      </header>

      <pre v-if="task.logs.length" ref="logBoxes" class="task-log">{{ task.logs.join('\n') }}</pre>
      <p v-else class="task-log muted">已提交，等待执行…</p>

      <p v-if="task.error" class="task-error">{{ task.error }}</p>
    </article>
  </div>
</template>

<script setup>
defineProps({
  tasks: { type: Array, default: () => [] }
})
defineEmits(['stop'])

const LABELS = {
  pending: '排队中',
  running: '执行中',
  success: '已完成',
  failed: '失败',
  cancelled: '已停止',
  timeout: '超时回收',
  unknown: '未知'
}

function statusLabel(status) {
  return LABELS[status] || status || '执行中'
}
</script>
