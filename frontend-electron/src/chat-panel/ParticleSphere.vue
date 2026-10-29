<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  state: { type: String, default: 'idle' }, // idle | thinking | confirm | done
  compact: { type: Boolean, default: false }, // 有回答卡片时球体上移并缩小，避免遮挡
  mode: { type: String, default: 'stage' } // stage：主界面；pet：悬浮球窗口
})
const emit = defineEmits(['activate'])

const canvas = ref(null)
let ctx = null
let frame = 0
let width = 0
let height = 0
let angle = 0
let localState = props.state
let glowUntil = 0
let resizeObserver = null

const PALETTE = {
  idle: { rgb: '76,194,255', speed: 0.004, breath: 8 },
  thinking: { rgb: '122,140,255', speed: 0.012, breath: 11 },
  confirm: { rgb: '255,176,92', speed: 0.008, breath: 6 },
  done: { rgb: '126,255,208', speed: 0.002, breath: 4 }
}

const bg = []
const ball = []

watch(
  () => props.state,
  (value) => {
    localState = value
    if (value === 'done') glowUntil = Date.now() + 1400
  }
)

function palette() {
  return PALETTE[localState] || PALETTE.idle
}

function ballRadius() {
  if (props.mode === 'pet') {
    return Math.min(width, height) * 0.34
  }
  const base = Math.max(92, Math.min(170, Math.min(width, height) * 0.165))
  return props.compact ? base * 0.7 : base
}

function center() {
  if (props.mode === 'pet') {
    return { x: width / 2, y: height / 2 }
  }
  return { x: width / 2, y: height * (props.compact ? 0.24 : 0.42) }
}

function seedBackground() {
  bg.length = 0
  const count = Math.min(56, Math.max(18, Math.floor((width * height) / 30000)))
  for (let i = 0; i < count; i += 1) {
    bg.push({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.22,
      vy: (Math.random() - 0.5) * 0.22
    })
  }
}

function seedBall() {
  ball.length = 0
  const count = 150
  const golden = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < count; i += 1) {
    const y = 1 - (i / (count - 1)) * 2
    const r = Math.sqrt(Math.max(0, 1 - y * y))
    const theta = golden * i
    ball.push({ x: Math.cos(theta) * r, y, z: Math.sin(theta) * r })
  }
}

function resize() {
  const element = canvas.value
  if (!element) return
  const nextWidth = element.clientWidth
  const nextHeight = element.clientHeight
  // 窗口隐藏时可能出现 0 尺寸，等 ResizeObserver 再次触发
  if (!nextWidth || !nextHeight) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  width = nextWidth
  height = nextHeight
  element.width = Math.round(width * dpr)
  element.height = Math.round(height * dpr)
  ctx = element.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  seedBackground()
}

function drawBackground() {
  for (const p of bg) {
    p.x += p.vx
    p.y += p.vy
    if (p.x < 0 || p.x > width) p.vx *= -1
    if (p.y < 0 || p.y > height) p.vy *= -1
  }
  for (let i = 0; i < bg.length; i += 1) {
    for (let j = i + 1; j < bg.length; j += 1) {
      const a = bg[i]
      const b = bg[j]
      const dx = a.x - b.x
      const dy = a.y - b.y
      const distance = dx * dx + dy * dy
      if (distance < 130 * 130) {
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.strokeStyle = `rgba(90,150,255,${0.1 * (1 - distance / (130 * 130))})`
        ctx.lineWidth = 1
        ctx.stroke()
      }
    }
  }
}

function drawBall() {
  const paletteNow = palette()
  const { x: cx, y: cy } = center()
  const baseRadius = ballRadius()
  const radius = baseRadius + Math.sin(Date.now() / 500) * paletteNow.breath
  angle += paletteNow.speed

  const cos = Math.cos(angle)
  const sin = Math.sin(angle)
  const points = ball.map((p) => {
    const x = p.x * cos - p.z * sin
    const z = p.x * sin + p.z * cos
    return { sx: cx + x * radius, sy: cy + p.y * radius, z }
  })

  const linkDistance = 55 * (radius / 150)
  for (let i = 0; i < points.length; i += 1) {
    for (let j = i + 1; j < points.length; j += 1) {
      const a = points[i]
      const b = points[j]
      const dx = a.sx - b.sx
      const dy = a.sy - b.sy
      const distance = dx * dx + dy * dy
      if (distance < linkDistance * linkDistance) {
        ctx.beginPath()
        ctx.moveTo(a.sx, a.sy)
        ctx.lineTo(b.sx, b.sy)
        ctx.strokeStyle = `rgba(${paletteNow.rgb},${0.16 * (1 - distance / (linkDistance * linkDistance))})`
        ctx.lineWidth = 0.6
        ctx.stroke()
      }
    }
  }

  for (const p of points) {
    const depth = (p.z + 1) / 2
    const isPet = props.mode === 'pet'
    const size = (isPet ? 1.7 : 1) + depth * (isPet ? 2.4 : 1.8)
    ctx.beginPath()
    ctx.arc(p.sx, p.sy, size, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(${paletteNow.rgb},${(isPet ? 0.5 : 0.32) + depth * 0.66})`
    ctx.fill()
  }

  // 悬浮球：加深色底盘，保证在浅色桌面上也有对比度
  if (props.mode === 'pet') {
    ctx.beginPath()
    ctx.arc(cx, cy, radius * 1.02, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(4, 10, 22, 0.42)'
    ctx.fill()
  }

  const gradient = ctx.createRadialGradient(cx, cy, 20, cx, cy, radius * 1.45)
  gradient.addColorStop(0, `rgba(${paletteNow.rgb},${props.mode === 'pet' ? 0.24 : 0.18})`)
  gradient.addColorStop(1, `rgba(${paletteNow.rgb},0)`)
  ctx.fillStyle = gradient
  ctx.beginPath()
  ctx.arc(cx, cy, radius * 1.45, 0, Math.PI * 2)
  ctx.fill()
}

function tick() {
  if (!ctx) return
  ctx.clearRect(0, 0, width, height)
  if (props.mode !== 'pet') drawBackground()
  drawBall()
  if (localState === 'done' && Date.now() > glowUntil) localState = 'idle'
  frame = requestAnimationFrame(tick)
}

function onCanvasClick(event) {
  const { x, y } = center()
  const distance = Math.hypot(event.clientX - x, event.clientY - y)
  if (distance <= ballRadius() * 1.35) emit('activate')
}

function onCanvasMove(event) {
  const element = canvas.value
  if (!element) return
  const { x, y } = center()
  const distance = Math.hypot(event.clientX - x, event.clientY - y)
  element.style.cursor = distance <= ballRadius() * 1.35 ? 'pointer' : 'default'
}

onMounted(() => {
  resize()
  seedBall()
  // 悬浮球窗口初始隐藏时尺寸可能为 0，用 ResizeObserver 兜底重新初始化
  resizeObserver = new ResizeObserver(() => resize())
  if (canvas.value) resizeObserver.observe(canvas.value)
  window.addEventListener('resize', resize)
  frame = requestAnimationFrame(tick)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  resizeObserver?.disconnect()
  window.removeEventListener('resize', resize)
})
</script>

<template>
  <canvas
    ref="canvas"
    class="stage-canvas"
    aria-hidden="true"
    @click="onCanvasClick"
    @mousemove="onCanvasMove"
  ></canvas>
</template>
