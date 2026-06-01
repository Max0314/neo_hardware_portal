/**
 * 后端 HTTP 根地址。生产环境（Docker/Nginx 同源反代）留空即可，请求走相对路径 /api。
 * 本地若前端与后端不同源，可设 VITE_API_BASE_URL=http://127.0.0.1:8000
 */
export const API_BASE = String(import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE}${p}`
}

/** WebSocket：未配置 VITE_WS_URL 时与当前页面同源（由 Nginx 反代 /ws） */
export function getWsUrl(): string {
  const env = import.meta.env.VITE_WS_URL
  if (env) return env
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/ws`
  }
  return 'ws://127.0.0.1:8000/ws'
}
