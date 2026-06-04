/**
 * 网表分析结果面板
 * 显示在右侧，包含多个标签页
 */
import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import { printHtmlDocument, getPrintMessage } from '@/utils/externalOpen';
import { NetlistResultModal } from './NetlistResultModal';
import { SchematicReviewPanel } from './SchematicReviewPanel';
import { formatNetConnectionsFull } from '@/utils/schematicReview';

interface NetlistResult {
  id: string;
  type: 'comparison' | 'analysis';
  netlist1_name?: string;
  netlist2_name?: string;
  netlist_name?: string;
  created_at: string;
}

export interface AIReviewEntry {
  id: string;
  content: string;
  parsed: any;
  timestamp: Date;
  aiName: string;
}

interface NetlistResultsPanelProps {
  aiReviewRound?: number;
  selectedResultId: string | null;
  resultType: 'comparison' | 'analysis' | null;
  onResultSelected?: (id: string, type: 'comparison' | 'analysis') => void;
  /** 从聊天中收集的 AI 评审结果（网表分析/接口检查 JSON），在 AI评审 标签页中展示 */
  aiReviewEntries?: AIReviewEntry[];
  /** 硬件分析结果聚合（网表解析 + AI 评审），在 评审总结 标签页展示 */
  aggregatedReviewSummary?: any;
  onClearAggregatedSummary?: () => void;
  /** SOP 模式下为 true，右侧对比结果与解析结果区域禁止输入，仅可查看 */
  readOnly?: boolean;
  /** 原理图 AI 审核模式：五步工作流面板 */
  schematicMode?: boolean;
  cleanedNetlistText?: string;
  onCleanedNetlistChange?: (text: string) => void;
  cleanConfirmed?: boolean;
  onCleanConfirmed?: (confirmed: boolean) => void;
  reviewExported?: boolean;
  onReviewExported?: () => void;
  onRunAiReview?: (payload: { prompt: string; netlist: string }) => void;
  aiReviewRunning?: boolean;
  onOpenChat?: () => void;
  canManagePrompt?: boolean;
  onOpenPromptSettings?: () => void;
  defaultAiName?: string;
  reviewPrompt?: string;
  historyViewMode?: boolean;
  viewingHistoryTitle?: string | null;
  historyDispositions?: import('@/utils/schematicReview').SchematicCheckDispositionMap;
  onApplyHistoryRecord?: (record: import('@/utils/schematicReviewHistory').SchematicReviewHistoryRecord) => void;
  onStartNewReview?: () => void;
}

