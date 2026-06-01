import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';

/** 上报主页等功能入口使用（用于「组件使用次数」看板） */
export function trackDashboardFeatureUse(feature: string): void {
  const f = (feature || '').trim().slice(0, 128);
  if (!f) return;
  axios.post(apiUrl('/api/dashboard/feature-use'), { feature: f }).catch(() => {});
}

/** 将数值序列转为 SVG polyline 的 points 字符串（用于迷你趋势图） */
export function buildSparklinePoints(
  values: number[] | undefined,
  width = 200,
  height = 40
): string {
  if (!values?.length) return '';
  const max = Math.max(...values, 1);
  const n = values.length;
  return values
    .map((v, i) => {
      const x = (i / Math.max(n - 1, 1)) * width;
      const y = height - (v / max) * (height - 6) - 3;
      return `${x},${y}`;
    })
    .join(' ');
}
