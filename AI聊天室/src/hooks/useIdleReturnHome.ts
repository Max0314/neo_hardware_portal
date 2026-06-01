import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { IDLE_TIMEOUT_MS, NEO_HOME_PATH } from '@/config/idleSession'
import { checkSession } from '@/auth/session'

function isNeoHome(pathname: string): boolean {
  return pathname === NEO_HOME_PATH || pathname === ''
}

/**
 * 长时间无操作：会话失效则跳转登录；在子页则回 NEO 主页；已在主页且会话有效则刷新以恢复僵死 UI。
 */
export function useIdleReturnHome() {
  const navigate = useNavigate()
  const location = useLocation()
  const locationRef = useRef(location)
  locationRef.current = location
  const lastActivityRef = useRef(Date.now())
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handlingRef = useRef(false)

  useEffect(() => {
    lastActivityRef.current = Date.now()

    const clearTimer = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }

    const scheduleCheck = () => {
      clearTimer()
      const elapsed = Date.now() - lastActivityRef.current
      const delay = Math.max(0, IDLE_TIMEOUT_MS - elapsed)
      timerRef.current = setTimeout(() => void handleIdle(), delay)
    }

    const handleIdle = async () => {
      if (handlingRef.current) return
      if (Date.now() - lastActivityRef.current < IDLE_TIMEOUT_MS) {
        scheduleCheck()
        return
      }
      handlingRef.current = true
      try {
        const { pathname } = locationRef.current
        const session = await checkSession()
        if (session !== 'authenticated') {
          if (session === 'unauthenticated') {
            return
          }
          scheduleCheck()
          return
        }
        if (isNeoHome(pathname)) {
          window.location.reload()
          return
        }
        navigate(NEO_HOME_PATH, { replace: true })
      } finally {
        handlingRef.current = false
      }
    }

    const bumpActivity = () => {
      lastActivityRef.current = Date.now()
      scheduleCheck()
    }

    const onVisibility = () => {
      if (document.visibilityState !== 'visible') return
      if (Date.now() - lastActivityRef.current >= IDLE_TIMEOUT_MS) {
        void handleIdle()
      } else {
        scheduleCheck()
      }
    }

    const onOnline = () => {
      void (async () => {
        const session = await checkSession()
        if (session === 'unauthenticated') return
        if (session === 'authenticated') scheduleCheck()
      })()
    }

    const events: (keyof DocumentEventMap)[] = [
      'mousedown',
      'keydown',
      'scroll',
      'touchstart',
      'click',
    ]
    events.forEach((e) => document.addEventListener(e, bumpActivity, { passive: true }))
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('online', onOnline)
    scheduleCheck()

    return () => {
      clearTimer()
      events.forEach((e) => document.removeEventListener(e, bumpActivity))
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('online', onOnline)
    }
  }, [location.pathname, location.search, navigate])
}
