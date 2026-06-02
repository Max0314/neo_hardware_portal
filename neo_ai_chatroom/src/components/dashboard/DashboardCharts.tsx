import { useMemo } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { DashboardStats } from '@/types/dashboard';
import { filterFeatureBreakdown, labelFeature } from './dashboardLabels';

const COLORS = ['#3899C9', '#2C8F8B', '#567F9F', '#9E6D5E', '#1E749C', '#59A5D1', '#C05A5A'];

interface DashboardChartsProps {
  stats: DashboardStats | null;
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="dash-chart-empty">
      <span>{label}</span>
    </div>
  );
}

const tooltipStyle = {
  fontSize: 12,
  borderRadius: 8,
  border: '1px solid #C1D9E8',
};

export function DashboardCharts({ stats }: DashboardChartsProps) {
  const weeklyTrend = useMemo(() => {
    const use = stats?.weekly_component_use ?? [];
    const net = stats?.weekly_netlist_counts ?? [];
    const len = Math.max(use.length, net.length, 1);
    return Array.from({ length: len }, (_, i) => ({
      week: use[i]?.week_label ?? net[i]?.week_label ?? `W${i + 1}`,
      componentUse: use[i]?.value ?? 0,
      netlistOps: net[i]?.value ?? 0,
    }));
  }, [stats?.weekly_component_use, stats?.weekly_netlist_counts]);

  const featurePie = useMemo(() => {
    const breakdown = filterFeatureBreakdown(stats?.feature_use_breakdown ?? {});
    return Object.entries(breakdown)
      .map(([key, value]) => ({ name: labelFeature(key), value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 8);
  }, [stats?.feature_use_breakdown]);

  const weeklyBom = useMemo(
    () =>
      (stats?.weekly_bom_defect_info ?? []).map((p) => ({
        week: p.week_label,
        info: p.value,
      })),
    [stats?.weekly_bom_defect_info]
  );

  const monthlyDensity = useMemo(
    () =>
      (stats?.monthly_defect_density ?? []).map((p) => ({
        month: p.label.slice(2),
        density: p.value,
      })),
    [stats?.monthly_defect_density]
  );

  const hasWeekly = weeklyTrend.some((d) => d.componentUse > 0 || d.netlistOps > 0);
  const hasPie = featurePie.length > 0;
  const hasBom = weeklyBom.some((d) => d.info > 0);
  const hasDensity = monthlyDensity.length > 0;

  return (
    <div className="dash-charts-grid">
      <div className="dash-chart-card">
        <h3 className="dash-chart-title">
          <i className="fas fa-chart-line" /> 近 4 周使用与网表趋势
        </h3>
        <div className="dash-chart-body">
          {hasWeekly ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={weeklyTrend} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E8F0F6" />
                <XAxis dataKey="week" tick={{ fontSize: 11, fill: '#4D748C' }} />
                <YAxis tick={{ fontSize: 11, fill: '#4D748C' }} allowDecimals={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line
                  type="monotone"
                  dataKey="componentUse"
                  name="组件使用"
                  stroke="#3899C9"
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                  activeDot={{ r: 5 }}
                />
                <Line
                  type="monotone"
                  dataKey="netlistOps"
                  name="网表操作"
                  stroke="#567F9F"
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart label="暂无周度趋势数据" />
          )}
        </div>
      </div>

      <div className="dash-chart-card">
        <h3 className="dash-chart-title">
          <i className="fas fa-chart-pie" /> 功能入口占比
        </h3>
        <div className="dash-chart-body">
          {hasPie ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={featurePie}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={52}
                  outerRadius={88}
                  paddingAngle={2}
                  label={({ name, percent }) =>
                    `${name} ${((percent ?? 0) * 100).toFixed(0)}%`
                  }
                  labelLine={{ stroke: '#4D748C', strokeWidth: 1 }}
                >
                  {featurePie.map((_, i) => (
                    <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart label="暂无功能使用分布" />
          )}
        </div>
      </div>

      <div className="dash-chart-card">
        <h3 className="dash-chart-title">
          <i className="fas fa-chart-column" /> 近 4 周 BOM INFO 上报
        </h3>
        <div className="dash-chart-body">
          {hasBom ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={weeklyBom} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E8F0F6" vertical={false} />
                <XAxis dataKey="week" tick={{ fontSize: 11, fill: '#4D748C' }} />
                <YAxis tick={{ fontSize: 11, fill: '#4D748C' }} allowDecimals={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="info" name="INFO 条数" fill="#2C8F8B" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart label="暂无 BOM 上报数据" />
          )}
        </div>
      </div>

      <div className="dash-chart-card">
        <h3 className="dash-chart-title">
          <i className="fas fa-chart-area" /> 近 6 月缺陷密度
        </h3>
        <div className="dash-chart-body">
          {hasDensity ? (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={monthlyDensity} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="densityGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#C05A5A" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#C05A5A" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#E8F0F6" />
                <XAxis dataKey="month" tick={{ fontSize: 11, fill: '#4D748C' }} />
                <YAxis tick={{ fontSize: 11, fill: '#4D748C' }} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(v) => [
                    typeof v === 'number' ? v.toFixed(2) : String(v ?? ''),
                    '密度',
                  ]}
                />
                <Area
                  type="monotone"
                  dataKey="density"
                  name="缺陷密度"
                  stroke="#C05A5A"
                  fill="url(#densityGrad)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart label="暂无月度密度数据" />
          )}
        </div>
      </div>
    </div>
  );
}
