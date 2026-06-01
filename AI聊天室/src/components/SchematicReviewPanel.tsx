/**
 * 原理图 AI 审核 — 五步工作流面板（Step1-4 核心 + Step5 开放指引）
 */
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import { trackNeoPoints } from '@/utils/neoPoints';
import {
  SCHEMATIC_WORKFLOW_STEPS,
  buildCleanedNetlistFromAnalysis,
  collectAiChecksFromAggregated,
  hasSchematicPointsAwarded,
  markSchematicPointsAwarded,
  getDispositionStorageKey,
  loadCheckDispositions,
  saveCheckDispositions,
  formatDispositionForReport,
  requiresUserDisposition,
  type SchematicWorkflowTab,
  type SchematicCheckDisposition,
  type SchematicCheckDispositionMap,
} from '@/utils/schematicReview';
import type { AIReviewEntry } from './NetlistResultsPanel';
import { SchematicReviewCheckCard } from './SchematicReviewCheckCard';
import { SchematicReviewHistoryModal } from './SchematicReviewHistoryModal';
import {
  saveSchematicReviewHistory,
  type SchematicReviewHistoryRecord,
} from '@/utils/schematicReviewHistory';

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export interface SchematicReviewPanelProps {
  selectedResultId: string | null;
  onResultSelected?: (id: string, type: 'analysis') => void;
  aiReviewEntries?: AIReviewEntry[];
  aggregatedReviewSummary?: any;
  cleanedNetlistText: string;
  onCleanedNetlistChange: (text: string) => void;
  cleanConfirmed: boolean;
  onCleanConfirmed: (confirmed: boolean) => void;
  reviewExported: boolean;
  onReviewExported: () => void;
  onRunAiReview: (payload: { prompt: string; netlist: string }) => void;
  aiReviewRunning?: boolean;
  aiReviewRound?: number;
  onOpenChat?: () => void;
  canManagePrompt?: boolean;
  onOpenPromptSettings?: () => void;
  reviewPrompt: string;
  defaultAiName?: string;
  historyViewMode?: boolean;
  viewingHistoryTitle?: string | null;
  historyDispositions?: SchematicCheckDispositionMap;
  onApplyHistoryRecord?: (record: SchematicReviewHistoryRecord) => void;
  onStartNewReview?: () => void;
}

