<template>
  <div class="settings-overlay" @click.self="$emit('close')">
    <section class="settings-modal mcp-store">
      <header class="settings-head">
        <h2>MCP 商店</h2>
        <button class="close" title="关闭" @click="$emit('close')">×</button>
      </header>

      <div class="mcp-tabs">
        <button class="mcp-tab" :class="{ active: tab === 'catalog' }" @click="tab = 'catalog'">
          商店
        </button>
        <button class="mcp-tab" :class="{ active: tab === 'installed' }" @click="openInstalled">
          已安装 <span class="mcp-badge">{{ servers.length }}</span>
        </button>
      </div>

      <div v-if="tab === 'catalog'" class="settings-body">
        <div class="mcp-filter">
          <input v-model="keyword" class="mcp-search" placeholder="搜索 MCP 服务" />
          <button
            v-for="item in ['全部', ...categories]"
            :key="item"
            class="chip"
            :class="{ active: category === item }"
            @click="category = item"
          >
            {{ item }}
          </button>
          <button class="chip paste" @click="openImport">粘贴配置</button>
        </div>

        <div class="mcp-grid">
          <article
            v-for="item in filteredCatalog"
            :key="item.id"
            class="mcp-card"
            :class="{ installed: installedIds.has(item.id) }"
          >
            <div class="mcp-card-head">
              <strong>{{ item.name }}</strong>
              <span class="mcp-card-tags">
                <span v-if="item.verified" class="mcp-verified">✓ 已实测</span>
                <span class="mcp-cat">{{ item.category }}</span>
              </span>
            </div>
            <p class="mcp-summary">{{ item.summary }}</p>
            <div class="mcp-card-actions">
              <span v-if="installedIds.has(item.id)" class="mcp-installed">已安装</span>
              <button class="mini" type="button" @click="openInstall(item)">
                {{ installedIds.has(item.id) ? '重新配置' : '安装' }}
              </button>
            </div>
          </article>
        </div>
      </div>

      <div v-else class="settings-body">
        <p v-if="!servers.length" class="group-desc">还没有安装任何 MCP 服务。</p>
        <article v-for="server in servers" :key="server.id" class="mcp-server">
          <div class="mcp-server-main">
            <div class="mcp-server-title">
              <strong>{{ server.name }}</strong>
              <span class="mcp-status" :class="server.status">{{ statusLabel(server.status) }}</span>
              <span class="mcp-tools">{{ server.tool_count }} 个工具</span>
            </div>
            <p class="mcp-cmd">
              <span class="mcp-transport">{{ server.transport === 'http' ? 'HTTP' : 'stdio' }}</span>
              {{
                server.transport === 'http'
                  ? server.url
                  : `${server.command} ${(server.args || []).join(' ')}`
              }}
            </p>
            <p v-if="server.error" class="mcp-error">{{ server.error }}</p>
            <div v-if="server.tools.length" class="mcp-tool-list">
              <span v-for="name in server.tools" :key="name" class="mcp-tool">{{ name }}</span>
            </div>
          </div>
          <div class="mcp-server-actions">
            <button class="link-btn" @click="openEdit(server)">编辑</button>
            <button class="link-btn" @click="toggleServer(server)">
              {{ server.enabled ? '停用' : '启用' }}
            </button>
            <button class="link-btn" @click="testServer(server.id)">测试</button>
            <button class="link-btn danger" @click="removeServer(server.id)">卸载</button>
          </div>
        </article>
        <p v-if="hint" class="group-desc">{{ hint }}</p>
      </div>

      <footer class="settings-actions">
        <button class="ghost" @click="$emit('close')">关闭</button>
      </footer>

      <div v-if="editor" class="mcp-editor-mask" @click.self="closeEditor">
        <div class="mcp-editor">
          <h3>{{ editingId ? `编辑：${editor.name}` : editor.name }}</h3>
          <p class="group-desc">
            {{ editingId ? '保存后立即按新配置重连，工具列表会刷新。' : editor.summary }}
          </p>

          <label class="field">
            <span class="field-label">服务名称</span>
            <input v-model="form.name" placeholder="例如 我的文件服务" />
          </label>

          <label class="field">
            <span class="field-label">传输方式</span>
            <select v-model="form.transport">
              <option value="stdio">stdio（本地进程）</option>
              <option value="http">streamable-http（远程地址）</option>
            </select>
          </label>

          <template v-if="form.transport === 'stdio'">
            <label class="field">
              <span class="field-label">启动命令</span>
              <input v-model="form.command" placeholder="npx / python / 可执行文件路径" />
            </label>
            <label class="field">
              <span class="field-label">参数（每行一个）</span>
              <textarea v-model="form.argsText" rows="3" placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;D:\work"></textarea>
            </label>
          </template>

          <template v-else>
            <label class="field">
              <span class="field-label">MCP 端点地址</span>
              <input v-model="form.url" placeholder="https://example.com/mcp" />
            </label>
            <label class="field">
              <span class="field-label">请求头（每行 Key: Value，密钥可写 ${ENV_NAME}）</span>
              <textarea
                v-model="form.headersText"
                rows="3"
                placeholder="Authorization: Bearer ${MY_MCP_TOKEN}"
              ></textarea>
            </label>
          </template>
          <label v-for="field in editor.env_schema" :key="field.key" class="field">
            <span class="field-label">
              {{ field.label }}<span v-if="field.required" class="req">*</span>
            </span>
            <input
              v-model="form.variables[field.key]"
              :type="field.secret ? 'password' : 'text'"
              :placeholder="field.secret ? '写入 .env，前端不保存' : field.key"
            />
          </label>
          <label class="field">
            <span class="field-label">
              环境变量（每行 KEY=VALUE；密钥类只写 .env，已配置的回填为 ${KEY} 占位，置空则保持不变）
            </span>
            <textarea v-model="form.envText" rows="2" placeholder="API_BASE=https://example.com"></textarea>
          </label>

          <p v-if="editorHint" class="group-desc">{{ editorHint }}</p>
          <div class="mcp-editor-actions">
            <button class="ghost" @click="closeEditor">取消</button>
            <button class="primary" :disabled="saving" @click="install">
              {{ saving ? '保存中…' : editingId ? '保存修改' : '安装并启用' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="importOpen" class="mcp-editor-mask" @click.self="importOpen = false">
        <div class="mcp-editor">
          <h3>粘贴配置</h3>
          <p class="group-desc">
            支持 Claude Desktop / Cursor 的 <code>mcpServers</code> 写法，自动识别 stdio 与
            streamable-http；请求头里的明文密钥会写入 .env，不落库。
          </p>
          <textarea
            v-model="importText"
            rows="12"
            class="import-area"
            spellcheck="false"
            placeholder='{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\\\work"]
    },
    "remote-demo": {
      "url": "https://example.com/mcp",
      "headers": { "Authorization": "Bearer ${MY_MCP_TOKEN}" }
    }
  }
}'
          ></textarea>
          <p v-if="importHint" class="group-desc">{{ importHint }}</p>
          <div class="mcp-editor-actions">
            <button class="ghost" @click="importOpen = false">取消</button>
            <button class="primary" :disabled="importing" @click="doImport">
              {{ importing ? '导入中…' : '导入并启用' }}
            </button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../ws'

