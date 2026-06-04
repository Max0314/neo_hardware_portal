/**
 * 事件流侧边栏：将多个事件组合成流程，一次输入文本即可按序执行，每步结束后可插入文本或直接下一步
 */
import React, { useState, useEffect, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import { trackNeoPoints } from '@/utils/neoPoints';
import { formatAnalysisResultMarkdown } from '@/utils/schematicReview';
import {
  Play,
  Plus,
  Trash2,
  Edit2,
  ChevronUp,
  ChevronDown,
  Send,
  FileText,
  ListOrdered,
} from 'lucide-react';

const EVENT_TYPE_NAMES: Record<string, string> = {
  open_sidebar_compare: '打开对比功能',
  open_sidebar_analyze: '打开解析功能',
  open_sidebar_review: '打开AI评审',
  open_sidebar_summary: '打开评审总结',
  open_sidebar_checklist: '打开待检查项',
  open_sidebar_tab: '打开指定标签页',
  open_game_tetris: '打开俄罗斯方块',
  aggregate_review_summary: '硬件分析结果聚合',
  prompt_review_chat: '审核提示词对话',
  execute_script: '执行脚本',
  send_message: '发送消息',
  call_api: '调用API',
  custom: '自定义事件',
};

const FLOW_STORAGE_KEY = 'event_flows';

/** 下一步的输入来源：本步 AI 结果 或 原文本（本步输入） */
export type NextInputSource = 'result' | 'original';

/** 本步输入来源：原始输入 或 某一步的输出（步骤索引 0-based） */
export type StepInputSource = 'original' | number;

export interface FlowStep {
  eventType: string;
  eventParams: Record<string, any>;
  triggerKeywords?: string;
  /** 传给下一步的输入（兼容旧数据） */
  nextInputSource?: NextInputSource;
  /** 本步输入来源：原始输入 或 步骤 N 的输出，默认第一步为 original，其余为上一步 */
  inputSource?: StepInputSource;
}

export interface EventFlow {
  id: string;
  name: string;
  steps: FlowStep[];
}

interface EventTriggerOption {
  id?: string;
  keywords: string;
  eventType: string;
  eventParams: Record<string, any>;
}

interface EventFlowPanelProps {
  onSendFlowStep: (content: string, options?: { targetAIIds?: string[]; maxTokens?: number }) => void;
  onTriggerNonChatEvent?: (eventType: string, params: Record<string, any>) => void;
  registerStepResponseCallback: (callback: ((content: string) => void) | null) => void;
  /** 将「打开XX功能」的解析/对比结果展示到聊天室并打开右侧结果面板 */
  onShowResultInChat?: (content: string, resultId: string, resultType: 'analysis' | 'comparison') => void;
  /** 从主页进入某 SOP 时传入对应事件流 id，将自动弹出运行输入框 */
  initialEventFlowId?: string | null;
}

const NETLIST2_DELIMITER = '\n---NETLIST2---\n';

export const EventFlowPanel: React.FC<EventFlowPanelProps> = ({
  onSendFlowStep,
  onTriggerNonChatEvent,
  registerStepResponseCallback,
  onShowResultInChat,
  initialEventFlowId,
}) => {
  const [flows, setFlows] = useState<EventFlow[]>(() => {
    try {
      const raw = localStorage.getItem(FLOW_STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  });
  const [triggers, setTriggers] = useState<EventTriggerOption[]>([]);
  const [editingFlow, setEditingFlow] = useState<EventFlow | null>(null);
  const [runState, setRunState] = useState<{
    flow: EventFlow;
    stepIndex: number;
    /** 运行时的初始输入；每步的实际输入由该步的 inputSource 决定 */
    initialInput: string;
    stepResults: string[];
  } | null>(null);
  const [insertTextModal, setInsertTextModal] = useState(false);
  const [insertTextValue, setInsertTextValue] = useState('');
  const [loadingTriggers, setLoadingTriggers] = useState(false);
  const [waitingForResponse, setWaitingForResponse] = useState(false);
  const [runInputModal, setRunInputModal] = useState<EventFlow | null>(null);
  const [runInputValue, setRunInputValue] = useState('');
  const hasAutoOpenedRunRef = useRef(false);
  const sopPointsAwardedRef = useRef(false);
  const runInputFileRef = useRef<HTMLInputElement>(null);
  const insertTextFileRef = useRef<HTMLInputElement>(null);

  const loadTriggers = async () => {
    setLoadingTriggers(true);
    try {
      const res = await axios.get(
        apiUrl('/api/custom-ai/babata/knowledge'),
        { params: { query: '', top_k: 100 } }
      );
      const list: EventTriggerOption[] = [];
      if (res.data.qa_pairs && Array.isArray(res.data.qa_pairs)) {
        for (const qa of res.data.qa_pairs) {
          if (qa.event_config) {
            const keywords = qa.event_config.params?.keywords || [qa.keywords];
            const keywordsStr = Array.isArray(keywords) ? keywords.join(', ') : keywords;
            list.push({
              id: qa.id,
              keywords: keywordsStr,
              eventType: qa.event_config.type,
              eventParams: qa.event_config.params || {},
            });
          }
        }
      }
      setTriggers(list);
    } catch (e) {
      console.error('加载事件触发列表失败', e);
    } finally {
      setLoadingTriggers(false);
    }
  };

  useEffect(() => {
    loadTriggers();
  }, []);

  useEffect(() => {
    if (initialEventFlowId && flows.length > 0 && !hasAutoOpenedRunRef.current) {
      const flow = flows.find((f) => f.id === initialEventFlowId);
      if (flow) {
        hasAutoOpenedRunRef.current = true;
        setRunInputModal(flow);
      }
    }
  }, [initialEventFlowId, flows]);

  useEffect(() => {
    if (!runState) {
      sopPointsAwardedRef.current = false;
      return;
    }
    const done =
      runState.flow.steps.length > 0 && runState.stepIndex >= runState.flow.steps.length;
    if (done && !sopPointsAwardedRef.current) {
      sopPointsAwardedRef.current = true;
      trackNeoPoints('sop_complete');
    }
  }, [runState?.stepIndex, runState?.flow.id, runState?.flow.steps.length]);

  useEffect(() => {
    try {
      localStorage.setItem(FLOW_STORAGE_KEY, JSON.stringify(flows));
    } catch (e) {
      console.error('保存事件流失败', e);
    }
  }, [flows]);

  const saveFlow = (flow: EventFlow) => {
    setFlows((prev) => {
      const idx = prev.findIndex((f) => f.id === flow.id);
      const next = idx >= 0 ? [...prev.slice(0, idx), flow, ...prev.slice(idx + 1)] : [...prev, flow];
      return next;
    });
    setEditingFlow(null);
  };

  const removeFlow = (id: string) => {
    if (!confirm('确定删除该事件流？')) return;
    setFlows((prev) => prev.filter((f) => f.id !== id));
    if (editingFlow?.id === id) setEditingFlow(null);
    if (runState?.flow.id === id) setRunState(null);
  };

  const addStepToEditing = (trigger: EventTriggerOption) => {
    if (!editingFlow) return;
    const steps = editingFlow.steps;
    const inputSource: StepInputSource = steps.length === 0 ? 'original' : steps.length - 1;
    setEditingFlow({
      ...editingFlow,
      steps: [
        ...steps,
        {
          eventType: trigger.eventType,
          eventParams: { ...trigger.eventParams },
          triggerKeywords: trigger.keywords,
          nextInputSource: 'original',
          inputSource,
        },
      ],
    });
  };

  /** 按事件类型添加步骤（无需先在事件触发管理中配置），便于加入如「硬件分析结果聚合」等 */
  const addStepByType = (eventType: string) => {
    if (!editingFlow) return;
    const steps = editingFlow.steps;
    const inputSource: StepInputSource = steps.length === 0 ? 'original' : steps.length - 1;
    setEditingFlow({
      ...editingFlow,
      steps: [
        ...steps,
        {
          eventType,
          eventParams: {},
          triggerKeywords: EVENT_TYPE_NAMES[eventType] || eventType,
          inputSource,
        },
      ],
    });
  };

  const removeStepFromEditing = (stepIndex: number) => {
    if (!editingFlow) return;
    setEditingFlow({
      ...editingFlow,
      steps: editingFlow.steps.filter((_, i) => i !== stepIndex),
    });
  };

  const moveStep = (index: number, dir: 1 | -1) => {
    if (!editingFlow || steps.length <= 1) return;
    const next = index + dir;
    if (next < 0 || next >= editingFlow.steps.length) return;
    const s = [...editingFlow.steps];
    [s[index], s[next]] = [s[next], s[index]];
    setEditingFlow({ ...editingFlow, steps: s });
  };

  /** 解析某一步的输入：原始输入 或 指定步骤的输出 */
  const getInputForStep = (step: FlowStep, stepIndex: number, initialInput: string, stepResults: string[]): string => {
    const src = step.inputSource ?? (stepIndex === 0 ? 'original' : (step.nextInputSource === 'result' ? stepIndex - 1 : 'original'));
    if (src === 'original') return initialInput;
    const idx = typeof src === 'number' ? src : 0;
    return stepResults[idx] ?? initialInput;
  };

  const startRun = (flow: EventFlow, initialInput: string) => {
    if (!initialInput.trim() || !flow.steps.length) return;
    const input = initialInput.trim();
    setRunState({
      flow,
      stepIndex: 0,
      initialInput: input,
      stepResults: [],
    });
    executeStep(flow, 0, input, []);
  };

  const formatAnalysisResult = (result: any, resultId: string): string =>
    formatAnalysisResultMarkdown(result, resultId);

  const formatCompareResult = (result: any, resultId: string): string => {
    const added = result?.added_components?.length ?? 0;
    const removed = result?.removed_components?.length ?? 0;
    const changed = result?.changed_components?.length ?? 0;
    const addedNets = result?.added_nets?.length ?? 0;
    const removedNets = result?.removed_nets?.length ?? 0;
    const changedNets = result?.changed_nets?.length ?? 0;
    return `✅ 网表对比完成！\n\n📊 对比结果：\n- 新增元件：${added} 个\n- 移除元件：${removed} 个\n- 修改元件：${changed} 个\n- 新增网络：${addedNets} 个\n- 移除网络：${removedNets} 个\n- 修改网络：${changedNets} 个\n\n结果ID: ${resultId}\n\n详细对比结果可在右侧结果记录中查看。`;
  };

  const executeStep = (flow: EventFlow, stepIndex: number, initialInput: string, stepResults: string[]) => {
    const step = flow.steps[stepIndex];
    if (!step) return;
    const input = getInputForStep(step, stepIndex, initialInput, stepResults);
    if (step.eventType === 'open_sidebar_analyze') {
      axios.post(apiUrl('/api/netlist/analyze'), { netlist: input, netlist_name: '网表' })
        .then((res) => {
          if (res.data.success && res.data.result_id != null) {
            const text = formatAnalysisResult(res.data.result, res.data.result_id);
            onShowResultInChat?.(text, res.data.result_id, 'analysis');
            setRunState((prev) => {
              if (!prev || prev.flow.id !== flow.id) return prev;
              const results = [...prev.stepResults];
              results[stepIndex] = text;
              return { ...prev, stepResults: results, stepIndex: stepIndex + 1 };
            });
          }
        })
        .catch((err) => {
          const errMsg = `网表分析失败：${err.response?.data?.error || err.message}`;
          setRunState((prev) => {
            if (!prev || prev.flow.id !== flow.id) return prev;
            const results = [...prev.stepResults];
            results[stepIndex] = errMsg;
            return { ...prev, stepResults: results, stepIndex: stepIndex + 1 };
          });
        });
      return;
    }
    if (step.eventType === 'open_sidebar_compare') {
      const parts = input.split(NETLIST2_DELIMITER).map((s: string) => s.trim());
      const netlist1 = parts[0] || '';
      const netlist2 = parts[1] || parts[0] || '';
      if (!netlist1 || !netlist2) {
        setRunState((prev) => {
          if (!prev || prev.flow.id !== flow.id) return prev;
          const results = [...prev.stepResults];
          results[stepIndex] = '网表对比需要两个网表，请用 "' + NETLIST2_DELIMITER + '" 分隔后重试。';
          return { ...prev, stepResults: results, stepIndex: stepIndex + 1 };
        });
        return;
      }
      axios.post(apiUrl('/api/netlist/compare'), {
        netlist1,
        netlist2,
        netlist1_name: '网表1',
        netlist2_name: '网表2',
      })
        .then((res) => {
          if (res.data.success && res.data.result_id != null) {
            const text = formatCompareResult(res.data.result, res.data.result_id);
            onShowResultInChat?.(text, res.data.result_id, 'comparison');
            setRunState((prev) => {
              if (!prev || prev.flow.id !== flow.id) return prev;
              const results = [...prev.stepResults];
              results[stepIndex] = text;
              return { ...prev, stepResults: results, stepIndex: stepIndex + 1 };
            });
          }
        })
        .catch((err) => {
          const errMsg = `网表对比失败：${err.response?.data?.error || err.message}`;
          setRunState((prev) => {
            if (!prev || prev.flow.id !== flow.id) return prev;
            const results = [...prev.stepResults];
            results[stepIndex] = errMsg;
            return { ...prev, stepResults: results, stepIndex: stepIndex + 1 };
          });
        });
      return;
    }
    if (step.eventType === 'prompt_review_chat') {
      const prompt = (step.eventParams?.prompt ?? '').trim();
      const content = prompt ? `${prompt}\n\n${input}` : input;
      setWaitingForResponse(true);
      registerStepResponseCallback((responseContent: string) => {
        setWaitingForResponse(false);
        setRunState((prev) => {
          if (!prev || prev.flow.id !== flow.id) return prev;
          const results = [...prev.stepResults];
          results[stepIndex] = responseContent;
          return { ...prev, stepResults: results, stepIndex: stepIndex + 1 };
        });
        registerStepResponseCallback(null);
      });
      const defaultAi = step.eventParams?.default_response_ai;
      const maxTokens = step.eventParams?.max_tokens;
      const opts: { targetAIIds?: string[]; maxTokens?: number } = {};
      if (Array.isArray(defaultAi) && defaultAi.length > 0) opts.targetAIIds = defaultAi;
      if (typeof maxTokens === 'number') opts.maxTokens = maxTokens;
      onSendFlowStep(content, Object.keys(opts).length > 0 ? opts : undefined);
    } else {
      if (onTriggerNonChatEvent) {
        onTriggerNonChatEvent(step.eventType, step.eventParams);
      }
      setRunState((prev) => {
        if (!prev || prev.flow.id !== flow.id) return prev;
        return { ...prev, stepIndex: prev.stepIndex + 1 };
      });
    }
  };

  const handleNextStep = () => {
    if (!runState) return;
    const { flow, stepIndex, initialInput, stepResults } = runState;
    if (stepIndex >= flow.steps.length) {
      setRunState(null);
      return;
    }
    executeStep(flow, stepIndex, initialInput, stepResults);
  };

  const openInsertText = () => setInsertTextModal(true);

  const submitInsertText = () => {
    if (!runState) return;
    const newInitial = insertTextValue.trim() || runState.initialInput;
    setRunState((prev) =>
      prev ? { ...prev, initialInput: newInitial } : null
    );
    setInsertTextValue('');
    setInsertTextModal(false);
    handleNextStep();
  };

  const steps = editingFlow?.steps ?? [];

  return (
    <div className="flex flex-col h-full bg-white overflow-hidden">
      {/* 事件流列表与编辑 */}
      {!runState && (
        <>
          <div className="flex-shrink-0 p-3 border-b">
            <h3 className="font-semibold text-gray-800 flex items-center gap-2">
              <ListOrdered size={18} />
              事件流
            </h3>
            <p className="text-xs text-gray-500 mt-1">
              可自主新建事件流，从已有事件中添加步骤；一次输入文本即可按序执行，每步结束后可插入文本或直接下一步。
            </p>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {flows.map((f) => (
              <div
                key={f.id}
                className="border rounded-lg p-3 bg-gray-50 hover:bg-gray-100"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-800">{f.name}</span>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => setEditingFlow({ ...f })}
                      className="p-1.5 text-blue-600 hover:bg-blue-50 rounded"
                      title="编辑"
                    >
                      <Edit2 size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => removeFlow(f.id)}
                      className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                      title="删除"
                    >
                      <Trash2 size={16} />
                    </button>
                    <button
                      type="button"
                      disabled={!f.steps.length}
                      onClick={() => {
                        setRunInputModal(f);
                        setRunInputValue('');
                      }}
                      className="p-1.5 text-green-600 hover:bg-green-50 rounded flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                      title={f.steps.length ? '运行' : '请先添加步骤'}
                    >
                      <Play size={16} />
                      运行
                    </button>
                  </div>
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {f.steps.length} 个步骤
                </div>
              </div>
            ))}
            <button
              type="button"
              onClick={() =>
                setEditingFlow({
                  id: uuidv4(),
                  name: '新事件流',
                  steps: [],
                })
              }
              className="w-full py-2 border border-dashed border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50 flex items-center justify-center gap-2"
            >
              <Plus size={16} />
              新建事件流
            </button>
          </div>
        </>
      )}

      {/* 编辑事件流 */}
      {editingFlow && !runState && (
        <div className="absolute inset-0 bg-white z-10 flex flex-col overflow-hidden">
          <div className="flex-shrink-0 p-3 border-b flex items-center justify-between">
            <input
              value={editingFlow.name}
              onChange={(e) =>
                setEditingFlow({ ...editingFlow, name: e.target.value })
              }
              className="border rounded px-2 py-1 flex-1 mr-2"
              placeholder="事件流名称"
            />
            <button
              type="button"
              onClick={() => saveFlow(editingFlow)}
              className="px-3 py-1 bg-blue-500 text-white rounded text-sm"
            >
              保存
            </button>
            <button
              type="button"
              onClick={() => setEditingFlow(null)}
              className="ml-2 px-3 py-1 border rounded text-sm"
            >
              取消
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            <div className="text-sm font-medium text-gray-700 mb-2">步骤顺序</div>
            {steps.map((step, i) => (
              <div
                key={i}
                className="py-2 border-b border-gray-100 space-y-1"
              >
                <div className="flex items-center gap-2">
                  <span className="text-gray-400 w-6">{i + 1}.</span>
                  <span className="flex-1 text-sm">
                    {step.triggerKeywords && (
                      <span className="text-gray-600">{step.triggerKeywords} → </span>
                    )}
                    {EVENT_TYPE_NAMES[step.eventType] || step.eventType}
                  </span>
                  <button
                    type="button"
                    onClick={() => moveStep(i, -1)}
                    disabled={i === 0}
                    className="p-1 text-gray-500 disabled:opacity-30"
                  >
                    <ChevronUp size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => moveStep(i, 1)}
                    disabled={i === steps.length - 1}
                    className="p-1 text-gray-500 disabled:opacity-30"
                  >
                    <ChevronDown size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => removeStepFromEditing(i)}
                    className="p-1 text-red-500"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="flex items-center gap-2 pl-6">
                  <span className="text-xs text-gray-500">本步输入来源：</span>
                  <select
                    value={
                      step.inputSource === undefined
                        ? (i === 0 ? 'original' : String(i - 1))
                        : step.inputSource === 'original'
                          ? 'original'
                          : String(step.inputSource)
                    }
                    onChange={(e) => {
                      const val = e.target.value;
                      const s = [...editingFlow.steps];
                      s[i] = {
                        ...s[i],
                        inputSource: val === 'original' ? 'original' : (parseInt(val, 10) as number),
                      };
                      setEditingFlow({ ...editingFlow, steps: s });
                    }}
                    className="text-xs border rounded px-2 py-0.5"
                  >
                    <option value="original">原始输入</option>
                    {Array.from({ length: i }, (_, j) => (
                      <option key={j} value={j}>
                        步骤{j + 1}输出
                      </option>
                    ))}
                  </select>
                </div>
                {step.eventType === 'open_sidebar_compare' && (
                  <div className="text-xs text-amber-600 pl-6">
                    对比时上一步输入需用 “---NETLIST2---” 分隔两个网表
                  </div>
                )}
              </div>
            ))}
            <div className="mt-3">
              <div className="text-sm font-medium text-gray-700 mb-2">添加步骤</div>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="text-xs text-gray-500">按事件类型添加：</span>
                <select
                  className="text-sm border rounded px-2 py-1"
                  value=""
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v) {
                      addStepByType(v);
                      e.target.value = '';
                    }
                  }}
                >
                  <option value="">选择事件类型…</option>
                  {Object.entries(EVENT_TYPE_NAMES).map(([type, name]) => (
                    <option key={type} value={type}>
                      {name}
                    </option>
                  ))}
                </select>
                <span className="text-xs text-gray-400">（含硬件分析结果聚合等，无需先配置触发词）</span>
              </div>
              {loadingTriggers ? (
                <div className="text-sm text-gray-500">加载中…</div>
              ) : (
                <>
                  <div className="text-xs text-gray-500 mb-1">从已配置的触发事件添加：</div>
                  <div className="flex flex-wrap gap-2">
                    {triggers.map((t) => (
                      <button
                        key={t.keywords + t.eventType}
                        type="button"
                        onClick={() => addStepToEditing(t)}
                        className="px-3 py-1.5 border rounded-lg text-sm hover:bg-gray-100"
                      >
                        {t.keywords}（{EVENT_TYPE_NAMES[t.eventType] || t.eventType}）
                      </button>
                    ))}
                    {triggers.length === 0 && (
                      <span className="text-sm text-gray-500">
                        暂无事件触发，请先在「事件触发管理」中添加，或使用上方按类型添加
                      </span>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 运行中：步骤进度与 插入文本 / 下一步 */}
      {runState && (
        <div className="flex flex-col h-full overflow-hidden">
          <div className="flex-shrink-0 p-3 border-b bg-blue-50">
            <h3 className="font-semibold text-gray-800">{runState.flow.name}</h3>
            <div className="text-xs text-gray-600 mt-1">
              {runState.stepIndex >= runState.flow.steps.length
                ? `全部 ${runState.flow.steps.length} 步已完成`
                : runState.stepIndex === 0
                  ? `步骤 1/${runState.flow.steps.length} 执行中…`
                  : `第 ${runState.stepIndex} 步已完成，共 ${runState.flow.steps.length} 步`}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {runState.stepResults.map((res, i) => (
              <div key={i} className="border rounded p-2 bg-gray-50 text-sm">
                <div className="text-gray-500 text-xs mb-1">步骤 {i + 1} 结果</div>
                <pre className="whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
                  {res.slice(0, 500)}
                  {res.length > 500 ? '…' : ''}
                </pre>
              </div>
            ))}
          </div>
          <div className="flex-shrink-0 p-3 border-t bg-white flex flex-wrap gap-2">
            {runState.stepIndex >= runState.flow.steps.length ? (
              <>
                <span className="text-green-600 text-sm font-medium">事件流执行完成</span>
                <button
                  type="button"
                  onClick={() => setRunState(null)}
                  className="px-3 py-1.5 border rounded-lg text-sm"
                >
                  关闭
                </button>
              </>
            ) : waitingForResponse ? (
              <span className="text-gray-500 text-sm">等待 AI 回复…</span>
            ) : (
              <>
                <button
                  type="button"
                  onClick={openInsertText}
                  className="inline-flex items-center gap-1 px-3 py-1.5 border rounded-lg text-sm hover:bg-gray-50"
                >
                  <FileText size={14} />
                  插入文本
                </button>
                <button
                  type="button"
                  onClick={handleNextStep}
                  className="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-500 text-white rounded-lg text-sm hover:bg-blue-600"
                >
                  <Send size={14} />
                  继续执行
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* 运行前：输入初始文本 */}
      {runInputModal && !runState && (
        <div className="absolute inset-0 bg-black/30 flex items-center justify-center z-20 p-4">
          <div className="bg-white rounded-lg shadow-lg w-full max-w-lg p-4">
            <h4 className="font-medium text-gray-800 mb-2">输入初始文本（将用于事件流第一步）</h4>
            {runInputModal.steps[0]?.eventType === 'open_sidebar_analyze' && (
              <p className="text-xs text-gray-600 mb-2">
                网表解析：支持在下方<strong>输入或粘贴网表</strong>，或点击<strong>「导入文件」</strong>上传网表文件（.asc / .txt）
              </p>
            )}
            <input
              type="file"
              ref={runInputFileRef}
              accept=".asc,.txt,.net,.cir"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  const reader = new FileReader();
                  reader.onload = (ev) => {
                    const text = (ev.target?.result as string) || '';
                    setRunInputValue(text);
                  };
                  reader.onerror = () => { alert('文件读取失败'); };
                  reader.readAsText(file, 'UTF-8');
                }
                e.target.value = '';
              }}
            />
            <div className="flex gap-2 mb-2">
              <textarea
                value={runInputValue}
                onChange={(e) => setRunInputValue(e.target.value)}
                placeholder="粘贴或输入内容，例如网表文本……"
                className="flex-1 border rounded-lg p-2 min-h-[120px] text-sm"
                rows={6}
              />
              <button
                type="button"
                onClick={() => runInputFileRef.current?.click()}
                className="self-start px-3 py-1.5 border border-blue-500 text-blue-600 rounded-lg text-sm hover:bg-blue-50 whitespace-nowrap"
                title="从文件导入网表"
              >
                导入文件
              </button>
            </div>
            <div className="flex justify-end gap-2 mt-3">
              <button
                type="button"
                onClick={() => { setRunInputModal(null); setRunInputValue(''); }}
                className="px-3 py-1.5 border rounded-lg text-sm"
              >
                取消
              </button>
              <button
                type="button"
                disabled={!runInputValue.trim()}
                onClick={() => {
                  if (runInputValue.trim()) {
                    startRun(runInputModal, runInputValue.trim());
                    setRunInputModal(null);
                    setRunInputValue('');
                  }
                }}
                className="px-3 py-1.5 bg-blue-500 text-white rounded-lg text-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                开始执行
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 插入文本弹窗 */}
      {insertTextModal && (
        <div className="absolute inset-0 bg-black/30 flex items-center justify-center z-20 p-4">
          <div className="bg-white rounded-lg shadow-lg w-full max-w-md p-4">
            <h4 className="font-medium text-gray-800 mb-2">插入文本（将作为下一步的输入）</h4>
            {runState && runState.flow.steps[runState.stepIndex]?.eventType === 'open_sidebar_analyze' && (
              <p className="text-xs text-gray-600 mb-2">网表解析步骤：可输入/粘贴网表，或点击「导入文件」</p>
            )}
            <input
              type="file"
              ref={insertTextFileRef}
              accept=".asc,.txt,.net,.cir"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  const reader = new FileReader();
                  reader.onload = (ev) => {
                    const text = (ev.target?.result as string) || '';
                    setInsertTextValue(text);
                  };
                  reader.onerror = () => { alert('文件读取失败'); };
                  reader.readAsText(file, 'UTF-8');
                }
                e.target.value = '';
              }}
            />
            <div className="flex gap-2 mb-2">
              <textarea
                value={insertTextValue}
                onChange={(e) => setInsertTextValue(e.target.value)}
                placeholder="可选：输入补充内容后点击确定，下一步将使用此内容；留空则继续使用当前内容"
                className="flex-1 border rounded-lg p-2 min-h-[80px] text-sm"
                rows={4}
              />
              <button
                type="button"
                onClick={() => insertTextFileRef.current?.click()}
                className="self-start px-3 py-1.5 border border-blue-500 text-blue-600 rounded-lg text-sm hover:bg-blue-50 whitespace-nowrap"
                title="从文件导入"
              >
                导入文件
              </button>
            </div>
            <div className="flex justify-end gap-2 mt-3">
              <button
                type="button"
                onClick={() => {
                  setInsertTextModal(false);
                  setInsertTextValue('');
                }}
                className="px-3 py-1.5 border rounded-lg text-sm"
              >
                取消
              </button>
              <button
                type="button"
                onClick={submitInsertText}
                className="px-3 py-1.5 bg-blue-500 text-white rounded-lg text-sm"
              >
                确定并下一步
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
