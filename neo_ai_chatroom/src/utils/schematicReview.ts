/** 原理图 AI 审核：工作流常量与网表清洗 */

import type { AIConfig } from '@/types';

export type SchematicWorkflowTab = 'import' | 'clean' | 'review' | 'export';

export const SCHEMATIC_WORKFLOW_STEPS: {
  id: string;
  order: number;
  label: string;
  tab: SchematicWorkflowTab | null;
  trackCompletion?: boolean;
  external?: boolean;
}[] = [
  { id: 'import', order: 1, label: '导入网表', tab: 'import', trackCompletion: true },
  { id: 'clean', order: 2, label: '网表清洗', tab: 'clean', trackCompletion: true },
  { id: 'review', order: 3, label: 'AI评审与报告', tab: 'review', trackCompletion: true },
  { id: 'export', order: 4, label: '报告预览与导出', tab: 'export', trackCompletion: true },
  { id: 'chat', order: 5, label: '与AI对话（可选）', tab: null, trackCompletion: false, external: true },
];

export const SCHEMATIC_REVIEW_PROMPT_KEY = 'neo-schematic-review-prompt';

export const DEFAULT_SCHEMATIC_REVIEW_PROMPT = `你是一名资深硬件工程师，请对以下网表进行原理图/接口评审。
请严格以 JSON 格式输出，包含 overall_status、summary、complete、interfaces（含 checks 数组，每项含 check_name、status、description）。
status 仅使用 PASS、WARNING、INFO、FAIL 四种。
若单次输出无法覆盖全部接口检查，请设 "complete": false 并输出已完成的 interfaces；续写轮次使用 "continuation": true 且仅输出新增检查项，不要重复已输出内容。全部完成时设 "complete": true。`;

/** Step1–3 单次 AI 输出 token 上限（与后端模型硬上限对齐） */
export const SCHEMATIC_MAX_OUTPUT_TOKENS = 8192;

/** 评审续写最大轮次 */
export const SCHEMATIC_REVIEW_MAX_ROUNDS = 10;

export const SCHEMATIC_POINTS_SESSION_PREFIX = 'neo-schematic-points-';

/** 原理图审核 Step1–4 默认 AI（管理员可在系统配置中修改） */
export const DEFAULT_SCHEMATIC_AI_ID = 'bailian-deepseekv4';

export interface SchematicAiModelOption {
  id: string;
  name: string;
  description: string;
}

/** Step1–4 锁定为默认模型；导出后（自由聊天）保留用户已选 */
export function applySchematicAiSelection(
  ais: AIConfig[],
  defaultAiId: string,
  reviewExported: boolean,
  previous?: AIConfig[]
): AIConfig[] {
  const filtered = ais.filter((ai) => ai.id !== 'babata');
  if (reviewExported) {
    if (previous?.length) {
      return filtered.map((ai) => {
        const prev = previous.find((p) => p.id === ai.id);
        return prev ? { ...ai, enabled: prev.enabled } : { ...ai, enabled: false };
      });
    }
    const hasEnabled = filtered.some((ai) => ai.enabled);
    if (!hasEnabled) {
      const pickId = filtered.some((ai) => ai.id === defaultAiId)
        ? defaultAiId
        : filtered[0]?.id;
      return filtered.map((ai) => ({ ...ai, enabled: ai.id === pickId }));
    }
    return filtered;
  }
  const pickId = filtered.some((ai) => ai.id === defaultAiId) ? defaultAiId : filtered[0]?.id;
  return filtered.map((ai) => ({ ...ai, enabled: ai.id === pickId }));
}

export function getSchematicReviewPrompt(): string {
  try {
    const saved = localStorage.getItem(SCHEMATIC_REVIEW_PROMPT_KEY);
    if (saved?.trim()) return saved.trim();
  } catch {
    /* ignore */
  }
  return DEFAULT_SCHEMATIC_REVIEW_PROMPT;
}

export function setSchematicReviewPrompt(prompt: string): void {
  localStorage.setItem(SCHEMATIC_REVIEW_PROMPT_KEY, prompt);
}

