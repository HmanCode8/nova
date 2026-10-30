<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { API_BASE, api, createSocket } from './ws'
import ParticleSphere from './chat-panel/ParticleSphere.vue'
import MessageList from './chat-panel/MessageList.vue'
import ConfirmModal from './chat-panel/ConfirmModal.vue'
import McpCards from './chat-panel/McpCards.vue'
import TaskCards from './chat-panel/TaskCards.vue'
import TracePanel from './trace/TracePanel.vue'
import SettingsPanel from './settings/SettingsPanel.vue'
import MemoryPanel from './settings/MemoryPanel.vue'
import McpStorePanel from './mcp-store/McpStorePanel.vue'
import RadarPanel from './workbench/RadarPanel.vue'
import BoardPanel from './workbench/BoardPanel.vue'

const sessions = ref([])
const activeId = ref('')
const messages = ref([])
const input = ref('')
const streaming = ref(false)
const streamText = ref('')
const activeTools = ref([])
const pendingConfirm = ref(null)
const connection = ref('connecting')
const modelReady = ref(true)
const notice = ref('')
const settingsOpen = ref(false)
const memoryOpen = ref(false)
const mcpStoreOpen = ref(false)
const lastAnswer = ref('')
const searchGroups = ref([])
const doneFlash = ref(false)
const inputEl = ref(null)
const fileInput = ref(null)
const uploading = ref(false)
const pendingSessionId = ref('')
const attachments = ref([])
const dragDepth = ref(0)
const UPLOAD_LIMIT = 5
const voiceState = ref('idle') // idle / recording / transcribing / speaking
const voiceBars = ref(new Array(28).fill(0.05))
const mcpCards = ref([])
const liveImages = ref([])
const previewUrl = ref('')

function openPreview(url) {
  const value = String(url || '')
  if (!value) return
  previewUrl.value = value.startsWith('http') ? value : `${API_BASE}${value}`
}
const bgTasks = ref([])
const view = ref('chat') // chat / trace / follows / about
const VIEW_TABS = [
  { id: 'chat', label: '对话' },
  { id: 'trace', label: '轨迹' },
  { id: 'follows', label: '我的关注' },
  { id: 'about', label: '它对我的了解' },
  { id: 'knowledge', label: '知识库' }
]

// 三栏工作台：左右两栏宽度可拖拽、可收起，状态持久化
const leftWidth = ref(Number(localStorage.getItem('nova_left_w') || 240))
const rightWidth = ref(Number(localStorage.getItem('nova_right_w') || 264))
const leftCollapsed = ref(localStorage.getItem('nova_left_c') === '1')
const rightCollapsed = ref(localStorage.getItem('nova_right_c') === '1')
const layoutStyle = computed(() => ({
  '--left-w': leftCollapsed.value ? '38px' : `${leftWidth.value}px`,
  '--right-w': rightCollapsed.value ? '38px' : `${rightWidth.value}px`
}))

let dragSide = ''
let dragStartX = 0
let dragStartWidth = 0

function startDrag(side, event) {
  dragSide = side
  dragStartX = event.clientX
  dragStartWidth = side === 'left' ? leftWidth.value : rightWidth.value
  event.preventDefault()
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', stopDrag)
}

function onDragMove(event) {
  if (!dragSide) return
  const delta = event.clientX - dragStartX
  if (dragSide === 'left') {
    leftWidth.value = Math.min(420, Math.max(180, Math.round(dragStartWidth + delta)))
    leftCollapsed.value = false
  } else {
    rightWidth.value = Math.min(440, Math.max(200, Math.round(dragStartWidth - delta)))
    rightCollapsed.value = false
  }
}

function stopDrag() {
  if (dragSide === 'left') localStorage.setItem('nova_left_w', String(leftWidth.value))
  if (dragSide === 'right') localStorage.setItem('nova_right_w', String(rightWidth.value))
  localStorage.setItem('nova_left_c', leftCollapsed.value ? '1' : '0')
  localStorage.setItem('nova_right_c', rightCollapsed.value ? '1' : '0')
  dragSide = ''
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', stopDrag)
}

