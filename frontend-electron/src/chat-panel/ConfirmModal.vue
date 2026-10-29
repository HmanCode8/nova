<template>
  <div class="confirm-overlay">
    <div class="confirm-modal">
      <div class="confirm-head">需要你确认后才执行</div>
      <p class="confirm-preview">{{ confirm.preview_text }}</p>

      <dl class="confirm-meta">
        <div>
          <dt>操作</dt>
          <dd>{{ confirm.action }}</dd>
        </div>
        <div v-if="paramsText">
          <dt>参数</dt>
          <dd><pre>{{ paramsText }}</pre></dd>
        </div>
      </dl>

      <div class="actions">
        <button class="primary" @click="$emit('accept')">确认执行</button>
        <button class="ghost" @click="$emit('reject')">取消</button>
      </div>
      <p class="hint">3 分钟内未操作将自动取消。</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  confirm: { type: Object, required: true }
})
defineEmits(['accept', 'reject'])

const paramsText = computed(() => {
  const params = props.confirm?.params
  if (!params || !Object.keys(params).length) return ''
  return JSON.stringify(params, null, 2)
})
</script>
