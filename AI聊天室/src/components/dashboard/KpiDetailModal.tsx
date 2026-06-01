import { useEffect, useState } from 'react';
import axios from 'axios';
import type { DashboardKpiDetailResponse, DashboardKpiKey } from '@/types/dashboard';
import { apiUrl } from '@/utils/apiBase';

export const KPI_TITLES: Record<DashboardKpiKey, string> = {
  component_use: '组件使用次数',
  netlist: '网表操作',
  bom: 'BOM 缺陷统计',
  netlist_check: '网表待检查项',
  defect_density: '缺陷密度趋势',
};

interface KpiDetailModalProps {
  kpi: DashboardKpiKey | null;
  onClose: () => void;
}

function formatTime(iso: string | number | null | undefined): string {
  if (iso == null || iso === '') return '--';
  try {
    const d = new Date(String(iso));
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString('zh-CN');
  } catch {
    return String(iso);
  }
}

function renderTable(kpi: DashboardKpiKey, items: DashboardKpiDetailResponse['items']) {
  if (!items.length) {
    return <p className="dash-kpi-detail-empty">暂无明细记录</p>;
  }

  switch (kpi) {
    case 'component_use':
      return (
        <table className="dash-kpi-detail-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>用户</th>
              <th>功能</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row, i) => (
              <tr key={i}>
                <td>{formatTime(row.created_at)}</td>
                <td>{row.user_name}</td>
                <td>{row.feature_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    case 'netlist':
      return (
        <table className="dash-kpi-detail-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>类型</th>
              <th>网表</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row, i) => (
              <tr key={i}>
                <td>{formatTime(row.created_at)}</td>
                <td>{row.operation}</td>
                <td>{row.name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    case 'bom':
      return (
        <table className="dash-kpi-detail-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>用户</th>
              <th>INFO 条数</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row, i) => (
              <tr key={i}>
                <td>{formatTime(row.created_at)}</td>
                <td>{row.user_name}</td>
                <td>{row.info_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    case 'netlist_check':
      return (
        <table className="dash-kpi-detail-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>网表</th>
              <th>待检查项</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row, i) => (
              <tr key={i}>
                <td>{formatTime(row.created_at)}</td>
                <td>{row.netlist_name}</td>
                <td>{row.need_check_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    case 'defect_density':
      return (
        <table className="dash-kpi-detail-table">
          <thead>
            <tr>
              <th>月份</th>
              <th>缺陷项合计</th>
              <th>组件使用次数</th>
              <th>密度</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row, i) => (
              <tr key={i}>
                <td>{row.month}</td>
                <td>{row.defect_items}</td>
                <td>{row.component_uses}</td>
                <td>{typeof row.density === 'number' ? row.density.toFixed(4) : row.density}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    default:
      return null;
  }
}

export function KpiDetailModal({ kpi, onClose }: KpiDetailModalProps) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<DashboardKpiDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!kpi) {
      setData(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    axios
      .get<DashboardKpiDetailResponse>(apiUrl('/api/dashboard/kpi-detail'), {
        params: { kpi },
      })
      .then((res) => {
        if (res.data?.success) setData(res.data);
        else {
          setData(null);
          setError(res.data?.error || '加载失败');
        }
      })
      .catch(() => {
        setData(null);
        setError('无法加载明细');
      })
      .finally(() => setLoading(false));
  }, [kpi]);

  if (!kpi) return null;

  const title = data?.title ?? KPI_TITLES[kpi];

  return (
    <div
      className="dash-kpi-modal-overlay"
      role="presentation"
      onClick={onClose}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div
        className="dash-kpi-modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dash-kpi-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="dash-kpi-modal-header">
          <div>
            <h2 id="dash-kpi-modal-title">{title}</h2>
            {data?.subtitle && <p className="dash-kpi-modal-subtitle">{data.subtitle}</p>}
          </div>
          <button type="button" className="dash-kpi-modal-close" onClick={onClose} aria-label="关闭">
            <i className="fas fa-times" />
          </button>
        </header>
        <div className="dash-kpi-modal-body">
          {loading ? (
            <div className="dash-kpi-detail-loading">
              <i className="fas fa-spinner fa-spin" /> 加载中…
            </div>
          ) : error ? (
            <p className="dash-kpi-detail-empty">{error}</p>
          ) : (
            renderTable(kpi, data?.items ?? [])
          )}
        </div>
      </div>
    </div>
  );
}


