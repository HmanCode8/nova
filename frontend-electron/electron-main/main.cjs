const { app, BrowserWindow, Menu, globalShortcut, screen } = require('electron')
const path = require('path')

// 独立 userData：避免和 Python 后端数据目录混用；NOVA_USER_DATA 仅开发/自测使用
app.setName('NovaSecretary')
app.setPath(
  'userData',
  process.env.NOVA_USER_DATA || path.join(app.getPath('appData'), 'NovaSecretary', 'electron')
)

const { createTray } = require('./tray.cjs')
const { registerIpc } = require('./ipc.cjs')
const { initLogger, logDir } = require('./logger.cjs')
const { startBackend, stopBackend, ownsBackend } = require('./backend.cjs')

const DEV_URL = process.env.VITE_DEV_SERVER_URL || 'http://127.0.0.1:5173'
// 开发态：通过 `electron .` 启动（process.defaultApp 为 true）；打包后为 false
const IS_DEV = Boolean(process.defaultApp) || !app.isPackaged
// 资源目录：开发时在上两级 /assets，打包后由 extraResources 复制到 resources/assets
const ASSETS_DIR = app.isPackaged
  ? path.join(process.resourcesPath, 'assets')
  : path.join(__dirname, '..', '..', 'assets')
const PET_SIZE = 200

let mainWindow = null
let petWindow = null
let isQuitting = false
let backendStopping = false

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => showWindow())

  app.whenReady().then(() => {
    initLogger()
    console.log(
      '[nova] 启动',
      `version=${app.getVersion()}`,
      `platform=${process.platform}`,
      `isPackaged=${app.isPackaged}`
    )
    registerIpc({
      getPetWindow: () => petWindow,
      showMainWindow: () => showWindow(),
      getLogDir: () => logDir()
    })
    createWindow()
    createPetWindow()
    const accelerator = registerGlobalHotkey()
    createTray({ showWindow, hideWindow, quitApp, accelerator, assetsDir: ASSETS_DIR })
    // 打包态托管后端（开发态复用外部启动的后端，不重复拉起）
    startBackend({
      isPackaged: app.isPackaged,
      appDataDir: app.getPath('appData'),
      logDir: logDir(),
      logger: console.log
    }).then((status) => console.log('[nova] backend status:', status))
  })
}

app.on('will-quit', () => {
  console.log('[nova] 正在退出，注销全局快捷键')
  globalShortcut.unregisterAll()
})

function loadPage(window, page) {
  if (!IS_DEV) {
    return window.loadFile(path.join(__dirname, '..', 'dist', page))
  }
  return window.loadURL(`${DEV_URL}/${page}`)
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1120,
    height: 780,
    minWidth: 900,
    minHeight: 620,
    show: false,
    backgroundColor: '#050810',
    autoHideMenuBar: true,
    icon: path.join(ASSETS_DIR, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, '..', 'src', 'preload', 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  Menu.setApplicationMenu(null)
  loadPage(mainWindow, 'index.html')

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
    console.log('[nova] main window ready')
  })

  // 关闭窗口只隐藏，保持后台常驻（托盘可再次唤起）
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault()
      mainWindow.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function createPetWindow() {
  const { workArea } = screen.getPrimaryDisplay()
  petWindow = new BrowserWindow({
    width: PET_SIZE,
    height: PET_SIZE,
    x: workArea.x + workArea.width - PET_SIZE - 32,
    y: workArea.y + workArea.height - PET_SIZE - 56,
    show: false,
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    movable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    fullscreenable: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, '..', 'src', 'preload', 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  petWindow.setAlwaysOnTop(true, 'floating')

  // Windows：用窗口形状裁剪出球体区域，形状外完全透明且鼠标穿透；
  // shape 不依赖 mousemove 转发，点击/拖拽更稳定。macOS 走忽略鼠标事件方案。
  if (process.platform === 'win32') {
    applyPetShape(petWindow, PET_SIZE)
  } else {
    petWindow.setIgnoreMouseEvents(true, { forward: true })
  }

  loadPage(petWindow, 'pet.html')

  petWindow.webContents.on('did-fail-load', (_event, code, description, url) => {
    console.log('[pet fail-load]', code, description, url)
  })
  petWindow.webContents.on('render-process-gone', (_event, details) => {
    console.log('[pet renderer gone]', JSON.stringify(details))
  })

  petWindow.once('ready-to-show', () => {
    petWindow.showInactive()
    console.log('[nova] pet window ready', JSON.stringify(petWindow.getBounds()))
  })

  petWindow.on('closed', () => {
    petWindow = null
  })
}

/** Windows 专用：把窗口裁剪成近似圆形，形状外不绘制也不接收鼠标事件 */
function applyPetShape(window, size) {
  const strips = 20
  const radius = size * 0.47
  const rects = []
  for (let index = 0; index < strips; index += 1) {
    const y0 = (size / strips) * index
    const y1 = y0 + size / strips
    const centerY = (y0 + y1) / 2 - size / 2
    const halfWidth = Math.sqrt(Math.max(0, radius * radius - centerY * centerY))
    rects.push({
      x: Math.round(size / 2 - halfWidth),
      y: Math.round(y0),
      width: Math.max(0, Math.round(halfWidth * 2)),
      height: Math.ceil(size / strips)
    })
  }
  try {
    window.setShape(rects)
    console.log('[nova] pet shape applied', rects.length)
  } catch (error) {
    console.log('[nova] pet shape failed', error.message)
  }
}

function showWindow() {
  if (!mainWindow) {
    createWindow()
    return
  }
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

function hideWindow() {
  mainWindow?.hide()
}

function toggleMainWindow() {
  if (!mainWindow) {
    createWindow()
    return
  }
  if (mainWindow.isVisible() && mainWindow.isFocused()) {
    mainWindow.hide()
  } else {
    showWindow()
  }
}

function registerGlobalHotkey() {
  // Windows 上 Alt+Space 常被系统窗口菜单占用，注册失败时自动降级到备用组合
  const candidates = ['Alt+Space', 'Ctrl+Alt+Space', 'Alt+Shift+Space']
  for (const accelerator of candidates) {
    if (globalShortcut.register(accelerator, toggleMainWindow)) {
      console.log('[nova] hotkey registered:', accelerator)
      return accelerator
    }
  }
  console.log('[nova] hotkey registered: none')
  return ''
}

function quitApp() {
  isQuitting = true
  app.quit()
}

app.on('before-quit', async (event) => {
  isQuitting = true
  if (backendStopping || !ownsBackend()) return
  // 先拦截退出，等后端优雅关闭后再真正退出，避免残留后端进程
  backendStopping = true
  event.preventDefault()
  await stopBackend({ logger: console.log })
  app.quit()
})

// 托盘/悬浮球常驻：窗口全部关闭也不退出应用
app.on('window-all-closed', () => {})
