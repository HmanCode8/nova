// 后端地址：默认本地 127.0.0.1:8000；Electron 打包后可注入 VITE_API_BASE
export const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
const WS_URL = `${API_BASE.replace(/^http/, 'ws')}/ws`

async function request(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const payload = await response.json()
      detail = payload.detail || detail
    } catch {
      /* 非 JSON 错误体，保留状态文本 */
    }
    throw new Error(detail)
  }
  return response.json()
}

export const api = {
  health: () => request('/api/health'),
  listSessions: async () => (await request('/api/sessions')).sessions,
  createSession: (title) => request('/api/sessions', { method: 'POST', body: { title } }),
  deleteSession: (id) => request(`/api/sessions/${id}`, { method: 'DELETE' }),
  listMessages: async (id) => (await request(`/api/sessions/${id}/messages`)).messages,
  getProject: async (id) =>
    (await request(`/api/sessions/${encodeURIComponent(id)}/project`)).project,
  getConfig: () => request('/api/config'),
  saveConfig: (patch) => request('/api/config', { method: 'PUT', body: patch }),
  listTraces: (params = {}) => {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, value)
    })
    const suffix = query.toString()
    return request(`/api/traces${suffix ? `?${suffix}` : ''}`)
  },
  clearTraces: (sessionId) =>
    request(`/api/traces?session_id=${encodeURIComponent(sessionId || '')}`, {
      method: 'DELETE'
    }),
  listTasks: async (sessionId) =>
    (await request(`/api/tasks?session_id=${encodeURIComponent(sessionId || '')}`)).tasks,
  createTask: (sessionId, prompt, title) =>
    request('/api/tasks', {
      method: 'POST',
      body: { session_id: sessionId, prompt, title }
    }),
  stopTask: (taskId) => request(`/api/tasks/${taskId}/stop`, { method: 'POST' }),
  getMcpCatalog: () => request('/api/mcp/catalog'),
  getRadar: (limit = 12) => request(`/api/radar?limit=${limit}`),
  listMcpServers: async () => (await request('/api/mcp/servers')).servers,
  installMcp: (payload) => request('/api/mcp/servers', { method: 'POST', body: payload }),
  importMcp: (text) => request('/api/mcp/import', { method: 'POST', body: { json: text } }),
  toggleMcp: (id, enabled) =>
    request(`/api/mcp/servers/${encodeURIComponent(id)}/toggle`, {
      method: 'POST',
      body: { enabled }
    }),
  deleteMcp: async (id) =>
    (await request(`/api/mcp/servers/${encodeURIComponent(id)}`, { method: 'DELETE' })).servers,
  testMcp: (id) =>
    request(`/api/mcp/servers/${encodeURIComponent(id)}/test`, { method: 'POST' }),
  listModels: () => request('/api/models'),
  saveModel: (profile) => request('/api/models', { method: 'POST', body: profile }),
  activateModel: (id) => request(`/api/models/${id}/activate`, { method: 'POST' }),
  setModelKey: (id, apiKey) =>
    request(`/api/models/${id}/key`, { method: 'PUT', body: { api_key: apiKey } }),
  deleteModel: (id) => request(`/api/models/${id}`, { method: 'DELETE' }),
  testModel: (id) => request('/api/models/test', { method: 'POST', body: { id } }),
  listMemory: (sessionId) =>
    request(`/api/memory?session_id=${encodeURIComponent(sessionId || '')}`),
  addMemory: (scope, text, sessionId) =>
    request('/api/memory', {
      method: 'POST',
      body: { scope, text, session_id: sessionId || '' }
    }),
  updateMemory: (scope, memoryId, text) =>
    request(`/api/memory/${scope}/${memoryId}`, { method: 'PATCH', body: { text } }),
  deleteMemory: (scope, memoryId) =>
    request(`/api/memory/${scope}/${memoryId}`, { method: 'DELETE' }),
  clearMemory: (scope, sessionId) =>
    request(`/api/memory?scope=${scope}&session_id=${encodeURIComponent(sessionId || '')}`, {
      method: 'DELETE'
    }),
  uploadFile: async (sessionId, file) => {
    const form = new FormData()
    form.append('session_id', sessionId)
    form.append('file', file)
    const response = await fetch(`${API_BASE}/upload`, { method: 'POST', body: form })
    if (!response.ok) {
      let detail = response.statusText
      try {
        const payload = await response.json()
        detail = payload.detail || detail
      } catch {
        /* 非 JSON 错误体 */
      }
      throw new Error(detail)
    }
    return response.json()
  },
  fileUrl: (sessionId, fileId) =>
    `${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(fileId)}`,
  openFile: (sessionId, fileId) =>
    request(
      `/api/sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(fileId)}/open`,
      { method: 'POST' }
    )
}

/**
 * WebSocket 客户端：断线自动重连（指数退避），事件透传给页面。
 */
export function createSocket({ onEvent, onStatus }) {
  let socket = null
  let retry = 0
  let closedByUser = false

  const connect = () => {
    onStatus?.('connecting')
    socket = new WebSocket(WS_URL)
    socket.onopen = () => {
      retry = 0
      onStatus?.('online')
    }
    socket.onmessage = (event) => {
      try {
        onEvent?.(JSON.parse(event.data))
      } catch {
        /* 忽略非法事件 */
      }
    }
    socket.onclose = () => {
      onStatus?.('offline')
      if (!closedByUser) {
        retry = Math.min(retry + 1, 6)
        setTimeout(connect, 500 * retry)
      }
    }
    socket.onerror = () => socket?.close()
  }

  connect()

  return {
    send(payload) {
      if (socket?.readyState !== WebSocket.OPEN) return false
      socket.send(JSON.stringify(payload))
      return true
    },
    close() {
      closedByUser = true
      socket?.close()
    }
  }
}
