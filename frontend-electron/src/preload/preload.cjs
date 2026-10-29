const { contextBridge, ipcRenderer } = require('electron')

// 预加载脚本：只暴露最小能力，保持 contextIsolation + 无 nodeIntegration
contextBridge.exposeInMainWorld('nova', {
  isElectron: true,
  platform: process.platform,
  openExternal: (url) => ipcRenderer.invoke('nova:open-external', url),
  // 主窗口 -> 悬浮球状态同步
  setPetState: (state) => ipcRenderer.send('nova:pet-state', state),
  // 悬浮球窗口
  onPetState: (callback) => ipcRenderer.on('pet:state', (_event, state) => callback(state)),
  petHover: (inside) => ipcRenderer.send('nova:pet-hover', Boolean(inside)),
  petDragStart: (x, y) => ipcRenderer.invoke('nova:pet-drag-start', x, y),
  petDragMove: (x, y) => ipcRenderer.send('nova:pet-drag-move', x, y),
  petDragEnd: () => ipcRenderer.send('nova:pet-drag-end'),
  openChat: () => ipcRenderer.send('nova:open-chat'),
  // 诊断与系统设置
  openLogs: () => ipcRenderer.invoke('nova:open-logs'),
  openConfigDir: () => ipcRenderer.invoke('nova:open-config-dir'),
  getAutostart: () => ipcRenderer.invoke('nova:get-autostart'),
  setAutostart: (enabled) => ipcRenderer.invoke('nova:set-autostart', Boolean(enabled))
})