defineProps({})
defineEmits(['close'])

const tab = ref('catalog')
const catalog = ref([])
const categories = ref([])
const servers = ref([])
const keyword = ref('')
const category = ref('全部')
const editor = ref(null)
const editingId = ref('')
const editorHint = ref('')
const hint = ref('')
const saving = ref(false)
const importOpen = ref(false)
const importText = ref('')
const importHint = ref('')
const importing = ref(false)

const form = reactive({
  name: '',
  transport: 'stdio',
  command: '',
  argsText: '',
  url: '',
  headersText: '',
  envText: '',
  variables: {}
})

const installedIds = computed(() => new Set(servers.value.map((item) => item.id)))

const filteredCatalog = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return catalog.value.filter((item) => {
    if (category.value !== '全部' && item.category !== category.value) return false
    if (!text) return true
    return (
      item.name.toLowerCase().includes(text) ||
      item.summary.toLowerCase().includes(text) ||
      item.id.includes(text)
    )
  })
})

const STATUS_LABELS = { running: '运行中', stopped: '已停用', error: '启动失败' }

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

async function loadCatalog() {
  try {
    const data = await api.getMcpCatalog()
    catalog.value = data.items || []
    categories.value = data.categories || []
  } catch (err) {
    hint.value = `加载商店失败：${err.message}`
  }
}

async function loadServers() {
  try {
    servers.value = await api.listMcpServers()
  } catch (err) {
    hint.value = `加载已安装服务失败：${err.message}`
  }
}

async function openInstalled() {
  tab.value = 'installed'
  await loadServers()
}

function openInstall(item) {
  const existing = servers.value.find((server) => server.id === item.id)
  editingId.value = ''
  editor.value = item
  editorHint.value = ''
  fillForm({
    name: existing?.name || item.name,
    transport: existing?.transport || item.transport || 'stdio',
    command: existing?.command || item.command,
    args: existing?.args || item.args || [],
    url: existing?.url || item.url || '',
    headers: existing?.headers || item.headers || {},
    env: existing?.env || {}
  })
}

