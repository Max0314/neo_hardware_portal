import React, { useCallback, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import { trackNeoPoints } from '@/utils/neoPoints';
import { NetlistResultModal } from '../components/NetlistResultModal';

const LIST_COPY_LIMIT = 400;

function appendIdList(lines: string[], title: string, items: string[] | undefined) {
  lines.push(title);
  if (!items?.length) {
    lines.push('(无)');
    lines.push('');
    return;
  }
  const slice = items.slice(0, LIST_COPY_LIMIT);
  slice.forEach((id) => lines.push(id));
  if (items.length > slice.length) {
    lines.push(`… 另有 ${items.length - slice.length} 项未写入剪贴板（共 ${items.length} 项）`);
  }
  lines.push('');
}

function buildComparisonReportText(
  name1: string,
  name2: string,
  result: Record<string, unknown>,
  resultId?: string
): string {
  const comp1 = (result.components1 as Record<string, unknown>) || {};
  const comp2 = (result.components2 as Record<string, unknown>) || {};
  const nets1 = (result.nets1 as Record<string, unknown>) || {};
  const nets2 = (result.nets2 as Record<string, unknown>) || {};
  const lines: string[] = [];
  lines.push('网表对比报告');
  lines.push(`生成时间: ${new Date().toLocaleString('zh-CN')}`);
  if (resultId) lines.push(`结果ID: ${resultId}`);
  lines.push('');
  lines.push(`「${name1}」 ↔ 「${name2}」`);
  lines.push('');
  lines.push('--- 概览 ---');
  lines.push(`网表1 元件数: ${Object.keys(comp1).length}，网络数: ${Object.keys(nets1).length}`);
  lines.push(`网表2 元件数: ${Object.keys(comp2).length}，网络数: ${Object.keys(nets2).length}`);
  lines.push(`新增元件: ${(result.added_components as string[])?.length ?? 0}`);
  lines.push(`移除元件: ${(result.removed_components as string[])?.length ?? 0}`);
  lines.push(`修改元件: ${(result.changed_components as string[])?.length ?? 0}`);
  lines.push(`新增网络: ${(result.added_nets as string[])?.length ?? 0}`);
  lines.push(`移除网络: ${(result.removed_nets as string[])?.length ?? 0}`);
  lines.push(`修改网络: ${(result.changed_nets as string[])?.length ?? 0}`);
  lines.push('');
  appendIdList(lines, '--- 新增元件 ---', result.added_components as string[]);
  appendIdList(lines, '--- 移除元件 ---', result.removed_components as string[]);
  appendIdList(lines, '--- 修改元件 ---', result.changed_components as string[]);
  appendIdList(lines, '--- 新增网络 ---', result.added_nets as string[]);
  appendIdList(lines, '--- 移除网络 ---', result.removed_nets as string[]);
  appendIdList(lines, '--- 修改网络 ---', result.changed_nets as string[]);
  lines.push('— 全文结束 —');
  return lines.join('\n');
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

export const NetlistComparePage: React.FC = () => {
  const navigate = useNavigate();
  const fileInput1Ref = useRef<HTMLInputElement>(null);
  const fileInput2Ref = useRef<HTMLInputElement>(null);

  const [netlist1, setNetlist1] = useState('');
  const [netlist2, setNetlist2] = useState('');
  const [netlist1Name, setNetlist1Name] = useState('网表 A');
  const [netlist2Name, setNetlist2Name] = useState('网表 B');
  const [loading, setLoading] = useState(false);
  const [comparisonResult, setComparisonResult] = useState<Record<string, unknown> | null>(null);
  const [resultId, setResultId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [copyHint, setCopyHint] = useState<string | null>(null);

  const handleFileUpload = useCallback(
    (file: File, setter: (content: string) => void, setName?: (name: string) => void) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const content = e.target?.result as string;
        setter(content);
        if (setName) {
          setName(file.name.replace(/\.(asc|txt)$/i, ''));
        }
      };
      reader.onerror = () => alert('文件读取失败');
      reader.readAsText(file, 'UTF-8');
    },
    []
  );

  const handleCompare = async () => {
    if (!netlist1.trim() || !netlist2.trim()) {
      alert('请同时在左右两侧填写或导入网表内容');
      return;
    }
    setLoading(true);
    setCopyHint(null);
    try {
      const response = await axios.post(apiUrl('/api/netlist/compare'), {
        netlist1,
        netlist2,
        netlist1_name: netlist1Name,
        netlist2_name: netlist2Name,
      });
      if (response.data.success) {
        setResultId(response.data.result_id ?? null);
        setComparisonResult(response.data.result ?? null);
        trackNeoPoints('compare_tool');
      } else {
        alert(`对比失败: ${response.data.error}`);
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } }; message?: string };
      console.error('对比失败:', error);
      alert(`对比失败: ${err.response?.data?.error || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setNetlist1('');
    setNetlist2('');
    setNetlist1Name('网表 A');
    setNetlist2Name('网表 B');
    setComparisonResult(null);
    setResultId(null);
    setCopyHint(null);
  };

  const handleCopyReport = async () => {
    if (!comparisonResult) return;
    const text = buildComparisonReportText(netlist1Name, netlist2Name, comparisonResult, resultId ?? undefined);
    const ok = await copyToClipboard(text);
    setCopyHint(ok ? '已复制对比报告到剪贴板' : '复制失败，请检查浏览器权限');
    window.setTimeout(() => setCopyHint(null), 2800);
  };

  const added = (comparisonResult?.added_components as string[])?.length ?? 0;
  const removed = (comparisonResult?.removed_components as string[])?.length ?? 0;
  const changed = (comparisonResult?.changed_components as string[])?.length ?? 0;
  const addedNets = (comparisonResult?.added_nets as string[])?.length ?? 0;
  const removedNets = (comparisonResult?.removed_nets as string[])?.length ?? 0;
  const changedNets = (comparisonResult?.changed_nets as string[])?.length ?? 0;

  return (
    <div
      className="h-screen w-screen flex flex-col overflow-hidden text-slate-800"
      style={{
        fontFamily: '"Inter", system-ui, sans-serif',
        background: 'linear-gradient(165deg, #e8f2f8 0%, #f4f6fb 42%, #eef3f9 100%)',
      }}
    >
      <header className="flex-shrink-0 flex items-center justify-between gap-4 px-5 py-3.5 border-b border-slate-200/80 bg-white/85 backdrop-blur-md shadow-sm">
        <div className="flex items-center gap-4 min-w-0">
          <Link
            to="/"
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100/90 transition-colors border border-transparent hover:border-slate-200"
          >
            <i className="fas fa-arrow-left" aria-hidden />
            <span>返回主页</span>
          </Link>
          <div className="h-8 w-px bg-slate-200 hidden sm:block" aria-hidden />
          <div className="min-w-0">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 truncate">
              <i className="fas fa-code-compare mr-2 text-sky-700" aria-hidden />
              网表对比
            </h1>
            <p className="text-xs text-slate-500 truncate hidden sm:block">
              左右对照编辑 PADS 网表（.asc / .txt），一键生成差异摘要
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {copyHint && (
            <span className="text-xs text-emerald-600 font-medium max-w-[min(200px,40vw)] truncate sm:max-w-[240px]" role="status">
              {copyHint}
            </span>
          )}
          <button
            type="button"
            onClick={handleClear}
            className="px-3 py-2 rounded-xl text-sm font-medium text-slate-600 bg-white border border-slate-200 hover:bg-slate-50 transition-colors"
          >
            清空
          </button>
          <button
            type="button"
            onClick={handleCopyReport}
            disabled={!comparisonResult}
            className="px-3 py-2 rounded-xl text-sm font-medium text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <i className="fas fa-copy mr-1.5" aria-hidden />
            复制报告
          </button>
          <button
            type="button"
            onClick={() => resultId && setModalOpen(true)}
            disabled={!resultId}
            className="hidden sm:inline-flex px-3 py-2 rounded-xl text-sm font-medium text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <i className="fas fa-table mr-1.5" aria-hidden />
            表格明细
          </button>
          <button
            type="button"
            onClick={handleCompare}
            disabled={loading || !netlist1.trim() || !netlist2.trim()}
            className="px-4 py-2 rounded-xl text-sm font-semibold text-white bg-gradient-to-r from-sky-600 to-cyan-700 hover:from-sky-500 hover:to-cyan-600 shadow-md shadow-sky-900/10 disabled:opacity-45 disabled:cursor-not-allowed disabled:shadow-none transition-all"
          >
            {loading ? (
              <>
                <i className="fas fa-circle-notch fa-spin mr-2" aria-hidden />
                对比中…
              </>
            ) : (
              <>
                <i className="fas fa-play mr-2" aria-hidden />
                开始对比
              </>
            )}
          </button>
        </div>
      </header>

      <div className="flex-1 flex flex-col min-h-0 p-4 gap-4">
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-0">
          {/* 左侧网表 */}
          <section className="flex flex-col min-h-0 rounded-2xl bg-white/95 border border-slate-200/90 shadow-sm shadow-slate-200/50 overflow-hidden">
            <div className="flex-shrink-0 flex flex-wrap items-center gap-2 px-4 py-3 border-b border-slate-100 bg-gradient-to-r from-sky-50/80 to-white">
              <span className="text-xs font-bold uppercase tracking-wider text-sky-800 bg-sky-100/90 px-2 py-0.5 rounded-md">
                左侧
              </span>
              <input
                type="text"
                value={netlist1Name}
                onChange={(e) => setNetlist1Name(e.target.value)}
                placeholder="网表名称"
                className="flex-1 min-w-[120px] px-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-sky-400/40 focus:border-sky-400 outline-none"
              />
              <input
                type="file"
                ref={fileInput1Ref}
                accept=".asc,.txt,text/plain"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file, setNetlist1, setNetlist1Name);
                  e.target.value = '';
                }}
              />
              <button
                type="button"
                onClick={() => fileInput1Ref.current?.click()}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
              >
                <i className="fas fa-file-import mr-1" aria-hidden />
                导入
              </button>
            </div>
            <textarea
              value={netlist1}
              onChange={(e) => setNetlist1(e.target.value)}
              placeholder="粘贴或导入第一份网表…"
              spellCheck={false}
              className="flex-1 min-h-[160px] w-full p-4 text-[13px] leading-relaxed font-mono text-slate-800 bg-slate-50/40 resize-none border-0 focus:ring-0 focus:outline-none"
            />
          </section>

          {/* 右侧网表 */}
          <section className="flex flex-col min-h-0 rounded-2xl bg-white/95 border border-slate-200/90 shadow-sm shadow-slate-200/50 overflow-hidden">
            <div className="flex-shrink-0 flex flex-wrap items-center gap-2 px-4 py-3 border-b border-slate-100 bg-gradient-to-r from-teal-50/80 to-white">
              <span className="text-xs font-bold uppercase tracking-wider text-teal-800 bg-teal-100/90 px-2 py-0.5 rounded-md">
                右侧
              </span>
              <input
                type="text"
                value={netlist2Name}
                onChange={(e) => setNetlist2Name(e.target.value)}
                placeholder="网表名称"
                className="flex-1 min-w-[120px] px-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:ring-2 focus:ring-teal-400/40 focus:border-teal-400 outline-none"
              />
              <input
                type="file"
                ref={fileInput2Ref}
                accept=".asc,.txt,text/plain"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file, setNetlist2, setNetlist2Name);
                  e.target.value = '';
                }}
              />
              <button
                type="button"
                onClick={() => fileInput2Ref.current?.click()}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
              >
                <i className="fas fa-file-import mr-1" aria-hidden />
                导入
              </button>
            </div>
            <textarea
              value={netlist2}
              onChange={(e) => setNetlist2(e.target.value)}
              placeholder="粘贴或导入第二份网表…"
              spellCheck={false}
              className="flex-1 min-h-[160px] w-full p-4 text-[13px] leading-relaxed font-mono text-slate-800 bg-slate-50/40 resize-none border-0 focus:ring-0 focus:outline-none"
            />
          </section>
        </div>

        {/* 对比摘要 */}
        <section className="flex-shrink-0 rounded-2xl bg-white/95 border border-slate-200/90 shadow-sm shadow-slate-200/40 overflow-hidden flex flex-col max-h-[min(40vh,320px)]">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-100 bg-slate-50/60">
            <h2 className="text-sm font-semibold text-slate-800">
              <i className="fas fa-chart-simple mr-2 text-slate-500" aria-hidden />
              对比摘要
            </h2>
            {comparisonResult && resultId && (
              <button
                type="button"
                onClick={() => setModalOpen(true)}
                className="text-xs font-medium text-sky-700 hover:text-sky-900"
              >
                打开完整表格 <i className="fas fa-external-link-alt ml-1" aria-hidden />
              </button>
            )}
          </div>
          <div className="p-4 overflow-y-auto min-h-[100px]">
            {!comparisonResult ? (
              <p className="text-sm text-slate-500 text-center py-6">
                在上方左右两侧填入两份网表后，点击「开始对比」查看元件与网络差异统计。
              </p>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2 justify-center sm:justify-start">
                  {[
                    { label: '新增元件', value: added, tone: 'sky' },
                    { label: '移除元件', value: removed, tone: 'rose' },
                    { label: '修改元件', value: changed, tone: 'amber' },
                    { label: '新增网络', value: addedNets, tone: 'emerald' },
                    { label: '移除网络', value: removedNets, tone: 'red' },
                    { label: '修改网络', value: changedNets, tone: 'orange' },
                  ].map((item) => (
                    <div
                      key={item.label}
                      className={`px-4 py-2.5 rounded-xl text-center min-w-[108px] border ${
                        item.tone === 'sky'
                          ? 'bg-sky-50 border-sky-100 text-sky-900'
                          : item.tone === 'rose'
                            ? 'bg-rose-50 border-rose-100 text-rose-900'
                            : item.tone === 'amber'
                              ? 'bg-amber-50 border-amber-100 text-amber-900'
                              : item.tone === 'emerald'
                                ? 'bg-emerald-50 border-emerald-100 text-emerald-900'
                                : item.tone === 'red'
                                  ? 'bg-red-50 border-red-100 text-red-900'
                                  : 'bg-orange-50 border-orange-100 text-orange-900'
                      }`}
                    >
                      <div className="text-2xl font-bold tabular-nums">{item.value}</div>
                      <div className="text-xs font-medium opacity-85">{item.label}</div>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-slate-500 text-center sm:text-left">
                  可使用「复制报告」导出文字摘要；复杂差异请用「表格明细」查看完整列表。
                  {resultId && (
                    <span className="block mt-1 font-mono text-[11px] text-slate-400">结果 ID：{resultId}</span>
                  )}
                </p>
                <div className="flex flex-wrap gap-2 justify-center sm:justify-start pb-1">
                  <button
                    type="button"
                    onClick={handleCopyReport}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-slate-900 text-white hover:bg-slate-800"
                  >
                    <i className="fas fa-copy" aria-hidden />
                    复制对比结果
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate('/meeting')}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                  >
                    <i className="fas fa-comments" aria-hidden />
                    进入 AI 工作室
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>
      </div>

      {resultId && (
        <NetlistResultModal
          isOpen={modalOpen}
          onClose={() => setModalOpen(false)}
          resultId={resultId}
          resultType="comparison"
        />
      )}
    </div>
  );
};
