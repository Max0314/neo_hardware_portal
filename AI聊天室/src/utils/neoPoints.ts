import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';

/** 与后端 POINTS_BY_EVENT 一致 */
export type NeoPointEvent =
  | 'ai_check_export'
  | 'schematic_review_export'
  | 'material_db_edit'
  | 'compare_tool'
  | 'sop_complete';

export function trackNeoPoints(event: NeoPointEvent): void {
  axios
    .post(apiUrl('/api/dashboard/points-event'), { event }, { withCredentials: true })
    .catch(() => {});
}

/** 展示积分：保留一位小数，整数不显示 .0 */
export function formatNeoPoints(value: number): string {
  const n = Math.round(Number(value) * 10 + 1e-9) / 10;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
