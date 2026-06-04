import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import type { DashboardStats, DashboardStatsResponse, DashboardKpiKey } from '@/types/dashboard';
import { DashboardCharts } from '@/components/dashboard/DashboardCharts';
import { ActivityTicker } from '@/components/dashboard/ActivityTicker';
import { KpiCard } from '@/components/dashboard/KpiCard';
import { KpiDetailModal } from '@/components/dashboard/KpiDetailModal';
import { apiUrl } from '@/utils/apiBase';
import { getExternalOpenMessage, openCurrentPageExternally } from '@/utils/externalOpen';
import './HomePage.css';
import './DashboardPage.css';

/** 评审效能看板 - 独立页面 */
export function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeKpi, setActiveKpi] = useState<DashboardKpiKey | null>(null);

  useEffect(() => {
    axios
      .get<DashboardStatsResponse>(apiUrl('/api/dashboard/stats'))
      .then((res) => {
        if (res.data?.success && res.data?.stats) setStats(res.data.stats);
        else setStats(null);
      })
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, []);

  const s = stats;
  const fmt = (v: number | null | undefined, suffix = '') =>
    v != null ? `${v}${suffix}` : '--';
  const handleExternalOpen = async () => {
    const result = await openCurrentPageExternally();
    alert(getExternalOpenMessage(result));
  };

  return (
    <div className="neo-home dash-page">
      <div className="neo-container">
        <header className="navbar" style={{ marginBottom: '1.5rem' }}>
          <div className="logo-area neo-page-actions">
            <Link
              to="/"
              className="neo-page-action"
              title="返回主页"
            >
              <i className="fas fa-arrow-left" />
              <span>返回主页</span>
            </Link>
            <button type="button" className="neo-page-action subtle" onClick={handleExternalOpen} title="在外部浏览器打开">
              <i className="fas fa-up-right-from-square" />
              <span>外部打开</span>
            </button>
          </div>
          <h1 className="logo-text" style={{ margin: 0, fontSize: '1.5rem' }}>
            <i className="fas fa-chart-line" style={{ marginRight: 8, color: '#1E749C' }} />
            评审效能看板
          </h1>
          <div style={{ width: 100 }} />
        </header>

        <section className="bi-dashboard">
          <div className="section-header" style={{ cursor: 'default' }}>
            <h2 style={{ margin: 0 }}>
              <i className="fas fa-chart-line" style={{ color: '#1E749C' }} /> 数据概览
            </h2>
            {stats?.updated_at && (
              <span>更新于 {new Date(stats.updated_at).toLocaleString('zh-CN')}</span>
            )}
          </div>

          {loading ? (
            <div style={{ textAlign: 'center', padding: '4rem', color: '#3C6478' }}>
              <i className="fas fa-spinner fa-spin" style={{ fontSize: '2rem', marginBottom: 12 }} />
              <div>加载中...</div>
            </div>
          ) : (
            <>
              <div className="bi-grid dash-kpi-grid">
                <KpiCard kpi="component_use" onOpen={setActiveKpi}>
                  <div className="bi-header">
                    <span className="bi-title">
                      <i className="fas fa-layer-group" style={{ color: '#31799B' }} /> 组件使用次数
                    </span>
                  </div>
                  <div className="bi-value">
                    {s ? fmt(s.component_use_total) : <span className="dashboard-placeholder">--</span>}
                  </div>
                  <div className="bi-trend">
                    {s ? `本周 ${fmt(s.component_use_this_week)} 次` : (
                      <span className="dashboard-placeholder">暂无数据</span>
                    )}
                  </div>
                </KpiCard>

                <KpiCard kpi="netlist" onOpen={setActiveKpi}>
                  <div className="bi-header">
                    <span className="bi-title">
                      <i className="fas fa-diagram-project" style={{ color: '#567F9F' }} /> 网表操作
                    </span>
                  </div>
                  <div className="bi-value">
                    {s
                      ? fmt((s.netlist_compare_count ?? 0) + (s.netlist_analyze_count ?? 0), ' 次')
                      : <span className="dashboard-placeholder">--</span>}
                  </div>
                  <div className="bi-trend">
                    {s ? (
                      `对比 ${fmt(s.netlist_compare_count)} / 分析 ${fmt(s.netlist_analyze_count)} · 本周 ${fmt(s.netlist_count_this_week)} 次`
                    ) : (
                      <span className="dashboard-placeholder">暂无数据</span>
                    )}
                  </div>
                </KpiCard>

                <KpiCard kpi="bom" onOpen={setActiveKpi}>
                  <div className="bi-header">
                    <span className="bi-title">
                      <i className="fas fa-clipboard-list" style={{ color: '#2A7F6E' }} /> BOM缺陷统计
                    </span>
                  </div>
                  <div className="bi-value">
                    {s ? fmt(s.bom_defect_info_total, ' 条') : (
                      <span className="dashboard-placeholder">--</span>
                    )}
                  </div>
                  <div className="bi-trend">
                    {s ? (
                      <>INFO 累计 · 本周 {fmt(s.bom_defect_info_this_week ?? 0)} 条</>
                    ) : (
                      <span className="dashboard-placeholder">BOM AI check 自动汇总</span>
                    )}
                  </div>
                </KpiCard>

                <KpiCard kpi="netlist_check" onOpen={setActiveKpi}>
                  <div className="bi-header">
                    <span className="bi-title">
                      <i className="fas fa-list-check" style={{ color: '#567F9F' }} /> 网表待检查项
                    </span>
                  </div>
                  <div className="bi-value">
                    {s ? fmt(s.netlist_need_check_total, ' 项') : (
                      <span className="dashboard-placeholder">--</span>
                    )}
                  </div>
                  <div className="bi-trend">
                    {s ? (
                      <>清单项合计 · 本周新建含 {fmt(s.netlist_need_check_this_week ?? 0)} 项</>
                    ) : (
                      <span className="dashboard-placeholder">暂无数据</span>
                    )}
                  </div>
                </KpiCard>

                <KpiCard kpi="defect_density" onOpen={setActiveKpi}>
                  <div className="bi-header">
                    <span className="bi-title">
                      <i className="fas fa-bug" style={{ color: '#9E6D5E' }} /> 缺陷密度趋势
                    </span>
                  </div>
                  <div className="bi-value">
                    {s?.defect_density != null ? (
                      <>
                        {fmt(s.defect_density)}
                        <small style={{ fontSize: '0.9rem' }}> 项/次</small>
                      </>
                    ) : (
                      <span className="dashboard-placeholder">--</span>
                    )}
                  </div>
                  <div className="bi-trend">
                    {s?.defect_density_trend_pct != null ? (
                      <>
                        <i className="fas fa-chart-line" style={{ color: '#567F9F' }} /> 较上月{' '}
                        <span
                          style={{
                            color: s.defect_density_trend_pct <= 0 ? '#1C8B6C' : '#B44A4A',
                          }}
                        >
                          {s.defect_density_trend_pct > 0 ? '+' : ''}
                          {s.defect_density_trend_pct}%
                        </span>
                      </>
                    ) : (
                      <span className="dashboard-placeholder">缺陷项 ÷ 组件使用次数</span>
                    )}
                  </div>
                </KpiCard>
              </div>

              <section className="dash-charts-section">
                <h2>
                  <i className="fas fa-chart-pie" style={{ color: '#1E749C' }} /> 可视化分析
                </h2>
                <DashboardCharts stats={s} />
              </section>
            </>
          )}
        </section>

        <footer className="neo-footer" style={{ marginBottom: '2.5rem' }}>
          <span>
            <i className="fas fa-shield-halved" /> NEO Hardware AI · 评审效能看板
          </span>
          <Link to="/" style={{ color: '#58809B', textDecoration: 'none' }}>
            返回主页
          </Link>
        </footer>
      </div>

      {!loading && <ActivityTicker items={s?.recent_activity} />}
      <KpiDetailModal kpi={activeKpi} onClose={() => setActiveKpi(null)} />
    </div>
  );
}