export const SchematicReviewPanel: React.FC<SchematicReviewPanelProps> = ({
  selectedResultId,
  onResultSelected,
  aiReviewEntries = [],
  aggregatedReviewSummary,
  cleanedNetlistText,
  onCleanedNetlistChange,
  cleanConfirmed,
  onCleanConfirmed,
  reviewExported,
  onReviewExported,
  onRunAiReview,
  aiReviewRunning = false,
  aiReviewRound = 0,
  onOpenChat,
  canManagePrompt = false,
  onOpenPromptSettings,
  reviewPrompt,
  defaultAiName = '百炼-deepseekV4',
  historyViewMode = false,
  viewingHistoryTitle = null,
  historyDispositions = {},
  onApplyHistoryRecord,
  onStartNewReview,
}) => {
  const [activeTab, setActiveTab] = useState<SchematicWorkflowTab>('import');
  const reviewAutoAdvancedRef = React.useRef(false);
  const historySavedRef = React.useRef<string | null>(null);
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [analysisData, setAnalysisData] = useState<any>(null);
  const [netlist, setNetlist] = useState('');
  const [netlistName, setNetlistName] = useState('网表');
  const [importLoading, setImportLoading] = useState(false);
  const [exportToast, setExportToast] = useState<string | null>(null);
  const [checkDispositions, setCheckDispositions] = useState<SchematicCheckDispositionMap>({});
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const dispositionStorageKey = useMemo(
    () => getDispositionStorageKey(selectedResultId, aggregatedReviewSummary?.aggregatedAt),
    [selectedResultId, aggregatedReviewSummary?.aggregatedAt]
  );

  useEffect(() => {
    if (historyViewMode) return;
    if (!aggregatedReviewSummary) {
      setCheckDispositions({});
      return;
    }
    setCheckDispositions(loadCheckDispositions(dispositionStorageKey));
  }, [aggregatedReviewSummary, dispositionStorageKey, historyViewMode]);

  const effectiveDispositions = historyViewMode ? historyDispositions : checkDispositions;

  const handleDispositionChange = useCallback(
    (checkId: string, disposition: SchematicCheckDisposition, note?: string) => {
      setCheckDispositions((prev) => {
        const next: SchematicCheckDispositionMap = {
          ...prev,
          [checkId]: {
            disposition,
            note: note?.trim() || undefined,
            updatedAt: new Date().toISOString(),
          },
        };
        saveCheckDispositions(dispositionStorageKey, next);
        return next;
      });
    },
    [dispositionStorageKey]
  );

  useEffect(() => {
    if (selectedResultId) {
      axios.get(apiUrl(`/api/netlist/result/${selectedResultId}`)).then((res) => {
        if (res.data.success && res.data.data?.type === 'analysis') {
          setAnalysisData(res.data.data.result);
        }
      }).catch(() => {});
    }
  }, [selectedResultId]);

  useEffect(() => {
    if (analysisData && !cleanedNetlistText.trim()) {
      onCleanedNetlistChange(buildCleanedNetlistFromAnalysis(analysisData, selectedResultId));
    }
  }, [analysisData, cleanedNetlistText, onCleanedNetlistChange, selectedResultId]);

  const stepDone = useMemo(() => ({
    import: !!analysisData && !!selectedResultId,
    clean: cleanConfirmed && !!cleanedNetlistText.trim(),
    review: aiReviewEntries.length > 0 && !!aggregatedReviewSummary,
    export: reviewExported,
    chat: reviewExported,
  }), [analysisData, selectedResultId, cleanConfirmed, cleanedNetlistText, aiReviewEntries.length, aggregatedReviewSummary, reviewExported]);

  const workflowProgress = useMemo(
    () =>
      SCHEMATIC_WORKFLOW_STEPS.map((meta) => ({
        ...meta,
        done:
          meta.trackCompletion === false
            ? reviewExported
            : stepDone[meta.id as keyof typeof stepDone] ?? false,
      })),
    [stepDone, reviewExported]
  );

  useEffect(() => {
    if (aiReviewRunning) {
      setActiveTab('review');
    }
  }, [aiReviewRunning]);

  useEffect(() => {
    if (aggregatedReviewSummary && cleanConfirmed && !reviewAutoAdvancedRef.current) {
      reviewAutoAdvancedRef.current = true;
      setActiveTab('export');
    }
  }, [aggregatedReviewSummary, cleanConfirmed]);

  const aiChecks = useMemo(
    () => collectAiChecksFromAggregated(aggregatedReviewSummary),
    [aggregatedReviewSummary]
  );

  const statusCounts = useMemo(() => {
    let pass = 0;
    let warning = 0;
    let info = 0;
    for (const c of aiChecks) {
      const s = c.status.toUpperCase();
      if (s === 'PASS') pass++;
      else if (s === 'WARNING' || s === 'FAIL') warning++;
      else info++;
    }
    return { pass, warning, info };
  }, [aiChecks]);

  const pendingDispositionCount = useMemo(() => {
    return aiChecks.filter(
      (c) => requiresUserDisposition(c.status) && !effectiveDispositions[c.checkId]
    ).length;
  }, [aiChecks, effectiveDispositions]);

  const handleAnalyze = async () => {
    if (!netlist.trim()) {
      alert('请提供网表内容');
      return;
    }
    setImportLoading(true);
    try {
      const response = await axios.post(apiUrl('/api/netlist/analyze'), {
        netlist,
        netlist_name: netlistName,
      });
      if (response.data.success && response.data.result_id) {
        const resultId = response.data.result_id;
        const analysisResult = response.data.result;
        if (analysisResult) {
          setAnalysisData(analysisResult);
          onResultSelected?.(resultId, 'analysis');
          onCleanConfirmed(false);
          onCleanedNetlistChange(
            buildCleanedNetlistFromAnalysis(
              analysisResult,
              resultId,
              response.data.formatted_markdown
            )
          );
          setActiveTab('clean');
          return;
        }
        const resultResponse = await axios.get(apiUrl(`/api/netlist/result/${resultId}`));
        if (resultResponse.data.success) {
          setAnalysisData(resultResponse.data.data.result);
          onResultSelected?.(resultId, 'analysis');
          onCleanConfirmed(false);
          onCleanedNetlistChange(
            buildCleanedNetlistFromAnalysis(
              resultResponse.data.data.result,
              resultId,
              resultResponse.data.formatted_markdown
            )
          );
          setActiveTab('clean');
        }
      } else {
        alert(`解析失败: ${response.data.error || '未知错误'}`);
      }
    } catch (e: any) {
      alert(`解析失败: ${e.response?.data?.error || e.message}`);
    } finally {
      setImportLoading(false);
    }
  };

  const handleFileUpload = (file: File) => {
    const reader = new FileReader();
    reader.onload = (ev) => {
      const content = (ev.target?.result as string) || '';
      setNetlist(content);
      setNetlistName(file.name.replace(/\.(asc|txt)$/i, ''));
    };
    reader.readAsText(file, 'UTF-8');
  };

  const handleExportReview = useCallback(() => {
    if (!aggregatedReviewSummary) {
      alert('请先完成 AI 评审并生成报告');
      return;
    }
    if (pendingDispositionCount > 0) {
      const ok = window.confirm(
        `仍有 ${pendingDispositionCount} 项 WARNING/INFO 未处置，是否仍要导出？\n建议先完成「待定 / 已修复 / 忽略并备注」后再导出。`
      );
      if (!ok) return;
    }
    try {
      const lines: string[] = [];
      lines.push('<!DOCTYPE html><html><head><meta charSet="utf-8" />');
      lines.push('<title>原理图AI审核报告</title>');
      lines.push(
        '<style>body{font-family:sans-serif;font-size:14px;padding:24px;line-height:1.5;}' +
          'h1,h2{margin:12px 0;} .item{margin:12px 0;padding:12px;border-radius:8px;border:1px solid #e5e7eb;}' +
          '.tag{display:inline-block;padding:2px 8px;border-radius:4px;margin-right:6px;font-size:11px;font-weight:bold;}' +
          '.pass{background:#dcfce7;color:#166534;border:1px solid #86efac;}' +
          '.warn{background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;}' +
          '.info{background:#e0f2fe;color:#075985;border:1px solid #7dd3fc;}' +
          '.disp{margin-top:8px;padding:8px;background:#f9fafb;border-radius:6px;font-size:13px;}' +
          '.disp-label{color:#6b7280;margin-right:4px;}</style></head><body>'
      );
      lines.push('<h1>原理图 AI 审核报告</h1>');
      lines.push(`<p>导出时间：${new Date().toLocaleString('zh-CN')}</p>`);
      lines.push(
        `<p>PASS: ${statusCounts.pass} · WARNING: ${statusCounts.warning} · INFO: ${statusCounts.info}</p>`
      );
      lines.push('<h2>检查项明细</h2>');
      for (const c of aiChecks) {
        const s = c.status.toUpperCase();
        const cls = s === 'PASS' ? 'pass' : s === 'INFO' ? 'info' : 'warn';
        const disp = formatDispositionForReport(effectiveDispositions[c.checkId]);
        lines.push('<div class="item">');
        lines.push(
          `<div><span class="tag ${cls}">${c.status}</span><strong>${escapeHtml(c.title)}</strong></div>`
        );
        if (c.description) {
          lines.push(`<div style="margin-top:6px;color:#374151;">${escapeHtml(c.description)}</div>`);
        }
        if (requiresUserDisposition(c.status)) {
          lines.push(
            `<div class="disp"><span class="disp-label">人工处置：</span>${escapeHtml(disp)}</div>`
          );
        }
        lines.push('</div>');
      }
      lines.push('</body></html>');
      const win = window.open('', '_blank');
      if (!win) {
        alert('无法打开打印窗口，请检查浏览器弹窗设置');
        return;
      }
      win.document.write(lines.join('\n'));
      win.document.close();
      win.focus();
      win.print();

      const rid = selectedResultId || 'session';
      if (!historyViewMode) {
        if (!hasSchematicPointsAwarded(rid)) {
          trackNeoPoints('schematic_review_export');
          markSchematicPointsAwarded(rid);
        }
        onReviewExported();

        const saveKey = `${selectedResultId || 'session'}::${aggregatedReviewSummary?.aggregatedAt || 't'}`;
        if (historySavedRef.current !== saveKey) {
          historySavedRef.current = saveKey;
          void saveSchematicReviewHistory({
            title: netlistName || '原理图审核',
            netlist_name: netlistName || '网表',
            netlist_result_id: selectedResultId,
            summary: statusCounts,
            aggregated_review_summary: aggregatedReviewSummary,
            ai_review_entries: aiReviewEntries,
            cleaned_netlist_text: cleanedNetlistText,
            check_dispositions: effectiveDispositions,
            default_ai_name: defaultAiName,
          }).catch((err) => console.warn('保存评审历史失败', err));
        }

        setExportToast('评审报告已导出，积分 +1；已保存至历史记录');
      } else {
        setExportToast('历史报告已导出');
      }
      window.setTimeout(() => setExportToast(null), 6000);
    } catch (e) {
      console.error(e);
      alert('导出失败');
    }
  }, [
    aggregatedReviewSummary,
    aiChecks,
    statusCounts,
    selectedResultId,
    onReviewExported,
    effectiveDispositions,
    pendingDispositionCount,
    aiReviewEntries,
    cleanedNetlistText,
    defaultAiName,
    netlistName,
    historyViewMode,
  ]);

  useEffect(() => {
    if (historyViewMode && aggregatedReviewSummary) {
      setActiveTab('export');
    }
  }, [historyViewMode, aggregatedReviewSummary]);

  const renderProgressBar = () => (
    <div className="rounded-xl border border-amber-200/80 bg-gradient-to-r from-amber-50/90 to-yellow-50/60 px-3 py-2.5 flex-shrink-0">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="text-[11px] font-semibold text-amber-900">
          原理图 AI 审核流程（Step 1–4 完成即闭环；Step 5 导出后可选）
        </div>
        <button
          type="button"
          onClick={() => setShowHistoryModal(true)}
          className="text-[11px] px-2 py-1 rounded-lg border border-sky-300 bg-white text-sky-800 hover:bg-sky-50 font-medium shrink-0"
        >
          历史记录
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {workflowProgress.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => {
              if (s.external && s.done) {
                onOpenChat?.();
                return;
              }
              if (s.tab) setActiveTab(s.tab);
            }}
            className={`text-[11px] px-2 py-1 rounded-lg border font-medium transition ${
              s.done
                ? 'border-emerald-500 bg-emerald-50 text-emerald-800 shadow-sm'
                : s.trackCompletion === false
                  ? 'border-amber-200 bg-amber-50/80 text-amber-900 hover:bg-amber-50'
                  : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
            }`}
          >
            第{s.order}步 {s.label}
            {s.done ? ' ✓' : s.trackCompletion === false ? ' ○' : ''}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col h-full bg-white text-xs">
      <div className="flex-shrink-0 p-3 border-b border-sky-100 bg-gradient-to-r from-sky-50 to-cyan-50 space-y-2">
        {renderProgressBar()}
        {historyViewMode && viewingHistoryTitle && (
          <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-[11px] text-sky-900 flex items-center justify-between gap-2 flex-wrap">
            <span>
              正在查看历史记录：<strong>{viewingHistoryTitle}</strong>（只读）
            </span>
            {onStartNewReview && (
              <button
                type="button"
                onClick={onStartNewReview}
                className="px-2 py-1 rounded bg-white border border-sky-300 text-sky-800 hover:bg-sky-100"
              >
                开始新评审
              </button>
            )}
          </div>
        )}
        {exportToast && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-emerald-900 text-[11px]">
            {exportToast}
          </div>
        )}
        {!reviewExported && (
          <p className="text-[11px] text-gray-500">
            Step 3 点击「发送 AI 评审」后将展开左侧 AI 聊天栏（只读展示评审过程）；完成 Step 4 导出报告后可输入对话，本次审核可获得 1 积分。
          </p>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {!historyViewMode && activeTab === 'import' && (
          <div className="space-y-3">
            <p className="text-gray-500">
              请粘贴 PADS Layout 导出的 ASCII 网表（含 <code>*PART*</code>、<code>*NET*</code>、<code>*SIGNAL*</code> 段），或导入 <strong>.txt</strong> / <strong>.asc</strong> 文件，点击「开始解析」。
            </p>
            <div className="border rounded-lg p-3 bg-gray-50">
              <div className="flex justify-between items-center mb-2 gap-2 flex-wrap">
                <label className="font-semibold">网表内容</label>
                <div className="flex gap-2 items-center">
                  <input
                    type="text"
                    value={netlistName}
                    onChange={(e) => setNetlistName(e.target.value)}
                    className="px-2 py-1 border rounded w-28"
                    placeholder="网表名称"
                  />
                  <input
                    type="file"
                    ref={fileInputRef}
                    accept=".txt,.asc"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) handleFileUpload(f);
                      e.target.value = '';
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="px-2 py-1 bg-blue-500 text-white rounded hover:bg-blue-600"
                  >
                    导入文件
                  </button>
                </div>
              </div>
              <textarea
                value={netlist}
                onChange={(e) => setNetlist(e.target.value)}
                placeholder="在此粘贴网表…"
                className="w-full h-40 p-2 border rounded font-mono text-[11px] resize-y"
              />
              <div className="flex justify-end gap-2 mt-2">
                <button
                  type="button"
                  onClick={() => { setNetlist(''); setAnalysisData(null); }}
                  className="px-3 py-1.5 bg-gray-500 text-white rounded"
                >
                  清空
                </button>
                <button
                  type="button"
                  disabled={importLoading || !netlist.trim()}
                  onClick={handleAnalyze}
                  className="px-3 py-1.5 bg-blue-600 text-white rounded disabled:bg-gray-400"
                >
                  {importLoading ? '解析中…' : '开始解析'}
                </button>
              </div>
            </div>
            {analysisData && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3 space-y-2">
                <div className="font-semibold text-emerald-800">解析完成（PADS *PART* / *NET* / ATTRIBUTE VALUES）</div>
                <div className="text-sm text-gray-700 grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <span>元件 <strong>{analysisData.summary?.total_components ?? 0}</strong></span>
                  <span>网络 <strong>{analysisData.summary?.total_nets ?? analysisData.nets?.length ?? 0}</strong></span>
                  <span>电源网络 <strong>{(analysisData.summary?.power_nets || []).length}</strong></span>
                  <span>差分对 <strong>{(analysisData.summary?.differential_pairs || []).length}</strong></span>
                </div>
                {(analysisData.summary?.total_nets ?? 0) === 0 && (analysisData.nets?.length ?? 0) === 0 && (
                  <p className="text-amber-800 text-xs">
                    未解析到网络：请确认网表包含 <code>*NET*</code> 与 <code>*SIGNAL*</code> 段。
                  </p>
                )}
                {(analysisData.summary?.power_nets || []).length > 0 && (
                  <p className="text-xs text-gray-600">
                    电源：{(analysisData.summary.power_nets as string[]).join('、')}
                  </p>
                )}
                <button type="button" className="text-blue-600 underline text-sm" onClick={() => setActiveTab('clean')}>
                  进入 Step 2 查看完整网表分析 →
                </button>
              </div>
            )}
          </div>
        )}

        {!historyViewMode && activeTab === 'clean' && (
          <div className="space-y-3">
            <p className="text-gray-500">
              系统按 PADS 网表结构（*PART* 元件、*NET* 网络、ATTRIBUTE VALUES 属性）解析后生成完整分析报告，请确认或编辑后供 Step 3 AI 评审使用。
            </p>
            {!analysisData ? (
              <p className="text-amber-700">请先在 Step 1 完成网表解析。</p>
            ) : (
              <>
                <textarea
                  value={cleanedNetlistText}
                  onChange={(e) => {
                    onCleanConfirmed(false);
                    onCleanedNetlistChange(e.target.value);
                  }}
                  className="w-full h-64 p-2 border rounded font-mono text-[11px]"
                />
                <div className="flex gap-2 flex-wrap">
                  <button
                    type="button"
                    className="px-3 py-1.5 bg-gray-100 border rounded hover:bg-gray-200"
                    onClick={() => onCleanedNetlistChange(buildCleanedNetlistFromAnalysis(analysisData, selectedResultId))}
                  >
                    重新生成
                  </button>
                  <button
                    type="button"
                    className="px-3 py-1.5 bg-emerald-600 text-white rounded hover:bg-emerald-700"
                    disabled={!cleanedNetlistText.trim()}
                    onClick={() => {
                      onCleanConfirmed(true);
                      setActiveTab('review');
                    }}
                  >
                    确认清洗结果
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {!historyViewMode && activeTab === 'review' && (
          <div className="space-y-3">
            <p className="text-gray-500">组合评审提示词与清洗网表，发送给已选 AI 模型，自动解析 JSON 并生成报告。</p>
            {!cleanConfirmed ? (
              <p className="text-amber-700">请先在 Step 2 确认网表清洗结果。</p>
            ) : (
              <>
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-[11px] text-gray-600">
                  {reviewExported ? (
                    <>导出已完成，可在左侧聊天栏自由选择 AI 伙伴继续讨论。</>
                  ) : (
                    <>
                      评审流程固定使用系统默认模型：<strong>{defaultAiName}</strong>
                      （导出报告后可自由选择）。
                    </>
                  )}
                  {canManagePrompt && onOpenPromptSettings && (
                    <button
                      type="button"
                      onClick={onOpenPromptSettings}
                      className="ml-2 text-sky-700 underline hover:text-sky-900"
                    >
                      打开提示词配置
                    </button>
                  )}
                </div>
                <button
                  type="button"
                  disabled={aiReviewRunning || !reviewPrompt.trim()}
                  onClick={() => onRunAiReview({ prompt: reviewPrompt, netlist: cleanedNetlistText })}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400"
                >
                  {aiReviewRunning
                    ? aiReviewRound > 1
                      ? `AI 评审中（第 ${aiReviewRound} 轮续写）…`
                      : 'AI 评审中…'
                    : '发送 AI 评审'}
                </button>
                {aggregatedReviewSummary && (
                  <div className="space-y-3 mt-4">
                    <div className="flex gap-3 text-[11px] font-medium">
                      <span className="text-emerald-700">PASS {statusCounts.pass}</span>
                      <span className="text-red-700">WARNING {statusCounts.warning}</span>
                      <span className="text-sky-700">INFO {statusCounts.info}</span>
                    </div>
                    {pendingDispositionCount > 0 && (
                      <p className="text-[11px] text-red-700">
                        还有 {pendingDispositionCount} 项 WARNING/INFO 待人工处置
                      </p>
                    )}
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                      {aiChecks.map((c) => (
                        <SchematicReviewCheckCard
                          key={c.checkId}
                          check={c}
                          dispositionRecord={effectiveDispositions[c.checkId]}
                          onDispositionChange={handleDispositionChange}
                          readOnly={historyViewMode}
                        />
                      ))}
                    </div>
                    <button type="button" className="text-blue-600 underline" onClick={() => setActiveTab('export')}>
                      进入 Step 4 报告导出 →
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {(historyViewMode || activeTab === 'export') && (
          <div className="space-y-3">
            {!historyViewMode && (
              <p className="text-gray-500">
                预览评审报告并导出 PDF；导出成功即完成本次审核（+1 积分）。
              </p>
            )}
            {historyViewMode && (
              <p className="text-gray-500">历史记录预览（可再次导出 PDF）。</p>
            )}
            {!aggregatedReviewSummary ? (
              <p className="text-amber-700">请先在 Step 3 完成 AI 评审。</p>
            ) : (
              <>
                {pendingDispositionCount > 0 && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-800">
                    还有 {pendingDispositionCount} 项 WARNING/INFO 未处置；导出前请为每项选择「待定 / 已修复 / 忽略并备注」。
                  </div>
                )}
                <div className="border rounded-lg p-3 bg-gray-50 max-h-[28rem] overflow-y-auto space-y-2">
                  {aiChecks.map((c) => (
                    <SchematicReviewCheckCard
                      key={c.checkId}
                      check={c}
                      dispositionRecord={effectiveDispositions[c.checkId]}
                      onDispositionChange={handleDispositionChange}
                      compact
                      readOnly={historyViewMode}
                    />
                  ))}
                </div>
                <button
                  type="button"
                  onClick={handleExportReview}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  {historyViewMode ? '再次导出 PDF' : '导出评审结果（PDF）'}
                </button>
                {reviewExported && (
                  <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sky-900">
                    审核已完成。如需进一步讨论，请点击进度条「第5步 与AI对话」或左侧聊天区（可选）。
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <SchematicReviewHistoryModal
        isOpen={showHistoryModal}
        onClose={() => setShowHistoryModal(false)}
        onSelect={(record) => {
          onApplyHistoryRecord?.(record);
          reviewAutoAdvancedRef.current = true;
          setActiveTab('export');
        }}
      />
    </div>
  );
};
