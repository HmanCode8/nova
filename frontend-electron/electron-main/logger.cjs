const { app } = require('electron')
const fs = require('fs')
const path = require('path')

// 主进程日志：userData/logs/main.log，超过 2MB 轮转一份 main.log.1
const MAX_BYTES = 2 * 1024 * 1024
let stream = null
let original = null

function logDir() {
  return path.join(app.getPath('userData'), 'logs')
}

function logFile() {
  return path.join(logDir(), 'main.log')
}

function format(value) {
  if (value instanceof Error) return value.stack || value.message
  if (typeof value === 'object' && value !== null) {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

function rotateIfNeeded() {
  try {
    const stat = fs.statSync(logFile())
    if (stat.size > MAX_BYTES) fs.renameSync(logFile(), `${logFile()}.1`)
  } catch {
    // 首次运行没有日志文件
  }
}

function write(level, args) {
  if (!stream) return
  const line = `${new Date().toISOString()} ${level} ${args.map(format).join(' ')}\n`
  try {
    stream.write(line)
  } catch {
    // 磁盘异常时不阻塞主进程
  }
}

/** 初始化文件日志，并接管 console 输出 */
function initLogger() {
  fs.mkdirSync(logDir(), { recursive: true })
  rotateIfNeeded()
  stream = fs.createWriteStream(logFile(), { flags: 'a' })
  original = { log: console.log, warn: console.warn, error: console.error }
  console.log = (...args) => {
    write('INFO', args)
    original.log(...args)
  }
  console.warn = (...args) => {
    write('WARN', args)
    original.warn(...args)
  }
  console.error = (...args) => {
    write('ERROR', args)
    original.error(...args)
  }
  process.on('uncaughtException', (error) => {
    write('FATAL', [error])
    original.error(error)
  })
  process.on('unhandledRejection', (reason) => {
    write('FATAL', [reason])
    original.error(reason)
  })
  console.log(`[nova] 日志目录：${logDir()}`)
  return logDir()
}

module.exports = { initLogger, logDir }
