<template>
  <transition name="fade">
    <div v-if="open" class="drawer-mask" @click="$emit('close')"></div>
  </transition>
  <transition name="drawer">
    <aside v-if="open" class="drawer">
      <div class="drawer-head">
        <h3>会话记录</h3>
        <button class="close" title="关闭" @click="$emit('close')">×</button>
      </div>

      <div class="drawer-sessions">
        <div class="drawer-section-head">
          <span>会话</span>
          <button class="mini" :disabled="disabled" @click="$emit('create')">+ 新建</button>
        </div>
        <div class="session-chips">
          <div
            v-for="session in sessions"
            :key="session.id"
            class="session-chip"
            :class="{ active: session.id === activeId }"
          >
            <button class="chip-title" :disabled="disabled" @click="$emit('select', session.id)">
              {{ session.title }}
            </button>
            <button
              class="chip-remove"
              title="删除会话"
              :disabled="disabled"
              @click.stop="$emit('remove', session.id)"
            >
              ×
            </button>
          </div>
        </div>
      </div>

      <div class="chat-scroll">
        <MessageList
          :messages="messages"
          :session-id="activeId"
          :stream-text="streamText"
          :streaming="streaming"
          :active-tools="activeTools"
        />
      </div>

      <div class="drawer-foot">本地 SQLite 存储 · 不上传云端</div>
    </aside>
  </transition>
</template>

<script setup>
import MessageList from './MessageList.vue'

defineProps({
  open: { type: Boolean, default: false },
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  messages: { type: Array, default: () => [] },
  streamText: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
  activeTools: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false }
})
defineEmits(['close', 'create', 'select', 'remove'])
</script>
