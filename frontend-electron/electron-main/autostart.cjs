const { app } = require('electron')

// 开机自启：Windows 走注册表 Run（Electron 内置封装），macOS 走登录项。
// 开发模式（electron .）注册的路径是 electron.exe，没有实际意义，直接禁用。

function supported() {
  return app.isPackaged
}

function getAutostart() {
  if (!supported()) return { supported: false, enabled: false }
  const settings = app.getLoginItemSettings()
  return { supported: true, enabled: Boolean(settings.openAtLogin) }
}

function setAutostart(enabled) {
  if (!supported()) {
    throw new Error('开发模式不支持开机自启，请在安装后的客户端中设置')
  }
  app.setLoginItemSettings({
    openAtLogin: Boolean(enabled),
    openAsHidden: true
  })
  return getAutostart()
}

module.exports = { getAutostart, setAutostart }
