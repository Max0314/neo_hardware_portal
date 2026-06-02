import React, { Component, type ErrorInfo, type ReactNode } from 'react'
import { loginRedirectUrl } from '@/auth/session'

type Props = { children: ReactNode }
type State = { hasError: boolean }

export class NeoErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[NEO] render error', error, info)
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }
    const loginHref = loginRedirectUrl()
    return (
      <div className="flex h-screen w-screen flex-col items-center justify-center gap-4 bg-slate-50 px-6 text-center">
        <p className="text-slate-700">页面加载异常，可能是会话已过期。</p>
        <div className="flex gap-3">
          <button
            type="button"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
            onClick={() => window.location.reload()}
          >
            重新加载
          </button>
          <a
            href={loginHref}
            className="rounded-lg bg-slate-800 px-4 py-2 text-sm text-white no-underline"
          >
            返回登录
          </a>
        </div>
      </div>
    )
  }
}