function togglePane(side) {
  if (side === 'left') leftCollapsed.value = !leftCollapsed.value
  else rightCollapsed.value = !rightCollapsed.value
  localStorage.setItem('nova_left_c', leftCollapsed.value ? '1' : '0')
  localStorage.setItem('nova_right_c', rightCollapsed.value ? '1' : '0')
}

function askFromRadar(text) {
  input.value = text
  view.value = 'chat'
  nextTick(() => {
    autoGrow()
    focusInput()
  })
}
const voicePressing = ref(false)
const reasoningText = ref('')
const modelProfiles = ref([])
const activeModelId = ref('')

let socket = null
let noticeTimer = null
let doneTimer = null

const activeSession = computed(
  () => sessions.value.find((session) => session.id === activeId.value) || null
)
const connectionLabel = computed(
  () => ({ online: '已连接', connecting: '连接中', offline: '已断开' })[connection.value] || ''
)
const sphereState = computed(() => {
  if (pendingConfirm.value) return 'confirm'
  if (streaming.value) return 'thinking'
  if (doneFlash.value) return 'done'
  return 'idle'
})

// 同步状态到桌面悬浮球（Electron 环境）
watch(sphereState, (value) => window.nova?.setPetState?.(value), { immediate: true })
const answerText = computed(() => (streaming.value ? streamText.value : lastAnswer.value))
const hasContent = computed(
  () =>
    Boolean(
      answerText.value || reasoningText.value || searchGroups.value.length || mcpCards.value.length
    )
)
const voiceLabel = computed(
  () =>
    ({
      recording: '正在聆听… 松开结束',
      transcribing: '正在识别…',
      speaking: '正在播报…'
    })[voiceState.value] || ''
)

function rid() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
}

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

function showNotice(text) {
  notice.value = text
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => (notice.value = ''), 4200)
}

function pushVoiceLevel(level) {
  const bars = voiceBars.value.slice(1)
  bars.push(Math.max(0.05, Math.min(1, Number(level) || 0)))
  voiceBars.value = bars
}

function flashDone() {
  doneFlash.value = true
  clearTimeout(doneTimer)
  doneTimer = setTimeout(() => (doneFlash.value = false), 1300)
}

function focusInput() {
  nextTick(() => inputEl.value?.focus())
}

