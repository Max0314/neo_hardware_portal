/**
 * 评审效能看板 - 数据接口定义（与 GET /api/dashboard/stats 的 stats 一致）
 */

/** 单周数据点（用于折线/柱状图） */
export interface WeeklyDataPoint {
  week_label: string;
  value: number;
}

/** 按月趋势点 */
export interface MonthTrendPoint {
  label: string;
  value: number;
}

/** 近期使用动态（底部滚动条） */
export interface DashboardActivityItem {
  kind: 'feature' | 'bom' | 'points';
  detail: string;
  user_key?: string;
  user_name: string;
  created_at: string;
}

/** 看板统计 */
export interface DashboardStats {
  /** 主页等功能入口累计点击次数 */
  component_use_total: number;
  component_use_this_week: number;
  weekly_component_use?: WeeklyDataPoint[];
  /** 各 feature 累计次数（可选，便于扩展展示） */
  feature_use_breakdown?: Record<string, number>;

  /** 网表对比：总次数 */
  netlist_compare_count: number;
  /** 网表分析：总次数 */
  netlist_analyze_count: number;
  /** 网表操作：本周总次数 */
  netlist_count_this_week: number;
  weekly_netlist_counts?: WeeklyDataPoint[];

  /** BOM AI check：上报的 INFO 条数累计（各次快照之和） */
  bom_defect_info_total: number;
  bom_defect_info_this_week?: number;
  weekly_bom_defect_info?: WeeklyDataPoint[];

  /** 已保存的网表分析结果中，待检查项总数（与网表 AI 待检查项算法一致） */
  netlist_need_check_total: number;
  netlist_need_check_this_week?: number;

  /** 当月缺陷密度 = 当月缺陷项合计 / max(当月组件使用次数, 1) */
  defect_density: number | null;
  defect_density_trend_pct?: number | null;
  /** 近 6 个月按月缺陷密度 */
  monthly_defect_density?: MonthTrendPoint[];

  /** 近期用户使用记录 */
  recent_activity?: DashboardActivityItem[];

  updated_at?: string;
}

/** API 响应结构 */
export interface DashboardStatsResponse {
  success: boolean;
  stats: DashboardStats;
  updated_at?: string;
  error?: string;
}

export type DashboardKpiKey =
  | 'component_use'
  | 'netlist'
  | 'bom'
  | 'netlist_check'
  | 'defect_density';

/** KPI 明细行（字段因 kpi 类型而异） */
export type DashboardKpiDetailRow = Record<string, string | number | null | undefined>;

export interface DashboardKpiDetailResponse {
  success: boolean;
  kpi: DashboardKpiKey;
  title: string;
  subtitle?: string;
  items: DashboardKpiDetailRow[];
  error?: string;
}
