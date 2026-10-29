<template>
  <div class="settings-overlay" @click.self="$emit('close')">
    <section class="settings-modal">
      <header class="settings-head">
        <h2>设置</h2>
        <button class="close" title="关闭" @click="$emit('close')">×</button>
      </header>

      <div v-if="loading" class="settings-loading">加载中…</div>

      <div v-else class="settings-body">
        <section class="setting-group">
          <h3>模型</h3>
          <p class="group-desc">OpenAI 兼容协议，可切换 DeepSeek / Ollama / 其他支持工具调用的服务。</p>

          <label class="field">
            <span class="field-label">Base URL</span>
            <input v-model="draft.base_url" placeholder="https://api.deepseek.com/v1" />
          </label>
          <label class="field">
            <span class="field-label">模型名称</span>
            <input v-model="draft.model_name" placeholder="deepseek-chat" />
          </label>
          <label class="field">
            <span class="field-label">Temperature（0 ~ 2）</span>
            <input v-model.number="draft.temperature" type="number" min="0" max="2" step="0.1" />
          </label>

          <label class="switch-row">
            <span>开启思考模式（enable_thinking）</span>
            <input v-model="draft.thinking_enabled" type="checkbox" />
          </label>
          <p class="group-desc">
            开启后随请求附带 enable_thinking=true，适用于 DashScope / 硅基流动 / vLLM 等；
            原生推理模型可不开。思考内容会以折叠块显示在对话里。
          </p>

          <label class="field">
            <span class="field-label">思考预算（tokens，0 = 不指定）</span>
            <input
              v-model.number="draft.thinking_budget"
              type="number"
              min="0"
              max="32000"
              step="256"
            />
          </label>
          <label class="field">
            <span class="field-label">推理强度 reasoning_effort（OpenAI 推理模型用）</span>
            <select v-model="draft.reasoning_effort">
              <option value="">不指定</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </label>
          <label class="field">
            <span class="field-label">单次最大输出 tokens（0 = 不指定）</span>
            <input v-model.number="draft.max_tokens" type="number" min="0" max="32000" step="256" />
          </label>
          <label class="field">
            <span class="field-label">额外请求参数 extra_body（JSON 对象，留空不发送）</span>
            <textarea
              v-model="draft.extra_body_text"
              rows="3"
              placeholder='{"enable_thinking": true, "thinking_budget": 2048}'
            ></textarea>
          </label>
          <p class="group-desc">
            各家服务商思考参数不同，这里直接透传给模型；写错会返回 400，保存时会校验 JSON 格式。
          </p>

          <div class="field">
            <span class="field-label">API Key</span>
            <div class="key-state">
              <span class="badge" :class="keyReady ? 'ok' : 'missing'">
                {{ keyReady ? '已配置' : '未配置' }}
              </span>
              <span class="tip">安全约束：Key 只写在 backend/.env 的 LLM_API_KEY，不写入数据库。</span>
            </div>
          </div>
        </section>

        <section class="setting-group">
          <h3>上下文</h3>
          <p class="group-desc">
            对话超过 token 上限时，较早内容会自动压缩为摘要，避免上下文过长导致费用与延迟上升。
          </p>
          <label class="field">
            <span class="field-label">上下文 token 上限（1000 ~ 32000）</span>
            <input
              v-model.number="draft.max_context_tokens"
              type="number"
              min="1000"
              max="32000"
              step="500"
            />
          </label>
        </section>

        <section class="setting-group">
          <h3>能力开关</h3>
          <label class="switch-row">
            <span>联网搜索（Tavily）</span>
            <input v-model="draft.web_search_enabled" type="checkbox" />
          </label>
          <label class="switch-row">
            <span>自动记忆</span>
            <input v-model="draft.auto_memory_enabled" type="checkbox" />
          </label>
          <label class="switch-row">
            <span>语音播报（语音提问后朗读回复）</span>
            <input v-model="draft.tts_enabled" type="checkbox" />
          </label>
        </section>

        <section class="setting-group">
          <h3>记忆</h3>
          <p class="group-desc">
            自动记忆会在对话后提炼长期偏好；关闭后不再生成新记忆，已有记忆仍会注入对话。
          </p>
          <button class="mini" type="button" @click="$emit('open-memory')">打开记忆管理</button>
        </section>

        <section class="setting-group">
          <h3>视觉理解</h3>
          <p class="group-desc">
            图片文字提取走本地 OCR；描述界面、流程图、图表、草图走视觉模型。
          </p>
          <label class="switch-row">
            <span>启用视觉理解</span>
            <input v-model="draft.vl_enabled" type="checkbox" />
          </label>
          <label class="field">
            <span class="field-label">图片来源</span>
            <select v-model="draft.vision_source">
              <option value="main">复用主模型（主模型支持看图时选这个）</option>
              <option value="separate">独立视觉模型</option>
            </select>
          </label>
          <p v-if="draft.vision_source === 'main'" class="group-desc">
            直接使用上面「模型」里的服务地址、模型名称与 LLM_API_KEY，无需再配一套 VL 密钥。
          </p>
          <template v-else>
            <label class="field">
              <span class="field-label">VL 服务地址（OpenAI 兼容）</span>
              <input
                v-model="draft.vl_base_url"
                placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
              />
            </label>
            <label class="field">
              <span class="field-label">VL 模型名称</span>
              <input v-model="draft.vl_model_name" placeholder="qwen-vl-max" />
            </label>
            <div class="field">
              <span class="field-label">VL 密钥</span>
              <div class="key-state">
                <span class="badge" :class="vlKeyReady ? 'ok' : 'missing'">
                  {{ vlKeyReady ? '已配置' : '未配置' }}
                </span>
                <span class="tip">
                  密钥只写在 backend/.env 的 VL_API_KEY；本机 Ollama 地址可留空。
                </span>
              </div>
            </div>
          </template>
          <label class="switch-row">
            <span>调用看图工具前人工确认</span>
            <input v-model="draft.vl_require_confirm" type="checkbox" />
          </label>
        </section>

        <section class="setting-group">
          <h3>文生图</h3>
          <p class="group-desc">
            聊天模型只能看图、不能出图；这里对接 OpenAI 兼容的 /images/generations 服务。
            密钥写在 .env 的 IMAGE_API_KEY，未配置时复用 LLM_API_KEY。
          </p>
          <label class="switch-row">
            <span>启用文生图（generate_image 工具）</span>
            <input v-model="draft.image_gen_enabled" type="checkbox" />
          </label>
          <label class="field">
            <span class="field-label">服务地址（留空则复用主模型地址）</span>
            <input
              v-model="draft.image_gen_base_url"
              placeholder="https://api.siliconflow.cn/v1"
            />
          </label>
          <label class="field">
            <span class="field-label">模型名称</span>
            <input v-model="draft.image_gen_model" placeholder="Kwai-Kolors/Kolors" />
          </label>
          <label class="field">
            <span class="field-label">默认尺寸</span>
            <input v-model="draft.image_gen_size" placeholder="1024x1024" />
          </label>
        </section>

        <section class="setting-group">
          <h3>系统</h3>
          <label class="switch-row">
            <span>开机自启</span>
            <input
              v-model="autostart"
              type="checkbox"
              :disabled="!autostartSupported"
              @change="onAutostartChange"
            />
          </label>
          <p class="group-desc">{{ autostartHint }}</p>
          <div class="btn-row">
            <button class="mini" type="button" @click="openLogs">打开日志目录</button>
            <button class="mini" type="button" @click="openConfigDir">打开配置目录</button>
          </div>
          <p class="group-desc">密钥写在配置目录的 .env 中（打包安装后首次启动会自动生成模板）。</p>
        </section>

        <section class="setting-group">
          <h3>文件访问</h3>
          <p class="group-desc">AI 只能读写以下目录内的文件；白名单为空时文件工具全部禁用。</p>

          <div class="dir-list">
            <div v-for="(dir, index) in draft.allowed_dirs" :key="dir" class="dir-item">
              <span class="dir-path">{{ dir }}</span>
              <button class="dir-remove" title="移除" @click="removeDir(index)">×</button>
            </div>
            <p v-if="!draft.allowed_dirs.length" class="dir-empty">尚未添加目录</p>
          </div>

          <div class="dir-add">
            <input
              v-model="newDir"
              placeholder="D:\work\项目目录（绝对路径）"
              @keydown.enter.prevent="addDir"
            />
            <button class="mini" type="button" @click="addDir">添加</button>
          </div>

          <label class="field">
            <span class="field-label">单文件大小上限（MB）</span>
            <input v-model.number="draft.max_file_size_mb" type="number" min="1" max="100" step="1" />
          </label>
        </section>

        <p v-if="error" class="settings-error">{{ error }}</p>
      </div>

      <footer class="settings-actions">
        <button class="ghost" @click="$emit('close')">取消</button>
        <button class="primary" :disabled="saving || loading" @click="save">
          {{ saving ? '保存中…' : '保存设置' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../ws'

const emit = defineEmits(['close', 'saved', 'open-memory'])

const loading = ref(true)
const saving = ref(false)
const error = ref('')
const keyReady = ref(false)
const vlKeyReady = ref(false)
const newDir = ref('')
const autostart = ref(false)
const autostartSupported = ref(Boolean(window.nova?.getAutostart))
const autostartHint = ref('仅安装版客户端支持开机自启，开发模式不会写入系统启动项。')

const draft = reactive({
  base_url: '',
  model_name: '',
  temperature: 0.7,
  max_tokens: 0,
  top_p: 0,
  reasoning_effort: '',
  thinking_enabled: false,
  thinking_budget: 0,
  extra_body_text: '',
  max_context_tokens: 6000,
  web_search_enabled: true,
  auto_memory_enabled: true,
  tts_enabled: true,
  vl_enabled: true,
  vision_source: 'main',
  vl_base_url: '',
  vl_model_name: '',
  vl_require_confirm: false,
  image_gen_enabled: false,
  image_gen_base_url: '',
  image_gen_model: '',
  image_gen_size: '1024x1024',
  max_file_size_mb: 10,
  allowed_dirs: []
})

function formatExtraBody(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  return Object.keys(value).length ? JSON.stringify(value, null, 2) : ''
}

async function load() {
  try {
    const config = await api.getConfig()
    draft.base_url = config.model?.base_url || ''
    draft.model_name = config.model?.model_name || ''
    draft.temperature = Number(config.model?.temperature ?? 0.7)
    draft.max_tokens = Number(config.model?.max_tokens ?? 0)
    draft.top_p = Number(config.model?.top_p ?? 0)
    draft.reasoning_effort = config.model?.reasoning_effort || ''
    draft.thinking_enabled = Boolean(config.model?.thinking_enabled)
    draft.thinking_budget = Number(config.model?.thinking_budget ?? 0)
    draft.extra_body_text = formatExtraBody(config.model?.extra_body)
    draft.max_context_tokens = Number(config.max_context_tokens ?? 6000)
    draft.web_search_enabled = Boolean(config.web_search_enabled)
    draft.auto_memory_enabled = Boolean(config.auto_memory_enabled)
    draft.tts_enabled = Boolean(config.tts_enabled ?? true)
    draft.vl_enabled = Boolean(config.vl_enabled ?? true)
    draft.vision_source = config.vision_source === 'separate' ? 'separate' : 'main'
    draft.vl_base_url = config.vl_base_url || ''
    draft.vl_model_name = config.vl_model_name || ''
    draft.vl_require_confirm = Boolean(config.vl_require_confirm)
    draft.image_gen_enabled = Boolean(config.image_gen_enabled)
    draft.image_gen_base_url = config.image_gen_base_url || ''
    draft.image_gen_model = config.image_gen_model || ''
    draft.image_gen_size = config.image_gen_size || '1024x1024'
    draft.max_file_size_mb = Number(config.max_file_size_mb ?? 10)
    draft.allowed_dirs = [...(config.allowed_dirs || [])]

    const health = await api.health()
    keyReady.value = Boolean(health.model_configured)
    vlKeyReady.value = Boolean(health.vl_key_configured)
  } catch (err) {
    error.value = `加载配置失败：${err.message}`
  } finally {
    loading.value = false
  }
}

async function loadAutostart() {
  if (!window.nova?.getAutostart) {
    autostartSupported.value = false
    autostartHint.value = '仅桌面客户端支持开机自启'
    return
  }
  try {
    const result = await window.nova.getAutostart()
    autostartSupported.value = Boolean(result?.supported)
    autostart.value = Boolean(result?.enabled)
    if (!result?.supported) {
      autostartHint.value = '开发模式不支持开机自启，安装后可用'
    }
  } catch (err) {
    autostartSupported.value = false
    autostartHint.value = `读取开机自启状态失败：${err.message}`
  }
}

async function onAutostartChange(event) {
  const enabled = event.target.checked
  try {
    const result = await window.nova.setAutostart(enabled)
    autostart.value = Boolean(result?.enabled)
    autostartHint.value = result?.enabled ? '已设置为开机自启' : '已关闭开机自启'
  } catch (err) {
    autostart.value = !enabled
    error.value = err.message
  }
}

async function openLogs() {
  if (!window.nova?.openLogs) {
    error.value = '仅桌面客户端支持打开日志目录'
    return
  }
  const ok = await window.nova.openLogs()
  if (!ok) error.value = '打开日志目录失败'
}

async function openConfigDir() {
  if (!window.nova?.openConfigDir) {
    error.value = '仅桌面客户端支持打开配置目录'
    return
  }
  const ok = await window.nova.openConfigDir()
  if (!ok) error.value = '打开配置目录失败'
}

function addDir() {
  const value = newDir.value.trim()
  if (!value) return
  if (draft.allowed_dirs.includes(value)) {
    newDir.value = ''
    return
  }
  draft.allowed_dirs.push(value)
  newDir.value = ''
}

function removeDir(index) {
  draft.allowed_dirs.splice(index, 1)
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    let extraBody = {}
    const rawBody = draft.extra_body_text.trim()
    if (rawBody) {
      try {
        extraBody = JSON.parse(rawBody)
      } catch {
        throw new Error('额外请求参数不是合法 JSON')
      }
      if (!extraBody || typeof extraBody !== 'object' || Array.isArray(extraBody)) {
        throw new Error('额外请求参数必须是 JSON 对象，例如 {"enable_thinking": true}')
      }
    }
    await api.saveConfig({
      model: {
        base_url: draft.base_url.trim(),
        model_name: draft.model_name.trim(),
        temperature: Number(draft.temperature),
        max_tokens: Number(draft.max_tokens) || 0,
        top_p: Number(draft.top_p) || 0,
        reasoning_effort: draft.reasoning_effort,
        thinking_enabled: draft.thinking_enabled,
        thinking_budget: Number(draft.thinking_budget) || 0,
        extra_body: extraBody
      },
      web_search_enabled: draft.web_search_enabled,
      auto_memory_enabled: draft.auto_memory_enabled,
      tts_enabled: draft.tts_enabled,
      vl_enabled: draft.vl_enabled,
      vision_source: draft.vision_source,
      vl_base_url: draft.vl_base_url.trim(),
      vl_model_name: draft.vl_model_name.trim(),
      vl_require_confirm: draft.vl_require_confirm,
      image_gen_enabled: draft.image_gen_enabled,
      image_gen_base_url: draft.image_gen_base_url.trim(),
      image_gen_model: draft.image_gen_model.trim(),
      image_gen_size: draft.image_gen_size.trim() || '1024x1024',
      max_context_tokens: Number(draft.max_context_tokens),
      max_file_size_mb: Number(draft.max_file_size_mb),
      allowed_dirs: [...draft.allowed_dirs]
    })
    emit('saved')
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  load()
  loadAutostart()
})
</script>