/** 从 AI 回复文本中提取原理图评审 JSON（兼容流式 DeepSeek 包装格式） */
export function parseSchematicReviewJson(content: string): any | null {
  if (!content || typeof content !== 'string') return null;

  let raw = content.trim();
  const finalAnswerMatch = raw.match(/\*\*最终回答：\*\*\s*([\s\S]*)/);
  if (finalAnswerMatch) raw = finalAnswerMatch[1].trim();

  const jsonBlock = raw.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (jsonBlock) raw = jsonBlock[1].trim();

  const tryObj = (text: string): any | null => {
    try {
      const obj = JSON.parse(text);
      if (!obj || typeof obj !== 'object') return null;
      if (Array.isArray(obj.interfaces) && (obj.summary != null || obj.overall_status != null || obj.power_rails != null)) {
        return obj;
      }
      if (obj.overall_status != null && Array.isArray(obj.interfaces)) return obj;
    } catch {
      /* ignore */
    }
    return null;
  };

  const direct = tryObj(raw);
  if (direct) return direct;

  const start = raw.indexOf('{');
  if (start < 0) return null;
  for (let end = raw.length; end > start; end--) {
    const slice = raw.slice(start, end).trim();
    const parsed = tryObj(slice);
    if (parsed) return parsed;
  }
  return null;
}

export interface SchematicPromptHistoryItem {
  id: string;
  content: string;
  note: string;
  created_by: string;
  created_at: string;
  is_current: boolean;
}

export interface SchematicPromptResponse {
  success: boolean;
  prompt: string;
  default_ai_id?: string;
  default_ai_name?: string;
  available_ai_models?: SchematicAiModelOption[];
  can_edit: boolean;
  current_id?: string | null;
  updated_at?: string | null;
  updated_by?: string | null;
  history?: SchematicPromptHistoryItem[];
  error?: string;
}

function escMarkdownTableCell(value: unknown): string {
  return String(value ?? '').replace(/\|/g, '/');
}

export function getNetConnectionList(net: {
  connections?: string[] | Record<string, unknown>;
}): string[] {
  const conns = net.connections;
  if (Array.isArray(conns)) return conns.map(String);
  if (conns && typeof conns === 'object') return Object.keys(conns);
  return [];
}

/** 全量连接，换行分隔（供 UI 展示） */
export function formatNetConnectionsFull(net: {
  connections?: string[] | Record<string, unknown>;
}): string {
  return getNetConnectionList(net).join('\n');
}

const STATUS_RANK: Record<string, number> = { PASS: 0, INFO: 1, WARNING: 2, FAIL: 3 };

function worstStatus(a: string, b: string): string {
  const ra = STATUS_RANK[a.toUpperCase()] ?? 1;
  const rb = STATUS_RANK[b.toUpperCase()] ?? 1;
  return ra >= rb ? a.toUpperCase() : b.toUpperCase();
}

function checkKey(iface: any, chk: any): string {
  const ifaceType = String(iface?.type ?? iface?.name ?? '接口');
  const name = String(chk?.check_name ?? chk?.name ?? '');
  return `${ifaceType}::${name}`;
}

export function isSchematicReviewComplete(parsed: any | null): boolean {
  if (!parsed || typeof parsed !== 'object') return false;
  if (parsed.complete === false) return false;
  if (!Array.isArray(parsed.interfaces)) return false;
  return true;
}

/** 合并多轮 AI 评审 JSON */
export function mergeSchematicReviewJson(parts: any[]): any {
  const mergedInterfaces: Record<string, { type: string; checks: any[] }> = {};
  const checkIndex: Record<string, [string, number]> = {};
  const summaries: string[] = [];
  let overall = 'PASS';

  for (const part of parts) {
    if (!part || typeof part !== 'object') continue;
    if (part.summary) summaries.push(String(part.summary).trim());
    overall = worstStatus(overall, String(part.overall_status ?? 'INFO'));
    for (const iface of part.interfaces || []) {
      if (!iface || typeof iface !== 'object') continue;
      const ifaceType = String(iface.type ?? iface.name ?? '接口');
      if (!mergedInterfaces[ifaceType]) {
        mergedInterfaces[ifaceType] = { type: ifaceType, checks: [] };
      }
      const target = mergedInterfaces[ifaceType];
      for (const chk of iface.checks || []) {
        if (!chk || typeof chk !== 'object') continue;
        const key = checkKey(iface, chk);
        if (key in checkIndex) {
          const [, idx] = checkIndex[key];
          target.checks[idx] = chk;
        } else {
          checkIndex[key] = [ifaceType, target.checks.length];
          target.checks.push(chk);
        }
      }
    }
  }

  return {
    overall_status: overall,
    summary: summaries.filter(Boolean).join('\n'),
    interfaces: Object.values(mergedInterfaces),
    complete: true,
  };
}

