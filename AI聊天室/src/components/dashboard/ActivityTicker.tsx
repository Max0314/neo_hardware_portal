import { useMemo } from 'react';
import type { DashboardActivityItem } from '@/types/dashboard';
import { formatActivityMessage } from './dashboardLabels';

interface ActivityTickerProps {
  items: DashboardActivityItem[] | undefined;
}

const EMPTY_HINT = '暂无使用记录，开始使用 NEO 功能后将在此滚动展示';

export function ActivityTicker({ items }: ActivityTickerProps) {
  const messages = useMemo(
    () => (items ?? []).map((item) => formatActivityMessage(item)),
    [items]
  );

  const display = messages.length > 0 ? messages : [EMPTY_HINT];
  const loop = [...display, ...display];

  return (
    <div className="dash-ticker" role="marquee" aria-live="polite">
      <div className="dash-ticker-label">
        <i className="fas fa-bolt" aria-hidden />
        <span>实时动态</span>
      </div>
      <div className="dash-ticker-track-wrap">
        <div className="dash-ticker-track">
          {loop.map((text, i) => (
            <span key={`${i}-${text.slice(0, 24)}`} className="dash-ticker-item">
              {text}
              <span className="dash-ticker-sep" aria-hidden>
                ·
              </span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
