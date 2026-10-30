<template>
  <div ref="scroller" class="chat-list">
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
        <div class="who">
          <span>{{ whoLabel(message) }}</span>
          <span class="msg-actions">
            <button
              v-if="message.role === 'user'"
              type="button"
              class="msg-action"
              title="把这条问题重新发送一次"
              :disabled="busy"
              @click="$emit('resend', message.content)"
            >
              重新发送
            </button>
            <button
              v-else-if="index === messages.length - 1"
              type="button"
              class="msg-action"
              title="用上一条问题重新生成回答"
              :disabled="busy || !previousUserText(index)"
              @click="$emit('resend', previousUserText(index))"
            >
              重新生成
            </button>
          </span>
        </div>

        <div v-if="message.role === 'assistant'" class="done-row">
          <details class="done-details">
            <summary>
              <span class="done-mark">✓</span>
              <span>已完成{{ durationText(index) }}</span>
              <span v-if="stepsBefore(index).length" class="done-count">
                {{ stepsBefore(index).length }} 个步骤
              </span>
            </summary>
            <ul class="done-steps">
              <li v-for="(step, stepIndex) in stepsBefore(index)" :key="step.id || stepIndex">
                <span class="step-tool">{{ step.tool_name || 'tool' }}</span>
                <span class="step-preview">{{ previewOf(step.tool_result) }}</span>
              </li>
            </ul>
          </details>
        </div>

        <div class="body">
          <details
            v-if="message.role === 'assistant' && message.reasoning"
            class="reason-card inline"
          >
            <summary>
              <span>思考过程</span>
              <span class="reason-len">{{ message.reasoning.length }} 字</span>
            </summary>
            <pre class="reason-body">{{ message.reasoning }}</pre>
          </details>
          <div
            v-if="message.role === 'assistant'"
            class="markdown"
            v-html="render(message.content)"
          ></div>
          <template v-else>{{ message.content }}</template>

          <div v-if="message.role === 'assistant' && imagesBefore(index).length" class="msg-images">
            <button
              v-for="img in imagesBefore(index)"
              :key="img.name"
              type="button"
              class="msg-image"
              :title="'查看大图'"
              @click="$emit('preview', img.url)"
            >
              <img :src="mediaUrl(img.url)" :alt="img.name" />
            </button>
          </div>

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

    <div v-if="streaming || activeTools.length || reasoning" class="cmsg">
      <div class="who">Nova · 正在回复</div>
      <div class="body">
        <details v-if="reasoning" class="reason-card inline" :open="!streamText">
          <summary>
            <span>思考过程</span>
            <span class="reason-len">{{ reasoning.length }} 字</span>
          </summary>
          <pre class="reason-body">{{ reasoning }}</pre>
        </details>
        <div v-if="activeTools.length" class="tool-chips">
          <span v-for="tool in activeTools" :key="tool.name" class="tool-chip" :class="tool.status">
            {{ tool.name }} · {{ tool.status === 'done' ? '完成' : '执行中' }}
          </span>
        </div>
        <div v-if="streamText" class="markdown" v-html="render(streamText)"></div>
        <div v-if="liveImages.length" class="msg-images">
          <button
            v-for="img in liveImages"
            :key="img.name"
            type="button"
            class="msg-image"
            title="查看大图"
            @click="$emit('preview', img.url)"
          >
            <img :src="mediaUrl(img.url)" :alt="img.name" />
          </button>
        </div>
        <div v-if="!streamText && !liveImages.length" class="typing"><span></span><span></span><span></span></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { API_BASE, api } from '../ws'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

// 模型偶尔会在回答里直接写 ![]('/api/generated/x.png')，补上后端地址，避免渲染成裂图
const defaultImageRule = md.renderer.rules.image
md.renderer.rules.image = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const index = token.attrIndex('src')
  if (index >= 0) {
    const src = String(token.attrs[index][1] || '')
    if (src.startsWith('/api/')) token.attrs[index][1] = `${API_BASE}${src}`
  }
  if (defaultImageRule) return defaultImageRule(tokens, idx, options, env, self)
  return self.renderToken(tokens, idx, options)
}

const props = defineProps({
  messages: { type: Array, default: () => [] },
  sessionId: { type: String, default: '' },
  streamText: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
  activeTools: { type: Array, default: () => [] },
  reasoning: { type: String, default: '' },
  liveImages: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false }
})
defineEmits(['resend', 'preview'])

const scroller = ref(null)

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

function mediaUrl(url) {
  const value = String(url || '')
  if (!value) return ''
  return value.startsWith('http') ? value : `${API_BASE}${value}`
}

/** 本轮执行过的工具步骤：上一条用户消息之后、本条回答之前的 tool 行。 */
function stepsBefore(index) {
  const steps = []
  for (let i = index - 1; i >= 0; i -= 1) {
    const item = props.messages[i]
    if (!item || item.role === 'user') break
    if (item.role === 'tool') steps.unshift(item)
  }
  return steps
}

function previewOf(result) {
  const text = String(result || '').replace(/\s+/g, ' ').trim()
  if (!text) return '无输出'
  return text.length > 90 ? `${text.slice(0, 90)}…` : text
}

function parseTime(value) {
  if (!value) return null
  const date = new Date(String(value).replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? null : date.getTime()
}

/** 用时 = 上一条用户消息 → 本条回答 的时间差。 */
function durationText(index) {
  const current = props.messages[index]
  const to = parseTime(current?.created_at)
  if (to === null) return ''
  let from = null
  for (let i = index - 1; i >= 0; i -= 1) {
    const item = props.messages[i]
    if (item?.role === 'user' && parseTime(item.created_at) !== null) {
      from = parseTime(item.created_at)
      break
    }
  }
  if (from === null) return ''
  const seconds = Math.max(0, Math.round((to - from) / 1000))
  if (seconds < 1) return ' · 用时 <1 秒'
  if (seconds < 60) return ` · 用时 ${seconds} 秒`
  return ` · 用时 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

/** 从工具结果里取图片（generate_image / show_image 返回的 JSON）。 */
function imagesBefore(index) {
  const images = []
  for (const step of stepsBefore(index)) {
    if (step.tool_name !== 'generate_image' && step.tool_name !== 'show_image') continue
    try {
      const data = JSON.parse(step.tool_result || '{}')
      for (const img of data.images || []) {
        if (img && img.url) images.push(img)
      }
    } catch {
      /* 非 JSON 结果忽略 */
    }
  }
  return images
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

/** 找到某条消息之前最近的一条用户消息文本，用于「重新生成」。 */
function previousUserText(index) {
  for (let i = index - 1; i >= 0; i -= 1) {
    if (props.messages[i]?.role === 'user') return props.messages[i].content || ''
  }
  return ''
}

function scrollToBottom() {
  nextTick(() => {
    const node = scroller.value
    if (node) node.scrollTop = node.scrollHeight
  })
}

watch(
  () => [props.messages.length, props.streamText.length, props.reasoning.length],
  scrollToBottom
)
</script>
