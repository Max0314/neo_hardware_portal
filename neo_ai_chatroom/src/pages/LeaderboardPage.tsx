import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import * as XLSX from 'xlsx';
import './HomePage.css';
import type { LeaderboardEntry } from '@/types/leaderboard';
import { fetchLeaderboard } from '@/utils/leaderboardApi';
import { formatNeoPoints } from '@/utils/neoPoints';
import { appUrl } from '@/utils/apiBase';
import { getExternalOpenMessage, openCurrentPageExternally } from '@/utils/externalOpen';

export function LeaderboardPage() {
  const [leaderboardType, setLeaderboardType] = useState<'total' | 'month'>('month');
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [myRankTotal, setMyRankTotal] = useState(0);
  const [myRankMonth, setMyRankMonth] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadLeaderboard = (showLoading = false) => {
      if (showLoading) {
        setLoading(true);
        setLoadError(null);
      }
      fetchLeaderboard()
        .then((data) => {
          if (cancelled) return;
          if (data.success && Array.isArray(data.entries)) {
            setEntries(data.entries);
            setMyRankTotal(data.myRankTotal ?? 0);
            setMyRankMonth(data.myRankMonth ?? 0);
            setLoadError(null);
          } else {
            setEntries([]);
            setLoadError(data.error || '加载排行榜失败');
          }
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setEntries([]);
          const msg =
            (err as { response?: { data?: { error?: string; detail?: string } } })?.response?.data
              ?.error ||
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
            (err as Error)?.message ||
            '加载排行榜失败';
          setLoadError(String(msg));
        })
        .finally(() => {
          if (!cancelled && showLoading) setLoading(false);
        });
    };

    loadLeaderboard(true);
    const pollTimer = window.setInterval(() => loadLeaderboard(false), 30000);
    const onRefresh = () => {
      if (!document.hidden) loadLeaderboard(false);
    };
    window.addEventListener('focus', onRefresh);
    document.addEventListener('visibilitychange', onRefresh);

    return () => {
      cancelled = true;
      window.clearInterval(pollTimer);
      window.removeEventListener('focus', onRefresh);
      document.removeEventListener('visibilitychange', onRefresh);
    };
  }, []);

  const leaderboardSorted = useMemo(() => {
    const rankBy = leaderboardType === 'total' ? 'totalPoints' : 'monthPoints';
    return [...entries].sort((a, b) => b[rankBy] - a[rankBy] || a.name.localeCompare(b.name, 'zh-CN'));
  }, [entries, leaderboardType]);

  const currentUserRank = leaderboardType === 'total' ? myRankTotal : myRankMonth;

  const handleExportLeaderboard = () => {
    const rows = leaderboardSorted.map((item, index) => ({
      排名: index + 1,
      用户: item.name,
      总积分: item.totalPoints,
      当月积分: item.monthPoints,
      当前榜单积分: leaderboardType === 'total' ? item.totalPoints : item.monthPoints,
    }));
    const worksheet = XLSX.utils.json_to_sheet(rows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, leaderboardType === 'total' ? '总排行榜' : '当月排行榜');
    const dateTag = new Date().toISOString().slice(0, 10);
    const filename = `积分排行榜_${leaderboardType === 'total' ? '总榜' : '月榜'}_${dateTag}.xlsx`;
    XLSX.writeFile(workbook, filename);
  };
  const handleExternalOpen = async () => {
    const result = await openCurrentPageExternally();
    alert(getExternalOpenMessage(result));
  };

  return (
    <div className="neo-home leaderboard-theme">
      <div className="neo-container">
        <header className="navbar">
          <div className="logo-area">
            <div className="neo-page-actions">
              <Link to="/" className="neo-page-action" title="返回首页">
                <i className="fas fa-arrow-left" aria-hidden />
                <span>返回首页</span>
              </Link>
              <a href={appUrl('/')} className="neo-page-action" title="返回硬件研发部管理系统">
                <i className="fas fa-house" aria-hidden />
                <span>管理系统</span>
              </a>
              <button type="button" className="neo-page-action subtle" onClick={handleExternalOpen} title="在外部浏览器打开">
                <i className="fas fa-up-right-from-square" aria-hidden />
                <span>外部打开</span>
              </button>
            </div>
            <div className="brand-title-wrap">
              <img src={`${import.meta.env.BASE_URL}logo.png`} alt="CHANGHONG NeoNet" className="brand-logo-inline" />
              <div className="brand-title-row">
                <div className="logo-text">NEO Hardware <span>AI</span></div>
                <div className="sys-subtitle-neo">硬件研发部管理系统</div>
              </div>
            </div>
          </div>
          <div className="nav-right" />
        </header>

        <section className="leaderboard-page-section">
          <div className="leaderboard-card leaderboard-page-card">
            <div className="leaderboard-header">
              <div className="leaderboard-title-wrap">
                <h3 className="leaderboard-title">NEO Hardware AI 积分荣耀排行榜</h3>
                <span className="leaderboard-rank-tip">
                  我的{leaderboardType === 'month' ? '当月' : '总'}排名：第 {loading ? '…' : currentUserRank || '-'} 名
                </span>
              </div>
              <button
                type="button"
                className="leaderboard-export-btn"
                onClick={handleExportLeaderboard}
                disabled={loading || entries.length === 0}
              >
                导出 Excel
              </button>
            </div>

            <div className="leaderboard-tabs">
              <button
                type="button"
                className={`leaderboard-tab ${leaderboardType === 'month' ? 'active' : ''}`}
                onClick={() => setLeaderboardType('month')}
              >
                当月排行榜
              </button>
              <button
                type="button"
                className={`leaderboard-tab ${leaderboardType === 'total' ? 'active' : ''}`}
                onClick={() => setLeaderboardType('total')}
              >
                总排行榜
              </button>
            </div>

            {loadError && (
              <p className="text-sm text-red-600 px-2 py-2" role="alert">
                {loadError}
              </p>
            )}

            <div className="leaderboard-list">
              {loading ? (
                <div className="leaderboard-row">
                  <span className="leaderboard-user text-slate-500">加载中…</span>
                </div>
              ) : leaderboardSorted.length === 0 ? (
                <div className="leaderboard-row">
                  <span className="leaderboard-user text-slate-500">暂无用户数据</span>
                </div>
              ) : (
                leaderboardSorted.map((item, index) => (
                  <div
                    key={item.userKey}
                    className={`leaderboard-row ${item.isSelf ? 'is-self' : ''}`}
                  >
                    <span className="leaderboard-rank">#{index + 1}</span>
                    <span className="leaderboard-user">{item.name}</span>
                    <span className="leaderboard-score">
                      {formatNeoPoints(leaderboardType === 'total' ? item.totalPoints : item.monthPoints)} 分
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