function autoGrow() {
  const element = inputEl.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 132)}px`
}

async function finishAssistant(content) {
  if (content) {
    messages.value.push({ id: rid(), role: 'assistant', content })
    lastAnswer.value = content
  }
  streaming.value = false
  streamText.value = ''
  activeTools.value = []
  pendingConfirm.value = null
  flashDone()
  await refreshSessions()
  await refreshActiveMessages()
  liveImages.value = []
  await refreshProject()
  if (pendingSessionId.value) {
    const target = pendingSessionId.value
    pendingSessionId.value = ''
    await selectSession(target)
  }
}

async function refreshActiveMessages() {
  const sessionId = activeId.value
  if (!sessionId) return
  try {
    const rows = await api.listMessages(sessionId)
    if (sessionId === activeId.value) messages.value = rows
  } catch {
    /* 忽略刷新失败，保留本地消息 */
  }
}

async function refreshProject(sessionId = activeId.value) {
  if (!sessionId) return
  try {
    const plan = await api.getProject(sessionId)
    if (sessionId !== activeId.value) return
    // 项目看板常驻首位，其余卡片最多保留 3 个，避免看板被挤掉
    const others = mcpCards.value.filter((card) => card.kind !== 'project_plan').slice(-3)
    mcpCards.value = plan ? [{ kind: 'project_plan', data: plan }, ...others] : others
  } catch {
    /* 项目看板刷新失败不影响对话 */
  }
}

async function handleEvent(event) {
  switch (event.type) {
    case 'token':
      streaming.value = true
      streamText.value += event.delta || ''
      break
    case 'reasoning':
      streaming.value = true
      reasoningText.value += event.delta || ''
      break
    case 'tool_status': {
      // 后台任务的工具状态只进任务日志，不影响当前对话的流式状态
      if (event.task_id) {
        appendTaskLog(
          event.task_id,
          `[工具] ${event.tool_name} ${event.status === 'done' ? '完成' : '执行中'}`
        )
        break
      }
      streaming.value = true
      const tool = activeTools.value.find((item) => item.name === event.tool_name)
      if (tool) tool.status = event.status
      else activeTools.value.push({ name: event.tool_name, status: event.status })
      break
    }
    case 'human_confirm':
    case 'delete_confirm':
      // 删除走 delete_confirm（文档协议），其它副作用工具走 human_confirm，弹窗一致
      streaming.value = false
      streamText.value = ''
      activeTools.value = []
      pendingConfirm.value = event
      break
    case 'message':
      await finishAssistant(event.content)
      break
    case 'session_created':
      pendingSessionId.value = event.session_id || ''
      showNotice(`已创建新会话：${event.title || '新会话'}`)
      break
    case 'search_results': {
      const items = Array.isArray(event.items) ? event.items : []
      if (!items.length) break
      const query = event.query || '联网搜索'
      const existing = searchGroups.value.find((group) => group.query === query)
      if (existing) {
        existing.items = items
      } else if (searchGroups.value.length < 2) {
        searchGroups.value.push({ query, items })
      } else {
        searchGroups.value[searchGroups.value.length - 1] = { query, items }
      }
      break
    }
    case 'card': {
      const data = event.data || {}
      // 图片内联到当前这条回答里，不再占用右侧卡片位
      if (event.kind === 'image_result') {
        for (const img of data.images || []) {
          if (img && img.url) liveImages.value.push(img)
        }
        break
      }
      const rest = mcpCards.value.filter((item) => item.kind !== event.kind)
      const card = { kind: event.kind, data }
      // 项目看板常驻首位，其余卡片最新优先
      mcpCards.value =
        event.kind === 'project_plan'
          ? [card, ...rest].slice(-4)
          : [...rest, card].slice(-4)
      break
    }
    case 'task_created':
      upsertTask(event.task_id, {
        title: event.title || '后台任务',
        status: 'pending'
      })
      showNotice(`后台任务已启动：${event.title || ''}`)
      break
    case 'task_log':
      appendTaskLog(event.task_id, event.log || '')
      break
    case 'task_status':
      upsertTask(event.task_id, {
        status: event.status || 'running',
        error: event.error || '',
        result: event.result || ''
      })
      break
    case 'voice_status':
      voiceState.value = event.status || 'idle'
      if (event.status !== 'recording') voiceBars.value = new Array(28).fill(0.05)
      break
    case 'voice_level':
      pushVoiceLevel(event.level)
      break
    case 'asr_result':
      voiceState.value = 'idle'
      if (event.text) submitText(event.text, 'voice')
      break
    case 'tts_status':
      if (event.status === 'speaking') voiceState.value = 'speaking'
      else if (event.status === 'failed') {
        voiceState.value = 'idle'
        showNotice(`语音播报失败：${event.message || '未知错误'}`)
      } else if (voiceState.value === 'speaking') voiceState.value = 'idle'
      break
    case 'error':
      await finishAssistant('')
      lastAnswer.value = ''
      reasoningText.value = ''
      messages.value.push({ id: rid(), role: 'error', content: event.message || '未知错误' })
      showNotice(event.message || '发生错误')
      break
    default:
      break
  }
}

async function refreshSessions() {
  try {
    sessions.value = await api.listSessions()
  } catch {
    /* 保持现有列表 */
  }
}

async function selectSession(sessionId) {
  if (streaming.value || pendingConfirm.value) {
    showNotice('请先等待当前回复结束或处理确认卡片')
    return
  }
  activeId.value = sessionId
  streamText.value = ''
  reasoningText.value = ''
  activeTools.value = []
  pendingConfirm.value = null
  lastAnswer.value = ''
  searchGroups.value = []
  mcpCards.value = []
  attachments.value = []
  try {
    messages.value = await api.listMessages(sessionId)
  } catch (error) {
    showNotice(`加载消息失败：${error.message}`)
  }
  await refreshProject(sessionId)
  await refreshTasks(sessionId)
}

async function createSession() {
  if (streaming.value || pendingConfirm.value) {
    showNotice('请先等待当前回复结束或处理确认卡片')
    return
  }
  try {
    const session = await api.createSession()
    sessions.value.unshift(session)
    await selectSession(session.id)
    focusInput()
  } catch (error) {
    showNotice(`新建会话失败：${error.message}`)
  }
}

async function removeSession(sessionId) {
  if (streaming.value || pendingConfirm.value) {
    showNotice('请先等待当前回复结束或处理确认卡片')
    return
  }
  if (!window.confirm('删除该会话及其全部消息？')) return
  try {
    await api.deleteSession(sessionId)
    sessions.value = sessions.value.filter((session) => session.id !== sessionId)
    if (activeId.value === sessionId) {
      if (sessions.value.length) await selectSession(sessions.value[0].id)
      else await createSession()
    }
  } catch (error) {
    showNotice(`删除失败：${error.message}`)
  }
}

function send() {
  const text = input.value.trim()
  if (!text && !attachments.value.length) return
  if (submitText(text, 'text')) {
    input.value = ''
    nextTick(autoGrow)
  }
}

function submitText(text, source = 'text') {
  if (streaming.value) {
    showNotice('正在生成回复，请稍候')
    return false
  }
  if (pendingConfirm.value) {
    showNotice('请先处理待确认操作')
    return false
  }
  if (!activeId.value) {
    showNotice('请先新建会话')
    return false
  }
  if (attachments.value.some((item) => item.status === 'uploading')) {
    showNotice('文件仍在上传，请稍候再发送')
    return false
  }
  const ready = attachments.value.filter((item) => item.status === 'ready')
  if (!text && !ready.length) return false
  const payload = ready.map((item) => ({
    file_id: item.file_id,
    filename: item.filename,
    size: item.size,
    kind: item.kind
  }))
  if (
    !socket?.send({
      type: 'user_message',
      session_id: activeId.value,
      message: text,
      source,
      attachments: payload
    })
  ) {
    showNotice('连接已断开，正在重连…')
    return false
  }
  const fallback = ready.length
    ? `（已附带文件：${ready.map((item) => item.filename).join('、')}）`
    : ''
  messages.value.push({
    id: rid(),
    role: 'user',
    content: text || fallback,
    attachments: payload
  })
  attachments.value = []
  streaming.value = true
  streamText.value = ''
  reasoningText.value = ''
  activeTools.value = []
  liveImages.value = []
  lastAnswer.value = ''
  searchGroups.value = []
  mcpCards.value = []
  return true
}

function startVoice() {
  if (streaming.value) return showNotice('正在生成回复，请稍候')
  if (pendingConfirm.value) return showNotice('请先处理待确认操作')
  if (!activeId.value) return showNotice('请先新建会话')
  if (voiceState.value !== 'idle') return
  if (!socket?.send({ type: 'voice', action: 'start' })) {
    return showNotice('连接已断开，正在重连…')
  }
  voicePressing.value = true
  voiceState.value = 'recording'
  voiceBars.value = new Array(28).fill(0.05)
}

function stopVoice() {
  if (!voicePressing.value) return
  voicePressing.value = false
  if (voiceState.value !== 'recording') return
  socket?.send({ type: 'voice', action: 'stop' })
  voiceState.value = 'transcribing'
}

function respondConfirm(accepted) {
  if (!pendingConfirm.value) return
  const ok = socket?.send({
    type: 'confirm_result',
    confirm_id: pendingConfirm.value.confirm_id,
    accepted
  })
  if (!ok) return showNotice('连接已断开，无法提交确认')
  pendingConfirm.value = null
  streaming.value = true
  streamText.value = ''
  activeTools.value = []
}

function stopGeneration() {
  socket?.send({ type: 'control', action: 'stop' })
  streaming.value = false
}

/** 重新发送一条历史问题：回到同一会话，把它当作新的一轮重新提问。 */
function resendMessage(text) {
  const content = String(text || '').trim()
  if (!content) return
  if (streaming.value || pendingConfirm.value) {
    showNotice('请先等待当前回复结束')
    return
  }
  if (!activeId.value) {
    showNotice('请先新建会话')
    return
  }
  input.value = content
  nextTick(() => {
    autoGrow()
    send()
  })
}

function onKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey) return
  if (event.isComposing) return // 中文输入法候选确认时不发送
  event.preventDefault()
  send()
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function chooseFile() {
  if (streaming.value || pendingConfirm.value) {
    showNotice('请先等待当前回复结束')
    return
  }
  if (!activeId.value) {
    showNotice('请先新建会话')
    return
  }
  fileInput.value?.click()
}

async function onFileSelected(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  await uploadFiles(files)
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList || [])
  if (!files.length) return
  if (!activeId.value) {
    showNotice('请先新建会话')
    return
  }
  const usable = attachments.value.filter((item) => item.status !== 'failed').length
  if (usable + files.length > UPLOAD_LIMIT) {
    showNotice(`单条消息最多 ${UPLOAD_LIMIT} 个文件`)
    return
  }
  uploading.value = true
  for (const file of files) {
    const localId = rid()
    const guessedKind = file.type?.startsWith('image/') ? 'image' : ''
    attachments.value.push({
      localId,
      filename: file.name || `paste-${Date.now()}.png`,
      size: file.size,
      kind: guessedKind,
      preview: '',
      status: 'uploading'
    })
    try {
      const record = await api.uploadFile(activeId.value, file)
      const target = attachments.value.find((item) => item.localId === localId)
      if (target) Object.assign(target, record, { status: 'ready' })
      const detail = record.chars ? `${kindLabel(record.kind)}，${record.chars} 字符` : kindLabel(record.kind)
      showNotice(`已上传：${record.filename}（${detail}）`)
    } catch (err) {
      const target = attachments.value.find((item) => item.localId === localId)
      if (target) target.status = 'failed'
      showNotice(`上传失败：${err.message}`)
    }
  }
  uploading.value = false
  focusInput()
}

function removeAttachment(localId) {
  attachments.value = attachments.value.filter((item) => item.localId !== localId)
}

function clearAttachments() {
  attachments.value = []
}

function onPaste(event) {
  const items = event.clipboardData?.items || []
  const files = []
  for (const item of items) {
    if (item.kind !== 'file') continue
    const file = item.getAsFile()
    if (file) files.push(file)
  }
  if (!files.length) return // 纯文本交给浏览器默认粘贴
  event.preventDefault()
  uploadFiles(files)
}

function onDragEnter(event) {
  if (event.dataTransfer?.types?.includes('Files')) dragDepth.value += 1
}

function onDragLeave() {
  dragDepth.value = Math.max(0, dragDepth.value - 1)
}

function onDrop(event) {
  dragDepth.value = 0
  const files = Array.from(event.dataTransfer?.files || [])
  if (files.length) uploadFiles(files)
}

function onDocumentClick(event) {
  // Electron 内把外链交给系统浏览器打开（浏览器环境保持默认行为）
  if (!window.nova?.openExternal) return
  const anchor = event.target?.closest?.('a[href^="http"]')
  if (!anchor) return
  event.preventDefault()
  window.nova.openExternal(anchor.href)
}

async function loadModelProfiles() {
  try {
    const data = await api.listModels()
    modelProfiles.value = data.profiles || []
    activeModelId.value = data.active_id || ''
  } catch {
    /* 后端未启动时静默，保留空列表 */
  }
}

async function switchModel(id) {
  if (!id || id === activeModelId.value) return
  try {
    const data = await api.activateModel(id)
    modelProfiles.value = data.profiles || modelProfiles.value
    activeModelId.value = data.active_id || id
    showNotice('已切换模型，下一句话生效')
    modelReady.value = true
  } catch (err) {
    showNotice(`切换模型失败：${err.message}`)
    loadModelProfiles()
  }
}

/** 后台任务卡片：按 task_id 局部更新，日志上限 200 行避免内存膨胀。 */
function upsertTask(taskId, patch) {
  if (!taskId) return
  const index = bgTasks.value.findIndex((item) => item.task_id === taskId)
  if (index === -1) {
    bgTasks.value.unshift({
      task_id: taskId,
      title: patch.title || '后台任务',
      status: patch.status || 'pending',
      logs: [],
      error: '',
      result: ''
    })
    bgTasks.value = bgTasks.value.slice(0, 5)
    return
  }
  Object.assign(bgTasks.value[index], patch)
}

function appendTaskLog(taskId, log) {
  if (!taskId || !log) return
  if (!bgTasks.value.some((item) => item.task_id === taskId)) {
    upsertTask(taskId, { status: 'running' })
  }
  const task = bgTasks.value.find((item) => item.task_id === taskId)
  if (!task) return
  task.logs.push(log)
  if (task.logs.length > 200) task.logs.splice(0, task.logs.length - 200)
}

function stopTask(taskId) {
  if (!socket?.send({ type: 'control', action: 'stop_task', task_id: taskId })) {
    showNotice('连接已断开，无法停止任务')
  }
}

async function refreshTasks(sessionId = activeId.value) {
  if (!sessionId) return
  try {
    const rows = await api.listTasks(sessionId)
    bgTasks.value = rows.slice(0, 5).map((row) => ({
      task_id: row.id,
      title: row.title || '后台任务',
      status: row.status,
      logs: row.result ? [String(row.result).slice(0, 2000)] : [],
      error: row.error || '',
      result: row.result || ''
    }))
  } catch {
    /* 任务列表加载失败不影响对话 */
  }
}

async function onSettingsSaved(payload = {}) {
  // 档案内的保存不关面板（用户要看到新增结果）；底部「保存设置」才关闭
  if (payload.close) {
    settingsOpen.value = false
    showNotice('设置已保存，下一轮对话生效')
  }
  loadModelProfiles()
  try {
    const health = await api.health()
    modelReady.value = Boolean(health.model_configured)
  } catch {
    /* 忽略健康检查失败 */
  }
}

function openMemoryPanel() {
  settingsOpen.value = false
  memoryOpen.value = true
}

onMounted(async () => {
  document.addEventListener('click', onDocumentClick)
  window.addEventListener('pointerup', stopVoice)
  window.addEventListener('pointercancel', stopVoice)
  window.addEventListener('blur', stopVoice)
  socket = createSocket({
    onEvent: handleEvent,
    onStatus: (status) => (connection.value = status)
  })
  try {
    const health = await api.health()
    modelReady.value = Boolean(health.model_configured)
  } catch {
    showNotice('无法连接后端服务，请确认 127.0.0.1:8000 已启动')
  }
  await refreshSessions()
  await loadModelProfiles()
  if (sessions.value.length) await selectSession(sessions.value[0].id)
  else await createSession()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  window.removeEventListener('pointerup', stopVoice)
  window.removeEventListener('pointercancel', stopVoice)
  window.removeEventListener('blur', stopVoice)
  socket?.close()
  clearTimeout(noticeTimer)
  clearTimeout(doneTimer)
})
</script>

<template>
  <div
    class="stage-shell"
    :style="layoutStyle"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <div v-if="dragDepth > 0" class="drop-overlay">松开鼠标上传文件</div>
    <ParticleSphere :state="sphereState" :compact="hasContent" @activate="focusInput" />

    <aside class="session-rail">
      <div class="rail-brand">
        <span class="dot"></span>
        <span>NOVA</span>
      </div>
      <button class="rail-new" :disabled="streaming || Boolean(pendingConfirm)" @click="createSession">
        <span>+</span> 新建会话
      </button>
      <div class="rail-list">
        <div
          v-for="session in sessions"
          :key="session.id"
          class="rail-item"
          :class="{ active: session.id === activeId }"
        >
          <button
            class="rail-title"
            :disabled="streaming || Boolean(pendingConfirm)"
            :title="session.title"
            @click="selectSession(session.id)"
          >
            {{ session.title || '未命名会话' }}
          </button>
          <button
            class="rail-remove"
            title="删除会话"
            :disabled="streaming || Boolean(pendingConfirm)"
            @click.stop="removeSession(session.id)"
          >
            ×
          </button>
        </div>
        <p v-if="!sessions.length" class="rail-empty">还没有会话</p>
      </div>
      <div class="rail-foot">
        <button class="rail-link" @click="memoryOpen = true">记忆</button>
        <button class="rail-link" @click="mcpStoreOpen = true">MCP</button>
        <button class="rail-link" @click="settingsOpen = true">设置</button>
      </div>
    </aside>

    <aside class="workbench-pane left" :class="{ collapsed: leftCollapsed }">
      <RadarPanel @ask="askFromRadar" @collapse="togglePane('left')" />
    </aside>
    <div
      class="pane-handle left"
      :class="{ hidden: leftCollapsed }"
      @pointerdown="startDrag('left', $event)"
    ></div>

    <header class="topbar">
      <div class="brand">
        <span class="brand-name">{{ activeSession?.title || '新会话' }}</span>
        <span class="brand-sub">NovaSecretary · 本地 AI 秘书</span>
      </div>
      <nav class="view-tabs">
        <button
          v-for="item in VIEW_TABS"
          :key="item.id"
          class="view-tab"
          :class="{ active: view === item.id }"
          @click="view = item.id"
        >
          {{ item.label }}
        </button>
      </nav>
      <div class="top-actions">
        <select
          v-if="modelProfiles.length"
          class="model-select"
          :value="activeModelId"
          title="切换模型"
          @change="switchModel($event.target.value)"
        >
          <option v-for="item in modelProfiles" :key="item.id" :value="item.id">
            {{ item.name }}{{ item.has_key ? '' : '（缺密钥）' }}
          </option>
        </select>
        <span class="conn" :class="connection">{{ connectionLabel }}</span>
        <button class="icon-btn" title="设置" @click="settingsOpen = true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
          </svg>
        </button>
      </div>
    </header>

    <main v-show="view === 'chat'" class="hud">
      <div v-if="searchGroups.length || mcpCards.length || bgTasks.length" class="hud-artifacts">
        <TaskCards v-if="bgTasks.length" :tasks="bgTasks" @stop="stopTask" />

        <section v-if="searchGroups.length" class="search-card">
          <template v-for="group in searchGroups" :key="group.query">
            <div class="search-head">联网搜索 · {{ group.query }}</div>
            <a
              v-for="item in group.items"
              :key="item.url || item.title"
              class="search-item"
              :href="item.url"
              target="_blank"
              rel="noreferrer"
            >
              <span class="search-title">{{ item.title }}</span>
              <span class="search-url">{{ hostOf(item.url) }}</span>
              <span class="search-snippet">{{ item.content }}</span>
            </a>
          </template>
        </section>

        <McpCards v-if="mcpCards.length" :cards="mcpCards" />
      </div>

      <MessageList
        :messages="messages"
        :session-id="activeId"
        :stream-text="streamText"
        :streaming="streaming"
        :active-tools="activeTools"
        :reasoning="reasoningText"
        :live-images="liveImages"
        :busy="streaming || Boolean(pendingConfirm)"
        @resend="resendMessage"
        @preview="openPreview"
      />
    </main>

    <main v-if="view === 'trace'" class="hud trace-pane">
      <TracePanel :session-id="activeId" />
    </main>

    <main v-else-if="view === 'follows'" class="hud placeholder-pane">
      <div class="placeholder-box">
        <h3>我的关注</h3>
        <p>资讯雷达 + 星标收藏，数据源来自 MCP（RSS / 资讯 / 邮件）。</p>
        <p class="muted">该模块随 MCP 商店一起上线，当前版本暂未开放。</p>
      </div>
    </main>

    <main v-else-if="view === 'about'" class="hud placeholder-pane">
      <div class="placeholder-box">
        <h3>它对我的了解</h3>
        <p>长期记忆与会话记忆在这里统一管理：偏好、习惯、常用路径。</p>
        <button class="mini" type="button" @click="memoryOpen = true">打开记忆管理</button>
      </div>
    </main>

    <main v-else-if="view === 'knowledge'" class="hud placeholder-pane">
      <div class="placeholder-box wide">
        <h3>知识库（V2 预留）</h3>
        <p>
          当前版本 Agent 通过 <code>file_read</code> 直接读取本地文件，已能满足单文件问答；
          向量检索属于 V2 扩展，入口先预留在导航里。
        </p>
        <ul class="plan-list">
          <li>文档切片入库 + Embedding 向量化（Milvus）</li>
          <li>RAG 检索工具，Agent 自主决定「读原文件」还是「检索知识库」</li>
          <li>知识库列表 / 入库进度 / 检索测试面板</li>
          <li>设置项：Milvus 连接、Embedding 模型、默认来源目录</li>
        </ul>
        <p class="muted">后端已按同一套工具与中间件协议预留接入点，启用时无需改动 Agent 编排。</p>
      </div>
    </main>

    <div
      class="pane-handle right"
      :class="{ hidden: rightCollapsed }"
      @pointerdown="startDrag('right', $event)"
    ></div>
    <aside class="workbench-pane right" :class="{ collapsed: rightCollapsed }">
      <BoardPanel :session-id="activeId" :tasks="bgTasks" @collapse="togglePane('right')" />
    </aside>

    <footer v-show="view === 'chat'" class="dock">
      <div v-if="!modelReady" class="banner warn">
        后端未配置 LLM_API_KEY，发送消息会返回配置错误。请在 backend/.env 中填写后重启后端。
      </div>
      <div v-if="notice" class="toast">{{ notice }}</div>
      <div v-if="attachments.length" class="attach-strip">
        <div
          v-for="item in attachments"
          :key="item.localId"
          class="attach-chip"
          :class="item.status"
        >
          <span class="attach-kind">{{ kindLabel(item.kind) }}</span>
          <span class="attach-name" :title="item.filename">{{ item.filename }}</span>
          <span class="attach-size">{{ formatSize(item.size) }}</span>
          <span v-if="item.status === 'uploading'" class="attach-state">上传中…</span>
          <span v-else-if="item.status === 'failed'" class="attach-state error">失败</span>
          <button
            v-else
            type="button"
            class="attach-remove"
            title="移除"
            @click="removeAttachment(item.localId)"
          >
            ×
          </button>
        </div>
        <button type="button" class="link-btn" @click="clearAttachments">清空</button>
      </div>
      <div v-if="voiceState !== 'idle'" class="voice-strip">
        <span class="voice-label">{{ voiceLabel }}</span>
        <div class="wave-bars">
          <span
            v-for="(level, index) in voiceBars"
            :key="index"
            :style="{ height: `${Math.round(3 + level * 20)}px` }"
          ></span>
        </div>
      </div>
      <form class="input-pill" @submit.prevent="send">
        <input
          ref="fileInput"
          class="file-input"
          type="file"
          multiple
          @change="onFileSelected"
        />
        <button
          type="button"
          class="attach-btn"
          title="上传文件到当前会话"
          :disabled="streaming || uploading || Boolean(pendingConfirm)"
          @click="chooseFile"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M21.4 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.2-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
          </svg>
        </button>
        <button type="button" class="sphere-btn" title="聚焦输入" @click="focusInput">
          <span class="mini-dot"></span>
        </button>
        <textarea
          ref="inputEl"
          v-model="input"
          rows="1"
          placeholder="输入指令，可粘贴截图/文件，Enter 发送"
          :disabled="streaming || Boolean(pendingConfirm)"
          @input="autoGrow"
          @keydown="onKeydown"
          @paste="onPaste"
        ></textarea>
        <button
          type="button"
          class="mic-btn"
          :class="{ recording: voiceState === 'recording' }"
          :title="voiceState === 'recording' ? '松开结束录音' : '按住说话'"
          :disabled="
            streaming ||
            Boolean(pendingConfirm) ||
            voiceState === 'transcribing' ||
            voiceState === 'speaking'
          "
          @pointerdown.prevent="startVoice"
          @pointerup="stopVoice"
          @contextmenu.prevent
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <rect x="9" y="2" width="6" height="12" rx="3" />
            <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
            <path d="M12 18v4" />
            <path d="M8 22h8" />
          </svg>
        </button>
        <button
          v-if="streaming"
          type="button"
          class="stop-btn"
          @click="stopGeneration"
        >
          停止
        </button>
        <button
          v-else
          type="submit"
          class="send-btn"
          :disabled="Boolean(pendingConfirm) || (!input.trim() && !attachments.length)"
        >
          发送
        </button>
      </form>
      <div class="foot">Enter 发送 · Shift+Enter 换行 · 数据本地 SQLite 存储</div>
    </footer>

    <ConfirmModal
      v-if="pendingConfirm"
      :confirm="pendingConfirm"
      @accept="respondConfirm(true)"
      @reject="respondConfirm(false)"
    />

    <div v-if="previewUrl" class="img-lightbox" @click="previewUrl = ''">
      <img :src="previewUrl" alt="预览" />
      <button class="lightbox-close" type="button" @click.stop="previewUrl = ''">×</button>
    </div>

    <SettingsPanel
      v-if="settingsOpen"
      @close="settingsOpen = false"
      @saved="onSettingsSaved"
      @open-memory="openMemoryPanel"
    />

    <MemoryPanel
      v-if="memoryOpen"
      :session-id="activeId"
      @close="memoryOpen = false"
    />

    <McpStorePanel v-if="mcpStoreOpen" @close="mcpStoreOpen = false" />
  </div>
</template>