const ClassicNetlistResultsPanel: React.FC<NetlistResultsPanelProps> = ({
  selectedResultId,
  resultType,
  onResultSelected,
  aiReviewEntries = [],
  aggregatedReviewSummary,
  onClearAggregatedSummary,
  readOnly = false,
}) => {
  const [activeTab, setActiveTab] = useState<'analysis' | 'review' | 'summary' | 'checklist'>('analysis');
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);

  const prevReviewCountRef = useRef(0);
  useEffect(() => {
    const n = aiReviewEntries.length;
    if (n > prevReviewCountRef.current) {
      setActiveTab('review');
      prevReviewCountRef.current = n;
    } else {
      prevReviewCountRef.current = n;
    }
  }, [aiReviewEntries.length]);

  useEffect(() => {
    if (aggregatedReviewSummary) setActiveTab('summary');
  }, [aggregatedReviewSummary]);
  const [results, setResults] = useState<NetlistResult[]>([]);
  const [, setLoading] = useState(false);
  const [analysisData, setAnalysisData] = useState<any>(null);
  const [reviewData, setReviewData] = useState<any>(null);
  const [summaryData, setSummaryData] = useState<any>(null);
  const [checklistData, setChecklistData] = useState<any>(null);
  const [selectedDetailResult, setSelectedDetailResult] = useState<{id: string, type: 'comparison' | 'analysis'} | null>(null);

  // 加载结果列表
  useEffect(() => {
    loadResults();
  }, []);

  // 当结果ID变化时，刷新结果列表
  useEffect(() => {
    if (selectedResultId) {
      loadResults();
    }
  }, [selectedResultId]);

  // 当选中结果ID变化时，加载对应的数据（右侧栏不再展示对比类型）
  useEffect(() => {
    if (selectedResultId) {
      loadResultData(selectedResultId, resultType || 'analysis');
      if (resultType === 'analysis' || resultType === 'comparison') {
        setActiveTab('analysis');
      }
    }
  }, [selectedResultId, resultType]);

  const loadResults = async () => {
    setLoading(true);
    try {
      const response = await axios.get(apiUrl('/api/netlist/results'));
      if (response.data.success) {
        setResults(response.data.results || []);
      }
    } catch (error) {
      console.error('加载结果列表失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadResultData = async (resultId: string, _type: 'comparison' | 'analysis') => {
    try {
      const response = await axios.get(apiUrl(`/api/netlist/result/${resultId}`));
      if (response.data.success) {
        const data = response.data.data;
        if (data.type === 'comparison') {
          return;
        }
        if (data.type === 'analysis') {
          setAnalysisData(data.result);
          extractReviewData(data.result);
        }
      }
    } catch (error) {
      console.error('加载结果数据失败:', error);
    }
  };

  const extractReviewData = (analysisResult: any) => {
    // 提取AI评审结果（从分析结果中生成）
    if (analysisResult.analysis) {
      const reviewText = generateReviewText(analysisResult);
      setReviewData(reviewText);
    }
    
    // 提取评审总结（使用summary）
    if (analysisResult.summary) {
      setSummaryData(analysisResult.summary);
    }
    
    // 提取待检查确认项（从potential_issues生成）
    if (analysisResult.analysis?.potential_issues) {
      setChecklistData({
        issues: analysisResult.analysis.potential_issues || [],
        checklist: generateChecklist(analysisResult)
      });
    }
  };

  const generateReviewText = (analysisResult: any): string => {
    const summary = analysisResult.summary || {};
    const analysis = analysisResult.analysis || {};
    const issues = analysis.potential_issues || [];
    
    let review = `# 网表评审报告\n\n`;
    review += `## 总体概况\n`;
    review += `- 总元件数: ${summary.total_components || 0}\n`;
    review += `- 总网络数: ${summary.total_nets || 0}\n`;
    review += `- 电源网络: ${summary.power_nets?.length || 0} 个\n`;
    
    if (summary.component_types) {
      review += `## 元件类型分布\n`;
      Object.entries(summary.component_types).forEach(([type, count]) => {
        review += `- ${type}: ${count} 个\n`;
      });
      review += `\n`;
    }
    
    if (issues.length > 0) {
      review += `## 潜在问题\n`;
      issues.forEach((issue: any, idx: number) => {
        review += `${idx + 1}. [${issue.severity || 'medium'}] ${issue.description}\n`;
        if (issue.component) review += `   元件: ${issue.component}\n`;
        if (issue.net) review += `   网络: ${issue.net}\n`;
      });
    }
    
    return review;
  };

  const generateChecklist = (analysisResult: any): string[] => {
    const checklist: string[] = [];
    const summary = analysisResult.summary || {};
    const analysis = analysisResult.analysis || {};
    
    // 基础检查项
    checklist.push(`检查总元件数: ${summary.total_components || 0}`);
    checklist.push(`检查总网络数: ${summary.total_nets || 0}`);
    
    // 电源网络检查
    if (summary.power_nets && summary.power_nets.length > 0) {
      checklist.push(`检查电源网络连接: ${summary.power_nets.length} 个电源网络`);
    }
    
    
    // 潜在问题检查
    if (analysis.potential_issues && analysis.potential_issues.length > 0) {
      analysis.potential_issues.forEach((issue: any) => {
        checklist.push(`处理问题: ${issue.description}`);
      });
    }
    
    return checklist;
  };


  // 判断各功能是否完成
  const isAnalysisCompleted = !!analysisData;
  const isReviewCompleted = !!reviewData;
  const isSummaryCompleted = !!summaryData;
  const isChecklistCompleted = !!(checklistData && (checklistData.issues?.length > 0 || checklistData.checklist?.length > 0));

  // 获取标签页样式
  const getTabClassName = (tabName: string, isCompleted: boolean) => {
    const isActive = activeTab === tabName;
    if (isActive) {
      // 选中时：已完成保持绿色，未完成保持红色
      if (isCompleted) {
        return `px-4 py-3 font-semibold transition bg-white border-b-2 border-green-600 text-green-600`;
      } else {
        return `px-4 py-3 font-semibold transition bg-white border-b-2 border-red-600 text-red-600`;
      }
    } else {
      // 未选中时：已完成显示绿色，未完成显示红色
      if (isCompleted) {
        return `px-4 py-3 font-semibold transition text-green-600 hover:text-green-700 hover:bg-green-50`;
      } else {
        return `px-4 py-3 font-semibold transition text-red-400 hover:text-red-600 hover:bg-red-50`;
      }
    }
  };

  // 导出当前评审结果为 PDF（通过浏览器打印为 PDF 实现）
  const handleExportReview = async () => {
    try {
      const lines: string[] = [];
      lines.push('<!DOCTYPE html><html><head><meta charSet="utf-8" />');
      lines.push('<title>网表评审报告导出</title>');
      lines.push('<style>');
      lines.push('body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.6;padding:24px;}');
      lines.push('h1,h2,h3{margin:16px 0 8px;}');
      lines.push('table{border-collapse:collapse;width:100%;margin:8px 0;}');
      lines.push('th,td{border:1px solid #ddd;padding:4px 6px;font-size:12px;}');
      lines.push('th{background:#f3f4f6;}');
      lines.push('.section{margin-bottom:24px;}');
      lines.push('.muted{color:#6b7280;font-size:12px;}');
      lines.push('.tag{display:inline-block;padding:2px 6px;border-radius:9999px;font-size:11px;font-weight:600;margin-right:4px;}');
      lines.push('.tag-pass{background:#dcfce7;color:#166534;}');
      lines.push('.tag-warn{background:#fef3c7;color:#92400e;}');
      lines.push('.tag-fail{background:#fee2e2;color:#b91c1c;}');
      lines.push('.tag-info{background:#e0f2fe;color:#075985;}');
      lines.push('.issue-box{border-left-width:4px;border-radius:4px;padding:6px 10px;margin-bottom:6px;}');
      lines.push('.issue-high{background:#fee2e2;border-color:#b91c1c;}');
      lines.push('.issue-medium{background:#fef3c7;border-color:#d97706;}');
      lines.push('.issue-low{background:#e0f2fe;border-color:#0284c7;}');
      lines.push('</style>');
      lines.push('</head><body>');
      lines.push('<h1>网表评审报告导出</h1>');
      lines.push(`<div class="muted">导出时间：${new Date().toLocaleString('zh-CN')}</div>`);

      // 解析结果摘要
      lines.push('<div class="section">');
      lines.push('<h2>一、解析结果摘要</h2>');
      const s = analysisData?.summary || summaryData || {};
      if (s && Object.keys(s).length > 0) {
        lines.push('<ul>');
        lines.push(`<li>总元件数：${s.total_components ?? 0}</li>`);
        lines.push(`<li>总网络数：${s.total_nets ?? 0}</li>`);
        if (s.power_nets) {
          lines.push(`<li>电源网络：${(s.power_nets || []).length} 个</li>`);
        }
        lines.push('</ul>');
      } else {
        lines.push('<div class="muted">暂无解析摘要</div>');
      }
      lines.push('</div>');

      // AI 评审结果（来自解析 + 对话 JSON）
      lines.push('<div class="section">');
      lines.push('<h2>二、AI 评审结果</h2>');
      if (reviewData) {
        lines.push('<h3>2.1 解析生成的评审报告</h3>');
        lines.push('<pre>');
        lines.push(String(reviewData).replace(/</g, '&lt;'));
        lines.push('</pre>');
      }
      const agg = aggregatedReviewSummary;
      const aiReviews =
        agg && Array.isArray(agg.aiReviews)
          ? agg.aiReviews
          : agg && agg.aiReview
            ? [{ parsed: agg.aiReview, aiName: agg.aiReviewMeta?.aiName, timestamp: agg.aiReviewMeta?.timestamp }]
            : [];
      if (aiReviews.length > 0) {
        lines.push('<h3>2.2 JSON 评审结果（聚合）</h3>');
        aiReviews.forEach((item: any, idx: number) => {
          const p = item.parsed || {};
          lines.push(`<h4>2.2.${idx + 1} ${item.aiName || ''}</h4>`);
          if (p.overall_status != null) {
            lines.push(`<div>总体结论：${String(p.overall_status)}</div>`);
          }
          if (typeof p.summary === 'string') {
            lines.push('<pre>');
            lines.push(p.summary.replace(/</g, '&lt;'));
            lines.push('</pre>');
          }
        });
      }
      lines.push('</div>');

      // 评审总结
      lines.push('<div class="section">');
      lines.push('<h2>三、评审总结</h2>');
      if (summaryData || agg) {
        lines.push('<div>详见系统中右侧“评审总结”标签页，本导出主要聚焦检查项明细。</div>');
      } else {
        lines.push('<div class="muted">暂无评审总结</div>');
      }
      lines.push('</div>');

      // 待检查项（网表 + AI JSON）
      lines.push('<div class="section">');
      lines.push('<h2>四、待检查项</h2>');
      const issues = checklistData?.issues || [];
      const checklist = checklistData?.checklist || [];
      if (issues.length === 0 && checklist.length === 0 && aiReviews.length === 0) {
        lines.push('<div class="muted">暂无待检查项。</div>');
      } else {
        if (issues.length > 0) {
          lines.push('<h3>4.1 网表潜在问题</h3>');
          issues.forEach((iss: any, idx: number) => {
            const sev = String(iss.severity || 'medium').toLowerCase();
            const sevClass =
              sev === 'high' ? 'issue-box issue-high' :
              sev === 'low' ? 'issue-box issue-low' :
              'issue-box issue-medium';
            lines.push(`<div class="${sevClass}"><div><strong>${idx + 1}）${iss.description}</strong></div>`);
            if (iss.component) {
              lines.push(`<div class="muted">元件：${iss.component}</div>`);
            }
            if (iss.net) {
              lines.push(`<div class="muted">网络：${iss.net}</div>`);
            }
            lines.push('</div>');
          });
        }
        if (checklist.length > 0) {
          lines.push('<h3>4.2 网表检查清单</h3>');
          lines.push('<ul>');
          checklist.forEach((item: any) => {
            lines.push(`<li>${String(item)}</li>`);
          });
          lines.push('</ul>');
        }
        if (aiReviews.length > 0) {
          lines.push('<h3>4.3 AI JSON 评审检查项</h3>');
          aiReviews.forEach((item: any, idx: number) => {
            const p = item.parsed || {};
            if (!Array.isArray(p.interfaces)) return;
            lines.push(`<h4>4.3.${idx + 1} ${item.aiName || ''}</h4>`);
            p.interfaces.forEach((iface: any) => {
              const ifaceType = String(iface?.type ?? '接口');
              const checks = Array.isArray(iface?.checks) ? iface.checks : [];
              if (!checks.length) return;
              lines.push(`<h5>${ifaceType}</h5>`);
              lines.push('<ul>');
              checks.forEach((chk: any) => {
                const statusRaw = String(chk?.status ?? '').toUpperCase();
                const status = statusRaw || 'INFO';
                const name = String(chk?.check_name ?? '');
                const desc = String(chk?.description ?? '');
                const cls =
                  status === 'PASS'
                    ? 'tag tag-pass'
                    : status === 'FAIL'
                      ? 'tag tag-fail'
                      : status === 'WARNING'
                        ? 'tag tag-warn'
                        : 'tag tag-info';
                lines.push(
                  `<li><span class="${cls}">${status}</span>${name ? name + '：' : ''}${desc}</li>`
                );
              });
              lines.push('</ul>');
            });
          });
        }
      }
      lines.push('</div>');

      lines.push('</body></html>');
      const html = lines.join('\n');
      const result = await printHtmlDocument(html);
      if (result === 'external' || result === 'failed') {
        alert(getPrintMessage(result));
      }
    } catch (e) {
      console.error('导出评审结果失败', e);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* 标签页 */}
      <div className="flex items-center justify-between border-b bg-gray-50 flex-shrink-0">
        <div className="flex">
        <button
          onClick={() => setActiveTab('analysis')}
          className={getTabClassName('analysis', isAnalysisCompleted)}
        >
          解析结果
        </button>
        <button
          onClick={() => setActiveTab('review')}
          className={getTabClassName('review', isReviewCompleted)}
        >
          AI评审
        </button>
        <button
          onClick={() => setActiveTab('summary')}
          className={getTabClassName('summary', isSummaryCompleted)}
        >
          评审总结
        </button>
        <button
          onClick={() => setActiveTab('checklist')}
          className={getTabClassName('checklist', isChecklistCompleted)}
        >
          待检查项
        </button>
        </div>
        <div className="pr-3">
          <button
            type="button"
            onClick={handleExportReview}
            className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700"
          >
            导出评审结果（PDF）
          </button>
        </div>
      </div>

      {/* 内容区域：可滚动，内容过多时支持鼠标滚轮/滚动条 */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {activeTab === 'analysis' && (
          <AnalysisTab
            readOnly={readOnly}
            data={analysisData}
            results={results}
            onSelectResult={(id) => {
              loadResultData(id, 'analysis');
              if (onResultSelected) {
                onResultSelected(id, 'analysis');
              }
            }}
            onViewDetails={(id) => setSelectedDetailResult({ id, type: 'analysis' })}
            onResultCreated={(id) => {
              loadResultData(id, 'analysis');
              if (onResultSelected) {
                onResultSelected(id, 'analysis');
              }
              loadResults(); // 刷新结果列表
            }}
          />
        )}
        
        {activeTab === 'review' && (
          <ReviewTab
            data={reviewData}
            aiReviewEntries={aiReviewEntries}
            selectedReviewId={selectedReviewId}
            onSelectReview={setSelectedReviewId}
          />
        )}
        
        {activeTab === 'summary' && (
          <SummaryTab
            data={summaryData}
            aggregated={aggregatedReviewSummary}
            onClearAggregated={onClearAggregatedSummary}
          />
        )}
        
        {activeTab === 'checklist' && (
          <ChecklistTab data={checklistData} aiAggregated={aggregatedReviewSummary} />
        )}
      </div>

      {/* 结果详情模态框 */}
      {selectedDetailResult && (
        <NetlistResultModal
          isOpen={!!selectedDetailResult}
          onClose={() => setSelectedDetailResult(null)}
          resultId={selectedDetailResult.id}
          resultType={selectedDetailResult.type}
        />
      )}
    </div>
  );
};


// 解析结果标签页
const AnalysisTab: React.FC<{
  readOnly?: boolean;
  data: any;
  results: NetlistResult[];
  onSelectResult: (id: string) => void;
  onViewDetails: (id: string) => void;
  onResultCreated?: (id: string) => void;
}> = ({ readOnly, data, results, onSelectResult, onResultCreated }) => {
  const [netlist, setNetlist] = React.useState('');
  const [netlistName, setNetlistName] = React.useState('网表');
  const [loading, setLoading] = React.useState(false);
  const [analysisResult, setAnalysisResult] = React.useState<any>(data);
  const [selectedDetail, setSelectedDetail] = React.useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const analysisResults = results.filter(r => r.type === 'analysis');

  // 当外部data变化时更新本地状态
  React.useEffect(() => {
    setAnalysisResult(data);
  }, [data]);

  const handleFileUpload = async (file: File, setter: (content: string) => void, setName?: (name: string) => void) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      setter(content);
      if (setName) {
        setName(file.name.replace(/\.(asc|txt)$/i, ''));
      }
    };
    reader.onerror = () => {
      alert('文件读取失败');
    };
    reader.readAsText(file, 'UTF-8');
  };

  const handleAnalyze = async () => {
    if (!netlist.trim()) {
      alert('请提供网表内容');
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(apiUrl('/api/netlist/analyze'), {
        netlist: netlist,
        netlist_name: netlistName
      });

      if (response.data.success) {
        // 加载解析结果
        const resultResponse = await axios.get(apiUrl(`/api/netlist/result/${response.data.result_id}`));
        if (resultResponse.data.success) {
          setAnalysisResult(resultResponse.data.data.result);
          // 通知父组件更新结果ID
          if (onResultCreated) {
            onResultCreated(response.data.result_id);
          }
        }
      } else {
        alert(`解析失败: ${response.data.error}`);
      }
    } catch (error: any) {
      console.error('解析失败:', error);
      alert(`解析失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setNetlist('');
    setNetlistName('网表');
    setAnalysisResult(null);
  };
  
  return (
    <div className="flex flex-col h-full">
      {/* 输入区域 - SOP 模式下禁止输入 */}
      {!readOnly ? (
      <div className="flex-shrink-0 border-b p-4 bg-gray-50">
        <p className="text-xs text-gray-600 mb-3">
          支持两种方式：<strong>在下方输入或粘贴网表内容</strong>，或<strong>点击「导入文件」</strong>上传网表文件（.asc / .txt）
        </p>
        <div className="border rounded-lg p-3 bg-white">
          <div className="flex justify-between items-center mb-2">
            <label className="font-semibold text-sm">网表内容</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={netlistName}
                onChange={(e) => setNetlistName(e.target.value)}
                placeholder="网表名称"
                className="px-2 py-1 border rounded text-xs w-32"
              />
              <input
                type="file"
                ref={fileInputRef}
                accept=".asc,.txt,.net,.cir"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    handleFileUpload(file, setNetlist, setNetlistName);
                  }
                }}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="px-2 py-1 bg-blue-500 text-white rounded text-xs hover:bg-blue-600"
                title="选择网表文件导入"
              >
                导入文件
              </button>
            </div>
          </div>
          <textarea
            value={netlist}
            onChange={(e) => setNetlist(e.target.value)}
            placeholder="在此输入或粘贴网表内容；也可使用上方「导入文件」上传..."
            className="w-full h-32 p-2 border rounded font-mono text-xs resize-none"
          />
        </div>
        
        {/* 操作按钮 */}
        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={handleClear}
            className="px-4 py-2 bg-gray-500 text-white rounded hover:bg-gray-600 transition text-sm"
          >
            清空
          </button>
          <button
            onClick={handleAnalyze}
            disabled={loading || !netlist}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition disabled:bg-gray-400 disabled:cursor-not-allowed text-sm"
          >
            {loading ? '解析中...' : '开始解析'}
          </button>
        </div>
      </div>
      ) : (
        <div className="flex-shrink-0 border-b p-3 bg-amber-50 text-amber-800 text-sm">
          SOP 模式下禁止输入，仅可查阅解析结果。
        </div>
      )}

      {/* 解析结果区域 - 可滚动 */}
      <div className="flex-1 overflow-auto p-4">
        {analysisResult ? (
          <div>
            <h3 className="text-lg font-semibold mb-4">解析结果</h3>
            <div className="grid grid-cols-3 gap-4 mb-6">
              <div 
                onClick={() => setSelectedDetail(selectedDetail === 'components' ? null : 'components')}
                className="bg-blue-50 p-4 rounded-lg text-center cursor-pointer hover:bg-blue-100 transition"
              >
                <div className="text-2xl font-bold text-blue-600">
                  {analysisResult.summary?.total_components || 0}
                </div>
                <div className="text-sm text-gray-600">总元件数</div>
              </div>
              <div 
                onClick={() => setSelectedDetail(selectedDetail === 'nets' ? null : 'nets')}
                className="bg-blue-50 p-4 rounded-lg text-center cursor-pointer hover:bg-blue-100 transition"
              >
                <div className="text-2xl font-bold text-blue-600">
                  {analysisResult.summary?.total_nets || 0}
                </div>
                <div className="text-sm text-gray-600">总网络数</div>
              </div>
              <div 
                onClick={() => setSelectedDetail(selectedDetail === 'power_nets' ? null : 'power_nets')}
                className="bg-green-50 p-4 rounded-lg text-center cursor-pointer hover:bg-green-100 transition"
              >
                <div className="text-2xl font-bold text-green-600">
                  {analysisResult.summary?.power_nets?.length || 0}
                </div>
                <div className="text-sm text-gray-600">电源网络</div>
              </div>
            </div>
            
            {/* 详细数据表格 */}
            {selectedDetail && (
              <div className="mt-4 border rounded-lg p-4 bg-white">
                <div className="flex justify-between items-center mb-3">
                  <h4 className="font-semibold">
                    {selectedDetail === 'components' && '元件列表'}
                    {selectedDetail === 'nets' && '网络列表'}
                    {selectedDetail === 'power_nets' && '电源网络列表'}
                  </h4>
                  <button
                    onClick={() => setSelectedDetail(null)}
                    className="text-gray-500 hover:text-gray-700"
                  >
                    ✕
                  </button>
                </div>
                <div className="max-h-64 overflow-auto">
                  {selectedDetail === 'components' && (
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 sticky top-0">
                        <tr>
                          <th className="px-3 py-2 text-left">元件ID</th>
                          <th className="px-3 py-2 text-left">类型</th>
                          <th className="px-3 py-2 text-left">元件名称</th>
                          <th className="px-3 py-2 text-left">值</th>
                          <th className="px-3 py-2 text-left">封装</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(analysisResult.components || []).map((comp: any) => (
                          <tr key={comp.id} className="hover:bg-gray-50">
                            <td className="px-3 py-2">{comp.id}</td>
                            <td className="px-3 py-2">{comp.type}</td>
                            <td className="px-3 py-2 font-mono text-xs">{comp.part_number || comp.id}</td>
                            <td className="px-3 py-2">{comp.value}</td>
                            <td className="px-3 py-2">{comp.package}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  
                  {selectedDetail === 'nets' && (
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 sticky top-0">
                        <tr>
                          <th className="px-3 py-2 text-left">网络名称</th>
                          <th className="px-3 py-2 text-left">连接数</th>
                          <th className="px-3 py-2 text-left">类型</th>
                          <th className="px-3 py-2 text-left">连接元件</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(analysisResult.nets || []).map((net: any) => (
                          <tr key={net.name} className="hover:bg-gray-50">
                            <td className="px-3 py-2 font-medium">{net.name}</td>
                            <td className="px-3 py-2">{net.connection_count}</td>
                            <td className="px-3 py-2">{net.type}</td>
                            <td className="px-3 py-2">{net.connections?.join(', ') || '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  
                  {selectedDetail === 'power_nets' && (
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 sticky top-0">
                        <tr>
                          <th className="px-3 py-2 text-left">电源网络名称</th>
                          <th className="px-3 py-2 text-left">连接元件</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(analysisResult.summary?.power_nets || []).map((netName: string) => {
                          const net = analysisResult.nets?.find((n: any) => n.name === netName);
                          return (
                            <tr key={netName} className="hover:bg-gray-50">
                              <td className="px-3 py-2 font-medium">{netName}</td>
                              <td className="px-3 py-2">{net?.connections?.join(', ') || '-'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                  
                </div>
              </div>
            )}
            
            {/* 元件类型统计 */}
            {analysisResult.summary?.component_types && (
              <div className="mt-4">
                <h4 className="font-semibold mb-2">元件类型分布</h4>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(analysisResult.summary.component_types).map(([type, count]) => (
                    <span key={type} className="bg-gray-100 px-3 py-1 rounded text-sm">
                      {type}: {count as number}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="text-center text-gray-400 py-12">
            <div className="text-4xl mb-4">🔍</div>
            <div>暂无解析结果</div>
            <div className="text-sm mt-2">在上方输入网表内容后点击"开始解析"</div>
          </div>
        )}
        
        {analysisResults.length > 0 && (
          <div className="mt-6">
            <h4 className="font-semibold mb-3">历史解析结果</h4>
            <div className="space-y-2">
              {analysisResults.map((result) => (
                <div
                  key={result.id}
                  onClick={() => onSelectResult(result.id)}
                  className="p-3 border rounded-lg cursor-pointer hover:bg-gray-50"
                >
                  <div className="font-medium">{result.netlist_name || '网表'}</div>
                  <div className="text-sm text-gray-500">
                    {new Date(result.created_at).toLocaleString('zh-CN')}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// AI评审标签页：展示来自解析的评审 + 从聊天收集的 AI 评审记录
const ReviewTab: React.FC<{
  data: any;
  aiReviewEntries: AIReviewEntry[];
  selectedReviewId: string | null;
  onSelectReview: (id: string | null) => void;
}> = ({ data, aiReviewEntries, selectedReviewId, onSelectReview }) => {
  const selected = aiReviewEntries.find((e) => e.id === selectedReviewId);
  const hasReviewData = !!data;
  const hasEntries = aiReviewEntries.length > 0;

  const formatReviewSummary = (entry: AIReviewEntry) => {
    const p = entry.parsed;
    if (p.summary && typeof p.summary === 'string') return p.summary.slice(0, 80) + (p.summary.length > 80 ? '…' : '');
    if (p.overall_status != null) return `接口检查: ${p.overall_status}`;
    if (Array.isArray(p.interfaces) && p.interfaces.length) return `接口 ${p.interfaces.length} 项`;
    return '评审结果';
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      {hasEntries && (
        <div className="flex-shrink-0 mb-3">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">AI评审记录（来自对话）</h3>
          <ul className="space-y-1 max-h-40 overflow-y-auto border rounded-lg p-2 bg-gray-50">
            {aiReviewEntries.slice().reverse().map((entry) => (
              <li key={entry.id}>
                <button
                  type="button"
                  onClick={() => onSelectReview(selectedReviewId === entry.id ? null : entry.id)}
                  className={`w-full text-left px-2 py-1.5 rounded text-sm truncate ${selectedReviewId === entry.id ? 'bg-blue-100 ring-1 ring-blue-300' : 'hover:bg-gray-200'}`}
                  title={formatReviewSummary(entry)}
                >
                  <span className="text-gray-500">{new Date(entry.timestamp).toLocaleTimeString('zh-CN')}</span>
                  <span className="mx-1">·</span>
                  <span className="font-medium">{entry.aiName}</span>
                  <span className="mx-1">·</span>
                  <span className="text-gray-700 truncate inline-block max-w-full">{formatReviewSummary(entry)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-auto">
        {selected ? (
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-2">
              {selected.aiName} · {new Date(selected.timestamp).toLocaleString('zh-CN')}
            </h3>
            <pre className="text-xs bg-gray-50 p-3 rounded-lg overflow-x-auto whitespace-pre-wrap break-words">
              {JSON.stringify(selected.parsed, null, 2)}
            </pre>
            <button type="button" onClick={() => onSelectReview(null)} className="mt-2 text-sm text-blue-600 hover:underline">
              收起
            </button>
          </div>
        ) : hasReviewData ? (
          <div>
            <h3 className="text-lg font-semibold mb-4">来自解析的评审结果</h3>
            <div className="prose max-w-none">
              {typeof data === 'string' ? (
                <div className="whitespace-pre-wrap text-sm">{data}</div>
              ) : (
                <pre className="text-xs bg-gray-50 p-3 rounded overflow-auto">{JSON.stringify(data, null, 2)}</pre>
              )}
            </div>
          </div>
        ) : !hasEntries ? (
          <div className="text-center text-gray-400 py-12">
            <div className="text-4xl mb-4">🤖</div>
            <div>暂无AI评审结果</div>
            <div className="text-sm mt-2">网表分析/接口检查等对话中的 AI 评审 JSON 会在此统计展示</div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

// 评审总结标签页（支持仅解析数据 或 聚合：网表解析 + 网络列表 + AI 评审 JSON）
const SummaryTab: React.FC<{
  data: any;
  aggregated?: any;
  onClearAggregated?: () => void;
}> = ({ data, aggregated, onClearAggregated }) => {
  const netlistSummary = aggregated?.netlist?.summary ?? (typeof data === 'object' ? data : null);
  const netlistNets = aggregated?.netlist?.nets;
  // 支持多个 JSON 解析结果：优先使用 aiReviews 数组，兼容旧的单条 aiReview/aiReviewMeta
  const aiReviewsList: Array<{ parsed: any; aiName?: string; timestamp?: any; id?: string }> = Array.isArray(aggregated?.aiReviews)
    ? aggregated.aiReviews
    : aggregated?.aiReview
      ? [{ parsed: aggregated.aiReview, aiName: aggregated.aiReviewMeta?.aiName, timestamp: aggregated.aiReviewMeta?.timestamp }]
      : [];

  const esc = (s: string) => String(s ?? '').replace(/\|/g, '/');
  const connStr = (net: { connections?: string[] | Record<string, unknown> }) =>
    formatNetConnectionsFull(net);

  return (
    <div className="space-y-4 p-4">
      {aggregated && (
        <div className="flex items-center justify-between flex-shrink-0">
          <h3 className="text-lg font-semibold">评审总结（硬件分析结果聚合）</h3>
          {onClearAggregated && (
            <button type="button" onClick={onClearAggregated} className="text-sm text-gray-500 hover:text-gray-700">
              清除聚合
            </button>
          )}
        </div>
      )}
      {netlistSummary && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2">网表解析结果</h4>
          <div className="bg-blue-50 p-4 rounded-lg space-y-2">
            <div>总元件数: {netlistSummary.total_components ?? 0}</div>
            <div>总网络数: {netlistSummary.total_nets ?? 0}</div>
            {netlistSummary.power_nets?.length != null && (
              <div>电源网络: {netlistSummary.power_nets.length} 个</div>
            )}
            {netlistSummary.component_types && Object.keys(netlistSummary.component_types).length > 0 && (
              <div className="mt-2">
                <div className="font-medium">元件类型分布</div>
                <div className="flex flex-wrap gap-2 mt-1">
                  {Object.entries(netlistSummary.component_types).map(([type, count]) => (
                    <span key={type} className="bg-white px-2 py-0.5 rounded text-sm">
                      {type}: {count as number}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {aggregated?.netlist && Array.isArray(netlistNets) && netlistNets.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2">网络列表（与解析结果结合）</h4>
          <div className="bg-gray-50 p-3 rounded-lg overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-1.5 px-2 font-medium">网络名称</th>
                  <th className="text-left py-1.5 px-2 font-medium">连接数</th>
                  <th className="text-left py-1.5 px-2 font-medium">类型</th>
                  <th className="text-left py-1.5 px-2 font-medium">连接元件</th>
                </tr>
              </thead>
              <tbody>
                {(netlistNets as Array<{ name?: string; connection_count?: number; type?: string; connections?: string[] | Record<string, unknown> }>).map((net, idx) => (
                  <tr key={idx} className="border-b border-gray-100">
                    <td className="py-1 px-2">{esc(net.name ?? '')}</td>
                    <td className="py-1 px-2">{net.connection_count ?? 0}</td>
                    <td className="py-1 px-2">{esc(net.type ?? 'Signal')}</td>
                    <td className="py-1 px-2 whitespace-pre-wrap break-all align-top">{connStr(net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {aiReviewsList.length > 0 && (
        <div className="space-y-4">
          <h4 className="text-sm font-semibold text-gray-700">AI 评审结果（共 {aiReviewsList.length} 条）</h4>
          {aiReviewsList.map((item, idx) => {
            const aiReview = item.parsed;
            return (
              <div key={item.id ?? idx} className="bg-amber-50 p-4 rounded-lg space-y-3 border border-amber-100">
                <div className="text-xs font-medium text-amber-800">
                  {item.aiName ? `${item.aiName}` : ''}
                  {item.timestamp != null && (
                    <span className="ml-2 text-amber-600">
                      {new Date(item.timestamp).toLocaleString('zh-CN')}
                    </span>
                  )}
                  {aiReviewsList.length > 1 && <span className="ml-2 text-amber-600">（第 {idx + 1} 条）</span>}
                </div>
                <div className="space-y-2">
                  {aiReview && aiReview.overall_status != null && (
                    <div><span className="font-medium">接口检查结论:</span> {String(aiReview.overall_status)}</div>
                  )}
                  {aiReview && typeof aiReview.summary === 'string' && (
                    <div className="text-sm whitespace-pre-wrap">{aiReview.summary}</div>
                  )}
                  {aiReview && Array.isArray(aiReview.interfaces) && aiReview.interfaces.length > 0 && (
                    <div>
                      <div className="font-medium mb-1">识别接口 ({aiReview.interfaces.length})</div>
                      <ul className="list-disc list-inside text-sm space-y-0.5">
                        {aiReview.interfaces.slice(0, 20).map((iface: any, i: number) => (
                          <li key={i}>{iface.type ?? iface.name ?? '—'} {iface.confidence ? `(${iface.confidence})` : ''}</li>
                        ))}
                        {aiReview.interfaces.length > 20 && <li className="text-gray-500">…共 {aiReview.interfaces.length} 项</li>}
                      </ul>
                    </div>
                  )}
                  {aiReview && Array.isArray(aiReview.power_rails) && aiReview.power_rails.length > 0 && (
                    <div>
                      <div className="font-medium mb-1">电源轨</div>
                      <ul className="list-disc list-inside text-sm">
                        {aiReview.power_rails.map((r: any, i: number) => (
                          <li key={i}>{r.name ?? r.net}{r.voltage ? ` (${r.voltage})` : ''}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {!netlistSummary && aiReviewsList.length === 0 && !aggregated && data && (
        <div>
          <h3 className="text-lg font-semibold mb-4">评审总结</h3>
          <div className="space-y-4">
            {typeof data === 'object' && (
              <>
                <div className="bg-blue-50 p-4 rounded-lg">
                  <div className="font-semibold">总体统计</div>
                  <div className="mt-2 text-sm">
                    <div>总元件数: {data.total_components || 0}</div>
                    <div>总网络数: {data.total_nets || 0}</div>
                  </div>
                </div>
                {data.component_types && (
                  <div className="bg-gray-50 p-4 rounded-lg">
                    <div className="font-semibold">元件类型分布</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {Object.entries(data.component_types).map(([type, count]) => (
                        <span key={type} className="bg-white px-3 py-1 rounded">{type}: {count as number}</span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
      {!netlistSummary && aiReviewsList.length === 0 && !data && (
        <div className="text-center text-gray-400 py-12">
          <div className="text-4xl mb-4">📋</div>
          <div>暂无评审总结</div>
          <div className="text-sm mt-2">可先进行网表解析与 AI 评审，再使用「硬件分析结果聚合」触发事件生成聚合总结</div>
        </div>
      )}
    </div>
  );
};

// 待检查项标签页
const ChecklistTab: React.FC<{ data: any; aiAggregated?: any }> = ({ data, aiAggregated }) => {
  // 从硬件分析 JSON 聚合结果中提取 AI 评审检查项（包含 PASS / WARNING / FAIL / INFO）
  const aiChecks: Array<{ status: string; title: string; description: string }> = [];

  const source = aiAggregated;
  if (source) {
    const aiReviews = Array.isArray(source.aiReviews)
      ? source.aiReviews
      : source.aiReview
        ? [{ parsed: source.aiReview, aiName: source.aiReviewMeta?.aiName, timestamp: source.aiReviewMeta?.timestamp }]
        : [];

    for (const item of aiReviews) {
      const parsed = item.parsed;
      if (!parsed || !Array.isArray(parsed.interfaces)) continue;
      for (const iface of parsed.interfaces) {
        const ifaceType = String(iface?.type ?? '接口');
        const checks = Array.isArray(iface?.checks) ? iface.checks : [];
        for (const chk of checks) {
          const statusRaw = String(chk?.status ?? '').toUpperCase();
          const status = statusRaw || 'INFO';
          const name = String(chk?.check_name ?? '');
          const desc = String(chk?.description ?? '');
          const title = name ? `${ifaceType} · ${name}` : ifaceType;
          aiChecks.push({ status, title, description: desc });
        }
      }
    }
  }

  const hasData =
    (data && (data.issues?.length > 0 || data.checklist?.length > 0)) ||
    aiChecks.length > 0;

  return (
    <div>
      {hasData ? (
        <div>
          <h3 className="text-lg font-semibold mb-4">待检查确认项</h3>
          
          {data?.issues && data.issues.length > 0 && (
            <div className="mb-6">
              <h4 className="font-semibold mb-3">潜在问题</h4>
              <div className="space-y-2">
                {data.issues.map((issue: any, idx: number) => (
                  <div
                    key={idx}
                    className={`p-3 rounded border-l-4 ${
                      issue.severity === 'high'
                        ? 'bg-red-50 border-red-500'
                        : issue.severity === 'medium'
                        ? 'bg-yellow-50 border-yellow-500'
                        : 'bg-blue-50 border-blue-500'
                    }`}
                  >
                    <div className="font-medium">{issue.description}</div>
                    {issue.component && (
                      <div className="text-sm text-gray-600 mt-1">元件: {issue.component}</div>
                    )}
                    {issue.net && (
                      <div className="text-sm text-gray-600 mt-1">网络: {issue.net}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {data?.checklist && data.checklist.length > 0 && (
            <div className="mb-6">
              <h4 className="font-semibold mb-3">检查清单</h4>
              <div className="space-y-2">
                {data.checklist.map((item: any, idx: number) => (
                  <div key={idx} className="p-3 border rounded-lg flex items-center">
                    <input type="checkbox" className="mr-3" />
                    <div className="flex-1">{item}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {aiChecks.length > 0 && (
            <div>
              <h4 className="font-semibold mb-3">AI 评审检查项</h4>
              <div className="space-y-2">
                {aiChecks.map((c, idx) => {
                  const s = c.status;
                  const colorClass =
                    s === 'PASS'
                      ? 'bg-green-50 border-green-500'
                      : s === 'FAIL'
                        ? 'bg-red-50 border-red-500'
                        : 'bg-yellow-50 border-yellow-500';
                  return (
                    <div
                      key={idx}
                      className={`p-3 rounded border-l-4 ${colorClass}`}
                    >
                      <div className="text-xs font-semibold mb-1">
                        {s === 'PASS' ? '通过' : s === 'FAIL' ? '错误' : '警告/待确认'} ({s})
                      </div>
                      <div className="font-medium">{c.title}</div>
                      {c.description && (
                        <div className="text-sm text-gray-700 mt-1 whitespace-pre-wrap">
                          {c.description}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="text-center text-gray-400 py-12">
          <div className="text-4xl mb-4">✅</div>
          <div>暂无待检查项</div>
        </div>
      )}
    </div>
  );
};

export const NetlistResultsPanel: React.FC<NetlistResultsPanelProps> = (props) => {
  if (props.schematicMode) {
    return (
      <SchematicReviewPanel
        selectedResultId={props.selectedResultId}
        onResultSelected={
          props.onResultSelected ? (id) => props.onResultSelected!(id, 'analysis') : undefined
        }
        aiReviewEntries={props.aiReviewEntries}
        aggregatedReviewSummary={props.aggregatedReviewSummary}
        cleanedNetlistText={props.cleanedNetlistText ?? ''}
        onCleanedNetlistChange={props.onCleanedNetlistChange ?? (() => {})}
        cleanConfirmed={props.cleanConfirmed ?? false}
        onCleanConfirmed={props.onCleanConfirmed ?? (() => {})}
        reviewExported={props.reviewExported ?? false}
        onReviewExported={props.onReviewExported ?? (() => {})}
        onRunAiReview={props.onRunAiReview ?? (() => {})}
        aiReviewRunning={props.aiReviewRunning ?? false}
        onOpenChat={props.onOpenChat}
        canManagePrompt={props.canManagePrompt ?? false}
        onOpenPromptSettings={props.onOpenPromptSettings}
        reviewPrompt={props.reviewPrompt ?? ''}
        defaultAiName={props.defaultAiName}
        historyViewMode={props.historyViewMode}
        viewingHistoryTitle={props.viewingHistoryTitle}
        historyDispositions={props.historyDispositions}
        onApplyHistoryRecord={props.onApplyHistoryRecord}
        onStartNewReview={props.onStartNewReview}
      />
    );
  }
  return <ClassicNetlistResultsPanel {...props} />;
};
