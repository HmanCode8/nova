<template>
  <div class="settings-overlay" @click.self="$emit('close')">
    <section class="settings-modal memory-modal">
      <header class="settings-head">
        <h2>记忆管理</h2>
        <button class="close" title="关闭" @click="$emit('close')">×</button>
      </header>

      <div class="memory-tabs">
        <button :class="{ active: scope === 'global' }" @click="switchScope('global')">
          全局偏好 · {{ globalItems.length }}
        </button>
        <button :class="{ active: scope === 'session' }" @click="switchScope('session')">
          本会话 · {{ sessionItems.length }}
        </button>
      </div>

      <div class="settings-body">
        <p class="group-desc">
          {{
            scope === 'global'
              ? '跨全部会话生效，例如回答风格、技术栈偏好。'
              : '仅当前会话生效，例如本项目的约定。'
          }}
          自动记忆开关关闭后不再生成新记忆，已有记忆仍会注入对话。
        </p>

        <div class="dir-add">
          <input
            v-model="draft"
            :placeholder="
              scope === 'global' ? '例如：回答尽量简洁' : '例如：本项目接口统一用 snake_case'
            "
            :disabled="scope === 'session' && !sessionId"
            @keydown.enter.prevent="add"
          />
          <button
            class="mini"
            :disabled="!draft.trim() || saving || (scope === 'session' && !sessionId)"
            @click="add"
          >
            添加
          </button>
        </div>

        <p v-if="scope === 'session' && !sessionId" class="dir-empty">请先在聊天页创建会话。</p>

        <div v-if="loading" class="settings-loading">加载中…</div>
        <div v-else class="memory-list">
          <div v-for="item in items" :key="item.id" class="memory-item">
            <template v-if="editingId === item.id">
              <textarea v-model="editingText" rows="2"></textarea>
              <div class="memory-actions">
                <button class="mini" :disabled="saving" @click="saveEdit(item)">保存</button>
                <button class="mini ghost-mini" @click="cancelEdit">取消</button>
              </div>
            </template>
            <template v-else>
              <span class="memory-text">{{ item.memory_text }}</span>
              <div class="memory-actions">
                <button class="mini ghost-mini" @click="startEdit(item)">编辑</button>
                <button class="mini ghost-mini danger-mini" @click="remove(item)">删除</button>
              </div>
            </template>
          </div>
          <p v-if="!items.length" class="dir-empty">暂无记忆</p>
        </div>

        <p v-if="error" class="settings-error">{{ error }}</p>
      </div>

      <footer class="settings-actions">
        <button class="ghost danger" :disabled="!items.length || saving" @click="clearAll">
          清空当前列表
        </button>
        <button class="primary" @click="$emit('close')">关闭</button>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../ws'

const props = defineProps({
  sessionId: { type: String, default: '' }
})
defineEmits(['close'])

const scope = ref('global')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const globalItems = ref([])
const sessionItems = ref([])
const draft = ref('')
const editingId = ref('')
const editingText = ref('')

const items = computed(() => (scope.value === 'global' ? globalItems.value : sessionItems.value))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.listMemory(props.sessionId)
    globalItems.value = data.global || []
    sessionItems.value = data.session || []
  } catch (err) {
    error.value = `加载记忆失败：${err.message}`
  } finally {
    loading.value = false
  }
}

function switchScope(next) {
  scope.value = next
  editingId.value = ''
  error.value = ''
}

async function add() {
  const text = draft.value.trim()
  if (!text) return
  if (scope.value === 'session' && !props.sessionId) return
  saving.value = true
  error.value = ''
  try {
    await api.addMemory(scope.value, text, props.sessionId)
    draft.value = ''
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

function startEdit(item) {
  editingId.value = item.id
  editingText.value = item.memory_text
}

function cancelEdit() {
  editingId.value = ''
  editingText.value = ''
}

async function saveEdit(item) {
  const text = editingText.value.trim()
  if (!text) return
  saving.value = true
  error.value = ''
  try {
    await api.updateMemory(scope.value, item.id, text)
    cancelEdit()
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

async function remove(item) {
  if (!window.confirm('删除这条记忆？')) return
  saving.value = true
  error.value = ''
  try {
    await api.deleteMemory(scope.value, item.id)
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

async function clearAll() {
  if (!window.confirm('清空当前分类的全部记忆？')) return
  if (scope.value === 'session' && !props.sessionId) return
  saving.value = true
  error.value = ''
  try {
    await api.clearMemory(scope.value, props.sessionId)
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
