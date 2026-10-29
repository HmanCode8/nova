/**
 * 后端进程托管（仅打包态生效）。
 *
 * - 启动前先探测 8000 端口：已有后端（开发态手动启动 / 上次残留）直接复用，不重复拉起。
 * - 打包态从 resources/backend 启动 PyInstaller 产出的 nova-backend.exe。
 * - 退出时先调 /api/admin/shutdown 优雅停止，超时再强杀进程树，避免残留 python 进程。
 * - .env 不打包：首次启动把 .env.example 复制到 %APPDATA%/NovaSecretary/.env 供用户填写密钥。
 */

const { spawn, spawnSync } = require('child_process')
const fs = require('fs')
const http = require('http')
const path = require('path')

const BACKEND_URL = process.env.NOVA_BACKEND_URL || 'http://127.0.0.1:8000'
const START_TIMEOUT = 120000
const STOP_TIMEOUT = 8000

let childProcess = null

function httpRequest(method, pathname, timeout) {
  return new Promise((resolve, reject) => {
    const request = http.request(
      `${BACKEND_URL}${pathname}`,
      { method, timeout },
      (response) => {
        let body = ''
        response.setEncoding('utf8')
        response.on('data', (chunk) => (body += chunk))
        response.on('end', () => resolve({ status: response.statusCode, body }))
      }
    )
    request.on('timeout', () => request.destroy(new Error('timeout')))
    request.on('error', reject)
    request.end()
  })
}

async function isHealthy() {
  try {
    const response = await httpRequest('GET', '/api/health', 1200)
    return response.status === 200 && response.body.includes('"status":"ok"')
  } catch {
    return false
  }
}

async function waitHealthy(timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await isHealthy()) return true
    if (childProcess && childProcess.exitCode !== null) return false
    await new Promise((resolve) => setTimeout(resolve, 800))
  }
  return false
}

function backendExe() {
  return path.join(process.resourcesPath, 'backend', 'nova-backend.exe')
}

/** 首次运行准备用户 .env：无文件时从安装包的 .env.example 复制。 */
function ensureEnvFile(appDataDir, logger) {
  const target = path.join(appDataDir, 'NovaSecretary', '.env')
  if (fs.existsSync(target)) return target
  fs.mkdirSync(path.dirname(target), { recursive: true })
  const template = path.join(process.resourcesPath, 'backend', '.env.example')
  try {
    if (fs.existsSync(template)) {
      fs.copyFileSync(template, target)
      logger(`[nova] 已生成配置模板：${target}`)
    } else {
      fs.writeFileSync(target, '', 'utf8')
      logger(`[nova] 已创建空白配置：${target}`)
    }
  } catch (error) {
    logger(`[nova] 创建配置模板失败：${error.message}`)
  }
  return target
}

async function startBackend({ isPackaged, appDataDir, logDir, logger = console.log }) {
  if (await isHealthy()) {
    logger('[nova] 检测到已运行的后端，直接复用')
    return 'reused'
  }
  if (!isPackaged) {
    logger('[nova] 开发态不托管后端，请手动启动 uv run python -m backend.server')
    return 'external'
  }

  const exePath = backendExe()
  if (!fs.existsSync(exePath)) {
    logger(`[nova] 未找到托管后端：${exePath}`)
    return 'missing'
  }

  const envFile = ensureEnvFile(appDataDir, logger)
  const logStream = fs.createWriteStream(path.join(logDir, 'backend-process.log'), {
    flags: 'a'
  })

  childProcess = spawn(exePath, [], {
    cwd: path.dirname(exePath),
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      NOVA_ENV_FILE: envFile,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUNBUFFERED: '1'
    }
  })
  childProcess.stdout.on('data', (chunk) => logStream.write(chunk))
  childProcess.stderr.on('data', (chunk) => logStream.write(chunk))
  childProcess.on('exit', (code, signal) => {
    logger(`[nova] 后端进程退出 code=${code} signal=${signal}`)
    logStream.end()
    childProcess = null
  })
  childProcess.on('error', (error) => {
    logger(`[nova] 后端启动失败：${error.message}`)
    logStream.end()
  })

  logger(`[nova] 正在启动托管后端：${exePath}（env=${envFile}）`)
  const healthy = await waitHealthy(START_TIMEOUT)
  logger(healthy ? '[nova] 后端健康检查通过' : '[nova] 后端启动超时/失败，请查看 backend-process.log')
  return healthy ? 'started' : 'timeout'
}

function waitExit(timeoutMs) {
  if (!childProcess) return Promise.resolve(true)
  const target = childProcess
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs)
    target.once('exit', () => {
      clearTimeout(timer)
      resolve(true)
    })
  })
}

function killTree(pid) {
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true })
  } else {
    try {
      process.kill(-pid, 'SIGKILL')
    } catch {
      try {
        process.kill(pid, 'SIGKILL')
      } catch {
        /* 进程可能已退出 */
      }
    }
  }
}

async function stopBackend({ logger = console.log } = {}) {
  if (!childProcess) return
  const pid = childProcess.pid
  logger('[nova] 正在优雅停止后端')
  try {
    await httpRequest('POST', '/api/admin/shutdown', 3000)
  } catch {
    /* 后端可能已退出或非托管模式 */
  }
  if (await waitExit(STOP_TIMEOUT)) {
    logger('[nova] 后端已优雅退出')
    return
  }
  logger('[nova] 后端未在时限内退出，强制结束进程树')
  killTree(pid)
  await waitExit(2000)
}

function ownsBackend() {
  return childProcess !== null
}

module.exports = { startBackend, stopBackend, ownsBackend }
