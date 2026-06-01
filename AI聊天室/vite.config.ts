import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'
import { execSync } from 'child_process'
import { fileURLToPath } from 'url'
import { stripHtmlComments } from './scripts/strip-html-comments.mjs'

/** 与生产环境 gateway 子路径一致（BrowserRouter basename） */
const NEO_PATH_PREFIX = '/neo'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function syncVendorAssets() {
  try {
    execSync('node scripts/sync-vendor.mjs', { cwd: __dirname, stdio: 'inherit' })
  } catch {
    console.warn('[vite] sync-vendor 未完全成功，请在本目录执行 npm install && npm run sync-vendor')
  }
}

function copyStaticToolDir(srcDir: string, destDir: string) {
  if (!fs.existsSync(srcDir)) return
  fs.mkdirSync(destDir, { recursive: true })
  for (const name of fs.readdirSync(srcDir)) {
    const src = path.join(srcDir, name)
    const dest = path.join(destDir, name)
    if (fs.statSync(src).isDirectory()) {
      copyStaticToolDir(src, dest)
      continue
    }
    let content = fs.readFileSync(src, 'utf-8')
    if (name.toLowerCase().endsWith('.html') || name.toLowerCase().endsWith('.htm')) {
      content = stripHtmlComments(content)
    }
    fs.writeFileSync(dest, content, 'utf-8')
  }
}

/** bom_tool / systm_tool 响应头：允许被 /neo 同源 iframe 嵌入，仅依赖同源脚本与样式 */
const BOM_TOOL_CSP =
  "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'; object-src 'none'; " +
  "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; " +
  "font-src 'self' data:; img-src 'self' data: blob:; connect-src 'self';"

function applyBomToolSecurityHeaders(res: import('http').ServerResponse) {
  res.setHeader('Content-Security-Policy', BOM_TOOL_CSP)
  res.setHeader('X-Frame-Options', 'SAMEORIGIN')
  res.setHeader('X-Content-Type-Options', 'nosniff')
}

export default defineConfig({
  base: `${NEO_PATH_PREFIX}/`,
  build: {
    sourcemap: false,
    minify: 'esbuild',
  },
  plugins: [
    react(),
    {
      name: 'sync-vendor-assets',
      buildStart() {
        syncVendorAssets()
      },
    },
    {
      name: 'serve-systm-tool',
      configureServer(server) {
        server.middlewares.use(`${NEO_PATH_PREFIX}/systm_tool`, (req, res, next) => {
          const url = req.url?.split('?')[0] || '/'
          const filePath = path.join(__dirname, 'systm_tool', url)
          if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
            return next()
          }
          const content = fs.readFileSync(filePath, 'utf-8')
          const ext = path.extname(filePath)
          const type = ext === '.html' ? 'text/html' : ext === '.css' ? 'text/css' : 'application/octet-stream'
          if (ext === '.html' || ext === '.htm') applyBomToolSecurityHeaders(res)
          res.setHeader('Content-Type', type + '; charset=utf-8')
          res.end(content)
        })
      },
      closeBundle() {
        const src = path.join(__dirname, 'systm_tool')
        const dest = path.join(__dirname, 'dist', 'systm_tool')
        if (fs.existsSync(src)) {
          copyStaticToolDir(src, dest)
        }
      },
    },
    {
      name: 'serve-bom-tool',
      configureServer(server) {
        const bomRoot = path.resolve(path.join(__dirname, 'BOM_TOOL'))
        server.middlewares.use(`${NEO_PATH_PREFIX}/bom_tool`, (req, res, next) => {
          const raw = req.url?.split('?')[0] || '/'
          const rel = raw.startsWith('/') ? raw.slice(1) : raw
          let decoded: string
          try {
            decoded = decodeURIComponent(rel)
          } catch {
            return next()
          }
          if (!decoded || decoded.includes('..')) return next()
          const filePath = path.join(bomRoot, decoded)
          const resolved = path.resolve(filePath)
          if (!resolved.startsWith(bomRoot)) return next()
          if (!fs.existsSync(resolved) || !fs.statSync(resolved).isFile()) {
            return next()
          }
          const content = fs.readFileSync(resolved, 'utf-8')
          const ext = path.extname(resolved).toLowerCase()
          const type =
            ext === '.html' || ext === '.htm'
              ? 'text/html'
              : ext === '.css'
                ? 'text/css'
                : ext === '.js'
                  ? 'application/javascript'
                  : 'application/octet-stream'
          if (ext === '.html' || ext === '.htm') applyBomToolSecurityHeaders(res)
          res.setHeader('Content-Type', `${type}; charset=utf-8`)
          res.end(content)
        })
      },
      closeBundle() {
        const src = path.join(__dirname, 'BOM_TOOL')
        const dest = path.join(__dirname, 'dist', 'bom_tool')
        if (fs.existsSync(src)) {
          copyStaticToolDir(src, dest)
          const coordSrc = path.join(src, '坐标文件bom封装对比.html')
          const coordAscii = path.join(dest, 'coord-bom-package.html')
          if (fs.existsSync(coordSrc)) {
            fs.copyFileSync(coordSrc, coordAscii)
          }
        }
      },
    },
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api/material-db': {
        target: process.env.VITE_HTMLSYSTM_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
    fs: {
      allow: ['.'],
    },
  },
})
