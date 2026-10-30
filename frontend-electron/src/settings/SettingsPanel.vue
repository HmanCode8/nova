<template>
  <div class="settings-overlay" @click.self="$emit('close')">
    <section class="settings-modal settings-modal--split">
      <header class="settings-head">
        <h2>设置</h2>
        <button class="close" title="关闭" @click="$emit('close')">×</button>
      </header>

      <div v-if="loading" class="settings-loading">加载中…</div>

      <div v-else class="settings-main">
        <nav class="settings-nav">
          <button
            v-for="item in TABS"
            :key="item.id"
            class="nav-item"
            :class="{ active: tab === item.id }"
            @click="tab = item.id"
          >
            <span class="nav-icon" v-html="item.icon"></span>
            <span>{{ item.label }}</span>
          </button>
        </nav>

        <div class="settings-body">
        <section v-show="tab === 'model'" class="setting-group">
          <h3>模型</h3>
          <p class="group-desc">
            填好 API 密钥即可使用该模型；切换后下一句话立即生效，无需重启。密钥由后端写入 .env，前端看不到明文。
          </p>

          <p v-if="profileHint" class="provider-banner" :class="hintTone">{{ profileHint }}</p>
          <p v-if="imageModelLabel" class="group-desc">当前出图使用：{{ imageModelLabel }}</p>

          <div class="provider-list">
            <div
              v-for="profile in profiles"
              :key="profile.id"
              class="provider-card"
              :class="{ editing: editingId === profile.id }"
            >
              <header class="provider-head">
                <span class="provider-name">
                  {{ profile.name }}
                  <i
                    class="provider-dot"
                    :class="profile.has_key ? 'ok' : 'bad'"
                    :title="profile.has_key ? '密钥已配置' : '缺少密钥'"
                  ></i>
                  <em v-if="hasProfileCap(profile, 'vision')" class="provider-cap">看图</em>
                  <em v-if="hasProfileCap(profile, 'image')" class="provider-cap image">出图</em>
                </span>
                <div class="provider-head-actions">
                  <span v-if="profile.id === activeModelId" class="provider-tag">使用中</span>
                  <button class="link-btn" @click="toggleEdit(profile)">
                    {{ editingId === profile.id ? '收起' : '编辑' }}
                  </button>
                </div>
              </header>

              <div v-if="editingId === profile.id" class="provider-body">
                <div class="provider-title">
                  {{ editor.name || profile.name }}
                  <span class="provider-model">{{ editor.model_name || profile.model_name || '未填模型名' }}</span>
                </div>

                <label class="field">
                  <span class="field-label">API 密钥</span>
                  <input
                    v-model="editor.api_key"
                    type="password"
                    autocomplete="off"
                    :placeholder="profile.has_key ? '已配置，输入新值可替换' : 'sk-...'"
                  />
                </label>

                <button class="provider-more" @click="moreOpen = !moreOpen">
                  {{ moreOpen ? '▾' : '▸' }} 自定义设置
                </button>

                <div v-if="moreOpen" class="provider-advanced">
                  <label class="field">
                    <span class="field-label">档案名称</span>
                    <input v-model="editor.name" placeholder="例如 DeepSeek Flash" />
                  </label>
                  <label class="field">
                    <span class="field-label">Base URL</span>
                    <input v-model="editor.base_url" placeholder="https://api.deepseek.com/v1" />
                  </label>
                  <label class="field">
                    <span class="field-label">模型名称</span>
                    <input v-model="editor.model_name" placeholder="deepseek-chat" />
                  </label>
                  <label class="field">
                    <span class="field-label">密钥环境变量名</span>
                    <input v-model="editor.api_key_env" placeholder="LLM_API_KEY" />
                  </label>
                </div>

                <div class="provider-caps">
                  <div class="caps-row">
                    <span class="field-label">能力</span>
                    <span class="cap-chip on">对话</span>
                    <label class="cap-chip" :class="{ on: hasCap('vision') }">
                      <input type="checkbox" :checked="hasCap('vision')" @change="toggleCap('vision')" />
                      看图
                    </label>
                    <label class="cap-chip" :class="{ on: hasCap('image') }">
                      <input type="checkbox" :checked="hasCap('image')" @change="toggleCap('image')" />
                      生成图片
                    </label>
                  </div>
                  <p class="caps-tip">
                    勾选后系统会按能力自动把「看图 / 出图」请求路由到该档案；出图不需要在对话里指定模型。
                  </p>

                  <div v-if="hasCap('image')" class="caps-image">
                    <label class="field">
                      <span class="field-label">出图接口</span>
                      <select v-model="editor.image_provider">
                        <option value="openai">OpenAI 兼容（/images/generations）</option>
                        <option value="dashscope">阿里百炼原生（异步任务）</option>
                      </select>
                    </label>
                    <label class="field">
                      <span class="field-label">出图模型</span>
                      <input v-model="editor.image_model" placeholder="如 wanx2.1-t2i-turbo / gpt-image-1" />
                    </label>
                    <label class="field">
                      <span class="field-label">出图尺寸</span>
                      <input v-model="editor.image_size" placeholder="1024x1024" />
                    </label>
                    <label class="field">
                      <span class="field-label">出图服务地址（留空沿用上方 Base URL）</span>
                      <input v-model="editor.image_base_url" placeholder="留空即复用当前提供商地址" />
                    </label>
                  </div>
                </div>

                <div class="provider-foot">
                  <button class="link-btn" @click="testModel(profile.id)">测试连接</button>
                  <button
                    class="link-btn"
                    :disabled="profile.id === activeModelId"
                    @click="activateModel(profile.id)"
                  >
                    {{ profile.id === activeModelId ? '当前模型' : '设为当前' }}
                  </button>
                  <button class="link-btn danger" @click="removeModel(profile.id)">删除</button>
                  <span class="provider-spacer"></span>
                  <button class="link-btn" @click="cancelEdit">取消</button>
                  <button class="provider-save" @click="saveProfile">保存</button>
                </div>
              </div>
            </div>

            <div v-if="editingId === 'new'" class="provider-card editing">
              <header class="provider-head">
                <span class="provider-name">新的模型提供商</span>
                <button class="link-btn" @click="cancelEdit">收起</button>
              </header>
              <div class="provider-body">
                <div class="provider-title">填写密钥与服务信息</div>
                <label class="field">
                  <span class="field-label">API 密钥</span>
                  <input v-model="editor.api_key" type="password" placeholder="sk-..." autocomplete="off" />
                </label>
                <label class="field">
                  <span class="field-label">模型名称</span>
                  <input v-model="editor.model_name" placeholder="deepseek-chat" />
                </label>
                <label class="field">
                  <span class="field-label">Base URL</span>
                  <input v-model="editor.base_url" placeholder="https://api.deepseek.com/v1" />
                </label>
                <label class="field">
                  <span class="field-label">提供商名称</span>
                  <input v-model="editor.name" placeholder="例如 DeepSeek" />
                </label>
                <label class="field">
                  <span class="field-label">密钥环境变量名</span>
                  <input v-model="editor.api_key_env" placeholder="LLM_API_KEY" />
                </label>

                <div class="provider-caps">
                  <div class="caps-row">
                    <span class="field-label">能力</span>
                    <span class="cap-chip on">对话</span>
                    <label class="cap-chip" :class="{ on: hasCap('vision') }">
                      <input type="checkbox" :checked="hasCap('vision')" @change="toggleCap('vision')" />
                      看图
                    </label>
                    <label class="cap-chip" :class="{ on: hasCap('image') }">
                      <input type="checkbox" :checked="hasCap('image')" @change="toggleCap('image')" />
                      生成图片
                    </label>
                  </div>
                  <div v-if="hasCap('image')" class="caps-image">
                    <label class="field">
                      <span class="field-label">出图接口</span>
                      <select v-model="editor.image_provider">
                        <option value="openai">OpenAI 兼容（/images/generations）</option>
                        <option value="dashscope">阿里百炼原生（异步任务）</option>
                      </select>
                    </label>
                    <label class="field">
                      <span class="field-label">出图模型</span>
                      <input v-model="editor.image_model" placeholder="如 wanx2.1-t2i-turbo / gpt-image-1" />
                    </label>
                  </div>
                </div>

                <div class="provider-foot">
                  <span class="provider-spacer"></span>
                  <button class="link-btn" @click="cancelEdit">取消</button>
                  <button class="provider-save" @click="saveProfile">保存</button>
                </div>
              </div>
            </div>

            <button v-if="editingId !== 'new'" class="provider-add" @click="startAdd">
              ＋ 添加模型提供商
            </button>
          </div>
        </section>

        <section v-show="tab === 'model'" class="setting-group">
          <h3>模型参数</h3>
          <p class="group-desc">
            连接信息（Base URL / 模型名 / 密钥）在「模型档案」中管理；这里调通用采样与思考参数。
          </p>

          <label class="field">
            <span class="field-label">Temperature（0 ~ 2）</span>
            <input v-model.number="draft.temperature" type="number" min="0" max="2" step="0.1" />
          </label>

          <label class="switch-row">
            <span>开启思考模式</span>
            <input v-model="draft.thinking_enabled" type="checkbox" />
          </label>
          <p class="group-desc">
            按服务商自动选择参数：DeepSeek（deepseek-flash / deepseek-v4-pro）用
            <code>thinking.type</code>，DashScope / 硅基流动 / vLLM 用 <code>enable_thinking</code>。
            DeepSeek V4 默认就开启思考，取消勾选会显式关闭；思考内容以折叠块显示在对话里。
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
            <span class="field-label">推理强度 reasoning_effort</span>
            <select v-model="draft.reasoning_effort">
              <option value="">不指定</option>
              <option value="minimal">minimal（最快）</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="max">max（DeepSeek V4 最长思考）</option>
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

        <section v-show="tab === 'chat'" class="setting-group">
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

        <section v-show="tab === 'agent'" class="setting-group">
          <h3>智能体模式</h3>
          <p class="group-desc">
            自主模式下，智能体会直接读写文件、打开文档、发邮件、建日程、执行命令，不再逐步弹确认；只有删除文件/目录会停下来等你确认。
          </p>
          <label class="switch-row">
            <span>自主模式（除删除外免确认）</span>
            <input v-model="draft.autonomy_mode" type="checkbox" />
          </label>
          <label class="switch-row">
            <span>允许执行命令（run_shell）</span>
            <input v-model="draft.shell_enabled" type="checkbox" />
          </label>
          <p class="group-desc">
            关闭自主模式后恢复“每步确认”；关闭命令执行后智能体无法安装依赖、跑构建或测试。
            删盘、格式化、关机等破坏性命令即使在自主模式下也会转为人工确认。
          </p>
        </section>

        <section v-show="tab === 'chat'" class="setting-group">
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

        <section v-show="tab === 'chat'" class="setting-group">
          <h3>记忆</h3>
          <p class="group-desc">
            自动记忆会在对话后提炼长期偏好；关闭后不再生成新记忆，已有记忆仍会注入对话。
          </p>
          <button class="mini" type="button" @click="$emit('open-memory')">打开记忆管理</button>
        </section>

        <section v-show="tab === 'vision'" class="setting-group">
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

        <section v-show="tab === 'vision'" class="setting-group">
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

        <section v-show="tab === 'system'" class="setting-group">
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

        <section v-show="tab === 'system'" class="setting-group">
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
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../ws'

