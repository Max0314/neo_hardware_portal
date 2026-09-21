import type { DashboardStats } from '@/types/dashboard';
import './EfficiencyPanel.css';

export function EfficiencyPanel({ stats, loading }: { stats: DashboardStats | null; loading: boolean }) {
  const volume = (value: number | undefined) => loading ? '加载中' : value == null ? '—' : `${value} 次`;
  const cards = [
    ['累计净节省人工时间', '待标定', '不同功能分别核定，不统一乘固定小时数'],
    ['单任务净节省时间', '待标定', '需人工基线与 AI 后核验、修改时间'],
    ['已保存网表对比结果', volume(stats?.netlist_compare_count), '结果记录数，仍需排除重复任务'],
    ['已保存网表分析结果', volume(stats?.netlist_analyze_count), '结果记录数，非入口点击量'],
  ];
  return (
    <section className="hardware-efficiency" aria-labelledby="hardware-efficiency-title">
      <h2 id="hardware-efficiency-title">提效与价值</h2>
      <p>累计业务参考量 · 按网表对比、网表分析、BOM 检查、原理图审核分别衡量</p>
      <div className="hardware-efficiency-grid">
        {cards.map(([label, value, note]) => <div key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>)}
      </div>
      <p role="status">{loading ? '正在读取业务量…' : !stats ? '业务量读取失败，请刷新重试；未将失败数据计为 0。' : '时间基线待标定；已有业务量仅作参考，不等同于已确认节省时间。'}</p>
      <details><summary>计算口径与待补数据</summary>
        <p>各功能净节时 = 去重有效任务数 × 同类任务平均净节时；净节时需扣除 AI 后人工整理、核验与修改。当前结果记录尚未按业务任务去重，不用于直接计算节时。</p>
        <p>BOM 的 INFO 累计是快照上报量，入口使用次数是点击量，都不能当作完成任务或确认缺陷。BOM、原理图需先确认有效任务口径，再补传统处理时间与 AI 后人工时间。</p>
      </details>
    </section>
  );
}
