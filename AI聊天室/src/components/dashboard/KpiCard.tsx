import type { ReactNode } from 'react';
import type { DashboardKpiKey } from '@/types/dashboard';

interface KpiCardProps {
  kpi: DashboardKpiKey;
  onOpen: (kpi: DashboardKpiKey) => void;
  children: ReactNode;
}

/** 可点击的数据概览 KPI 卡片 */
export function KpiCard({ kpi, onOpen, children }: KpiCardProps) {
  return (
    <button
      type="button"
      className="bi-card dash-kpi-card"
      onClick={() => onOpen(kpi)}
      aria-label="查看明细记录"
    >
      <span className="dash-kpi-card-hint">
        <i className="fas fa-list-ul" aria-hidden /> 点击查看明细
      </span>
      {children}
    </button>
  );
}
