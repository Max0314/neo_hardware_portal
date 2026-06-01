import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import './HomePage.css';
import type { DashboardStats, DashboardStatsResponse } from '@/types/dashboard';
import { trackDashboardFeatureUse, buildSparklinePoints } from '@/utils/dashboardTelemetry';
import { apiUrl } from '@/utils/apiBase';
import type { AuthMeResponse, AuthMeUser } from '@/utils/authDisplay';
import { pickNeoAvatarLetter, pickNeoDisplayName } from '@/utils/authDisplay';
import { fetchLeaderboard } from '@/utils/leaderboardApi';
import { formatNeoPoints } from '@/utils/neoPoints';

interface UserLevelConfig {
  level: number;
  requiredPoints: number;
  title: string;
}

type RankTier =
  | 'black-iron'
  | 'bronze'
  | 'silver'
  | 'gold'
  | 'platinum'
  | 'diamond'
  | 'master'
  | 'grandmaster'
  | 'challenger';

const USER_LEVELS: UserLevelConfig[] = [
  { level: 1, requiredPoints: 0, title: '新生工科生' },
  { level: 2, requiredPoints: 10, title: '见习布线员' },
  { level: 3, requiredPoints: 30, title: '初级制板师' },
  { level: 4, requiredPoints: 60, title: '中级焊将' },
  { level: 5, requiredPoints: 100, title: '认证调试员' },
  { level: 6, requiredPoints: 150, title: '一板就成俠' },
  { level: 7, requiredPoints: 210, title: '焊武帝' },
  { level: 8, requiredPoints: 280, title: '洞洞板散人' },
  { level: 9, requiredPoints: 370, title: '覆铜板修士' },
  { level: 10, requiredPoints: 480, title: '四层板道长' },
  { level: 11, requiredPoints: 610, title: '主任设计师' },
  { level: 12, requiredPoints: 770, title: '资深硬件专家' },
  { level: 13, requiredPoints: 960, title: '高级专家' },
  { level: 14, requiredPoints: 1200, title: '首席硬件官' },
  { level: 15, requiredPoints: 1500, title: '万用表真人' },
  { level: 16, requiredPoints: 1900, title: '示波器仙人' },
  { level: 17, requiredPoints: 2400, title: '硬件合伙人' },
  { level: 18, requiredPoints: 3100, title: '院士级宗师' },
  { level: 19, requiredPoints: 4200, title: '架构开拓者' },
  { level: 20, requiredPoints: 8000, title: '平台硬件之神 👑' },
];

function getTierByLevel(level: number): RankTier {
  if (level <= 2) return 'black-iron';
  if (level <= 4) return 'bronze';
  if (level <= 6) return 'silver';
  if (level <= 8) return 'gold';
  if (level <= 10) return 'platinum';
  if (level <= 12) return 'diamond';
  if (level <= 14) return 'master';
  if (level <= 17) return 'grandmaster';
  return 'challenger';
}

