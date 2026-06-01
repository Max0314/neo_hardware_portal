/** 无操作超过该时长后返回 NEO 主页（毫秒），可用 VITE_IDLE_TIMEOUT_MINUTES 覆盖 */
const minutes = Number(import.meta.env.VITE_IDLE_TIMEOUT_MINUTES ?? 30)
export const IDLE_TIMEOUT_MS = Math.max(5, minutes) * 60 * 1000

/** NEO 主页路由（相对 basename /neo） */
export const NEO_HOME_PATH = '/'
