<template>
  <div class="chat-list">
    <div v-if="!messages.length && !streaming" class="chat-empty">
      <p class="empty-title">还没有对话</p>
      <p>在下方输入框告诉 Nova 你要做什么。</p>
    </div>

    <template v-for="(message, index) in messages" :key="message.id || index">
      <div v-if="message.role === 'tool'" class="tool-row">
        <details>
          <summary>工具 · {{ message.tool_name || 'unknown' }}</summary>
          <pre>{{ message.tool_result || '（无输出）' }}</pre>
        </details>
      </div>

      <div v-else-if="message.role === 'error'" class="cmsg error">
        <div class="who">系统</div>
        <div class="body">{{ message.content }}</div>
      </div>

      <div v-else class="cmsg" :class="{ me: message.role === 'user' }">
        <div class="who">{{ whoLabel(message) }}</div>
        <div class="body">
          <div
            v-if="message.role === 'assistant'"
            class="markdown"
            v-html="render(message.content)"
          ></div>
          <template v-else>{{ message.content }}</template>
          <div v-if="message.attachments?.length" class="msg-attachments">
            <button
              v-for="file in message.attachments"
              :key="file.file_id"
              type="button"
              class="msg-file"
              :title="`打开 ${file.filename}`"
              @click="openFile(file)"
            >
              <img
                v-if="file.kind === 'image'"
                class="msg-file-thumb"
                :src="fileUrl(file)"
                alt=""
              />
              <span v-else class="msg-file-icon">{{ kindLabel(file.kind) }}</span>
              <span class="msg-file-main">
                <span class="msg-file-name">{{ file.filename }}</span>
                <span class="msg-file-meta">{{ kindLabel(file.kind) }} · {{ formatSize(file.size) }}</span>
              </span>
            </button>
          </div>
        </div>
      </div>
    </template>

    <div v-if="streaming || activeTools.length" class="cmsg">
      <div class="who">Nova · 正在回复</div>
      <div class="body">
        <div v-if="activeTools.length" class="tool-chips">
          <span v-for="tool in activeTools" :key="tool.name" class="tool-chip" :class="tool.status">
            {{ tool.name }} · {{ tool.status === 'done' ? '完成' : '执行中' }}
          </span>
        </div>
        <div v-if="streamText" class="markdown" v-html="render(streamText)"></div>
        <div v-else class="typing"><span></span><span></span><span></span></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import MarkdownIt from 'markdown-it'
import { api } from '../ws'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const props = defineProps({
  messages: { type: Array, default: () => [] },
  sessionId: { type: String, default: '' },
  streamText: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
  activeTools: { type: Array, default: () => [] }
})

const KIND_LABELS = { text: '文本', image: '图片', other: '文件' }

function kindLabel(kind) {
  return KIND_LABELS[kind] || '文件'
}

function formatSize(bytes) {
  const value = Number(bytes) || 0
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function fileUrl(file) {
  return api.fileUrl(props.sessionId, file.file_id)
}

async function openFile(file) {
  try {
    await api.openFile(props.sessionId, file.file_id)
  } catch (error) {
    console.warn('[nova] 打开文件失败：', error)
  }
}

function render(text) {
  return md.render(text || '')
}

function whoLabel(message) {
  const name = message.role === 'user' ? '你' : 'Nova'
  const time = formatTime(message.created_at)
  return time ? `${name} · ${time}` : name
}

function formatTime(value) {
  if (!value) return ''
  const date = new Date(String(value).replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ''
  const pad = (num) => String(num).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}
</script>
