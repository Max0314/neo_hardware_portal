/**
 * 后端 HTTP 根地址。生产环境（Docker/Nginx 同源反代）留空即可，请求走相对路径 /api。
 * 本地若前端与后端不同源，可设 VITE_API_BASE_URL=http://127.0.0.1:8000
 */
function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '')
}

function normalizePathPrefix(value: string): string {
  const trimmed = trimTrailingSlash((value || '').trim())
  if (!trimmed || trimmed === '/') return ''
  return trimmed.startsWith('/') ? trimmed : `/${trimmed}`
}

function derivePublicBasePath(neoPathPrefix: string): string {
  if (neoPathPrefix === '/neo') return ''
  if (neoPathPrefix.endsWith('/neo')) {
    return neoPathPrefix.slice(0, -4)
  }
  return ''
}

export const NEO_BASE_PATH = normalizePathPrefix(
  String(import.meta.env.VITE_NEO_PATH_PREFIX || import.meta.env.BASE_URL || '/neo')
)

export const PUBLIC_BASE_PATH = normalizePathPrefix(
  String(import.meta.env.VITE_PUBLIC_BASE_PATH || derivePublicBasePath(NEO_BASE_PATH))
)

export const API_BASE = trimTrailingSlash(String(import.meta.env.VITE_API_BASE_URL ?? ''))

export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  if (API_BASE) return `${API_BASE}${p}`
  return `${PUBLIC_BASE_PATH}${p}`
}

export function appUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  return `${PUBLIC_BASE_PATH}${p}`
}

/** WebSocket：未配置 VITE_WS_URL 时与当前页面同源（由 Nginx 反代 /ws） */
export function getWsUrl(): string {
  const env = import.meta.env.VITE_WS_URL
  if (env) return env
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}${PUBLIC_BASE_PATH}/ws`
  }
  return 'ws://127.0.0.1:8000/ws'
}
