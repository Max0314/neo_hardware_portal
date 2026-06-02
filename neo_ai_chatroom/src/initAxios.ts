import axios from 'axios'
import { handleApiUnauthorized } from '@/auth/session'

axios.defaults.withCredentials = true

/** 与 htmlsystm 同域：NEO 业务 API 401 时先确认会话再决定是否回登录页 */
axios.interceptors.response.use(
  (r) => r,
  (err: unknown) => {
    const status = (err as { response?: { status?: number } })?.response?.status
    const url = String((err as { config?: { url?: string } })?.config?.url ?? '')
    if (
      status === 401 &&
      typeof window !== 'undefined' &&
      url.includes('/api/') &&
      !url.includes('/api/auth/me')
    ) {
      void handleApiUnauthorized()
    }
    return Promise.reject(err)
  }
)

if (typeof window !== 'undefined') {
  const nativeFetch = window.fetch.bind(window)
  window.fetch = async function authAwareFetch(
    input: RequestInfo | URL,
    init?: RequestInit
  ): Promise<Response> {
    const res = await nativeFetch(input, init)
    if (res.status === 401) {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : String(input)
      if (url.includes('/api/') && !url.includes('/api/auth/me')) {
        void handleApiUnauthorized()
      }
    }
    return res
  }
}
