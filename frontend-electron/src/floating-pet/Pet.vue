<template>
  <div
    class="pet-root"
    @mousedown="onMouseDown"
    @mousemove="onMouseMove"
    @mouseleave="onMouseLeave"
  >
    <ParticleSphere :state="state" mode="pet" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import ParticleSphere from '../chat-panel/ParticleSphere.vue'

const state = ref('idle')
let dragging = false
let moved = false
let startX = 0
let startY = 0

function insideSphere(event) {
  const radius = Math.min(window.innerWidth, window.innerHeight) * 0.36
  const cx = window.innerWidth / 2
  const cy = window.innerHeight / 2
  return Math.hypot(event.clientX - cx, event.clientY - cy) <= radius
}

function onMouseDown(event) {
  if (event.button !== 0 || !insideSphere(event)) return
  dragging = true
  moved = false
  startX = event.screenX
  startY = event.screenY
  window.nova?.petDragStart?.(event.screenX, event.screenY)
}

function onMouseMove(event) {
  if (dragging) {
    if (Math.abs(event.screenX - startX) + Math.abs(event.screenY - startY) > 6) moved = true
    window.nova?.petDragMove?.(event.screenX, event.screenY)
    return
  }
  // macOS 透明区域穿透：只有光标落在球体上时才让窗口接收鼠标
  window.nova?.petHover?.(insideSphere(event))
}

function onMouseLeave() {
  if (!dragging) window.nova?.petHover?.(false)
}

function onGlobalMouseUp() {
  if (!dragging) return
  dragging = false
  window.nova?.petDragEnd?.()
  if (!moved) window.nova?.openChat?.()
}

onMounted(() => {
  window.nova?.onPetState?.((value) => {
    if (value) state.value = value
  })
  window.addEventListener('mouseup', onGlobalMouseUp)
})

onBeforeUnmount(() => {
  window.removeEventListener('mouseup', onGlobalMouseUp)
})
</script>
