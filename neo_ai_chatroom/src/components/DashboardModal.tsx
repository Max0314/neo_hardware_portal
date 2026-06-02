import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import type { DashboardStats, DashboardStatsResponse } from '@/types/dashboard';
import { buildSparklinePoints } from '@/utils/dashboardTelemetry';
import { apiUrl } from '@/utils/apiBase';
import './DashboardModal.css';

interface DashboardModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/** 评审效能看板弹层：使用统一数据接口，预留字段便于后期真实数据导入 */
export const DashboardModal: React.FC<DashboardModalProps> = ({ isOpen, onClose }) => {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    axios
      .get<DashboardStatsResponse>(apiUrl('/api/dashboard/stats'))
      .then((res) => {
        if (res.data?.success && res.data?.stats) setStats(res.data.stats);
        else setStats(null);
      })
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, [isOpen]);

  if (!isOpen) return null;

  const s = stats;
  const fmt = (v: number | null | undefined, suffix = '') =>
    v != null ? `${v}${suffix}` : '--';

  const lineUse = useMemo(
    () => buildSparklinePoints(s?.weekly_component_use?.map((p) => p.value)),
    [s?.weekly_component_use]
  );

  return (
    <div className="dashboard-modal-overlay" onClick={onClose} role="presentation">
      <div
        className="dashboard-modal-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="dashboard-modal-title"
      >
        <div className="dashboard-modal-header">
          <h2 id="dashboard-modal-title">
            <i className="fas fa-chart-line" style={{ color: '#1E749C' }} /> 评审效能看板
          </h2>
          <button
            type="button"
            className="dashboard-modal-close"
            onClick={onClose}
            aria-label="关闭"
          >
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="dashboard-modal-body">
          {loading ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: '#3C6478' }}>
              <i className="fas fa-spinner fa-spin" style={{ fontSize: '1.5rem', marginBottom: 8 }} />
              <div>加载中…</div>
            </div>
          ) : (
            <div className="bi-grid">
              <div className="bi-card">
                <div className="bi-header">
                  <span className="bi-title">
                    <i className="fas fa-layer-group" style={{ color: '#31799B' }} /> 组件使用次数
                  </span>
                </div>
                <div className="bi-value">
                  {s ? fmt(s.component_use_total) : <span className="dashboard-placeholder">--</span>}
                </div>
                <div className="bi-trend">
                  {s ? `本周 ${fmt(s.component_use_this_week)} 次` : <span className="dashboard-placeholder">暂无数据</span>}
                </div>
                <div className="mini-chart">
                  <svg className="chart-svg" viewBox="0 0 200 40" preserveAspectRatio="none">
                    <polyline
                      points={lineUse || '0,35 200,35'}
                      style={{
                        fill: 'none',
                        stroke: lineUse ? '#3899C9' : '#A1CCEC',
                        strokeWidth: 2.2,
                        strokeLinecap: 'round',
                        opacity: lineUse ? 1 : 0.7,
                      }}
                    />
                  </svg>
                </div>
              </div>

              {/* 2. 网表操作 */}
              <div className="bi-card">
                <div className="bi-header">
                  <span className="bi-title">
                    <i className="fas fa-diagram-project" style={{ color: '#567F9F' }} /> 网表操作
                  </span>
                </div>
                <div className="bi-value">
                  {s ? fmt((s.netlist_compare_count ?? 0) + (s.netlist_analyze_count ?? 0), ' 次') : <span className="dashboard-placeholder">--</span>}
                </div>
                <div className="bi-trend">
                  {s
                    ? `对比 ${fmt(s.netlist_compare_count)} / 分析 ${fmt(s.netlist_analyze_count)} · 本周 ${fmt(s.netlist_count_this_week)} 次`
                    : <span className="dashboard-placeholder">暂无数据</span>}
                </div>
              </div>

              <div className="bi-card">
                <div className="bi-header">
                  <span className="bi-title">
                    <i className="fas fa-clipboard-list" style={{ color: '#2A7F6E' }} /> BOM缺陷统计
                  </span>
                </div>
                <div className="bi-value">
                  {s ? fmt(s.bom_defect_info_total, ' 条') : <span className="dashboard-placeholder">--</span>}
                </div>
                <div className="bi-trend">
                  {s ? (
                    <>本周 INFO 上报 {fmt(s.bom_defect_info_this_week ?? 0)} 条</>
                  ) : (
                    <span className="dashboard-placeholder">暂无数据</span>
                  )}
                </div>
              </div>

              <div className="bi-card">
                <div className="bi-header">
                  <span className="bi-title">
                    <i className="fas fa-list-check" style={{ color: '#567F9F' }} /> 网表待检查项
                  </span>
                </div>
                <div className="bi-value">
                  {s ? fmt(s.netlist_need_check_total, ' 项') : <span className="dashboard-placeholder">--</span>}
                </div>
                <div className="bi-trend">
                  {s ? (
                    <>本周新建分析含 {fmt(s.netlist_need_check_this_week ?? 0)} 项</>
                  ) : (
                    <span className="dashboard-placeholder">暂无数据</span>
                  )}
                </div>
              </div>

              <div className="bi-card">
                <div className="bi-header">
                  <span className="bi-title">
                    <i className="fas fa-bug" style={{ color: '#9E6D5E' }} /> 缺陷密度趋势
                  </span>
                </div>
                <div className="bi-value">
                  {s?.defect_density != null ? (
                    <>{fmt(s.defect_density)}<small style={{ fontSize: '0.9rem' }}> 项/次</small></>
                  ) : (
                    <span className="dashboard-placeholder">--</span>
                  )}
                </div>
                <div className="bi-trend">
                  <span className="dashboard-placeholder">按月：缺陷项 ÷ 组件使用次数</span>
                </div>
              </div>
            </div>
          )}
          {stats?.updated_at && (
            <div style={{ marginTop: '1rem', fontSize: '0.8rem', color: '#58809B' }}>
              更新于 {new Date(stats.updated_at).toLocaleString('zh-CN')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