export function buildSchematicContinuationPrompt(
  priorParsed: any[],
  round: number
): string {
  const ifaceTypes = new Set<string>();
  for (const p of priorParsed) {
    for (const iface of p?.interfaces || []) {
      ifaceTypes.add(String(iface?.type ?? iface?.name ?? '接口'));
    }
  }
  const listed = [...ifaceTypes].slice(0, 30).join('、') || '（无）';
  return `【续写指令·第 ${round} 轮】上一轮原理图评审 JSON 未完整输出（可能因长度限制被截断）。
请从上次中断处继续，仅输出剩余部分的 JSON，格式示例：
{"continuation":true,"complete":false,"overall_status":"INFO","summary":"续写摘要","interfaces":[{"type":"接口类型","checks":[{"check_name":"...","status":"PASS","description":"..."}]}]}
不要重复已输出的检查项。已覆盖的接口类型包括：${listed}
若本轮已覆盖全部剩余检查，请设 "complete": true。`;
}

function countInterfaceNetCategories(interfaceNets: unknown): number {
  if (!interfaceNets) return 0;
  if (Array.isArray(interfaceNets)) return interfaceNets.length;
  if (typeof interfaceNets === 'object') return Object.keys(interfaceNets as Record<string, unknown>).length;
  return 0;
}

