/** 功能入口占比饼图不统计的 feature 键 */
export const EXCLUDED_FEATURE_PIE_KEYS = new Set(['dashboard', 'leaderboard']);

export function isExcludedFromFeaturePie(feature: string): boolean {
  return EXCLUDED_FEATURE_PIE_KEYS.has((feature || '').trim());
}

/** 过滤后的功能入口占比（用于饼图） */
export function filterFeatureBreakdown(breakdown: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(breakdown)) {
    if (!isExcludedFromFeaturePie(key)) out[key] = value;
  }
  return out;
}

/** 看板功能入口 / 积分事件中文展示名 */

const FEATURE_LABELS: Record<string, string> = {  dashboard: '评审效能看板',
  leaderboard: '积分排行榜',
  ai_studio: 'AI 工作室',
  netlist_compare: '网表对比',
  bom_compare: 'BOM 对比',
  bom_check: 'BOM AI 检查',
  material_db: '物料数据库',
};

const POINTS_LABELS: Record<string, string> = {
  ai_check_export: '导出 AI 检查报告',
  material_db_edit: '编辑物料库',
  compare_tool: '对比工具',
  sop_complete: '完成 SOP',
};

export function labelFeature(feature: string): string {
  const key = (feature || '').trim();
  if (!key) return '未知功能';
  if (FEATURE_LABELS[key]) return FEATURE_LABELS[key];
  if (key.startsWith('sop:')) return `SOP · ${key.slice(4)}`;
  return key;
}

export function labelPointsEvent(eventType: string): string {
  const key = (eventType || '').trim();
  return POINTS_LABELS[key] || key || '积分事件';
}

export function formatActivityMessage(item: {
  kind: string;
  detail: string;
  user_name: string;
  created_at: string;
}): string {
  const time = formatActivityTime(item.created_at);
  const who = item.user_name || '访客';
  switch (item.kind) {
    case 'feature':
      return `${time} ${who} 打开了 ${labelFeature(item.detail)}`;
    case 'bom': {
      const n = parseInt(item.detail, 10);
      const count = Number.isFinite(n) ? n : 0;
      return `${time} ${who} BOM 检查上报 ${count} 条 INFO`;
    }
    case 'points':
      return `${time} ${who} 获得积分 · ${labelPointsEvent(item.detail)}`;
    default:
      return `${time} ${who} 使用了系统`;
  }
}

function formatActivityTime(iso: string): string {
  if (!iso) return '--:--';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(11, 16) || iso;
    return d.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso.slice(0, 16);
  }
}
