import type { ReactNode } from 'react'
import { useIdleReturnHome } from '@/hooks/useIdleReturnHome'

/** 挂载于路由外层，为所有 NEO 页面启用空闲回主页 */
export function IdleSessionGuard({ children }: { children: ReactNode }) {
  useIdleReturnHome()
  return <>{children}</>
}
