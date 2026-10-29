const { app, ipcMain, shell } = require('electron')
const fs = require('fs')
const path = require('path')
const { getAutostart, setAutostart } = require('./autostart.cjs')

function registerIpc({ getPetWindow, showMainWindow, getLogDir }) {
  let dragStart = null

  // 只允许 http/https 外链交给系统浏览器打开
  ipcMain.handle('nova:open-external', async (_event, url) => {
    if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) return false
    await shell.openExternal(url)
    return true
  })

  // 打开日志目录（设置面板「诊断」入口）
  ipcMain.handle('nova:open-logs', async () => {
    const dir = getLogDir ? getLogDir() : ''
    if (!dir) return false
    const error = await shell.openPath(dir)
    return !error
  })

  // 打开配置目录（%APPDATA%/NovaSecretary，含 .env 与数据库，打包态用户改密钥用）
  ipcMain.handle('nova:open-config-dir', async () => {
    const dir = path.join(app.getPath('appData'), 'NovaSecretary')
    try {
      fs.mkdirSync(dir, { recursive: true })
    } catch {
      /* 目录已存在或无法创建时交给 openPath 反馈 */
    }
    const error = await shell.openPath(dir)
    return !error
  })

  ipcMain.handle('nova:get-autostart', () => getAutostart())
  ipcMain.handle('nova:set-autostart', (_event, enabled) => setAutostart(Boolean(enabled)))

  // 主窗口状态 -> 悬浮球
  ipcMain.on('nova:pet-state', (_event, state) => {
    const pet = getPetWindow()
    pet?.webContents.send('pet:state', String(state || 'idle'))
  })

  // 透明区域穿透：macOS 依赖忽略鼠标事件；Windows 用窗口形状裁剪，无需切换
  ipcMain.on('nova:pet-hover', (_event, inside) => {
    if (process.platform !== 'darwin') return
    const pet = getPetWindow()
    if (!pet) return
    pet.setIgnoreMouseEvents(!inside, { forward: true })
  })

  ipcMain.handle('nova:pet-drag-start', (_event, x, y) => {
    const pet = getPetWindow()
    if (!pet) return
    const [winX, winY] = pet.getPosition()
    dragStart = { x: Number(x), y: Number(y), winX, winY }
  })

  ipcMain.on('nova:pet-drag-move', (_event, x, y) => {
    const pet = getPetWindow()
    if (!pet || !dragStart) return
    pet.setPosition(
      Math.round(dragStart.winX + Number(x) - dragStart.x),
      Math.round(dragStart.winY + Number(y) - dragStart.y)
    )
  })

  ipcMain.on('nova:pet-drag-end', () => {
    dragStart = null
  })

  ipcMain.on('nova:open-chat', () => showMainWindow())
}

module.exports = { registerIpc }