/** 将网表分析结果格式化为完整 Markdown（与后端 _format_analysis_result_for_chat 一致） */
export function formatAnalysisResultMarkdown(analysisResult: any, resultId?: string | null): string {
  if (!analysisResult) return '';
  const summary = analysisResult.summary || {};
  const nets: any[] = analysisResult.nets || [];
  const components: any[] = analysisResult.components || [];
  const powerNets: string[] = summary.power_nets || [];
  const differentialPairs = summary.differential_pairs || [];
  const interfaceCount = countInterfaceNetCategories(summary.interface_nets);
  const totalNets = summary.total_nets ?? nets.length;
  const totalComponents = summary.total_components ?? components.length;

  const lines: string[] = [
    '# 网表分析结果',
    '',
    `**分析摘要**：总元件 ${totalComponents} 个，总网络 ${totalNets} 个，电源网络 ${powerNets.length} 个，差分对 ${differentialPairs.length} 对，接口网络 ${interfaceCount} 类。${resultId ? `结果ID: \`${resultId}\`` : ''}`.trimEnd(),
    '',
  ];

  if (powerNets.length > 0) {
    lines.push('## 电源网络（供接口供电与地参考）');
    lines.push('');
    for (const name of powerNets) {
      lines.push(`- **${escMarkdownTableCell(name)}**`);
    }
    lines.push('');
  }

  if (differentialPairs.length > 0) {
    lines.push('## 差分对');
    lines.push('');
    for (const pair of differentialPairs) {
      lines.push(
        `- **${escMarkdownTableCell(pair.base_name)}**：+ ${escMarkdownTableCell(pair.positive)} / - ${escMarkdownTableCell(pair.negative)}`
      );
    }
    lines.push('');
  }

  const interfaceNets = summary.interface_nets;
  if (interfaceNets && typeof interfaceNets === 'object' && !Array.isArray(interfaceNets)) {
    lines.push('## 接口网络分类');
    lines.push('');
    for (const [ifaceType, netNames] of Object.entries(interfaceNets as Record<string, string[]>)) {
      if (!netNames?.length) continue;
      lines.push(`### ${escMarkdownTableCell(ifaceType)}`);
      for (const nn of netNames) {
        lines.push(`- ${escMarkdownTableCell(nn)}`);
      }
      lines.push('');
    }
  }

  const byType: Record<string, any[]> = {};
  for (const net of nets) {
    const type = net.type || 'Signal';
    if (!byType[type]) byType[type] = [];
    byType[type].push(net);
  }
  const typeOrder = ['Power', 'Clock', 'Signal'];

  lines.push('## 网络连接详情（按类型：Power → Clock → Signal）');
  lines.push('');

  const appendNetSection = (net: any) => {
    const connList = getNetConnectionList(net);
    const count = net.connection_count ?? connList.length;
    lines.push(
      `### ${escMarkdownTableCell(net.name)}（${escMarkdownTableCell(net.type || 'Signal')}，${count} 个连接）`
    );
    for (const ref of connList) {
      lines.push(`- ${escMarkdownTableCell(ref)}`);
    }
    lines.push('');
  };

  for (const type of typeOrder) {
    for (const net of byType[type] || []) appendNetSection(net);
  }
  for (const type of Object.keys(byType).sort()) {
    if (typeOrder.includes(type)) continue;
    for (const net of byType[type]) appendNetSection(net);
  }

  lines.push('## 元件列表（位号、类型、值、耐压/精度、封装）');
  lines.push('');
  lines.push('| 位号 | 类型 | 值 | 耐压/精度 | 封装 |');
  lines.push('| --- | --- | --- | --- | --- |');

  for (const comp of components) {
    const ctype = String(comp.type || '');
    let extra = '';
    if (ctype === 'Capacitor') {
      extra = comp.voltage_rating || '';
    } else if (ctype === 'Resistor') {
      extra = comp.tolerance || '';
    } else {
      extra = comp.voltage_rating || comp.tolerance || '';
    }
    lines.push(
      `| ${escMarkdownTableCell(comp.id ?? comp.ref)} | ${escMarkdownTableCell(comp.type)} | ${escMarkdownTableCell(comp.value)} | ${escMarkdownTableCell(extra)} | ${escMarkdownTableCell(comp.package)} |`
    );
  }

  lines.push('');
  lines.push('## 元件引脚连接');
  lines.push('');
  for (const comp of components) {
    const pins = comp.pins;
    if (!pins || typeof pins !== 'object' || !Object.keys(pins).length) continue;
    const ref = escMarkdownTableCell(comp.id ?? comp.ref);
    const meta = [comp.type, comp.value, comp.package].filter(Boolean).map(String).join('，');
    lines.push(`### ${ref}${meta ? `（${escMarkdownTableCell(meta)}）` : ''}`);
    for (const [pin, netName] of Object.entries(pins as Record<string, string>).sort(([a], [b]) =>
      String(a).localeCompare(String(b))
    )) {
      lines.push(`- ${escMarkdownTableCell(pin)} → ${escMarkdownTableCell(netName)}`);
    }
    lines.push('');
  }

  return lines.join('\n');
}

/** 从解析结果生成供 AI 消费的清洗文本 */
export function buildCleanedNetlistFromAnalysis(
  analysisResult: any,
  resultId?: string | null,
  formattedMarkdown?: string | null
): string {
  if (formattedMarkdown?.trim()) return formattedMarkdown.trim();
  return formatAnalysisResultMarkdown(analysisResult, resultId);
}

export function buildReportSummaryText(aggregated: any): string {
  if (!aggregated) return '';
  const merged = aggregated.mergedReview;
  if (merged?.interfaces) {
    const aiReviews = [{ parsed: merged }];
    return buildReportSummaryFromParsedList(aiReviews);
  }
  const aiReviews = Array.isArray(aggregated.aiReviews)
    ? aggregated.aiReviews
    : aggregated.aiReview
      ? [{ parsed: aggregated.aiReview }]
      : [];
  return buildReportSummaryFromParsedList(aiReviews);
}

function buildReportSummaryFromParsedList(
  aiReviews: Array<{ parsed?: any }>
): string {
  let pass = 0;
  let warning = 0;
  let info = 0;
  let fail = 0;
  const highlights: string[] = [];

  for (const item of aiReviews) {
    const p = item.parsed;
    if (!p?.interfaces) continue;
    for (const iface of p.interfaces) {
      for (const chk of iface.checks || []) {
        const s = String(chk?.status ?? 'INFO').toUpperCase();
        if (s === 'PASS') pass++;
        else if (s === 'WARNING') warning++;
        else if (s === 'FAIL') fail++;
        else info++;
        if ((s === 'WARNING' || s === 'FAIL') && highlights.length < 8) {
          highlights.push(`[${s}] ${chk.check_name ?? ''}: ${chk.description ?? ''}`);
        }
      }
    }
  }

  const lines = [
    `PASS: ${pass}, WARNING: ${warning}, INFO: ${info}${fail ? `, FAIL: ${fail}` : ''}`,
    ...highlights,
  ];
  return lines.join('\n');
}

