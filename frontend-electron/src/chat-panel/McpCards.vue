<script setup>
import { API_BASE } from '../ws'

defineProps({
  cards: { type: Array, default: () => [] }
})

function mediaUrl(url) {
  const value = String(url || '')
  if (!value) return ''
  return value.startsWith('http') ? value : `${API_BASE}${value}`
}
</script>

<template>
  <section class="mcp-cards">
    <article v-for="card in cards" :key="card.kind" class="mcp-card">
      <!-- 今日邮件 -->
      <template v-if="card.kind === 'emails'">
        <header class="mcp-head">
          <span class="mcp-tag">邮件</span>
          <span>{{ card.data.date }} · 共 {{ card.data.count }} 封 · 未读 {{ card.data.unread }}</span>
        </header>
        <ul class="mcp-list">
          <li v-for="mail in card.data.emails || []" :key="mail.id" class="mail-row">
            <span class="unread-dot" :class="{ on: mail.unread }"></span>
            <div class="mail-main">
              <div class="mail-title">{{ mail.subject }}</div>
              <div class="mail-meta">{{ mail.from }} · {{ mail.time }}</div>
              <div class="mail-snippet">{{ mail.summary }}</div>
            </div>
          </li>
        </ul>
      </template>

      <!-- 今日日程 -->
      <template v-else-if="card.kind === 'calendar'">
        <header class="mcp-head">
          <span class="mcp-tag">日程</span>
          <span>{{ card.data.date }} · 共 {{ card.data.count }} 项</span>
        </header>
        <ul class="mcp-list">
          <li v-for="(event, index) in card.data.events || []" :key="index" class="event-row">
            <div class="event-time">{{ String(event.start || '').slice(11) }}</div>
            <div class="event-main">
              <div class="mail-title">{{ event.title }}</div>
              <div class="mail-meta">
                {{ event.location || '—' }}
                <template v-if="event.attendees && event.attendees.length">
                  · {{ event.attendees.join('、') }}
                </template>
              </div>
            </div>
          </li>
        </ul>
      </template>

      <!-- 单封邮件全文 -->
      <template v-else-if="card.kind === 'email_detail'">
        <header class="mcp-head">
          <span class="mcp-tag">邮件正文</span>
          <span>{{ card.data.time }}</span>
        </header>
        <div class="mail-title">{{ card.data.subject }}</div>
        <div class="mail-meta">{{ card.data.from }}</div>
        <pre class="mail-body">{{ card.data.body }}</pre>
      </template>

      <!-- 发送成功 -->
      <template v-else-if="card.kind === 'email_sent'">
        <header class="mcp-head">
          <span class="mcp-tag ok">已发送</span>
          <span>本地 Mock · 未真实投递</span>
        </header>
        <div class="mail-title">收件人：{{ card.data.to }}</div>
        <div class="mail-meta">主题：{{ card.data.subject }}</div>
        <div class="mail-meta">message_id：{{ card.data.message_id }}</div>
      </template>

      <!-- 日程创建成功 -->
      <template v-else-if="card.kind === 'calendar_created'">
        <header class="mcp-head">
          <span class="mcp-tag ok">已创建</span>
          <span>本地 Mock · 未写入真实日历</span>
        </header>
        <div class="mail-title">{{ card.data.title }}</div>
        <div class="mail-meta">{{ card.data.start_time }} → {{ card.data.end_time }}</div>
        <div class="mail-meta" v-if="card.data.location">地点：{{ card.data.location }}</div>
      </template>

      <!-- 生成图片 -->
      <template v-else-if="card.kind === 'image_result'">
        <header class="mcp-head">
          <span class="mcp-tag">生成图片</span>
          <span>{{ card.data.model }} · {{ card.data.size }}</span>
        </header>
        <div class="gen-grid">
          <a
            v-for="img in card.data.images || []"
            :key="img.name"
            :href="mediaUrl(img.url)"
            target="_blank"
            rel="noreferrer"
          >
            <img
              class="gen-img"
              :src="mediaUrl(img.url)"
              :alt="card.data.prompt || '生成图片'"
            />
          </a>
        </div>
        <div class="mcp-foot">{{ card.data.prompt }}</div>
      </template>

      <!-- 项目计划看板 -->
      <template v-else-if="card.kind === 'project_plan'">
        <header class="mcp-head">
          <span class="mcp-tag">{{ card.data.status === 'done' ? '已完成' : '项目' }}</span>
          <span>{{ card.data.done }}/{{ card.data.total }} 步完成</span>
        </header>
        <div class="mail-title">{{ card.data.title }}</div>
        <div class="mail-meta" v-if="card.data.goal">{{ card.data.goal }}</div>
        <ul class="mcp-list">
          <li v-for="step in card.data.steps || []" :key="step.index" class="task-row">
            <span class="task-state" :class="step.status">
              {{ { done: '✓', failed: '✕', skipped: '—', pending: '·' }[step.status] || '·' }}
            </span>
            <div class="event-main">
              <div class="mail-title" :class="{ dim: step.status !== 'pending' }">
                {{ step.name }}
              </div>
              <div class="mail-meta" v-if="step.note">{{ step.note }}</div>
            </div>
          </li>
        </ul>
        <div class="mcp-foot" v-if="card.data.root_dir">目录：{{ card.data.root_dir }}</div>
      </template>
    </article>
  </section>
</template>
