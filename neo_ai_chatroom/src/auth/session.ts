import axios from 'axios'
import { apiUrl, appUrl } from '@/utils/apiBase'

export type SessionCheckResult = 'authenticated' | 'unauthenticated' | 'offline'

let redirectInFlight = false
let redirectCooldownUntil = 0

/** 当前 NEO 路径对应的登录后回跳地址 */
export function loginRedirectUrl(): string {
  const path = window.location.pathname || '/neo/'
  const search = window.location.search || ''
  return appUrl(`/login?redirect=${encodeURIComponent(path + search)}`)
}

export function redirectToLogin(): void {
  const now = Date.now()
  if (redirectInFlight || now < redirectCooldownUntil) {
    return
  }
  redirectInFlight = true
  redirectCooldownUntil = now + 8000
  window.location.href = loginRedirectUrl()
}

/**
 * 业务 API 返回 401 时：先向 /api/auth/me 确认会话是否真的失效，避免误踢引发登录页闪烁。
 */
export async function handleApiUnauthorized(): Promise<void> {
  const now = Date.now()
  if (redirectInFlight || now < redirectCooldownUntil) {
    return
  }
  try {
    const res = await axios.get<{ authenticated?: boolean }>(apiUrl('/api/auth/me'), {
      withCredentials: true,
      timeout: 6000,
      // 避免被全局拦截器再次处理
      validateStatus: (s) => s < 500,
    })
    if (res.status === 200 && res.data?.authenticated) {
      return
    }
  } catch {
    /* 网络异常时仍尝试跳转登录 */
  }
  redirectToLogin()
}

export async function checkSession(): Promise<SessionCheckResult> {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return 'offline'
  }
  try {
    const res = await axios.get<{ authenticated?: boolean }>(apiUrl('/api/auth/me'), {
      withCredentials: true,
      timeout: 8000,
    })
    if (res.data?.authenticated) {
      redirectInFlight = false
      return 'authenticated'
    }
    redirectToLogin()
    return 'unauthenticated'
  } catch (err: unknown) {
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 401) {
      redirectToLogin()
      return 'unauthenticated'
    }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      return 'offline'
    }
    return 'offline'
  }
}