export function hasSchematicPointsAwarded(resultId: string): boolean {
  try {
    return sessionStorage.getItem(`${SCHEMATIC_POINTS_SESSION_PREFIX}${resultId}`) === '1';
  } catch {
    return false;
  }
}

export function markSchematicPointsAwarded(resultId: string): void {
  try {
    sessionStorage.setItem(`${SCHEMATIC_POINTS_SESSION_PREFIX}${resultId}`, '1');
  } catch {
    /* ignore */
  }
}

export interface SchematicReviewCheckItem {
  checkId: string;
  status: string;
  title: string;
  description: string;
}

export type SchematicCheckDisposition = 'pending' | 'fixed' | 'ignored';

export interface SchematicCheckDispositionRecord {
  disposition: SchematicCheckDisposition;
  note?: string;
  updatedAt: string;
}

export type SchematicCheckDispositionMap = Record<string, SchematicCheckDispositionRecord>;

export const SCHEMATIC_DISPOSITION_PREFIX = 'neo-schematic-dispositions-';

export const SCHEMATIC_DISPOSITION_LABELS: Record<SchematicCheckDisposition, string> = {
  pending: '待定',
  fixed: '已修复',
  ignored: '忽略并备注',
};

export function requiresUserDisposition(status: string): boolean {
  const s = status.toUpperCase();
  return s === 'WARNING' || s === 'INFO' || s === 'FAIL';
}

export function isWarningLikeStatus(status: string): boolean {
  const s = status.toUpperCase();
  return s === 'WARNING' || s === 'FAIL';
}

export function getCheckCardClassName(status: string): string {
  const s = status.toUpperCase();
  if (s === 'PASS') return 'bg-green-50 border-green-500 text-green-900';
  if (s === 'INFO') return 'bg-sky-50 border-sky-400 text-sky-950';
  return 'bg-red-50 border-red-500 text-red-900';
}

export function getDispositionStorageKey(resultId: string | null, aggregatedAt?: string | null): string {
  const rid = resultId || 'session';
  const at = aggregatedAt || 'latest';
  return `${SCHEMATIC_DISPOSITION_PREFIX}${rid}::${at}`;
}

export function loadCheckDispositions(storageKey: string): SchematicCheckDispositionMap {
  try {
    const raw = sessionStorage.getItem(storageKey);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export function saveCheckDispositions(storageKey: string, map: SchematicCheckDispositionMap): void {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

export function formatDispositionForReport(
  record: SchematicCheckDispositionRecord | undefined
): string {
  if (!record) return '未处置';
  const label = SCHEMATIC_DISPOSITION_LABELS[record.disposition];
  if (record.note?.trim()) return `${label}（${record.note.trim()}）`;
  return label;
}

export function collectAiChecksFromAggregated(aggregated: any): SchematicReviewCheckItem[] {
  const aiChecks: SchematicReviewCheckItem[] = [];
  if (!aggregated) return aiChecks;

  const parsedSource =
    aggregated.mergedReview ??
  (Array.isArray(aggregated.aiReviews) && aggregated.aiReviews.length
      ? mergeSchematicReviewJson(aggregated.aiReviews.map((e: any) => e.parsed).filter(Boolean))
      : aggregated.aiReview);

  if (!parsedSource?.interfaces) return aiChecks;

  parsedSource.interfaces.forEach((iface: any, ifaceIdx: number) => {
    const ifaceType = String(iface?.type ?? '接口');
    (iface.checks || []).forEach((chk: any, chkIdx: number) => {
      const status = String(chk?.status ?? 'INFO').toUpperCase() || 'INFO';
      const name = String(chk?.check_name ?? '');
      const desc = String(chk?.description ?? '');
      aiChecks.push({
        checkId: `c-0-${ifaceIdx}-${chkIdx}`,
        status,
        title: name ? `${ifaceType} · ${name}` : ifaceType,
        description: desc,
      });
    });
  });
  return aiChecks;
}
