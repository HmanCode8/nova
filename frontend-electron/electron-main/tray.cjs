const { Tray, Menu, nativeImage } = require('electron')
const path = require('path')

let tray = null

function createTray({ showWindow, hideWindow, quitApp, accelerator, assetsDir }) {
  const iconPath = path.join(assetsDir, 'tray.png')
  const image = nativeImage.createFromPath(iconPath)
  if (image.isEmpty()) console.warn('[nova] 托盘图标加载失败：', iconPath)
  tray = new Tray(image.isEmpty() ? nativeImage.createEmpty() : image.resize({ width: 16, height: 16 }))
  tray.setToolTip(accelerator ? `NovaSecretary · ${accelerator} 唤起` : 'NovaSecretary · 本地 AI 秘书')

  const menu = Menu.buildFromTemplate([
    { label: '显示主界面', click: () => showWindow() },
    { label: '隐藏主界面', click: () => hideWindow() },
    { type: 'separator' },
    {
      label: accelerator ? `全局快捷键：${accelerator}` : '全局快捷键：未注册',
      enabled: false
    },
    { type: 'separator' },
    { label: '退出 NovaSecretary', click: () => quitApp() }
  ])
  tray.setContextMenu(menu)
  tray.on('double-click', () => showWindow())
  console.log('[nova] tray created')
}

module.exports = { createTray }
