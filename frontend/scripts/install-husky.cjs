const { existsSync } = require('node:fs')
const { join } = require('node:path')
const { spawnSync } = require('node:child_process')

const root = join(__dirname, '..', '..')
const gitDir = join(root, '.git')

if (!existsSync(gitDir)) {
  process.exit(0)
}

const huskyBin = join(
  root,
  'frontend',
  'node_modules',
  '.bin',
  process.platform === 'win32' ? 'husky.cmd' : 'husky',
)

const result = spawnSync(huskyBin, ['.husky'], {
  cwd: root,
  stdio: 'inherit',
  shell: process.platform === 'win32',
})

process.exit(result.status ?? 1)
