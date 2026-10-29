/**
 * 跨平台构建后端安装包（PyInstaller），供 electron-builder 打进 resources/backend。
 *
 * 优先用 uv 执行；找不到 uv（未加入 PATH）时回退到 backend 虚拟环境里的 pyinstaller，
 * 保证 Windows PowerShell 与 macOS zsh 都能一条命令构建。
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, '..')
const backendDir = path.join(repoRoot, 'backend')
const args = [
  path.join(backendDir, 'nova-backend.spec'),
  '--noconfirm',
  '--distpath',
  path.join(backendDir, 'dist'),
  '--workpath',
  path.join(backendDir, 'build')
]

function run(command, commandArgs) {
  return spawnSync(command, commandArgs, { stdio: 'inherit', cwd: repoRoot })
}

const venvPyInstaller = path.join(
  backendDir,
  '.venv',
  process.platform === 'win32' ? 'Scripts/pyinstaller.exe' : 'bin/pyinstaller'
)

let result = run('uv', ['run', '--project', backendDir, 'pyinstaller', ...args])
if (result.error && fs.existsSync(venvPyInstaller)) {
  console.log('[build-backend] 未找到 uv，改用 backend/.venv 内的 pyinstaller')
  result = run(venvPyInstaller, args)
}
if (result.error) {
  console.error(
    `[build-backend] 无法启动构建：${result.error.message}；请先安装 uv 并执行 uv sync --project backend`
  )
  process.exit(1)
}
if (result.status !== 0) {
  process.exit(result.status || 1)
}
console.log('[build-backend] 完成：backend/dist/nova-backend')
