/** 管理系统 / NEO 用户是否可配置 AI 模型（API 密钥等） */
export function canManageModelConfig(
  user: { username?: string; roles?: string[]; capabilities?: { canManageModelConfig?: boolean } } | null | undefined
): boolean {
  if (!user) return false
  if (user.capabilities?.canManageModelConfig) return true
  const roles = user.roles ?? []
  return ['management', 'admin', 'super_admin'].some((r) => roles.includes(r))
}