const emit = defineEmits(['close', 'saved', 'open-memory'])

// 左侧分类导航：与主流 IDE 设置面板一致，避免一屏堆十几个分组
const TABS = [
  { id: 'model', label: '模型', icon: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><circle cx="7.5" cy="7.5" r="1"/><circle cx="7.5" cy="16.5" r="1"/></svg>' },
  { id: 'chat', label: '对话', icon: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z"/></svg>' },
  { id: 'agent', label: '智能体', icon: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l7 4v6c0 4-3 6.5-7 8-4-1.5-7-4-7-8V7z"/></svg>' },
  { id: 'vision', label: '视觉与生图', icon: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M4 18l5-5 3 3 3-3 5 5"/></svg>' },
  { id: 'system', label: '系统与文件', icon: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 7h6l2 2h10v10H3z"/><path d="M3 7V5h6"/></svg>' }
]
const tab = ref('model')

const loading = ref(true)
const saving = ref(false)
const error = ref('')
const keyReady = ref(false)
const vlKeyReady = ref(false)
const newDir = ref('')
const autostart = ref(false)
const autostartSupported = ref(Boolean(window.nova?.getAutostart))
const autostartHint = ref('仅安装版客户端支持开机自启，开发模式不会写入系统启动项。')

const profiles = ref([])
const activeModelId = ref('')
const profileHint = ref('')
const hintTone = ref('info')
const editingId = ref('')
const moreOpen = ref(false)

function hasProfileCap(profile, name) {
  return (profile.capabilities || []).includes(name)
}

/** 与后端一致：激活档案优先，其次列表顺序，第一个声明「可生成图片」的档案。 */
const imageModelLabel = computed(() => {
  const ordered = [...profiles.value].sort(
    (a, b) => Number(b.id === activeModelId.value) - Number(a.id === activeModelId.value)
  )
  const target = ordered.find((item) => hasProfileCap(item, 'image'))
  if (!target) return ''
  const image = target.image || {}
  const provider = image.provider === 'dashscope' ? '百炼原生' : 'OpenAI 兼容'
  return `${target.name} · ${provider} · ${image.model || target.model_name}`
})
const editor = reactive({
  id: '',
  name: '',
  base_url: '',
  model_name: '',
  api_key_env: 'LLM_API_KEY',
  api_key: '',
  capabilities: ['chat'],
  image_provider: 'openai',
  image_model: '',
  image_base_url: '',
  image_size: '1024x1024'
})

function resetEditor() {
  Object.assign(editor, {
    id: '',
    name: '',
    base_url: '',
    model_name: '',
    api_key_env: 'LLM_API_KEY',
    api_key: '',
    capabilities: ['chat'],
    image_provider: 'openai',
    image_model: '',
    image_base_url: '',
    image_size: '1024x1024'
  })
}

async function loadProfiles() {
  try {
    const data = await api.listModels()
    profiles.value = data.profiles || []
    activeModelId.value = data.active_id || ''
    const active = profiles.value.find((item) => item.id === activeModelId.value)
    if (active) {
      draft.base_url = active.base_url
      draft.model_name = active.model_name
    }
  } catch (err) {
    profileHint.value = `加载模型档案失败：${err.message}`
  }
}

async function activateModel(id) {
  try {
    const data = await api.activateModel(id)
    profiles.value = data.profiles || []
    activeModelId.value = data.active_id || ''
    const active = profiles.value.find((item) => item.id === id)
    if (active) {
      draft.base_url = active.base_url
      draft.model_name = active.model_name
    }
    profileHint.value = '已切换，下一句话立即生效'
    hintTone.value = 'ok'
    emit('saved')
  } catch (err) {
    hintTone.value = 'error'
    profileHint.value = `切换失败：${err.message}`
  }
}

async function testModel(id) {
  hintTone.value = 'info'
  profileHint.value = '正在测试连接…'
  try {
    const result = await api.testModel(id)
    hintTone.value = result.ok ? 'ok' : 'error'
    profileHint.value = result.ok
      ? `连接正常（${result.latency_ms} ms）`
      : `测试失败：${result.message}`
  } catch (err) {
    hintTone.value = 'error'
    profileHint.value = `测试失败：${err.message}`
  }
}

function editModel(profile) {
  const image = profile.image || {}
  Object.assign(editor, {
    id: profile.id,
    name: profile.name,
    base_url: profile.base_url,
    model_name: profile.model_name,
    api_key_env: profile.api_key_env || 'LLM_API_KEY',
    api_key: '',
    capabilities: profile.capabilities || ['chat'],
    image_provider: image.provider || 'openai',
    image_model: image.model || '',
    image_base_url: image.base_url || '',
    image_size: image.size || '1024x1024'
  })
}

function toggleEdit(profile) {
  if (editingId.value === profile.id) {
    cancelEdit()
    return
  }
  editModel(profile)
  editingId.value = profile.id
  // 没填全的服务信息默认展开，避免用户找不到 Base URL / 模型名
  moreOpen.value = !profile.model_name || !profile.base_url
  profileHint.value = ''
}

function startAdd() {
  resetEditor()
  editingId.value = 'new'
  moreOpen.value = true
  profileHint.value = ''
}

function cancelEdit() {
  editingId.value = ''
  moreOpen.value = false
  profileHint.value = ''
  resetEditor()
}

function editorDirty() {
  if (editingId.value) return Boolean(editor.model_name.trim())
  return Boolean(
    editor.name.trim() ||
      editor.base_url.trim() ||
      editor.model_name.trim() ||
      editor.api_key.trim()
  )
}

/** 能力勾选：chat 恒开，vision / image 可切换；勾出图时按服务商预填推荐配置。 */
function hasCap(name) {
  return (editor.capabilities || []).includes(name)
}

function inferImagePreset() {
  const url = (editor.base_url || '').toLowerCase()
  if (url.includes('dashscope') || url.includes('aliyuncs.com')) {
    return { provider: 'dashscope', model: 'wanx2.1-t2i-turbo' }
  }
  return { provider: 'openai', model: 'gpt-image-1' }
}

function toggleCap(name) {
  const caps = new Set(editor.capabilities || ['chat'])
  const enabling = !caps.has(name)
  if (enabling) caps.add(name)
  else caps.delete(name)
  caps.add('chat')
  editor.capabilities = [...caps]
  if (name === 'image' && enabling) {
    // 勾选即预填，避免「还要再配一堆」的体感
    const preset = inferImagePreset()
    if (!editor.image_model.trim()) editor.image_model = preset.model
    editor.image_provider = preset.provider
  }
}

/**
 * 提交档案编辑器里的内容。
 * 关键点：底部「保存设置」也会调用这里，避免用户在编辑器里填完却点了底部按钮导致内容丢失。
 * 新增档案后自动切换为当前使用，避免“保存了但没生效”的错觉。
 */
async function commitEditor() {
  if (!editorDirty()) return ''
  const isNew = editingId.value === 'new' || !editor.id
  const profileId = editor.id || `p${Date.now().toString(36)}`
  const data = await api.saveModel({
    id: profileId,
    name: editor.name.trim() || '未命名模型',
    base_url: editor.base_url.trim(),
    model_name: editor.model_name.trim(),
    api_key_env: (editor.api_key_env || 'LLM_API_KEY').trim(),
    capabilities: editor.capabilities.length ? editor.capabilities : ['chat'],
    image: {
      provider: editor.image_provider || 'openai',
      model: editor.image_model.trim(),
      base_url: editor.image_base_url.trim(),
      size: editor.image_size.trim() || '1024x1024'
    }
  })
  profiles.value = data.profiles || []
  activeModelId.value = data.active_id || ''
  if (editor.api_key.trim()) {
    const refreshed = await api.setModelKey(profileId, editor.api_key.trim())
    profiles.value = refreshed.profiles || profiles.value
  }
  if (isNew) {
    const activated = await api.activateModel(profileId)
    profiles.value = activated.profiles || profiles.value
    activeModelId.value = activated.active_id || profileId
  }
  resetEditor()
  return profileId
}

async function saveProfile() {
  if (!editor.model_name.trim()) {
    hintTone.value = 'error'
    profileHint.value = '请填写模型名称（例如 deepseek-chat）'
    return
  }
  const isNew = editingId.value === 'new' || !editor.id
  try {
    await commitEditor()
    editingId.value = ''
    moreOpen.value = false
    hintTone.value = 'ok'
    profileHint.value = isNew ? '已新增并切换为当前模型' : '已保存'
    // 档案内的保存不关闭面板，用户要能看到结果
    emit('saved', { close: false })
  } catch (err) {
    hintTone.value = 'error'
    profileHint.value = `保存失败：${err.message}`
  }
}

async function removeModel(id) {
  try {
    const data = await api.deleteModel(id)
    profiles.value = data.profiles || []
    activeModelId.value = data.active_id || ''
    if (editingId.value === id) cancelEdit()
    hintTone.value = 'ok'
    profileHint.value = '已删除该提供商'
    emit('saved')
  } catch (err) {
    hintTone.value = 'error'
    profileHint.value = `删除失败：${err.message}`
  }
}

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
  autonomy_mode: true,
  shell_enabled: true,
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
    draft.autonomy_mode = config.autonomy_mode !== false
    draft.shell_enabled = config.shell_enabled !== false
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
    // 先把编辑器里填的档案存下来，再存其它设置；两者都不会丢
    const savedProfileId = await commitEditor()
    if (savedProfileId) {
      editingId.value = ''
      moreOpen.value = false
      hintTone.value = 'ok'
      profileHint.value = '模型提供商已保存并切换为当前模型'
    }
    const active = profiles.value.find((item) => item.id === activeModelId.value)
    await api.saveConfig({
      model: {
        base_url: (active?.base_url || draft.base_url).trim(),
        model_name: (active?.model_name || draft.model_name).trim(),
        temperature: Number(draft.temperature),
        max_tokens: Number(draft.max_tokens) || 0,
        top_p: Number(draft.top_p) || 0,
        reasoning_effort: draft.reasoning_effort,
        thinking_enabled: draft.thinking_enabled,
        thinking_budget: Number(draft.thinking_budget) || 0,
        extra_body: extraBody
      },
      web_search_enabled: draft.web_search_enabled,
      autonomy_mode: draft.autonomy_mode,
      shell_enabled: draft.shell_enabled,
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
    // 底部「保存设置」：保存后关闭面板
    emit('saved', { close: true })
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  load()
  loadAutostart()
  loadProfiles()
})
</script>