/** 编辑已安装服务：沿用原 id 覆盖保存，密钥字段回填 ${KEY} 占位（真实值在 .env）。 */
function openEdit(server) {
  editingId.value = server.id
  editor.value = { id: server.id, name: server.name, summary: '', transport: server.transport, env_schema: [] }
  editorHint.value = ''
  fillForm(server)
}

function closeEditor() {
  editor.value = null
  editingId.value = ''
  editorHint.value = ''
}

function fillForm(data) {
  Object.assign(form, {
    name: data.name || '',
    transport: data.transport || 'stdio',
    command: data.command || '',
    argsText: (data.args || []).join('\n'),
    url: data.url || '',
    headersText: Object.entries(data.headers || {})
      .map(([key, value]) => `${key}: ${value}`)
      .join('\n'),
    envText: Object.entries(data.env || {})
      .map(([key, value]) => `${key}=${value}`)
      .join('\n'),
    variables: {}
  })
}

function openImport() {
  importOpen.value = true
  importHint.value = ''
}

async function doImport() {
  if (!importText.value.trim()) {
    importHint.value = '请先粘贴配置'
    return
  }
  importing.value = true
  importHint.value = ''
  try {
    const data = await api.importMcp(importText.value)
    servers.value = data.servers || []
    const ok = (data.imported || []).length
    const bad = data.failed || []
    importHint.value = bad.length
      ? `成功 ${ok} 个，失败 ${bad.length} 个：${bad.map((item) => `${item.name}(${item.error})`).join('；')}`
      : `已导入 ${ok} 个服务，工具已注册给 Agent`
    if (!bad.length) {
      tab.value = 'installed'
      importOpen.value = false
    }
  } catch (err) {
    importHint.value = `导入失败：${err.message}`
  } finally {
    importing.value = false
  }
}

function parseHeaders(text) {
  const headers = {}
  String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const index = line.indexOf(':')
      if (index > 0) headers[line.slice(0, index).trim()] = line.slice(index + 1).trim()
    })
  return headers
}

function parseEnv(text) {
  const env = {}
  String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const index = line.indexOf('=')
      if (index > 0) env[line.slice(0, index).trim()] = line.slice(index + 1).trim()
    })
  return env
}

async function install() {
  if (!editor.value) return
  saving.value = true
  editorHint.value = ''
  const isEdit = Boolean(editingId.value)
  try {
    const payload = {
      // 编辑沿用原 id；自定义条目不能用固定 id，否则多个服务会互相覆盖
      id: isEdit
        ? editingId.value
        : ['custom', 'http-custom'].includes(editor.value.id)
          ? ''
          : editor.value.id,
      // 编辑时不再带 catalog_id，避免目录模板的必填参数校验
      catalog_id: isEdit ? '' : editor.value.id,
      name: form.name.trim(),
      transport: form.transport,
      command: form.command.trim(),
      args: form.argsText
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean),
      url: form.url.trim(),
      headers: parseHeaders(form.headersText),
      env: parseEnv(form.envText),
      variables: { ...form.variables }
    }
    await api.installMcp(payload)
    closeEditor()
    tab.value = 'installed'
    await loadServers()
    hint.value = isEdit
      ? '已保存修改，服务已按新配置重连'
      : '安装完成，工具已注册给 Agent（下一句话即可调用）'
  } catch (err) {
    editorHint.value = `${isEdit ? '保存' : '安装'}失败：${err.message}`
  } finally {
    saving.value = false
  }
}

async function toggleServer(server) {
  try {
    servers.value = await api.toggleMcp(server.id, !server.enabled)
    hint.value = server.enabled ? '已停用，工具已从 Agent 移除' : '已启用，工具已重新注册'
  } catch (err) {
    hint.value = `操作失败：${err.message}`
  }
}

async function testServer(id) {
  hint.value = '正在测试连接…'
  try {
    const result = await api.testMcp(id)
    hint.value = result.ok ? result.message : `连接失败：${result.message}`
    await loadServers()
  } catch (err) {
    hint.value = `测试失败：${err.message}`
  }
}

async function removeServer(id) {
  if (!window.confirm('卸载该 MCP 服务？相关工具会立即从 Agent 移除。')) return
  try {
    servers.value = await api.deleteMcp(id)
    hint.value = '已卸载'
  } catch (err) {
    hint.value = `卸载失败：${err.message}`
  }
}

onMounted(async () => {
  await loadCatalog()
  await loadServers()
})
</script>