export function HomePage() {
  const [userPoints, setUserPoints] = useState(0);
  const [monthPoints, setMonthPoints] = useState(0);
  const [dashStats, setDashStats] = useState<DashboardStats | null>(null);
  const [sessionUser, setSessionUser] = useState<AuthMeUser | null | undefined>(undefined);

  useEffect(() => {
    axios
      .get<AuthMeResponse>(apiUrl('/api/auth/me'), { withCredentials: true })
      .then((res) => {
        if (res.data?.authenticated && res.data.user) setSessionUser(res.data.user);
        else setSessionUser(null);
      })
      .catch(() => setSessionUser(null));
  }, []);

  useEffect(() => {
    axios
      .get<DashboardStatsResponse>(apiUrl('/api/dashboard/stats'))
      .then((res) => {
        if (res.data?.success && res.data?.stats) setDashStats(res.data.stats);
        else setDashStats(null);
      })
      .catch(() => setDashStats(null));
  }, []);

  const lineUse = useMemo(
    () => buildSparklinePoints(dashStats?.weekly_component_use?.map((p) => p.value)),
    [dashStats?.weekly_component_use]
  );
  const lineBom = useMemo(
    () => buildSparklinePoints(dashStats?.weekly_bom_defect_info?.map((p) => p.value)),
    [dashStats?.weekly_bom_defect_info]
  );
  const lineDefect = useMemo(
    () => buildSparklinePoints(dashStats?.monthly_defect_density?.map((p) => p.value)),
    [dashStats?.monthly_defect_density]
  );

  const fmtDash = (v: number | null | undefined, suffix = '') =>
    v != null ? `${v}${suffix}` : '--';
  const currentLevel = [...USER_LEVELS].reverse().find((item) => userPoints >= item.requiredPoints) ?? USER_LEVELS[0];
  const nextLevel = USER_LEVELS.find((item) => item.level === currentLevel.level + 1) ?? null;
  const currentLevelBase = currentLevel.requiredPoints;
  const nextLevelBase = nextLevel ? nextLevel.requiredPoints : currentLevelBase;
  const levelSpan = Math.max(1, nextLevelBase - currentLevelBase);
  const progressInLevel = Math.max(0, userPoints - currentLevelBase);
  const progressPercent = nextLevel ? Math.min(100, (progressInLevel / levelSpan) * 100) : 100;
  const pointsToNext = nextLevel ? Math.max(0, nextLevel.requiredPoints - userPoints) : 0;
  const currentTier = getTierByLevel(currentLevel.level);
  const neoDisplayName = sessionUser === undefined ? '…' : pickNeoDisplayName(sessionUser);
  const neoAvatarLetter = sessionUser === undefined ? '…' : pickNeoAvatarLetter(neoDisplayName);

  const syncMyPoints = () => {
    fetchLeaderboard()
      .then((data) => {
        if (data.success) {
          setUserPoints(data.myTotalPoints ?? 0);
          setMonthPoints(data.myMonthPoints ?? 0);
        }
      })
      .catch(() => {
        setUserPoints(0);
        setMonthPoints(0);
      });
  };

  useEffect(() => {
    syncMyPoints();
    const onRefresh = () => syncMyPoints();
    window.addEventListener('focus', onRefresh);
    document.addEventListener('visibilitychange', onRefresh);
    return () => {
      window.removeEventListener('focus', onRefresh);
      document.removeEventListener('visibilitychange', onRefresh);
    };
  }, []);

  return (
    <div className="neo-home">
      <div className="neo-container">
        {/* 导航栏 · NEO Hardware AI */}
        <header className="navbar">
          <div className="logo-area">
            <div className="brand-title-wrap">
              <img src="/logo.png" alt="CHANGHONG NeoNet" className="brand-logo-inline" />
              <div className="brand-title-row">
                <div className="logo-text">NEO Hardware <span>AI</span></div>
                <div className="sys-subtitle-neo">硬件研发部管理系统</div>
                <p className="sys-tagline-neo">专业、高效、可靠的硬件研发管理平台</p>
              </div>
            </div>
          </div>
          <div className="nav-right">
            <a href="/" className="nav-back-admin-link" title="返回硬件研发部管理系统">
              <i className="fas fa-arrow-left" aria-hidden />
              <span>返回管理系统</span>
            </a>
            <Link
              to="/leaderboard"
              className="leaderboard-nav-link"
              onClick={() => trackDashboardFeatureUse('leaderboard')}
            >
              <i className="fas fa-flag" aria-hidden />
              <span>排行榜</span>
            </Link>
            <div
              className={`user-level-wrap user-level-in-nav tier-${currentTier}`}
              role="region"
              aria-label="用户积分与等级"
            >
              <div className="user-level-top">
                <span className="user-level-label">用户等级</span>
                <span className="user-level-name">Lv.{currentLevel.level} · {currentLevel.title}</span>
              </div>
              <div className="user-level-progress-track" aria-hidden>
                <div className="user-level-progress-fill" style={{ width: `${progressPercent}%` }} />
              </div>
              <div className="user-level-meta">
                <span>当月积分：{formatNeoPoints(monthPoints)}</span>
                <span>总积分：{formatNeoPoints(userPoints)}</span>
                {nextLevel ? <span>距下一级 {formatNeoPoints(pointsToNext)} 分</span> : <span>已满级</span>}
              </div>
            </div>
            <i className="far fa-bell nav-icon" />
            <div className="user-profile">
              <div className="avatar">{neoAvatarLetter}</div>
              <span style={{ fontWeight: 500, color: '#194D66' }}>{neoDisplayName}</span>
              <i className="fas fa-chevron-down" style={{ color: '#8EA9BC', fontSize: '0.8rem' }} />
            </div>
          </div>
        </header>

        {/* 核心工具：每个 SOP 独立成卡，与网表等共用 4 列网格自动换行；物料库固定最下 */}
        <div className="home-modules-stack">
          <div className="home-main-tools-grid">
            {/* 原理图 AI 审核 */}
            <Link
              to="/meeting"
              className="feature-card"
              style={{ textDecoration: 'none', color: 'inherit' }}
              onClick={() => trackDashboardFeatureUse('schematic_review')}
            >
              <div className="icon-wrapper dual-icon">
                <i className="fas fa-microchip" />
                <i className="fas fa-clipboard-check" />
              </div>
              <div className="card-title">
                原理图AI审核
                <span className="ai-tag" style={{ background: '#DDEFF7' }}>网表</span>
              </div>
              <div className="card-desc">
                四步完成网表导入、清洗、AI 评审与报告导出（+1 积分）；导出后可与 AI 继续讨论原理图问题。
              </div>
              <div className="card-action">
                <div className="action-btn">
                  <i className="fas fa-arrow-right" />
                  <span>开始审核</span>
                </div>
                <i className="fas fa-diagram-project" style={{ color: '#6F95B0', opacity: 0.8 }} />
              </div>
            </Link>

            {/* 网表对比 */}
            <Link
              to="/netlist-compare"
              className="feature-card"
              style={{ textDecoration: 'none', color: 'inherit' }}
              onClick={() => trackDashboardFeatureUse('netlist_compare')}
            >
              <div className="icon-wrapper">
                <i className="fas fa-code-compare" />
              </div>
              <div className="card-title">网表对比</div>
              <div className="card-desc">
                智能差异引擎：连接增减、器件变更、网络重命名。支持EDIF/SPICE，高亮快照对比。
              </div>
              <div className="card-action">
                <div className="action-btn">
                  <i className="fas fa-arrow-right" />
                  <span>开始对比</span>
                </div>
                <i className="fas fa-not-equal" style={{ color: '#6F95B0', opacity: 0.8 }} />
              </div>
            </Link>

            {/* BOM 对比 */}
            <Link
              to="/bom-compare"
              className="feature-card"
              style={{ textDecoration: 'none', color: 'inherit' }}
              onClick={() => trackDashboardFeatureUse('bom_compare')}
            >
              <div className="icon-wrapper dual-icon">
                <i className="fas fa-table-list" />
                <i className="fas fa-code-branch" />
              </div>
              <div className="card-title">
                BOM 对比
                <span className="ai-tag" style={{ background: '#DDEFF7' }}>Excel</span>
              </div>
              <div className="card-desc">
                上传两份 BOM（xls/xlsx）：全量对比、仅位号，或坐标文件与 BOM 封装对照（含 R/C 模糊匹配）；本地解析，可导出。
              </div>
              <div className="card-action">
                <div className="action-btn">
                  <i className="fas fa-arrow-right" />
                  <span>进入对比</span>
                </div>
                <i className="fas fa-file-excel" style={{ color: '#6F95B0', opacity: 0.8 }} />
              </div>
            </Link>

            {/* BOM AI check */}
            <Link
              to="/bom-check"
              className="feature-card"
              style={{ textDecoration: 'none', color: 'inherit' }}
              onClick={() => trackDashboardFeatureUse('bom_check')}
            >
              <div className="icon-wrapper dual-icon">
                <i className="fas fa-clipboard-check" />
                <i className="fas fa-coins" />
              </div>
              <div className="card-title">
                BOM AI check
                <span className="ai-tag" style={{ background: '#DDEFF7' }}>检查+成本</span>
              </div>
              <div className="card-desc">
                自动纠错（位号重复/封装缺失/停产风险）、智能替代选型；多维成本拆解、阶梯价格模拟与AI替代比价，提升DFM与降本。
              </div>
              <div className="card-action">
                <div className="action-btn">
                  <i className="fas fa-arrow-right" />
                  <span>进入检查</span>
                </div>
                <i className="fas fa-cubes" style={{ color: '#6F95B0', opacity: 0.8 }} />
              </div>
            </Link>
          </div>

          {/* 物料数据库：独占一行；左图右名、说明随标题列、右下进入 */}
          <a
            href={`${import.meta.env.BASE_URL}systm_tool/物料数据库.html`}
            target="_blank"
            rel="noopener noreferrer"
            className="feature-card home-material-library-card"
            style={{ textDecoration: 'none', color: 'inherit' }}
            aria-label="在新页面打开物料数据库"
            onClick={() => trackDashboardFeatureUse('material_db')}
          >
            <div className="home-material-library-inner">
              <div className="home-material-library-icon" aria-hidden>
                <i className="fas fa-database" />
              </div>
              <div className="home-material-library-title-block">
                <h2 className="home-material-library-name">
                  物料数据库
                  <span className="home-material-library-tag">多库 · 查询</span>
                </h2>
              </div>
              <p className="home-material-library-lead">
                当前表与历史表并存，Excel 导入与列映射，服务 BOM 检查匹配与物料查询。
              </p>
              <div className="home-material-library-footer">
                <span className="home-material-library-enter">
                  打开物料库
                  <i className="fas fa-arrow-right" aria-hidden />
                </span>
              </div>
            </div>
          </a>
        </div>

        {/* BI 智能看板 - 点击在新页面打开 */}
        <section className="bi-dashboard">
          <Link
            to="/dashboard"
            target="_blank"
            rel="noopener noreferrer"
            style={{ textDecoration: 'none', color: 'inherit' }}
            aria-label="在新页面打开评审效能看板"
            onClick={() => trackDashboardFeatureUse('dashboard')}
          >
            <div className="section-header" style={{ cursor: 'pointer' }}>
              <h2>
                <i className="fas fa-chart-line" style={{ color: '#1E749C' }} /> 评审效能看板
              </h2>
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span>更新至本周 · NEO分析</span>
                <i className="fas fa-external-link-alt" style={{ fontSize: '0.8rem', color: '#1E749C' }} aria-hidden />
              </span>
            </div>
          </Link>
          <Link
            to="/dashboard"
            target="_blank"
            rel="noopener noreferrer"
            style={{ textDecoration: 'none', color: 'inherit' }}
            aria-label="在新页面打开评审效能看板"
            onClick={() => trackDashboardFeatureUse('dashboard')}
          >
            <div className="bi-grid" style={{ cursor: 'pointer' }}>
            <div className="bi-card">
              <div className="bi-header">
                <span className="bi-title"><i className="fas fa-layer-group" style={{ color: '#31799B' }} /> 组件使用次数</span>
                <i className="fas fa-ellipsis-h" style={{ color: '#96B4C9' }} />
              </div>
              <div className="bi-value">{dashStats ? fmtDash(dashStats.component_use_total) : '—'}</div>
              <div className="bi-trend">
                {dashStats ? (
                  <>本周 {fmtDash(dashStats.component_use_this_week)} 次 · 主页入口累计</>
                ) : (
                  <span style={{ color: '#96B4C9' }}>加载中…</span>
                )}
              </div>
              <div className="mini-chart">
                <svg className="chart-svg" viewBox="0 0 200 40" preserveAspectRatio="none">
                  <polyline
                    points={lineUse || '0,35 200,35'}
                    style={{ fill: 'none', stroke: lineUse ? '#3899C9' : '#B0DAF0', strokeWidth: 2.2, strokeLinecap: 'round', strokeLinejoin: 'round', opacity: lineUse ? 0.9 : 0.35 }}
                  />
                </svg>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, color: '#4D748C', fontSize: '0.7rem' }}>
                {(dashStats?.weekly_component_use?.length
                  ? dashStats.weekly_component_use
                  : [
                      { week_label: 'W-4', value: 0 },
                      { week_label: 'W-3', value: 0 },
                      { week_label: 'W-2', value: 0 },
                      { week_label: '本周', value: 0 },
                    ]
                ).map((p) => (
                  <span key={p.week_label}>{p.week_label}</span>
                ))}
              </div>
            </div>
            <div className="bi-card">
              <div className="bi-header">
                <span className="bi-title"><i className="fas fa-clipboard-list" style={{ color: '#2A7F6E' }} /> BOM缺陷统计</span>
                <i className="fas fa-ellipsis-h" style={{ color: '#96B4C9' }} />
              </div>
              <div className="bi-value">{dashStats ? fmtDash(dashStats.bom_defect_info_total, ' 条') : '—'}</div>
              <div className="bi-trend">
                {dashStats ? (
                  <>BOM AI check · INFO 累计 · 本周 {fmtDash(dashStats.bom_defect_info_this_week ?? 0)} 条</>
                ) : (
                  <span style={{ color: '#96B4C9' }}>加载中…</span>
                )}
              </div>
              <div className="mini-chart">
                <svg className="chart-svg" viewBox="0 0 200 40" preserveAspectRatio="none">
                  <polyline
                    points={lineBom || '0,35 200,35'}
                    style={{ fill: 'none', stroke: lineBom ? '#2C8F8B' : '#A1D9D0', strokeWidth: 2.2, strokeLinecap: 'round', opacity: lineBom ? 0.9 : 0.35 }}
                  />
                </svg>
              </div>
            </div>
            <div className="bi-card">
              <div className="bi-header">
                <span className="bi-title"><i className="fas fa-list-check" style={{ color: '#567F9F' }} /> 网表待检查项</span>
                <i className="fas fa-ellipsis-h" style={{ color: '#96B4C9' }} />
              </div>
              <div className="bi-value">{dashStats ? fmtDash(dashStats.netlist_need_check_total, ' 项') : '—'}</div>
              <div className="bi-trend">
                {dashStats ? (
                  <>网表 AI_CHECK 清单项 · 本周新建 {fmtDash(dashStats.netlist_need_check_this_week ?? 0)} 项</>
                ) : (
                  <span style={{ color: '#96B4C9' }}>加载中…</span>
                )}
              </div>
            </div>
            <div className="bi-card">
              <div className="bi-header">
                <span className="bi-title"><i className="fas fa-bug" style={{ color: '#9E6D5E' }} /> 缺陷密度趋势</span>
                <i className="fas fa-ellipsis-h" style={{ color: '#96B4C9' }} />
              </div>
              <div className="bi-value">
                {dashStats?.defect_density != null ? (
                  <>{fmtDash(dashStats.defect_density)}<small style={{ fontSize: '0.9rem' }}> 项/次</small></>
                ) : (
                  '—'
                )}
              </div>
              <div className="bi-trend">
                {dashStats?.defect_density_trend_pct != null ? (
                  <>
                    较上月密度{' '}
                    <span style={{ color: dashStats.defect_density_trend_pct <= 0 ? '#1C8B6C' : '#B44A4A' }}>
                      {dashStats.defect_density_trend_pct > 0 ? '+' : ''}{dashStats.defect_density_trend_pct}%
                    </span>
                  </>
                ) : (
                  <span>按月：缺陷项 ÷ 组件使用</span>
                )}
              </div>
              <div className="mini-chart">
                <svg className="chart-svg" viewBox="0 0 200 40" preserveAspectRatio="none">
                  <polyline
                    points={lineDefect || '0,35 200,35'}
                    style={{ fill: 'none', stroke: lineDefect ? '#C05A5A' : '#F0C0C0', strokeWidth: 2.2, strokeLinecap: 'round', opacity: lineDefect ? 0.8 : 0.25 }}
                  />
                </svg>
              </div>
            </div>
          </div>
          </Link>
        </section>

        {/* 活跃评审 + NEO Product life cycle */}
        <div className="recent-mini">
          <div className="recent-header">
            <i className="fas fa-microchip" style={{ color: '#2C7DA0' }} />
            <span style={{ fontWeight: 600, color: '#0F4B66' }}>活跃评审</span>
          </div>
          <div className="recent-tag">
            <span className="neo-chip-small"><i className="fas fa-diagram-project" /> 5G前端PA_v4</span>
            <span className="neo-chip-small"><i className="fas fa-bolt" /> 电源BOM成本</span>
            <span className="neo-chip-small"><i className="fas fa-chart-line" /> 网表对比 · DDR</span>
            <span className="neo-chip-small"><i className="fas fa-arrow-right" /> 所有项目</span>
          </div>
          <div className="product-life-row">
            <span className="neo-chip-small" style={{ background: '#E4F0F7', borderColor: '#7FADCC' }}>
              <i className="fas fa-sync-alt" /> NEO Product life cycle
            </span>
            <span className="product-life-desc">
              <i className="fas fa-info-circle" style={{ color: '#3A7C9C' }} /> 代表着NEO公司下的所有产品管理
            </span>
          </div>
        </div>

        {/* 底部 */}
        <footer className="neo-footer">
          <span><i className="fas fa-shield-halved" /> NEO Hardware AI · 评审套件 v2.0</span>
          <span><i className="fas fa-robot" /> 深度求索 智能引擎</span>
        </footer>
      </div>
    </div>
  );
}
