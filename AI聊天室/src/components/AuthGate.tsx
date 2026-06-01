import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { checkSession, type SessionCheckResult } from '@/auth/session'

type GateState = 'loading' | SessionCheckResult

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>('loading')

  const runCheck = useCallback(async () => {
    const result = await checkSession()
    setState(result)
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const result = await checkSession()
      if (!cancelled) setState(result)
    })()
    const onOnline = () => {
      void (async () => {
        const result = await checkSession()
        if (!cancelled) setState(result)
      })()
    }
    window.addEventListener('online', onOnline)
    return () => {
      cancelled = true
      window.removeEventListener('online', onOnline)
    }
  }, [runCheck])

  if (state === 'loading') {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-50 text-slate-600">
        正在验证登录状态…
      </div>
    )
  }

  if (state === 'offline') {
    return (
      <div className="flex h-screen w-screen flex-col items-center justify-center gap-3 bg-slate-50 px-6 text-center text-slate-600">
        <p>网络已断开，恢复连接后将自动验证登录。</p>
        <button
          type="button"
          className="rounded-lg bg-slate-800 px-4 py-2 text-sm text-white"
          onClick={() => void runCheck()}
        >
          重试
        </button>
      </div>
    )
  }

  if (state === 'unauthenticated') {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-50 text-slate-600">
        正在跳转到登录页…
      </div>
    )
  }

  return <>{children}</>
}
