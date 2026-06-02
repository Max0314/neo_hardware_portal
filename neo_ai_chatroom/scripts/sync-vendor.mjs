/**
 * 将 xlsx、Font Awesome、FileSaver、jsPDF 复制到 public/vendor，供生产 CSP 仅允许 'self' 时仍可加载。
 * Docker 构建前由 vite 插件调用；也可手动：node scripts/sync-vendor.mjs
 */
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const vendorDir = path.join(root, 'public', 'vendor')

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true })
}

function copyFile(src, dest) {
  if (!fs.existsSync(src)) {
    console.warn('[sync-vendor] 跳过（源不存在）:', src)
    return false
  }
  ensureDir(path.dirname(dest))
  fs.copyFileSync(src, dest)
  return true
}

function copyDir(src, dest) {
  if (!fs.existsSync(src)) {
    console.warn('[sync-vendor] 跳过目录:', src)
    return false
  }
  ensureDir(dest)
  for (const name of fs.readdirSync(src)) {
    const s = path.join(src, name)
    const d = path.join(dest, name)
    if (fs.statSync(s).isDirectory()) copyDir(s, d)
    else copyFile(s, d)
  }
  return true
}

let ok = true

ok =
  copyFile(
    path.join(root, 'node_modules/xlsx/dist/xlsx.full.min.js'),
    path.join(vendorDir, 'xlsx.full.min.js'),
  ) && ok

ok =
  copyFile(
    path.join(root, 'node_modules/file-saver/dist/FileSaver.min.js'),
    path.join(vendorDir, 'file-saver/FileSaver.min.js'),
  ) && ok

ok =
  copyFile(
    path.join(root, 'node_modules/jspdf/dist/jspdf.umd.min.js'),
    path.join(vendorDir, 'jspdf/jspdf.umd.min.js'),
  ) && ok

const faRoot = path.join(root, 'node_modules/@fortawesome/fontawesome-free')
if (fs.existsSync(faRoot)) {
  copyFile(path.join(faRoot, 'css/all.min.css'), path.join(vendorDir, 'fontawesome/css/all.min.css'))
  copyDir(path.join(faRoot, 'webfonts'), path.join(vendorDir, 'fontawesome/webfonts'))
} else {
  console.warn('[sync-vendor] 未安装 @fortawesome/fontawesome-free，请执行 npm install')
  ok = false
}

if (ok) console.log('[sync-vendor] 已同步到 public/vendor')
process.exit(ok ? 0 : 1)
