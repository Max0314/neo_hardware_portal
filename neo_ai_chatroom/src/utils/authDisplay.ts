/** 管理系统 / NEO /api/auth/me 返回的用户字段子集 */
export type AuthMeUser = {
  id?: number
  username?: string
  userid?: string
  userKey?: string
  name?: string
  nickname?: string
  roles?: string[]
}

export type AuthMeResponse = {
  authenticated: boolean
  user: AuthMeUser | null
}

export function pickNeoDisplayName(user: AuthMeUser | null | undefined): string {
  if (!user) return '未登录'
  const s = (user.name || user.nickname || user.username || '').trim()
  return s || '用户'
}

export function pickNeoAvatarLetter(displayName: string): string {
  const t = displayName.trim()
  if (!t) return '?'
  return t[0]!
}
