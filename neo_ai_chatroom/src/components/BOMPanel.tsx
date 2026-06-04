import React, { useState, useEffect, useRef, useMemo } from 'react';
import * as XLSX from 'xlsx';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { apiUrl } from '@/utils/apiBase';
import { printHtmlDocument, getPrintMessage } from '@/utils/externalOpen';
import { trackNeoPoints } from '@/utils/neoPoints';
import type { BOMState, BOMItem, BOMDesignatorTagIssue } from '@/utils/bomStore';
import { fetchMaterialLibraries, buildCodeToGroupLabel } from '@/utils/materialDb';

/** 替换对检查：单个物料在替换组中的检查结果 */
export interface BOMReplacementCheckItem {
  code: string;
  name?: string;
  /** 是否在当前 BOM 中出现 */
  inBom: boolean;
  /** 若在 BOM 中，汇总数量 */
  bomQuantity?: number;
  /** 若在 BOM 中，所有位号 */
  bomDesignators?: string[];
}

/** 替换对检查：单个替换组的检查结果 */
export interface BOMReplacementCheckGroup {
  id: string;
  remark?: string;
  /** 本替换组下的所有物料检查结果（包含已在 BOM 中和缺失的） */
  items: BOMReplacementCheckItem[];
}
import { saveBOM, loadBOM, computeGroupKey } from '@/utils/bomStore';
import {
  PLM_TEMPLATE_HEADERS,
  convertRowsToPlmFormat,
  formatDesignatorsForPlm,
  writePlmXlsxFile,
} from '@/utils/plmBomFormat';

type TabKey = 'import' | 'match' | 'group' | 'replacement' | 'optimize';

/** BOM AI CHECK 线性流程步骤（用于进度展示与导出）
 * trackCompletion: false 表示暂不参与「已完成变绿」（仅展示为进行中）
 */
const BOM_WORKFLOW_STEP_META: {
  id: string;
  order: number;
  label: string;
  tab: TabKey;
  trackCompletion?: boolean;
}[] = [
  { id: 'import', order: 1, label: '导入并生成 BOM', tab: 'import' },
  { id: 'match', order: 2, label: '物料匹配', tab: 'match' },
  { id: 'group', order: 3, label: '替代组验证', tab: 'group' },
  { id: 'replacement', order: 4, label: '替换对检查', tab: 'replacement' },
  {
    id: 'optimize',
    order: 5,
    label: '最终 BOM 预览（AI CHECK）',
    tab: 'optimize',
    trackCompletion: false,
  },
];

export type { BOMDesignatorTagIssue };

export interface BOMMatchRow {
  code: string;
  name: string;
  quantity: number;
  designators: string[];
  qtyCheck: string;
  libMatch: string;
}

export interface BOMMatchGroup {
  label: string;
  badge: '🟥' | '🟨' | '🟢';
  labelSummary: string;
  issues: string[];
  designators: string[];
  rows: BOMMatchRow[];
}

/** 替代组验证：物料库中同替代组但 BOM 中缺失的物料（自动增加并标红 INFO） */
export interface BOMGroupValidateMissingItem {
  code: string;
  name: string;
  libName: string;
  groupLabel: string;
}

/** 替代组验证：单个替代组的验证结果 */
export interface BOMGroupValidateGroup {
  label: string;
  labelConsistent: boolean;
  labelConflictMessage?: string;
  libLabel?: string;
  missingInBom: BOMGroupValidateMissingItem[];
  rows: BOMMatchRow[];
}

interface BOMPanelProps {
  /** 是否收起右侧栏 */
  collapsed: boolean;
  onCollapseToggle: () => void;
  /** BOM 物料匹配结果，用于「物料匹配」标签页展示 */
  matchGroups?: BOMMatchGroup[] | null;
  /** 同位号替代组标签检查结果 */
  matchDesignatorIssues?: BOMDesignatorTagIssue[] | null;
  /** 当 BOM 导入并生成后，自动触发物料匹配 */
  onAutoMatch?: () => void;
  /** 用户在右侧手动点击触发物料匹配 */
  onRunMatch?: () => void;
  /** 替代组验证结果 */
  groupValidateGroups?: BOMGroupValidateGroup[] | null;
  /** 用户点击触发替代组验证 */
  onRunGroupValidate?: () => void;
  /** 替换对检查结果 */
  replacementCheckGroups?: BOMReplacementCheckGroup[] | null;
  /** 用户点击触发替换对检查 */
  onRunReplacementCheck?: () => void;
  /** 是否在容器中占满可用宽度（用于折叠聊天室后拉伸 BOM 面板） */
  fullWidth?: boolean;
}

export const BOMPanel: React.FC<BOMPanelProps> = ({
  collapsed,
  onCollapseToggle,
  matchGroups,
  matchDesignatorIssues,
  onAutoMatch,
  onRunMatch,
  groupValidateGroups,
  onRunGroupValidate,
  replacementCheckGroups,
  onRunReplacementCheck,
  fullWidth = false,
}) => {
  const primaryButtonClass =
    'px-4 py-2.5 rounded-xl text-sm font-semibold border border-blue-600 bg-blue-600 text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:border-gray-300 disabled:cursor-not-allowed disabled:text-white transition shadow-sm';
  const secondaryButtonClass =
    'px-4 py-2.5 rounded-xl text-sm font-semibold border border-sky-300 bg-white text-sky-700 hover:bg-sky-50 disabled:border-gray-300 disabled:text-gray-400 disabled:cursor-not-allowed transition';
  const successButtonClass =
    'px-4 py-2.5 rounded-xl text-sm font-semibold border border-emerald-400 bg-emerald-500 text-white hover:bg-emerald-600 transition shadow-sm';
  const sectionToggleButtonClass =
    'w-full flex items-center justify-between px-4 py-3 border-b bg-sky-50 hover:bg-sky-100 rounded-t-lg transition';

  const [activeTab, setActiveTab] = useState<TabKey>('import');
  const [bomState, setBomState] = useState<BOMState | null>(null);
  const [fileName, setFileName] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  // 原始表头与数据，用于手动映射
  const [rawHeader, setRawHeader] = useState<string[] | null>(null);
  const [rawRows, setRawRows] = useState<string[][]>([]);
  const [mapCodeIdx, setMapCodeIdx] = useState<number>(-1);
  const [mapNameIdx, setMapNameIdx] = useState<number>(-1);
  const [mapQtyIdx, setMapQtyIdx] = useState<number>(-1);
  const [mapDesIdx, setMapDesIdx] = useState<number>(-1);
  const [reachRequired, setReachRequired] = useState(false);
  const [rohsRequired, setRohsRequired] = useState(false);
  const [filterCode, setFilterCode] = useState('');
  const [filterName, setFilterName] = useState('');
  const [filterDes, setFilterDes] = useState('');
  const [desSepPreset, setDesSepPreset] = useState<'auto' | 'comma' | 'space' | 'semicolon' | 'custom'>('auto');
  const [desSepCustom, setDesSepCustom] = useState<string>(',');
  const [matchFilterCode, setMatchFilterCode] = useState('');
  const [matchFilterName, setMatchFilterName] = useState('');
  const [matchFilterDes, setMatchFilterDes] = useState('');
  const [matchPassCollapsed, setMatchPassCollapsed] = useState(true);
  const [matchWarnCollapsed, setMatchWarnCollapsed] = useState(false);
  const [matchDesignatorCollapsed, setMatchDesignatorCollapsed] = useState(false);
  const [expandedDesignatorRows, setExpandedDesignatorRows] = useState<Record<string, boolean>>({});

  type OptimizeLevel = 'INFO';
  type OptimizeStatus = 'pending' | 'accepted' | 'ignored';

  interface BOMOptimizeRow {
    id: string;
    level: OptimizeLevel;
    source: 'match' | 'group' | 'replacement';
    groupLabel?: string;
    row: BOMMatchRow;
    status: OptimizeStatus;
    ignoreReason?: string;
  }

  // 替代组验证 / 替换对检查中缺失物料的处理决策：待定 / 接受 / 忽略（需原因）
  type GroupMissingDecisionStatus = 'pending' | 'accepted' | 'ignored';

  // 物料匹配中「⚠️ 未在物料库中找到」行的处理决策：待定 / 新器件 / 忽略（需原因）
  type MatchLibMissingDecisionStatus = 'pending' | 'accepted' | 'ignored';

  const MATCH_LIB_MISSING_DECISIONS_STORAGE_KEY = 'bom_match_lib_missing_decisions_v1';
  const GROUP_LABEL_CONFLICT_DECISIONS_STORAGE_KEY =
    'bom_group_label_conflict_decisions_v1';
  const DESIGNATOR_TAG_CONFLICT_DECISIONS_STORAGE_KEY =
    'bom_designator_tag_conflict_decisions_v1';

  const [optimizeRows, setOptimizeRows] = useState<BOMOptimizeRow[]>([]);
  const [groupMissingDecisions, setGroupMissingDecisions] = useState<
    Record<string, { status: GroupMissingDecisionStatus; reason?: string }>
  >({});
  const [matchLibMissingDecisions, setMatchLibMissingDecisions] = useState<
    Record<string, { status: MatchLibMissingDecisionStatus; reason?: string }>
  >({});
  const [groupLabelConflictDecisions, setGroupLabelConflictDecisions] = useState<
    Record<string, { status: GroupMissingDecisionStatus; reason?: string }>
  >({});
  const [designatorTagConflictDecisions, setDesignatorTagConflictDecisions] = useState<
    Record<string, { status: GroupMissingDecisionStatus; reason?: string }>
  >({});
  const [optimizeInfoCollapsed, setOptimizeInfoCollapsed] = useState(false);
  const [optimizeDoneCollapsed, setOptimizeDoneCollapsed] = useState(false);
  const [optimizePassCollapsed, setOptimizePassCollapsed] = useState(false);
  /** PLM 格式整理：父项编码 / 父项标准描述（与 BOM_TOOL 独立工具一致） */
  const [plmParentCode, setPlmParentCode] = useState('');
  const [plmParentStdDesc, setPlmParentStdDesc] = useState('');
  const [plmExporting, setPlmExporting] = useState(false);

  const optimizeRowsDerived = useMemo<BOMOptimizeRow[]>(() => {
    const rows: BOMOptimizeRow[] = [];

    // 1) 物料匹配中的非通过组里，物料库未匹配到的物料：逐行展开，统一归为 INFO
    if (matchGroups && matchGroups.length > 0) {
      matchGroups.forEach((g, gi) => {
        if (g.badge === '🟢') return;
        g.rows.forEach((r, ri) => {
          if (!r.libMatch.startsWith('⚠️ 未在物料库中找到')) {
            return;
          }
          const decisionKey = `match-missing::${g.label || '未分组'}::${r.code}::${ri}`;
          const decision = matchLibMissingDecisions[decisionKey];
          let status: OptimizeStatus = 'pending';
          let ignoreReason: string | undefined;
          if (decision && decision.status !== 'pending') {
            status = decision.status === 'accepted' ? 'accepted' : 'ignored';
            if (decision.status === 'ignored') {
              ignoreReason = decision.reason?.trim() || undefined;
            }
          }
          rows.push({
            id: `match-${gi}-${ri}`,
            level: 'INFO',
            source: 'match',
            groupLabel: g.label,
            row: r,
            status,
            ignoreReason,
          });
        });
      });
    }

    // 1b) 同位号替代组标签不一致
    if (matchDesignatorIssues && matchDesignatorIssues.length > 0 && matchGroups) {
      const conflictIssues = matchDesignatorIssues.filter((i) => i.kind === 'tag_conflict');
      conflictIssues.forEach((issue, di) => {
        const decisionKey = `designator-tag-conflict::${issue.designator}`;
        const decision = designatorTagConflictDecisions[decisionKey];
        let status: OptimizeStatus = 'pending';
        let ignoreReason: string | undefined;
        if (decision && decision.status !== 'pending') {
          status = decision.status === 'accepted' ? 'accepted' : 'ignored';
          if (decision.status === 'ignored') {
            ignoreReason = decision.reason?.trim() || undefined;
          }
        }
        const groupLabel = `位号 ${issue.designator}：${issue.message}`;
        issue.codes.forEach((code, ci) => {
          let foundRow: BOMMatchRow | undefined;
          for (const g of matchGroups) {
            foundRow = g.rows.find((r) => r.code === code);
            if (foundRow) break;
          }
          if (!foundRow) return;
          rows.push({
            id: `designator-conflict-${di}-${ci}`,
            level: 'INFO',
            source: 'match',
            groupLabel,
            row: foundRow,
            status,
            ignoreReason,
          });
        });
      });
    }

    // 2) 替代组验证：标签不一致的组 & 缺失物料
    if (groupValidateGroups && groupValidateGroups.length > 0) {
      groupValidateGroups.forEach((g, gi) => {
        // 标签不一致：将该组已有 BOM 行都视为需要关注的 INFO
        if (!g.labelConsistent && g.rows.length > 0) {
          const decisionKey = `group-label-conflict::${g.label || '未分组'}`;
          const decision = groupLabelConflictDecisions[decisionKey];
          let status: OptimizeStatus = 'pending';
          let ignoreReason: string | undefined;
          if (decision && decision.status !== 'pending') {
            status = decision.status === 'accepted' ? 'accepted' : 'ignored';
            if (decision.status === 'ignored') {
              ignoreReason = decision.reason?.trim() || undefined;
            }
          }
          g.rows.forEach((r, ri) => {
            rows.push({
              id: `group-conflict-${gi}-${ri}`,
              level: 'INFO',
              source: 'group',
              groupLabel: g.label,
              row: r,
              status,
              ignoreReason,
            });
          });
        }
        // 缺失物料：构造虚拟行，标为 INFO，并结合在“替代组验证”中的处理决策
        if (g.missingInBom && g.missingInBom.length > 0) {
          g.missingInBom.forEach((m, mi) => {
            const fakeRow: BOMMatchRow = {
              code: m.code,
              name: m.name,
              quantity: 0,
              designators: [],
              qtyCheck: '—',
              libMatch: `来自 ${m.libName}，替代组 ${m.groupLabel}，BOM 缺失`,
            };

            const decisionKey = `${g.label || '未分组'}__${m.code}__${mi}`;
            const decision = groupMissingDecisions[decisionKey];
            let status: OptimizeStatus = 'pending';
            let ignoreReason: string | undefined;
            if (decision && decision.status !== 'pending') {
              status = decision.status === 'accepted' ? 'accepted' : 'ignored';
              if (decision.status === 'ignored') {
                ignoreReason = decision.reason?.trim() || undefined;
              }
            }

            rows.push({
              id: `group-missing-${gi}-${mi}`,
              level: 'INFO',
              source: 'group',
              groupLabel: g.label,
              row: fakeRow,
              status,
              ignoreReason,
            });
          });
        }
      });
    }

    // 3) 替换对检查：缺失物料 -> 构造虚拟行，标为 INFO，并结合在“替换对检查”中的处理决策
    if (replacementCheckGroups && replacementCheckGroups.length > 0) {
      replacementCheckGroups.forEach((g, gi) => {
        const missing = g.items.filter((it) => !it.inBom);
        if (missing.length === 0) return;
        missing.forEach((m, mi) => {
          const fakeRow: BOMMatchRow = {
            code: m.code,
            name: m.name || '—',
            quantity: 0,
            designators: [],
            qtyCheck: '—',
            libMatch: '来自替换对检查：BOM 当前未包含',
          };

          const decisionKey = `${g.id || 'replacement'}__${m.code}__${mi}`;
          const decision = groupMissingDecisions[decisionKey];
          let status: OptimizeStatus = 'pending';
          let ignoreReason: string | undefined;
          if (decision && decision.status !== 'pending') {
            status = decision.status === 'accepted' ? 'accepted' : 'ignored';
            if (decision.status === 'ignored') {
              ignoreReason = decision.reason?.trim() || undefined;
            }
          }

          rows.push({
            id: `replacement-missing-${gi}-${mi}`,
            level: 'INFO',
            source: 'replacement',
            groupLabel: g.items
              .map((it) => (it.name ? `${it.code} ${it.name}` : it.code))
              .join(' / '),
            row: fakeRow,
            status,
            ignoreReason,
          });
        });
      });
    }

    return rows;
  }, [
    matchGroups,
    matchDesignatorIssues,
    groupValidateGroups,
    replacementCheckGroups,
    groupMissingDecisions,
    matchLibMissingDecisions,
    groupLabelConflictDecisions,
    designatorTagConflictDecisions,
  ]);
  useEffect(() => {
    setOptimizeRows(optimizeRowsDerived);
  }, [optimizeRowsDerived]);

  const bomDashboardReportTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const n = optimizeRows.length;
    if (bomDashboardReportTimer.current) clearTimeout(bomDashboardReportTimer.current);
    if (n <= 0) return;
    bomDashboardReportTimer.current = setTimeout(() => {
      axios.post(apiUrl('/api/dashboard/bom-info-report'), { info_count: n }).catch(() => {});
    }, 4000);
    return () => {
      if (bomDashboardReportTimer.current) clearTimeout(bomDashboardReportTimer.current);
    };
  }, [optimizeRows.length]);

  const bomWorkflowProgress = useMemo(() => {
    const step1Done = !!(bomState?.items?.length);
    const step2Done = matchGroups != null;
    const step3Done = groupValidateGroups != null;
    const step4Done = replacementCheckGroups != null;
    const step5Done =
      step4Done &&
      (optimizeRowsDerived.length === 0 ||
        optimizeRowsDerived.every((r) => r.status !== 'pending'));

    const doneFlags = [step1Done, step2Done, step3Done, step4Done, step5Done];
    const steps = BOM_WORKFLOW_STEP_META.map((meta, i) => ({
      ...meta,
      done:
        meta.trackCompletion === false
          ? false
          : doneFlags[i] ?? false,
    }));
    return { steps, doneFlags };
  }, [
    bomState?.items?.length,
    matchGroups,
    groupValidateGroups,
    replacementCheckGroups,
    optimizeRowsDerived,
  ]);

  const isWorkflowStepDoneForTab = (tab: TabKey) =>
    bomWorkflowProgress.steps.find((s) => s.tab === tab)?.done ?? false;

  const tabNavBtnClass = (tab: TabKey) =>
    `px-4 py-2.5 text-sm font-semibold rounded-xl border transition ${
      activeTab === tab
        ? 'bg-blue-600 text-white border-blue-600 shadow-sm'
        : isWorkflowStepDoneForTab(tab)
        ? 'bg-emerald-50 text-emerald-800 border-emerald-400 hover:bg-emerald-100'
        : 'bg-white text-gray-700 border-sky-200 hover:bg-sky-50'
    }`;

  useEffect(() => {
    try {
      if (typeof window === 'undefined') return;
      const raw = window.localStorage.getItem(MATCH_LIB_MISSING_DECISIONS_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') {
        setMatchLibMissingDecisions(parsed);
      }
    } catch (e) {
      console.error('加载物料匹配缺失物料决策失败', e);
    }
  }, []);

  useEffect(() => {
    try {
      if (typeof window === 'undefined') return;
      window.localStorage.setItem(
        MATCH_LIB_MISSING_DECISIONS_STORAGE_KEY,
        JSON.stringify(matchLibMissingDecisions)
      );
    } catch (e) {
      console.error('保存物料匹配缺失物料决策失败', e);
    }
  }, [matchLibMissingDecisions]);

  useEffect(() => {
    try {
      if (typeof window === 'undefined') return;
      const raw = window.localStorage.getItem(
        GROUP_LABEL_CONFLICT_DECISIONS_STORAGE_KEY
      );
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') {
        setGroupLabelConflictDecisions(parsed);
      }
    } catch (e) {
      console.error('加载替代组标签冲突决策失败', e);
    }
  }, []);

  useEffect(() => {
    try {
      if (typeof window === 'undefined') return;
      window.localStorage.setItem(
        GROUP_LABEL_CONFLICT_DECISIONS_STORAGE_KEY,
        JSON.stringify(groupLabelConflictDecisions)
      );
    } catch (e) {
      console.error('保存替代组标签冲突决策失败', e);
    }
  }, [groupLabelConflictDecisions]);

  useEffect(() => {
    try {
      if (typeof window === 'undefined') return;
      const raw = window.localStorage.getItem(
        DESIGNATOR_TAG_CONFLICT_DECISIONS_STORAGE_KEY
      );
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') {
        setDesignatorTagConflictDecisions(parsed);
      }
    } catch (e) {
      console.error('加载同位号替代组标签冲突决策失败', e);
    }
  }, []);

  useEffect(() => {
    try {
      if (typeof window === 'undefined') return;
      window.localStorage.setItem(
        DESIGNATOR_TAG_CONFLICT_DECISIONS_STORAGE_KEY,
        JSON.stringify(designatorTagConflictDecisions)
      );
    } catch (e) {
      console.error('保存同位号替代组标签冲突决策失败', e);
    }
  }, [designatorTagConflictDecisions]);

  const highlightText = (text: string, keyword: string) => {
    if (!keyword.trim()) return text;
    const lower = text.toLowerCase();
    const kw = keyword.toLowerCase();
    const parts: React.ReactNode[] = [];
    let idx = 0;
    let hitIndex = lower.indexOf(kw);
    let key = 0;
    while (hitIndex !== -1) {
      if (hitIndex > idx) {
        parts.push(text.slice(idx, hitIndex));
      }
      parts.push(
        <span key={`hl-${key++}`} className="bg-green-200">
          {text.slice(hitIndex, hitIndex + kw.length)}
        </span>
      );
      idx = hitIndex + kw.length;
      hitIndex = lower.indexOf(kw, idx);
    }
    if (idx < text.length) {
      parts.push(text.slice(idx));
    }
    return parts;
  };

  const escapeRegExp = (s: string) =>
    s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  const splitDesignators = (raw: string): string[] => {
    let regex: RegExp;
    if (desSepPreset === 'comma') {
      regex = /,+/;
    } else if (desSepPreset === 'space') {
      regex = /\s+/;
    } else if (desSepPreset === 'semicolon') {
      regex = /;+/;
    } else if (desSepPreset === 'custom' && desSepCustom.trim()) {
      regex = new RegExp('[' + escapeRegExp(desSepCustom.trim()) + ']+');
    } else {
      // auto：逗号 + 空格
      regex = /[,\s]+/;
    }
    return raw
      .split(regex)
      .map((d) => d.trim())
      .filter(Boolean);
  };

  useEffect(() => {
    const stored = loadBOM();
    if (stored) {
      setBomState(stored);
      setFileName(stored.sourceFileName || '');
    }
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    const ext = file.name.toLowerCase().split('.').pop() || '';
    const reader = new FileReader();
    reader.onerror = () => {
      alert('BOM 文件读取失败');
    };
    if (ext === 'xlsx' || ext === 'xls') {
      reader.onload = (ev) => {
        try {
          const data = new Uint8Array(ev.target?.result as ArrayBuffer);
          const wb = XLSX.read(data, { type: 'array' });
          const sheetName = wb.SheetNames[0];
          const sheet = wb.Sheets[sheetName];
          const aoa = XLSX.utils.sheet_to_json<string[]>(sheet, { header: 1, defval: '' });
          parseBOMFromAOA(aoa, file.name);
        } catch (err: any) {
          console.error('解析 Excel BOM 失败', err);
          alert(`解析 Excel BOM 失败：${err?.message || String(err)}`);
        }
      };
      reader.readAsArrayBuffer(file);
    } else {
      reader.onload = (ev) => {
        const text = (ev.target?.result as string) || '';
        parseBOMText(text, file.name);
      };
      reader.readAsText(file, 'UTF-8');
    }
    e.target.value = '';
  };

  const parseFromHeaderAndRows = async (header: string[], rows: string[][], source: string) => {
    const codeIdx = mapCodeIdx;
    const nameIdx = mapNameIdx;
    const qtyIdx = mapQtyIdx;
    const desIdx = mapDesIdx;
    if (codeIdx < 0 || qtyIdx < 0 || desIdx < 0) {
      alert('请先在映射区域选择物料代码 / 数量 / 位号三列。');
      return;
    }
    const items: BOMItem[] = [];
    for (const cols of rows) {
      const code = (cols[codeIdx] || '').trim();
      if (!code) continue;
      const name = nameIdx >= 0 ? (cols[nameIdx] || '').trim() : '';
      const qtyRaw = (cols[qtyIdx] || '').trim();
      const qty = parseFloat(qtyRaw || '0');
      const desRaw = (cols[desIdx] || '').trim();
      const designators = splitDesignators(desRaw);
      const item: BOMItem = {
        code,
        name: name || undefined,
        quantity: Number.isFinite(qty) && qty > 0 ? qty : designators.length || 0,
        designators,
      };
      item.groupKey = computeGroupKey(item.designators);
      items.push(item);
    }

    // 根据 MySQL 物料库中的「替代组标签」重写替代组（优先使用库中的分组）
    try {
      const libs = await fetchMaterialLibraries();
      const codeToGroup = buildCodeToGroupLabel(libs);
      if (Object.keys(codeToGroup).length > 0) {
        for (const item of items) {
          const g = codeToGroup[item.code];
          if (g) {
            item.groupKey = g;
          } else {
            item.groupKey = computeGroupKey(item.designators);
          }
        }
      }
    } catch (e) {
      console.error('根据物料库替代组标签设置 BOM 替代组失败', e);
    }
    const next: BOMState = {
      items,
      sourceFileName: source,
      importedAt: new Date().toISOString(),
      reachRequired,
      rohsRequired,
    };
    setBomState(next);
    saveBOM(next);
    if (onAutoMatch) {
      onAutoMatch();
    }
  };

  const parseBOMText = (text: string, source: string) => {
    const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
    if (lines.length <= 1) {
      alert('BOM 文件内容不足，请检查是否包含表头和数据行');
      return;
    }
    const header = lines[0].split(/,|\t|;/).map((h) => h.trim());
    const bodyRows = lines.slice(1).map((line) => line.split(/,|\t|;/));
    setRawHeader(header);
    setRawRows(bodyRows);
    // 清空上次映射，要求用户手动选择
    setMapCodeIdx(-1);
    setMapNameIdx(-1);
    setMapQtyIdx(-1);
    setMapDesIdx(-1);
  };

  const parseBOMFromAOA = (aoa: any[][], source: string) => {
    if (!aoa || aoa.length <= 1) {
      alert('Excel BOM 内容不足，请检查是否包含表头和数据行');
      return;
    }
    const header = (aoa[0] || []).map((h) => (h != null ? String(h).trim() : ''));
    const rows = aoa.slice(1).map((r) => r.map((c) => (c != null ? String(c) : '')));
    setRawHeader(header);
    setRawRows(rows);
    setMapCodeIdx(-1);
    setMapNameIdx(-1);
    setMapQtyIdx(-1);
    setMapDesIdx(-1);
  };

  const renderSummary = () => {
    if (!bomState) {
      return <div className="text-sm text-gray-500">尚未导入 BOM，请先在上方导入文件或粘贴内容。</div>;
    }
    const totalItems = bomState.items.length;
    const groups = new Set(bomState.items.map((i) => i.groupKey || i.code));
    const totalQty = bomState.items.reduce((sum, i) => sum + (i.quantity || 0), 0);
    return (
      <div className="text-xs text-gray-600 space-y-1">
        <div>物料行数：{totalItems}</div>
        <div>替代组数：{groups.size}</div>
        <div>总数量：{totalQty}</div>
        {bomState.sourceFileName && <div>来源文件：{bomState.sourceFileName}</div>}
        <div>导入时间：{new Date(bomState.importedAt).toLocaleString('zh-CN')}</div>
      </div>
    );
  };

  const renderImportTab = () => {
    const importRawLoaded = !!(rawHeader && rawHeader.length > 0 && rawRows.length > 0);
    const importMappingReady =
      importRawLoaded && mapCodeIdx >= 0 && mapQtyIdx >= 0 && mapDesIdx >= 0;
    const importBomGenerated = !!(bomState?.items?.length);

    return (
    <div className="p-3 space-y-3">
      <div className="rounded-xl border border-amber-200/80 bg-gradient-to-r from-amber-50/90 to-yellow-50/60 px-3 py-2.5">
        <div className="text-[11px] font-semibold text-amber-900 mb-2">
          BOM AI CHECK 流程进度（点击步骤可跳转对应页签）
        </div>
        <div className="flex flex-wrap gap-1.5">
          {bomWorkflowProgress.steps.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setActiveTab(s.tab)}
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
      <div className="rounded-lg border border-sky-100 bg-sky-50/40 px-3 py-2">
        <div className="text-[11px] font-semibold text-sky-900 mb-1.5">
          第 1 步 · 三个小步进度
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span
            className={`text-[11px] px-2 py-0.5 rounded-md border font-medium ${
              importRawLoaded
                ? 'border-emerald-500 bg-emerald-50 text-emerald-800'
                : 'border-gray-200 bg-white text-gray-600'
            }`}
          >
            1-1 载入源表 {importRawLoaded ? '✓' : '○'}
          </span>
          <span
            className={`text-[11px] px-2 py-0.5 rounded-md border font-medium ${
              importMappingReady
                ? 'border-emerald-500 bg-emerald-50 text-emerald-800'
                : 'border-gray-200 bg-white text-gray-600'
            }`}
          >
            1-2 列映射与规则 {importMappingReady ? '✓' : '○'}
          </span>
          <span
            className={`text-[11px] px-2 py-0.5 rounded-md border font-medium ${
              importBomGenerated
                ? 'border-emerald-500 bg-emerald-50 text-emerald-800'
                : 'border-gray-200 bg-white text-gray-600'
            }`}
          >
            1-3 生成结构化 BOM {importBomGenerated ? '✓' : '○'}
          </span>
        </div>
      </div>
      <div className="font-semibold text-sm text-gray-800">第 1 步 · 导入并生成 BOM</div>
      <div className="text-xs text-gray-500 -mt-2">
        支持 Excel / CSV / 文本（首行为表头）。按下方 1-1 → 1-2 → 1-3 顺序完成即可进入物料匹配。
      </div>

      <div className="border rounded-lg p-3 bg-white space-y-2">
        <div className="text-xs font-semibold text-gray-800">1-1 载入源表文件</div>
        <div className="text-[11px] text-gray-500">
          选择本地 BOM 文件，系统将读取表头与数据行；尚未生成结构化 BOM 前可反复更换文件。
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls,.csv,.txt"
            className="hidden"
            onChange={handleFileChange}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className={importRawLoaded ? successButtonClass : primaryButtonClass}
          >
            选择文件
          </button>
          {fileName ? (
            <span className="text-[11px] text-gray-600 truncate max-w-[240px]" title={fileName}>
              当前文件：{fileName}
            </span>
          ) : null}
        </div>
      </div>

      <div className="border rounded-lg p-3 bg-white">
        <div className="text-xs font-semibold text-gray-700 mb-1">当前 BOM 概要</div>
        {renderSummary()}
      </div>
      {rawHeader && rawHeader.length > 0 && (
        <div className="border rounded-lg p-3 bg-white space-y-3">
          <div className="text-xs font-semibold text-gray-800">1-2 列映射与字段规则</div>
          <div className="text-[11px] text-gray-500 -mt-2">
            将表格列对应到「物料代码 / 物料名称 / 数量 / 位号」，并设置位号分隔方式与 REACH / RoHS 标记。
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="text-xs">
              <div className="mb-1 text-gray-600">物料代码列（必选）</div>
              <select
                className="w-full border rounded px-2 py-1 text-xs"
                value={mapCodeIdx}
                onChange={(e) => setMapCodeIdx(parseInt(e.target.value, 10))}
              >
                <option value={-1}>请选择列</option>
                {rawHeader.map((h, idx) => (
                  <option key={idx} value={idx}>
                    {idx + 1}. {h || `列${idx + 1}`}
                  </option>
                ))}
              </select>
            </div>
            <div className="text-xs">
              <div className="mb-1 text-gray-600">物料名称列（可选）</div>
              <select
                className="w-full border rounded px-2 py-1 text-xs"
                value={mapNameIdx}
                onChange={(e) => setMapNameIdx(parseInt(e.target.value, 10))}
              >
                <option value={-1}>不使用</option>
                {rawHeader.map((h, idx) => (
                  <option key={idx} value={idx}>
                    {idx + 1}. {h || `列${idx + 1}`}
                  </option>
                ))}
              </select>
            </div>
            <div className="text-xs">
              <div className="mb-1 text-gray-600">数量列（必选）</div>
              <select
                className="w-full border rounded px-2 py-1 text-xs"
                value={mapQtyIdx}
                onChange={(e) => setMapQtyIdx(parseInt(e.target.value, 10))}
              >
                <option value={-1}>请选择列</option>
                {rawHeader.map((h, idx) => (
                  <option key={idx} value={idx}>
                    {idx + 1}. {h || `列${idx + 1}`}
                  </option>
                ))}
              </select>
            </div>
            <div className="text-xs">
              <div className="mb-1 text-gray-600">位号列（必选）</div>
              <select
                className="w-full border rounded px-2 py-1 text-xs"
                value={mapDesIdx}
                onChange={(e) => setMapDesIdx(parseInt(e.target.value, 10))}
              >
                <option value={-1}>请选择列</option>
                {rawHeader.map((h, idx) => (
                  <option key={idx} value={idx}>
                    {idx + 1}. {h || `列${idx + 1}`}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="mt-2 space-y-1 text-xs">
            <div className="font-semibold text-gray-700">位号分隔符</div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="inline-flex items-center gap-1">
                <input
                  type="radio"
                  checked={desSepPreset === 'auto'}
                  onChange={() => setDesSepPreset('auto')}
                />
                <span>自动（逗号 / 空格）</span>
              </label>
              <label className="inline-flex items-center gap-1">
                <input
                  type="radio"
                  checked={desSepPreset === 'comma'}
                  onChange={() => setDesSepPreset('comma')}
                />
                <span>逗号 ,</span>
              </label>
              <label className="inline-flex items-center gap-1">
                <input
                  type="radio"
                  checked={desSepPreset === 'space'}
                  onChange={() => setDesSepPreset('space')}
                />
                <span>空格</span>
              </label>
              <label className="inline-flex items-center gap-1">
                <input
                  type="radio"
                  checked={desSepPreset === 'semicolon'}
                  onChange={() => setDesSepPreset('semicolon')}
                />
                <span>分号 ;</span>
              </label>
              <label className="inline-flex items-center gap-1">
                <input
                  type="radio"
                  checked={desSepPreset === 'custom'}
                  onChange={() => setDesSepPreset('custom')}
                />
                <span>自定义</span>
              </label>
              {desSepPreset === 'custom' && (
                <input
                  value={desSepCustom}
                  onChange={(e) => setDesSepCustom(e.target.value)}
                  placeholder="例如 / 或 |"
                  className="border rounded px-2 py-1 text-xs w-28"
                />
              )}
            </div>
          </div>
          <div className="flex items-center gap-4 text-xs mt-2">
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={reachRequired}
                onChange={(e) => setReachRequired(e.target.checked)}
              />
              <span>满足 REACH</span>
            </label>
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={rohsRequired}
                onChange={(e) => setRohsRequired(e.target.checked)}
              />
              <span>满足 RoHS</span>
            </label>
          </div>
          <div className="border-t border-gray-100 pt-3 mt-1 space-y-1">
            <div className="text-xs font-semibold text-gray-800">1-3 生成结构化 BOM</div>
            <div className="text-[11px] text-gray-500">
              解析当前映射结果并写入系统 BOM（生成成功后即可进入第 2 步物料匹配）。
            </div>
            <div className="flex justify-end mt-1">
              <button
                type="button"
                className={
                  mapCodeIdx < 0 || mapQtyIdx < 0 || mapDesIdx < 0 || rawRows.length === 0
                    ? primaryButtonClass
                    : importBomGenerated
                    ? successButtonClass
                    : primaryButtonClass
                }
                disabled={mapCodeIdx < 0 || mapQtyIdx < 0 || mapDesIdx < 0 || rawRows.length === 0}
                onClick={() => {
                  if (!rawHeader || rawRows.length === 0) return;
                  void parseFromHeaderAndRows(rawHeader, rawRows, fileName || 'BOM');
                }}
              >
                生成 BOM
              </button>
            </div>
          </div>
        </div>
      )}
      {bomState && bomState.items.length > 0 && (
        <div className="border rounded-lg bg-white max-h-[60vh] overflow-auto">
          <div className="sticky top-0 z-10 px-2 pt-2 pb-1 border-b border-gray-200 bg-white">
            <div className="grid grid-cols-3 gap-2 text-xs">
              <input
                value={filterCode}
                onChange={(e) => setFilterCode(e.target.value)}
                placeholder="物料代码搜索"
                className="border rounded px-2 py-1"
              />
              <input
                value={filterName}
                onChange={(e) => setFilterName(e.target.value)}
                placeholder="物料描述搜索"
                className="border rounded px-2 py-1"
              />
              <input
                value={filterDes}
                onChange={(e) => setFilterDes(e.target.value)}
                placeholder="位号搜索"
                className="border rounded px-2 py-1"
              />
            </div>
          </div>
          <div className="divide-y divide-gray-200">
            {(() => {
              const matchesFilter = (item: BOMItem) => {
                if (filterCode && !item.code.toLowerCase().includes(filterCode.toLowerCase())) return false;
                if (filterName && !(item.name || '').toLowerCase().includes(filterName.toLowerCase())) return false;
                if (filterDes) {
                  const d = (item.designators || []).join(', ').toLowerCase();
                  if (!d.includes(filterDes.toLowerCase())) return false;
                }
                return true;
              };
              const filteredItems = bomState.items.filter(matchesFilter);
              const groups: Record<string, BOMItem[]> = {};
              for (const item of filteredItems) {
                const key = item.groupKey || item.code || '未分组';
                if (!groups[key]) groups[key] = [];
                groups[key].push(item);
              }
              const keys = Object.keys(groups).sort((a, b) => a.localeCompare(b));
              return keys.slice(0, 200).map((key) => {
                const items = groups[key];
                const allDesignators = Array.from(
                  new Set(items.flatMap((i) => i.designators || []).map((d) => d.trim()).filter(Boolean))
                ).sort((a, b) => a.localeCompare(b));
                const totalQty = items.reduce((sum, i) => sum + (i.quantity || 0), 0);
                const collapsed = collapsedGroups[key] ?? true;
                const fullDes = allDesignators.join(', ');
                const maxShown = 6;
                const shownDes = allDesignators.slice(0, maxShown);
                const restCount = allDesignators.length > maxShown ? allDesignators.length - maxShown : 0;
                // 显示用的替代组标签：优先用物料库标签；若为按位号拼出来的长串，则用位号摘要代替
                let groupLabel = key || '未分组';
                if (groupLabel.includes(',')) {
                  // 这是按位号 join 出来的 key，直接显示会很长，用位号摘要替代
                  if (allDesignators.length <= maxShown) {
                    groupLabel = allDesignators.join(', ');
                  } else {
                    groupLabel = `${shownDes.join(', ')} 等 ${allDesignators.length} 个位号`;
                  }
                } else if (groupLabel.length > 40) {
                  groupLabel = groupLabel.slice(0, 40) + '…';
                }
                return (
                  <div key={key}>
                    <button
                      type="button"
                      className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium bg-sky-50 hover:bg-sky-100 transition"
                      onClick={() =>
                        setCollapsedGroups((prev) => ({
                          ...prev,
                          [key]: !collapsed,
                        }))
                      }
                    >
                      <div className="flex flex-col gap-0.5 text-left">
                        <div className="flex items-center gap-2">
                          <span className="text-gray-700 font-semibold">
                            替代组：{groupLabel}
                          </span>
                          <span className="text-gray-500">
                            ({items.length} 个物料)
                          </span>
                        </div>
                        <div className="text-gray-500 text-[11px]" title={fullDes || undefined}>
                          位号（{allDesignators.length} 个）:
                          {' '}
                          {shownDes.join(', ') || '-'}
                          {restCount > 0 && `，等 ${restCount} 个已折叠`}
                        </div>
                      </div>
                      <span className="text-gray-400">{collapsed ? '展开' : '收起'}</span>
                    </button>
                    {!collapsed && (
                      <table className="min-w-full text-xs">
                        <thead className="bg-white">
                          <tr>
                            <th className="px-2 py-1 text-left">物料代码</th>
                            <th className="px-2 py-1 text-left">物料描述</th>
                            <th className="px-2 py-1 text-right">数量</th>
                            <th className="px-2 py-1 text-left">位号</th>
                          </tr>
                        </thead>
                        <tbody>
                          {items.map((item, idx) => (
                            <tr key={idx} className="border-t">
                              <td className="px-2 py-1">{item.code}</td>
                              <td className="px-2 py-1">{item.name || '-'}</td>
                              <td className="px-2 py-1 text-right">{item.quantity}</td>
                              <td className="px-2 py-1">{item.designators.join(', ')}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                );
              });
            })()}
          </div>
        </div>
      )}
    </div>
    );
  };

  const renderTabContent = () => {
    if (activeTab === 'import') return renderImportTab();
    if (activeTab === 'match') {
      if (!matchGroups || matchGroups.length === 0) {
        return (
          <div className="p-3 space-y-3 text-xs text-gray-500">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <span>物料匹配结果暂不可用，请先在聊天中触发事件或点击下方按钮。</span>
              <button
                type="button"
                disabled={!onRunMatch}
                onClick={() => onRunMatch && onRunMatch()}
                className={
                  isWorkflowStepDoneForTab('match') ? successButtonClass : secondaryButtonClass
                }
              >
                第 2 步 · 执行物料匹配
              </button>
            </div>
          </div>
        );
      }
      const filterRow = (r: BOMMatchRow) => {
        if (matchFilterCode && !r.code.toLowerCase().includes(matchFilterCode.toLowerCase())) return false;
        if (matchFilterName && !r.name.toLowerCase().includes(matchFilterName.toLowerCase())) return false;
        if (matchFilterDes) {
          const d = r.designators.join(', ').toLowerCase();
          if (!d.includes(matchFilterDes.toLowerCase())) return false;
        }
        return true;
      };
      const filteredGroups = matchGroups
        .map((g) => ({
          ...g,
          rows: g.rows.filter(filterRow),
        }))
        .filter((g) => g.rows.length > 0);
      const passGroups = filteredGroups.filter((g) => g.badge === '🟢');
      const warnGroups = filteredGroups.filter((g) => g.badge !== '🟢'); // 这里视为 INFO 组
      return (
        <div className="h-full flex flex-col text-xs">
          <div className="flex-shrink-0 px-3 pt-2 pb-2 border-b border-gray-200 bg-white sticky top-0 z-10">
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="grid grid-cols-3 gap-2 flex-1">
                <input
                  value={matchFilterCode}
                  onChange={(e) => setMatchFilterCode(e.target.value)}
                  placeholder="物料代码搜索"
                  className="border rounded px-2 py-1"
                />
                <input
                  value={matchFilterName}
                  onChange={(e) => setMatchFilterName(e.target.value)}
                  placeholder="物料描述搜索"
                  className="border rounded px-2 py-1"
                />
                <input
                  value={matchFilterDes}
                  onChange={(e) => setMatchFilterDes(e.target.value)}
                  placeholder="位号搜索"
                  className="border rounded px-2 py-1"
                />
              </div>
              <button
                type="button"
                disabled={!onRunMatch}
                onClick={() => onRunMatch && onRunMatch()}
                className={`ml-2 flex-shrink-0 ${
                  isWorkflowStepDoneForTab('match') ? successButtonClass : secondaryButtonClass
                }`}
              >
                第 2 步 · 重新匹配
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {/* 同位号替代组标签检查 */}
            {matchDesignatorIssues && matchDesignatorIssues.length > 0 && (
              <div className="border rounded-lg bg-white shadow-sm">
                <button
                  type="button"
                  className={sectionToggleButtonClass}
                  onClick={() => setMatchDesignatorCollapsed((v) => !v)}
                >
                  <div className="flex items-center gap-2 text-xs font-semibold text-amber-800">
                    <span>⚠️ 同位号替代组标签检查</span>
                    <span className="text-[11px] text-amber-700">
                      {matchDesignatorIssues.length} 项
                    </span>
                  </div>
                  <span className="text-[11px] text-amber-700">
                    {matchDesignatorCollapsed ? '展开' : '收起'}
                  </span>
                </button>
                {!matchDesignatorCollapsed && (
                  <div className="p-3 space-y-2">
                    <ul className="list-disc list-inside text-[11px] text-gray-700 space-y-1">
                      {matchDesignatorIssues.map((issue, i) => (
                        <li key={i}>
                          {issue.kind === 'tag_conflict' ? (
                            <>
                              位号 {issue.designator}：{issue.message}
                              <span className="text-gray-500">
                                {' '}
                                （{issue.codes.join(', ')}）
                              </span>
                            </>
                          ) : (
                            <>
                              位号 {issue.designator} · 物料 {issue.code}
                              ：物料库此物料替代组标签为空
                            </>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {/* INFO 部分（有提示的组） */}
            <div className="border rounded-lg bg-white shadow-sm">
              <button
                type="button"
                className={sectionToggleButtonClass}
                onClick={() => setMatchWarnCollapsed((v) => !v)}
              >
                <div className="flex items-center gap-2 text-xs font-semibold text-blue-800">
                  <span>ℹ️ INFO 组</span>
                  <span className="text-[11px] text-blue-700">
                    {warnGroups.length} 个替代组
                  </span>
                </div>
                <span className="text-[11px] text-blue-700">
                  {matchWarnCollapsed ? '展开' : '收起'}
                </span>
              </button>
              {!matchWarnCollapsed && (
                <div className="p-3 space-y-3">
                  {warnGroups.length === 0 ? (
                    <div className="text-[11px] text-gray-500">暂无 INFO 组。</div>
                  ) : (
                    warnGroups.map((g, idx) => (
                      <div key={idx} className="border rounded-lg bg-white shadow-sm">
                        <div className="flex items-center justify-between px-3 py-2 border-b bg-gray-50">
                          <div className="flex items-center gap-2">
                            <span>{g.badge}</span>
                            <span className="font-semibold text-gray-800">{g.label}</span>
                          </div>
                          <span className="text-[11px] text-gray-500">{g.labelSummary}</span>
                        </div>
                        <div className="px-3 pt-2 pb-3 space-y-1">
                          {g.issues.length > 0 ? (
                            <ul className="list-disc list-inside text-[11px] text-gray-700">
                              {g.issues.map((it, i) => (
                                <li key={i}>{it}</li>
                              ))}
                            </ul>
                          ) : (
                            <div className="text-[11px] text-green-600">检查结果：通过</div>
                          )}
                          {(() => {
                            const fullDes = g.designators.join(', ');
                            const maxShown = 6;
                            const shownDes = g.designators.slice(0, maxShown);
                            const restCount =
                              g.designators.length > maxShown ? g.designators.length - maxShown : 0;
                            return (
                              <div
                                className="text-[11px] text-gray-500"
                                title={fullDes || undefined}
                              >
                                位号（{g.designators.length} 个）:
                                {' '}
                                {shownDes.join(', ') || '—'}
                                {restCount > 0 && `，等 ${restCount} 个已折叠`}
                              </div>
                            );
                          })()}
                          <div className="mt-2 border rounded overflow-hidden">
                            <table className="min-w-full table-fixed text-[11px]">
                              <thead className="bg-gray-50">
                                <tr>
                                  <th className="px-2 py-1 text-left w-28">物料代码</th>
                                  <th className="px-2 py-1 text-left w-64">物料名称</th>
                                  <th className="px-2 py-1 text-right w-12">数量</th>
                                  <th className="px-2 py-1 text-left w-40">位号</th>
                                  <th className="px-2 py-1 text-left w-32">数量/位号校验</th>
                                  <th className="px-2 py-1 text-left w-40">物料库匹配</th>
                                  <th className="px-2 py-1 text-left w-40">处理决策</th>
                                </tr>
                              </thead>
                              <tbody>
                                {g.rows.map((r, i) => {
                                  const rowKey = `warn-${idx}-${i}-${r.code}`;
                                  const expanded = !!expandedDesignatorRows[rowKey];
                                  const fullDes = r.designators.join(', ');
                                  const maxShown = 6;
                                  const des = r.designators || [];
                                  const shown = des.slice(0, maxShown);
                                  const rest =
                                    des.length > maxShown ? des.length - maxShown : 0;
                                  const foldedText =
                                    (shown.join(', ') || '—') +
                                    (rest > 0 ? `，等 ${rest} 个已折叠` : '');
                                  const isMissingInLib = r.libMatch.startsWith('⚠️ 未在物料库中找到');
                                  const decisionKey = `match-missing::${g.label || '未分组'}::${r.code}::${i}`;
                                  const decision =
                                    matchLibMissingDecisions[decisionKey] || {
                                      status: 'pending' as MatchLibMissingDecisionStatus,
                                    };
                                  return (
                                    <tr key={i} className="border-t">
                                      <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                        {highlightText(r.code, matchFilterCode)}
                                      </td>
                                      <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                        {highlightText(r.name, matchFilterName)}
                                      </td>
                                      <td className="px-2 py-1 text-right whitespace-nowrap">
                                        {r.quantity}
                                      </td>
                                      <td
                                        className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis cursor-pointer"
                                        title={fullDes || undefined}
                                        onClick={() =>
                                          setExpandedDesignatorRows((prev) => ({
                                            ...prev,
                                            [rowKey]: !expanded,
                                          }))
                                        }
                                      >
                                        {expanded
                                          ? highlightText(fullDes || '—', matchFilterDes)
                                          : highlightText(foldedText, matchFilterDes)}
                                      </td>
                                      <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                        {r.qtyCheck}
                                      </td>
                                      <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                        {r.libMatch}
                                      </td>
                                      <td className="px-2 py-1 whitespace-nowrap">
                                        {isMissingInLib ? (
                                          <div className="flex flex-col gap-1 items-start">
                                            <div className="flex items-center gap-1">
                                              <label className="inline-flex items-center gap-1">
                                                <input
                                                  type="radio"
                                                  checked={decision.status === 'pending'}
                                                  onChange={() =>
                                                    setMatchLibMissingDecisions((prev) => ({
                                                      ...prev,
                                                      [decisionKey]: { status: 'pending' },
                                                    }))
                                                  }
                                                />
                                                <span>待定</span>
                                              </label>
                                              <label className="inline-flex items-center gap-1">
                                                <input
                                                  type="radio"
                                                  checked={decision.status === 'accepted'}
                                                  onChange={() =>
                                                    setMatchLibMissingDecisions((prev) => ({
                                                      ...prev,
                                                      [decisionKey]: { status: 'accepted' },
                                                    }))
                                                  }
                                                />
                                                <span>新器件</span>
                                              </label>
                                              <label className="inline-flex items-center gap-1">
                                                <input
                                                  type="radio"
                                                  checked={decision.status === 'ignored'}
                                                  onChange={() => {
                                                    const reason =
                                                      window.prompt(
                                                        '请输入忽略该物料库缺失的原因（必填）：',
                                                        decision.reason || ''
                                                      ) ?? '';
                                                    if (!reason.trim()) return;
                                                    setMatchLibMissingDecisions((prev) => ({
                                                      ...prev,
                                                      [decisionKey]: {
                                                        status: 'ignored',
                                                        reason: reason.trim(),
                                                      },
                                                    }));
                                                  }}
                                                />
                                                <span>忽略</span>
                                              </label>
                                            </div>
                                            {decision.status === 'ignored' && (
                                              <button
                                                type="button"
                                                className="text-sm text-blue-700 underline underline-offset-2"
                                                onClick={() => {
                                                  const reason =
                                                    window.prompt(
                                                      '修改忽略原因：',
                                                      decision.reason || ''
                                                    ) ?? '';
                                                  if (!reason.trim()) return;
                                                  setMatchLibMissingDecisions((prev) => ({
                                                    ...prev,
                                                    [decisionKey]: {
                                                      status: 'ignored',
                                                      reason: reason.trim(),
                                                    },
                                                  }));
                                                }}
                                              >
                                                忽略原因：{decision.reason || '点击填写'}
                                              </button>
                                            )}
                                          </div>
                                        ) : (
                                          <span className="text-[11px] text-gray-400">—</span>
                                        )}
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>

            {/* Pass 部分（通过组） */}
            <div className="border rounded-lg bg-white shadow-sm">
              <button
                type="button"
                className="w-full flex items-center justify-between px-4 py-3 border-b bg-emerald-50 hover:bg-emerald-100 rounded-t-lg transition"
                onClick={() => setMatchPassCollapsed((v) => !v)}
              >
                <div className="flex items-center gap-2 text-xs font-semibold text-emerald-800">
                  <span>✅ Pass 组</span>
                  <span className="text-[11px] text-emerald-700">
                    {passGroups.length} 个替代组
                  </span>
                </div>
                <span className="text-[11px] text-emerald-700">
                  {matchPassCollapsed ? '展开' : '收起'}
                </span>
              </button>
              {!matchPassCollapsed && (
                <div className="p-3 space-y-3">
                  {passGroups.length === 0 ? (
                    <div className="text-[11px] text-gray-500">暂无 Pass 组。</div>
                  ) : (
                    passGroups.map((g, idx) => (
                      <div key={idx} className="border rounded-lg bg-white shadow-sm">
                        <div className="flex items-center justify-between px-3 py-2 border-b bg-gray-50">
                          <div className="flex items-center gap-2">
                            <span>{g.badge}</span>
                            <span className="font-semibold text-gray-800">{g.label}</span>
                          </div>
                          <span className="text-[11px] text-gray-500">{g.labelSummary}</span>
                        </div>
                        <div className="px-3 pt-2 pb-3 space-y-1">
                          {g.issues.length > 0 ? (
                            <ul className="list-disc list-inside text-[11px] text-gray-700">
                              {g.issues.map((it, i) => (
                                <li key={i}>{it}</li>
                              ))}
                            </ul>
                          ) : (
                            <div className="text-[11px] text-green-600">检查结果：通过</div>
                          )}
                          {(() => {
                            const fullDes = g.designators.join(', ');
                            const maxShown = 6;
                            const shownDes = g.designators.slice(0, maxShown);
                            const restCount =
                              g.designators.length > maxShown ? g.designators.length - maxShown : 0;
                            return (
                              <div
                                className="text-[11px] text-gray-500"
                                title={fullDes || undefined}
                              >
                                位号（{g.designators.length} 个）:
                                {' '}
                                {shownDes.join(', ') || '—'}
                                {restCount > 0 && `，等 ${restCount} 个已折叠`}
                              </div>
                            );
                          })()}
                          <div className="mt-2 border rounded overflow-hidden">
                            <table className="min-w-full table-fixed text-[11px]">
                              <thead className="bg-gray-50">
                                <tr>
                                  <th className="px-2 py-1 text-left w-28">物料代码</th>
                                  <th className="px-2 py-1 text-left w-64">物料名称</th>
                                  <th className="px-2 py-1 text-right w-12">数量</th>
                                  <th className="px-2 py-1 text-left w-40">位号</th>
                                  <th className="px-2 py-1 text-left w-32">数量/位号校验</th>
                                  <th className="px-2 py-1 text-left w-40">物料库匹配</th>
                                </tr>
                              </thead>
                              <tbody>
                                {g.rows.map((r, i) => {
                                  const rowKey = `pass-${idx}-${i}-${r.code}`;
                                  const expanded = !!expandedDesignatorRows[rowKey];
                                  const fullDes = r.designators.join(', ');
                                  const maxShown = 6;
                                  const des = r.designators || [];
                                  const shown = des.slice(0, maxShown);
                                  const rest =
                                    des.length > maxShown ? des.length - maxShown : 0;
                                  const foldedText =
                                    (shown.join(', ') || '—') +
                                    (rest > 0 ? `，等 ${rest} 个已折叠` : '');
                                  return (
                                    <tr key={i} className="border-t">
                                      <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                        {highlightText(r.code, matchFilterCode)}
                                      </td>
                                      <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                        {highlightText(r.name, matchFilterName)}
                                      </td>
                                      <td className="px-2 py-1 text-right whitespace-nowrap">
                                        {r.quantity}
                                      </td>
                                      <td
                                        className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis cursor-pointer"
                                        title={fullDes || undefined}
                                        onClick={() =>
                                          setExpandedDesignatorRows((prev) => ({
                                            ...prev,
                                            [rowKey]: !expanded,
                                          }))
                                        }
                                      >
                                        {expanded
                                          ? highlightText(fullDes || '—', matchFilterDes)
                                          : highlightText(foldedText, matchFilterDes)}
                                      </td>
                                      <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                        {r.qtyCheck}
                                      </td>
                                      <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                        {r.libMatch}
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      );
    }
    if (activeTab === 'group') {
      if (!groupValidateGroups || groupValidateGroups.length === 0) {
        return (
          <div className="p-3 space-y-3 text-xs text-gray-500">
            <p>替代组验证基于物料匹配结果，检查：① 同组物料在物料库中的替代组标签是否一致；② 物料库中同替代组物料是否均在 BOM 中。缺失项将自动列出并标红 INFO。</p>
            <button
              type="button"
              disabled={!onRunGroupValidate}
              onClick={() => onRunGroupValidate?.()}
              className={
                isWorkflowStepDoneForTab('group') ? successButtonClass : secondaryButtonClass
              }
            >
              第 3 步 · 执行替代组验证
            </button>
          </div>
        );
      }
      return (
        <div className="h-full flex flex-col text-xs">
          <div className="flex-shrink-0 px-3 pt-2 pb-2 border-b border-gray-200 bg-white sticky top-0 z-10 flex items-center justify-between">
            <span className="text-gray-600">替代组验证结果</span>
            <button
              type="button"
              disabled={!onRunGroupValidate}
              onClick={() => onRunGroupValidate?.()}
              className={
                isWorkflowStepDoneForTab('group') ? successButtonClass : secondaryButtonClass
              }
            >
              第 3 步 · 重新验证
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-4">
            {([...groupValidateGroups]
              .map((g, idx) => ({ g, idx }))
              .sort((a, b) => {
                const aInfo =
                  !a.g.labelConsistent || (a.g.missingInBom && a.g.missingInBom.length > 0);
                const bInfo =
                  !b.g.labelConsistent || (b.g.missingInBom && b.g.missingInBom.length > 0);
                if (aInfo === bInfo) return 0;
                return aInfo ? -1 : 1;
              })
              ).map(({ g, idx }) => (
              <div key={idx} className="border rounded-lg bg-white shadow-sm overflow-hidden">
                <div className="px-3 py-2 border-b bg-gray-50 flex items-center justify-between">
                  <span className="font-semibold text-gray-800">替代组：{g.label}</span>
                  {g.labelConsistent ? (
                    <span className="text-[11px] text-green-600">替代组标签一致</span>
                  ) : (
                    <div className="flex flex-col items-end gap-1">
                      <span className="text-[11px] text-red-600">
                        {g.labelConflictMessage || '替代组标签不一致'}
                      </span>
                      {(() => {
                        const key = `group-label-conflict::${g.label || '未分组'}`;
                        const decision =
                          groupLabelConflictDecisions[key] || {
                            status: 'pending' as GroupMissingDecisionStatus,
                          };
                        const handled = decision.status !== 'pending';
                        const textClass = handled ? 'text-blue-700' : 'text-red-700';
                        return (
                          <div className={`flex items-center gap-2 text-[11px] ${textClass}`}>
                            <span>标签不一致处理决策：</span>
                            <label className="inline-flex items-center gap-1">
                              <input
                                type="radio"
                                checked={decision.status === 'pending'}
                                onChange={() =>
                                  setGroupLabelConflictDecisions((prev) => ({
                                    ...prev,
                                    [key]: { status: 'pending' },
                                  }))
                                }
                              />
                              <span>待定</span>
                            </label>
                            <label className="inline-flex items-center gap-1">
                              <input
                                type="radio"
                                checked={decision.status === 'accepted'}
                                onChange={() =>
                                  setGroupLabelConflictDecisions((prev) => ({
                                    ...prev,
                                    [key]: { status: 'accepted' },
                                  }))
                                }
                              />
                              <span>接受</span>
                            </label>
                            <label className="inline-flex items-center gap-1">
                              <input
                                type="radio"
                                checked={decision.status === 'ignored'}
                                onChange={() => {
                                  const reason =
                                    window.prompt(
                                      '请输入忽略该替代组标签不一致问题的原因（必填）：',
                                      decision.reason || ''
                                    ) ?? '';
                                  if (!reason.trim()) return;
                                  setGroupLabelConflictDecisions((prev) => ({
                                    ...prev,
                                    [key]: { status: 'ignored', reason: reason.trim() },
                                  }));
                                }}
                              />
                              <span>忽略</span>
                            </label>
                            {decision.status === 'ignored' && decision.reason && (
                              <button
                                type="button"
                                className="text-sm text-blue-700 underline underline-offset-2"
                                onClick={() => {
                                  const reason =
                                    window.prompt(
                                      '修改忽略原因：',
                                      decision.reason || ''
                                    ) ?? '';
                                  if (!reason.trim()) return;
                                  setGroupLabelConflictDecisions((prev) => ({
                                    ...prev,
                                    [key]: { status: 'ignored', reason: reason.trim() },
                                  }));
                                }}
                              >
                                忽略原因：{decision.reason || '点击填写'}
                              </button>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                  )}
                </div>
                <div className="px-3 py-2 space-y-2">
                  {/* 先展示 BOM 中已有的物料列表 */}
                  {g.rows.length > 0 && (
                    <>
                      <div className="text-[11px] font-medium text-gray-700">BOM 中已有物料</div>
                      <div className="border rounded overflow-hidden">
                        <table className="min-w-full table-fixed text-[11px]">
                          <thead className="bg-gray-50">
                            <tr>
                              <th className="px-2 py-1 text-left w-28">物料代码</th>
                              <th className="px-2 py-1 text-left w-64">物料名称</th>
                              <th className="px-2 py-1 text-right w-12">数量</th>
                              <th className="px-2 py-1 text-left w-40">位号</th>
                              <th className="px-2 py-1 text-left w-32">数量/位号校验</th>
                              <th className="px-2 py-1 text-left w-40">物料库匹配</th>
                            </tr>
                          </thead>
                          <tbody>
                            {g.rows.map((r, i) => (
                              <tr key={i} className="border-t">
                                <td className="px-2 py-1">{r.code}</td>
                                <td className="px-2 py-1 overflow-hidden text-ellipsis">{r.name}</td>
                                <td className="px-2 py-1 text-right">{r.quantity}</td>
                                <td className="px-2 py-1 overflow-hidden text-ellipsis">
                                  {r.designators.slice(0, 6).join(', ')}
                                  {r.designators.length > 6 ? `，等${r.designators.length - 6}个` : ''}
                                </td>
                                <td className="px-2 py-1">{r.qtyCheck}</td>
                                <td className="px-2 py-1">{r.libMatch}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  )}
                  {/* 再展示 INFO：物料库中同替代组但 BOM 中缺失的物料 */}
                  {g.missingInBom.length > 0 && (() => {
                    const allHandled = g.missingInBom.every((m, i) => {
                      const key = `${g.label || '未分组'}__${m.code}__${i}`;
                      const status = groupMissingDecisions[key]?.status || 'pending';
                      return status !== 'pending';
                    });
                    const headerTextClass = allHandled ? 'text-blue-700' : 'text-red-700';
                    const headerBgClass = allHandled ? 'bg-blue-100' : 'bg-red-100';
                    const boxBorderClass = allHandled ? 'border-blue-200' : 'border-red-200';
                    const boxBgClass = allHandled ? 'bg-blue-50/50' : 'bg-red-50/50';
                    const infoText =
                      'INFO：物料库中同替代组物料，BOM 中未包含（已自动列入，建议加入 BOM）' +
                      (allHandled ? ' · 已全部由用户处理' : '');
                    return (
                      <>
                        <div className={`text-[11px] font-medium flex items-center gap-1 ${headerTextClass}`}>
                          <span>{infoText}</span>
                        </div>
                        <div className={`border rounded overflow-hidden ${boxBorderClass} ${boxBgClass}`}>
                        <table className="min-w-full table-fixed text-[11px]">
                          <thead className={headerBgClass}>
                            <tr>
                              <th className="px-2 py-1 text-left w-28">物料代码</th>
                              <th className="px-2 py-1 text-left w-64">物料名称</th>
                                <th className="px-2 py-1 text-left w-40">所属库</th>
                                <th className="px-2 py-1 text-left w-32">替代组标签</th>
                                <th className="px-2 py-1 text-left w-40">处理决策</th>
                              </tr>
                            </thead>
                            <tbody>
                              {g.missingInBom.map((m, i) => {
                                const key = `${g.label || '未分组'}__${m.code}__${i}`;
                                const decision =
                                  groupMissingDecisions[key] || {
                                    status: 'pending' as GroupMissingDecisionStatus,
                                  };
                                const isHandled = decision.status !== 'pending';
                                const rowClass = isHandled
                                  ? 'border-t border-blue-200 bg-blue-50'
                                  : 'border-t border-red-200 bg-red-50';
                                const textClass = isHandled ? 'text-blue-700' : 'text-red-700';
                                const decisionTextClass = isHandled ? 'text-blue-700' : '';
                                const ignoreReasonColorClass = isHandled ? 'text-blue-700' : 'text-red-700';
                                return (
                                  <tr key={i} className={rowClass}>
                                    <td className={`px-2 py-1 ${textClass} font-medium`}>{m.code}</td>
                                    <td className={`px-2 py-1 ${textClass} overflow-hidden text-ellipsis`}>
                                      {m.name}
                                    </td>
                                    <td className={`px-2 py-1 ${textClass}`}>{m.libName}</td>
                                    <td className={`px-2 py-1 ${textClass}`}>{m.groupLabel}</td>
                                    <td className={`px-2 py-1 ${decisionTextClass}`}>
                                      <div className="flex flex-col gap-1 items-start">
                                        <div className="flex items-center gap-1">
                                          <label className="inline-flex items-center gap-1">
                                            <input
                                              type="radio"
                                              checked={decision.status === 'pending'}
                                              onChange={() =>
                                                setGroupMissingDecisions((prev) => ({
                                                  ...prev,
                                                  [key]: { status: 'pending' },
                                                }))
                                              }
                                            />
                                            <span>待定</span>
                                          </label>
                                          <label className="inline-flex items-center gap-1">
                                            <input
                                              type="radio"
                                              checked={decision.status === 'accepted'}
                                              onChange={() =>
                                                setGroupMissingDecisions((prev) => ({
                                                  ...prev,
                                                  [key]: { status: 'accepted' },
                                                }))
                                              }
                                            />
                                            <span>接受</span>
                                          </label>
                                          <label className="inline-flex items-center gap-1">
                                            <input
                                              type="radio"
                                              checked={decision.status === 'ignored'}
                                              onChange={() => {
                                                const reason =
                                                  window.prompt(
                                                    '请输入拒绝加入 BOM 的原因（必填）：',
                                                    decision.reason || ''
                                                  ) ?? '';
                                                if (!reason.trim()) return;
                                                setGroupMissingDecisions((prev) => ({
                                                  ...prev,
                                                  [key]: { status: 'ignored', reason: reason.trim() },
                                                }));
                                              }}
                                            />
                                            <span>忽略</span>
                                          </label>
                                        </div>
                                        {decision.status === 'ignored' && (
                                          <button
                                            type="button"
                                            className={`text-sm ${ignoreReasonColorClass} underline underline-offset-2`}
                                            onClick={() => {
                                              const reason =
                                                window.prompt('修改忽略原因：', decision.reason || '') ?? '';
                                              if (!reason.trim()) return;
                                              setGroupMissingDecisions((prev) => ({
                                                ...prev,
                                                [key]: { status: 'ignored', reason: reason.trim() },
                                              }));
                                            }}
                                          >
                                            忽略原因：{decision.reason || '点击填写'}
                                          </button>
                                        )}
                                      </div>
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </>
                    );
                  })()}
                  {g.rows.length === 0 && g.missingInBom.length === 0 && (
                    <div className="text-[11px] text-gray-500">该组无匹配到物料库的物料，无法做替代组一致性检查。</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      );
    }
    if (activeTab === 'replacement') {
      if (!replacementCheckGroups || replacementCheckGroups.length === 0) {
        return (
          <div className="p-3 space-y-3 text-xs text-gray-500">
            <p>
              替换对检查基于替换对管理中维护的替换组：若 BOM 中出现了某个替换组内的任一物料，则该替换组内其他物料也应在 BOM 中体现；缺失项将以
              INFO 方式列出，便于后续补充。
            </p>
            <button
              type="button"
              disabled={!onRunReplacementCheck}
              onClick={() => onRunReplacementCheck?.()}
              className={
                isWorkflowStepDoneForTab('replacement')
                  ? successButtonClass
                  : secondaryButtonClass
              }
            >
              第 4 步 · 执行替换对检查
            </button>
          </div>
        );
      }
      return (
        <div className="h-full flex flex-col text-xs">
          <div className="flex-shrink-0 px-3 pt-2 pb-2 border-b border-gray-200 bg-white sticky top-0 z-10 flex items-center justify-between">
            <span className="text-gray-600">替换对检查结果</span>
            <button
              type="button"
              disabled={!onRunReplacementCheck}
              onClick={() => onRunReplacementCheck?.()}
              className={
                isWorkflowStepDoneForTab('replacement')
                  ? successButtonClass
                  : secondaryButtonClass
              }
            >
              第 4 步 · 重新检查
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-4">
            {replacementCheckGroups.map((g) => {
              if (g.items.length === 0 && g.id === '__all_pass__') {
                return (
                  <div key={g.id} className="border rounded-lg bg-emerald-50 shadow-sm px-3 py-2">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-emerald-700">替换对检查：通过</span>
                      <span className="text-[11px] text-emerald-700">未命中任何替换对中的物料</span>
                    </div>
                    {g.remark && (
                      <div className="mt-1 text-[11px] text-emerald-800">
                        {g.remark}
                      </div>
                    )}
                  </div>
                );
              }
              const missingItems = g.items.filter((it) => !it.inBom);
              const presentItems = g.items.filter((it) => it.inBom);
              const hasInfo = missingItems.length > 0;
              const allMissingHandled = missingItems.length
                ? missingItems.every((m, i) => {
                    const key = `${g.id || 'replacement'}__${m.code}__${i}`;
                    const status = groupMissingDecisions[key]?.status || 'pending';
                    return status !== 'pending';
                  })
                : false;
              return (
                <div
                  key={g.id}
                  className={`border rounded-lg shadow-sm overflow-hidden ${
                    allMissingHandled ? 'bg-blue-50' : 'bg-white'
                  }`}
                >
                  <div className="px-3 py-2 border-b bg-gray-50 flex items-center justify-between">
                    <div className="flex flex-col gap-0.5">
                      <span className="font-semibold text-gray-800">
                        替换组：{g.items.map((it) => (it.name ? `${it.code} ${it.name}` : it.code)).join(' / ')}
                      </span>
                      {g.remark && (
                        <span className="text-[11px] text-gray-500">
                          备注：{g.remark}
                        </span>
                      )}
                    </div>
                    {hasInfo ? (
                      <span
                        className={`text-[11px] font-medium ${
                          allMissingHandled ? 'text-blue-700' : 'text-red-600'
                        }`}
                      >
                        INFO：存在替换对物料未在 BOM 中出现
                        {allMissingHandled ? ' · 已全部由用户处理' : ''}
                      </span>
                    ) : (
                      <span className="text-[11px] text-emerald-600">检查结果：通过</span>
                    )}
                  </div>
                  <div className="px-3 py-2 space-y-2">
                    <div className="border rounded overflow-hidden">
                      <table className="min-w-full table-fixed text-[11px]">
                        <thead className={allMissingHandled ? 'bg-blue-100' : 'bg-gray-50'}>
                          <tr>
                            <th className="px-2 py-1 text-left w-24">物料代码</th>
                            <th className="px-2 py-1 text-left w-40">物料名称</th>
                            <th className="px-2 py-1 text-left w-20">在 BOM 中</th>
                            <th className="px-2 py-1 text-right w-16">BOM 数量</th>
                            <th className="px-2 py-1 text-left">BOM 位号</th>
                            <th className="px-2 py-1 text-left w-32">替代对备注</th>
                            <th className="px-2 py-1 text-left w-32">处理决策</th>
                            <th className="px-2 py-1 text-left w-28">说明</th>
                          </tr>
                        </thead>
                        <tbody>
                          {g.items.map((it, idx) => {
                            const isMissing = !it.inBom;
                            const des = (it.bomDesignators || []).join(', ');
                            const maxShown = 6;
                            const arr = it.bomDesignators || [];
                            const shown = arr.slice(0, maxShown);
                            const rest = arr.length > maxShown ? arr.length - maxShown : 0;
                            const foldedText =
                              (shown.join(', ') || '—') +
                              (rest > 0 ? `，等 ${rest} 个已折叠` : '');
                            const decisionKey = `${g.id || 'replacement'}__${it.code}__${idx}`;
                            const decision =
                              groupMissingDecisions[decisionKey] || {
                                status: 'pending' as GroupMissingDecisionStatus,
                              };
                            const isHandled = decision.status !== 'pending';
                            const rowClass = isMissing
                              ? isHandled
                                ? 'border-t bg-blue-50'
                                : 'border-t bg-amber-50'
                              : 'border-t';
                            const textClassMissing = isMissing
                              ? isHandled
                                ? 'text-blue-800'
                                : 'text-amber-800'
                              : 'text-gray-800';
                            const decisionTextClass = isMissing && isHandled ? 'text-blue-800' : '';
                            const ignoreReasonTextClass =
                              isMissing && isHandled ? 'text-blue-800' : 'text-amber-800';
                            return (
                              <tr
                                key={idx}
                                className={rowClass}
                              >
                                <td
                                  className={`px-2 py-1 ${
                                    isMissing ? `${textClassMissing} font-medium` : 'text-gray-800'
                                  }`}
                                >
                                  {it.code}
                                </td>
                                <td
                                  className={`px-2 py-1 overflow-hidden text-ellipsis ${
                                    isMissing ? textClassMissing : 'text-gray-800'
                                  }`}
                                >
                                  {it.name || '—'}
                                </td>
                                <td className="px-2 py-1">
                                  {it.inBom ? '是' : '否'}
                                </td>
                                <td className="px-2 py-1 text-right">
                                  {it.inBom ? it.bomQuantity ?? '—' : '—'}
                                </td>
                                <td
                                  className="px-2 py-1 overflow-hidden text-ellipsis"
                                  title={des || undefined}
                                >
                                  {it.inBom ? foldedText : '—'}
                                </td>
                                <td className="px-2 py-1 text-gray-600">
                                  {g.remark || '—'}
                                </td>
                                <td className={`px-2 py-1 ${decisionTextClass}`}>
                                  {isMissing ? (
                                    <div className="flex flex-col gap-1 items-start">
                                      <div className="flex items-center gap-1">
                                        <label className="inline-flex items-center gap-1">
                                          <input
                                            type="radio"
                                            checked={decision.status === 'pending'}
                                            onChange={() =>
                                              setGroupMissingDecisions((prev) => ({
                                                ...prev,
                                                [decisionKey]: { status: 'pending' },
                                              }))
                                            }
                                          />
                                          <span>待定</span>
                                        </label>
                                        <label className="inline-flex items-center gap-1">
                                          <input
                                            type="radio"
                                            checked={decision.status === 'accepted'}
                                            onChange={() =>
                                              setGroupMissingDecisions((prev) => ({
                                                ...prev,
                                                [decisionKey]: { status: 'accepted' },
                                              }))
                                            }
                                          />
                                          <span>接受</span>
                                        </label>
                                        <label className="inline-flex items-center gap-1">
                                          <input
                                            type="radio"
                                            checked={decision.status === 'ignored'}
                                            onChange={() => {
                                              const reason =
                                                window.prompt(
                                                  '请输入拒绝加入 BOM 的原因（必填）：',
                                                  decision.reason || ''
                                                ) ?? '';
                                              if (!reason.trim()) return;
                                              setGroupMissingDecisions((prev) => ({
                                                ...prev,
                                                [decisionKey]: {
                                                  status: 'ignored',
                                                  reason: reason.trim(),
                                                },
                                              }));
                                            }}
                                          />
                                          <span>忽略</span>
                                        </label>
                                      </div>
                                      {decision.status === 'ignored' && (
                                        <button
                                          type="button"
                                          className={`text-sm ${ignoreReasonTextClass} underline underline-offset-2`}
                                          onClick={() => {
                                            const reason =
                                              window.prompt(
                                                '修改忽略原因：',
                                                decision.reason || ''
                                              ) ?? '';
                                            if (!reason.trim()) return;
                                            setGroupMissingDecisions((prev) => ({
                                              ...prev,
                                              [decisionKey]: {
                                                status: 'ignored',
                                                reason: reason.trim(),
                                              },
                                            }));
                                          }}
                                        >
                                          忽略原因：{decision.reason || '点击填写'}
                                        </button>
                                      )}
                                    </div>
                                  ) : (
                                    <span className="text-gray-600">—</span>
                                  )}
                                </td>
                                <td className={`px-2 py-1 ${isMissing ? textClassMissing : 'text-gray-600'}`}>
                                  {isMissing
                                    ? 'INFO：替换对中存在，但当前 BOM 未包含，建议评估是否需要加入。'
                                    : '已在 BOM 中'}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    {hasInfo && (
                      <div className="text-[11px] text-amber-700 mt-1">
                        INFO：以上标记为「否」的物料来自替换对定义，但当前 BOM 未包含，可根据项目需要评估是否补充。
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      );
    }
    if (activeTab === 'optimize') {
      const pendingItems = optimizeRows.filter((it) => it.status === 'pending');
      const doneItems = optimizeRows.filter((it) => it.status !== 'pending');
      // PASS 分组统计
      type PassGroup = {
        source: 'match' | 'group' | 'replacement';
        label: string;
        summary: string;
      };
      const passGroups: PassGroup[] = [];
      const problemKeys = new Set(
        optimizeRows.map(
          (it) => `${it.source}::${it.groupLabel || it.row.code || '未分组'}`
        )
      );
      if (matchGroups && matchGroups.length > 0) {
        matchGroups.forEach((g) => {
          const key = `match::${g.label}`;
          if (g.badge === '🟢' && !problemKeys.has(key)) {
            passGroups.push({
              source: 'match',
              label: g.label,
              summary: g.labelSummary || '物料匹配通过',
            });
          }
        });
      }
      if (groupValidateGroups && groupValidateGroups.length > 0) {
        groupValidateGroups.forEach((g) => {
          const key = `group::${g.label}`;
          const noMissing = !g.missingInBom || g.missingInBom.length === 0;
          if (g.labelConsistent && noMissing && !problemKeys.has(key)) {
            passGroups.push({
              source: 'group',
              label: g.label,
              summary: '替代组标签一致，物料库中同替代组物料均已在 BOM 中',
            });
          }
        });
      }
      if (replacementCheckGroups && replacementCheckGroups.length > 0) {
        replacementCheckGroups.forEach((g) => {
          if (g.id === '__all_pass__') {
            return;
          }
          const missing = g.items.filter((it) => !it.inBom);
          if (missing.length > 0) return;
          const label = g.items
            .map((it) => (it.name ? `${it.code} ${it.name}` : it.code))
            .join(' / ');
          const key = `replacement::${label}`;
          if (!problemKeys.has(key)) {
            passGroups.push({
              source: 'replacement',
              label,
              summary: '替换对物料均已在 BOM 中出现',
            });
          }
        });
      }

      const groupByLabel = (items: typeof optimizeRows) => {
        const groups: Record<string, typeof optimizeRows> = {};
        items.forEach((it) => {
          const key = it.groupLabel || '未分组/无替代组信息';
          if (!groups[key]) groups[key] = [];
          groups[key].push(it);
        });
        return Object.entries(groups);
      };

      type FinalExportSimpleRow = {
        code: string;
        name?: string;
        quantity: number;
        designators: string[];
        groupLabel?: string;
        aiResult?: string;
        aiReason?: string;
        infoReason?: string;
      };

      /** 与「导出最终 BOM」相同的行集合（含 AI CHECK 接受加入的行），供 PLM 格式整理复用 */
      const buildAiCheckFinalSimpleRows = (): FinalExportSimpleRow[] => {
        if (!bomState || !bomState.items.length) {
          return [];
        }

        const aiCheckSummary: Record<
          string,
          {
            result: string;
            reason: string;
            fromMatchMissingLib?: boolean;
          }
        > = {};
        const infoReasonSummary: Record<string, string> = {};

        optimizeRows.forEach((it) => {
          const code = it.row.code;
          if (code) {
            let baseInfo = '';
            if (it.source === 'match') {
              const parts: string[] = [];
              if (it.row.qtyCheck && !it.row.qtyCheck.includes('一致')) {
                parts.push(it.row.qtyCheck);
              }
              if (it.row.libMatch) {
                parts.push(it.row.libMatch);
              }
              baseInfo = parts.join('；');
            } else if (it.source === 'group' || it.source === 'replacement') {
              if (it.row.libMatch) {
                baseInfo = it.row.libMatch;
              }
            }
            if (baseInfo) {
              const prev = infoReasonSummary[code];
              infoReasonSummary[code] = prev ? `${prev}；${baseInfo}` : baseInfo;
            }
          }

          if (it.status === 'pending') return;
          if (!code) return;

          let resultText = '';
          let reasonText = it.ignoreReason || '';

          if (it.status === 'accepted') {
            if (it.source === 'match') {
              resultText = '用户处理决策-接受';
            } else if (it.source === 'group') {
              resultText = '系统加入-替代组验证';
              if (!reasonText) {
                reasonText = `替代组验证：同替代组物料缺失，已接受加入（替代组：${
                  it.groupLabel || '未分组'
                }）`;
              }
            } else if (it.source === 'replacement') {
              resultText = '系统加入-替换对检查';
              if (!reasonText) {
                reasonText = `替换对检查：替换对中缺失物料，已接受加入（替换组：${
                  it.groupLabel || '未分组'
                }）`;
              }
            } else {
              resultText = 'AI建议-接受';
            }
          } else if (it.status === 'ignored') {
            if (it.source === 'match') {
              resultText = '用户处理决策-忽略';
              reasonText = it.ignoreReason || reasonText || '';
            } else {
              resultText = 'AI建议-忽略';
              reasonText = it.ignoreReason || reasonText || '';
            }
          }

          if (!resultText && !reasonText) return;

          const fromMatchMissingLib = it.source === 'match';
          const prev = aiCheckSummary[code];
          if (!prev) {
            aiCheckSummary[code] = {
              result: resultText,
              reason: reasonText,
              fromMatchMissingLib,
            };
          } else {
            const mergedResult = prev.result || resultText;
            const mergedReason =
              prev.reason && reasonText
                ? `${prev.reason}；${reasonText}`
                : prev.reason || reasonText;
            aiCheckSummary[code] = {
              result: mergedResult,
              reason: mergedReason,
              fromMatchMissingLib: prev.fromMatchMissingLib || fromMatchMissingLib,
            };
          }
        });

        const acceptedByGroupLabel: Record<
          string,
          { code: string; name?: string }[]
        > = {};
        if (groupValidateGroups && groupValidateGroups.length > 0) {
          groupValidateGroups.forEach((g) => {
            if (!g.missingInBom || g.missingInBom.length === 0) return;
            g.missingInBom.forEach((m, i) => {
              const key = `${g.label || '未分组'}__${m.code}__${i}`;
              const decision = groupMissingDecisions[key];
              if (decision && decision.status === 'accepted') {
                const labelKey = g.label || '未分组';
                if (!acceptedByGroupLabel[labelKey]) {
                  acceptedByGroupLabel[labelKey] = [];
                }
                acceptedByGroupLabel[labelKey].push({
                  code: m.code,
                  name: m.name,
                });
              }
            });
          });
        }

        const extraRowsFromReplacement: FinalExportSimpleRow[] = [];
        if (replacementCheckGroups && replacementCheckGroups.length > 0) {
          replacementCheckGroups.forEach((g) => {
            const missing = g.items.filter((it) => !it.inBom);
            if (!missing.length) return;
            missing.forEach((m, i) => {
              const key = `${g.id || 'replacement'}__${m.code}__${i}`;
              const decision = groupMissingDecisions[key];
              if (decision && decision.status === 'accepted') {
                extraRowsFromReplacement.push({
                  code: m.code,
                  name: m.name,
                  quantity: 0,
                  designators: [],
                });
              }
            });
          });
        }

        const finalRows: FinalExportSimpleRow[] = [];
        const handledGroupLabels = new Set<string>();

        for (const item of bomState.items) {
          const groupKey = item.groupKey || item.code || '未分组';
          const summary = aiCheckSummary[item.code];
          const groupLabelForRow =
            summary && summary.fromMatchMissingLib ? '' : groupKey;
          finalRows.push({
            code: item.code,
            name: item.name,
            quantity: item.quantity,
            designators: item.designators || [],
            groupLabel: groupLabelForRow,
            aiResult: summary?.result,
            aiReason: summary?.reason,
            infoReason: infoReasonSummary[item.code],
          });

          if (!handledGroupLabels.has(groupKey) && acceptedByGroupLabel[groupKey]) {
            const extras = acceptedByGroupLabel[groupKey];
            extras.forEach((m) => {
              finalRows.push({
                code: m.code,
                name: m.name,
                quantity: item.quantity,
                designators: item.designators || [],
                groupLabel: groupKey,
                aiResult: aiCheckSummary[m.code]?.result,
                aiReason: aiCheckSummary[m.code]?.reason,
                infoReason: infoReasonSummary[m.code],
              });
            });
            handledGroupLabels.add(groupKey);
          }
        }

        if (extraRowsFromReplacement.length > 0) {
          finalRows.push(...extraRowsFromReplacement);
        }

        return finalRows;
      };

      const exportFinalBOM = () => {
        if (!bomState || !bomState.items.length) {
          alert('当前尚未导入 BOM，无法导出。');
          return;
        }

        const finalRows = buildAiCheckFinalSimpleRows();

        const header = [
          '物料代码',
          '物料名称',
          '数量',
          '位号',
          '替代组标签',
          'INFO原因',
          'AI CHECK结果',
          'AI CHECK说明',
        ];
        const data = finalRows.map((it) => [
          it.code,
          it.name || '',
          it.quantity,
          it.designators.join(', '),
          it.groupLabel || '',
          it.infoReason || '',
          it.aiResult || '',
          it.aiReason || '',
        ]);
        const aoa = [header, ...data];
        const ws = XLSX.utils.aoa_to_sheet(aoa);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, 'BOM');

        const flowHeader = ['步骤', '名称', '状态'];
        const flowData = bomWorkflowProgress.steps.map((s) => [
          s.order,
          s.label,
          s.trackCompletion === false
            ? '未完成（本步骤暂不判定完成）'
            : s.done
            ? '已完成'
            : '未完成',
        ]);
        const wsFlow = XLSX.utils.aoa_to_sheet([flowHeader, ...flowData]);
        XLSX.utils.book_append_sheet(wb, wsFlow, '流程进度');

        const name = bomState.sourceFileName || 'BOM_optimized.xlsx';
        XLSX.writeFile(wb, name);
        trackNeoPoints('ai_check_export');
      };

      const exportPlmStandardBom = () => {
        if (!bomState || !bomState.items.length) {
          alert('当前尚未导入 BOM，无法导出。');
          return;
        }
        setPlmExporting(true);
        try {
          const finalRows = buildAiCheckFinalSimpleRows();
          const plmSource = finalRows.map((r) => ({
            itemCode: r.code,
            itemName: r.name || '',
            quantity: r.quantity,
            reference: formatDesignatorsForPlm(r.designators || []),
          }));
          const converted = convertRowsToPlmFormat(plmSource, PLM_TEMPLATE_HEADERS, {
            parentCode: plmParentCode,
            parentStandardDesc: plmParentStdDesc,
          });
          const base =
            (bomState.sourceFileName || 'BOM').replace(/\.(xlsx|xls|csv|txt)$/i, '') || 'BOM';
          writePlmXlsxFile(PLM_TEMPLATE_HEADERS, converted, `PLM_${base}_${Date.now()}.xlsx`);
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : String(e);
          alert(`PLM 格式整理失败：${msg}`);
        } finally {
          setPlmExporting(false);
        }
      };

      const exportOptimizeReport = async () => {
        const safeJoin = (arr: string[], sep = '；') =>
          arr
            .map((s) => (s || '').trim())
            .filter(Boolean)
            .join(sep);

        const rowsBySource: Record<
          'match' | 'group' | 'replacement',
          typeof optimizeRows
        > = {
          match: [],
          group: [],
          replacement: [],
        };
        optimizeRows.forEach((it) => {
          rowsBySource[it.source].push(it);
        });

        const sourceLabel = (s: 'match' | 'group' | 'replacement') =>
          s === 'match' ? '物料匹配' : s === 'group' ? '替代组验证' : '替换对检查';

        const statusLabel = (s: OptimizeStatus) =>
          s === 'pending' ? '待定' : s === 'accepted' ? '接受' : '忽略';

        const totalChecked =
          bomState && bomState.items ? bomState.items.length : undefined;
        const infoItemCodes = new Set(
          optimizeRows.map((it) => (it.row.code || '').trim()).filter(Boolean)
        );
        const infoItemCount = infoItemCodes.size;
        const passCount =
          totalChecked != null ? Math.max(totalChecked - infoItemCount, 0) : undefined;

        const htmlParts: string[] = [];
        htmlParts.push(`
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>BOM AI CHECK 报告</title>
  <style>
    body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,'Microsoft YaHei',sans-serif; margin: 24px; color: #111827; }
    h1 { font-size: 20px; margin-bottom: 8px; }
    h2 { font-size: 16px; margin: 18px 0 6px; }
    h3 { font-size: 14px; margin: 14px 0 4px; }
    p { font-size: 12px; margin: 2px 0; }
    table { border-collapse: collapse; width: 100%; font-size: 11px; margin-top: 4px; table-layout: fixed; }
    th, td { border: 1px solid #e5e7eb; padding: 4px 6px; vertical-align: top; word-wrap: break-word; }
    th { background: #f3f4f6; font-weight: 600; }
    .col-code { width: 80px; }
    .col-name { width: 220px; }
    .tr-info-pending td { background: #fef2f2; }
    .tr-info-handled td { background: #eff6ff; }
    .tr-pass td { background: #ecfdf3; }
    .section-summary { font-size: 12px; margin-bottom: 8px; }
    .badge { display:inline-block; padding:1px 6px; border-radius:999px; font-size:10px; }
    .badge-pending { background:#fef3c7; color:#92400e; }
    .badge-accepted { background:#dcfce7; color:#166534; }
    .badge-ignored { background:#fee2e2; color:#991b1b; }
  </style>
</head>
<body>
  <h1>BOM AI CHECK 报告</h1>
  <p class="section-summary">
    生成时间：${new Date().toLocaleString()}<br/>
    ${totalChecked != null ? `共检查物料：${totalChecked} 个；` : ''}
    PASS 物料：${
      passCount != null ? passCount : '（无法统计 PASS 数量，仅统计 INFO 项）'
    }；INFO 条目：${optimizeRows.length} 条，覆盖物料：${infoItemCount} 个。
  </p>
`);

        const workflowRowsHtml = bomWorkflowProgress.steps
          .map((s) => {
            const statusText =
              s.trackCompletion === false
                ? '未完成（本步骤暂不判定完成）'
                : s.done
                ? '已完成'
                : '未完成';
            const rowClass = s.done ? 'tr-pass' : 'tr-info-pending';
            return `<tr class="${rowClass}"><td>${s.order}</td><td>${s.label}</td><td>${statusText}</td></tr>`;
          })
          .join('');
        htmlParts.push(`
  <h2>BOM AI CHECK 流程进度</h2>
  <table>
    <thead>
      <tr><th>步骤</th><th>名称</th><th>状态</th></tr>
    </thead>
    <tbody>
${workflowRowsHtml}
    </tbody>
  </table>
`);

        (['match', 'group', 'replacement'] as const).forEach((src) => {
          const list = rowsBySource[src];
          if (!list.length) return;

          const total = list.length;
          const pending = list.filter((r) => r.status === 'pending').length;
          const accepted = list.filter((r) => r.status === 'accepted').length;
          const ignored = list.filter((r) => r.status === 'ignored').length;

          htmlParts.push(`
  <h2>${sourceLabel(src)} · INFO 项汇总（共 ${total} 条）</h2>
  <p class="section-summary">
    <span class="badge badge-pending">待定：${pending}</span>
    &nbsp; <span class="badge badge-accepted">接受：${accepted}</span>
    &nbsp; <span class="badge badge-ignored">忽略：${ignored}</span>
  </p>
`);

          // 替代组验证：使用与 Web 类似的分组结构输出
          if (src === 'group' && groupValidateGroups && groupValidateGroups.length > 0) {
            groupValidateGroups.forEach((g) => {
              htmlParts.push(`
  <h3>替代组：${g.label}</h3>
  <p>
    ${
      g.labelConsistent
        ? '替代组标签一致'
        : g.labelConflictMessage || '同一替代组中物料在物料库中的替代组标签不一致'
    }
  </p>
`);

              // BOM 中已有物料
              if (g.rows && g.rows.length > 0) {
                htmlParts.push(`
  <p><strong>BOM 中已有物料</strong></p>
  <table>
    <thead>
      <tr>
        <th class="col-code">物料代码</th>
        <th class="col-name">物料名称</th>
        <th>数量</th>
        <th>位号</th>
        <th>数量/位号校验</th>
        <th>物料库匹配</th>
      </tr>
    </thead>
    <tbody>
`);
                g.rows.forEach((r) => {
                  const des = safeJoin(r.designators, ', ');
                  htmlParts.push(`
      <tr>
        <td>${r.code}</td>
        <td>${r.name}</td>
        <td>${r.quantity}</td>
        <td>${des}</td>
        <td>${r.qtyCheck}</td>
        <td>${r.libMatch}</td>
      </tr>
`);
                });
                htmlParts.push(`
    </tbody>
  </table>
`);
              }

              // INFO：BOM 中未包含的同替代组物料 + 用户处理决策
              if (g.missingInBom && g.missingInBom.length > 0) {
                const allHandled = g.missingInBom.every((m, i) => {
                  const key = `${g.label || '未分组'}__${m.code}__${i}`;
                  const st = groupMissingDecisions[key]?.status || 'pending';
                  return st !== 'pending';
                });
                const prefix =
                  'INFO：物料库中同替代组物料，BOM 中未包含（已自动列入，建议加入 BOM）';
                htmlParts.push(`
  <p>${prefix}${allHandled ? ' · 已全部由用户处理' : ''}</p>
  <table>
    <thead>
      <tr>
        <th class="col-code">物料代码</th>
        <th class="col-name">物料名称</th>
        <th>所属库</th>
        <th>替代组标签</th>
        <th>用户处理决策</th>
      </tr>
    </thead>
    <tbody>
`);
                g.missingInBom.forEach((m, i) => {
                  const key = `${g.label || '未分组'}__${m.code}__${i}`;
                  const decision = groupMissingDecisions[key] || {
                    status: 'pending' as GroupMissingDecisionStatus,
                  };
                  const decLabel = statusLabel(decision.status);
                  const ignoreReason = decision.reason || '';
                  const iconPrefix =
                    decision.status === 'pending'
                      ? '🔴 待处理'
                      : '🔵 已处理';
                  const decisionTextCore =
                    decision.status === 'ignored' && ignoreReason
                      ? `${decLabel}（原因：${ignoreReason}）`
                      : decLabel;
                  const decisionText = `${iconPrefix} · ${decisionTextCore}`;
                  const rowClass =
                    decision.status === 'pending' ? 'tr-info-pending' : 'tr-info-handled';
                  htmlParts.push(`
      <tr class="${rowClass}">
        <td>${m.code}</td>
        <td>${m.name}</td>
        <td>${m.libName}</td>
        <td>${m.groupLabel}</td>
        <td>${decisionText}</td>
      </tr>
`);
                });
                htmlParts.push(`
    </tbody>
  </table>
`);
              }
            });
          } else {
            // 物料匹配 / 替换对检查：按行列表展示（仅 INFO 项 + 用户处理决策）
            htmlParts.push(`
  <table>
    <thead>
      <tr>
        <th class="col-code">物料代码</th>
        <th class="col-name">物料名称</th>
        <th>数量</th>
        <th>位号</th>
        <th>数量/位号校验</th>
        <th>物料库匹配 / INFO 来源</th>
        <th>用户处理决策</th>
        <th>用户忽略原因</th>
      </tr>
    </thead>
    <tbody>
`);

            list.forEach((it) => {
              const designators = safeJoin(it.row.designators, ', ');
              const igReason = it.ignoreReason || '';
              const decisionLabel = statusLabel(it.status);
              const iconPrefix =
                it.status === 'pending'
                  ? '🔴 待处理'
                  : '🔵 已处理';
              const decisionText =
                it.status === 'ignored' && igReason
                  ? `${iconPrefix} · ${decisionLabel}（原因：${igReason}）`
                  : `${iconPrefix} · ${decisionLabel}`;
              const rowClass =
                it.status === 'pending' ? 'tr-info-pending' : 'tr-info-handled';
              htmlParts.push(`
      <tr class="${rowClass}">
        <td>${it.row.code}</td>
        <td>${it.row.name}</td>
        <td>${it.row.quantity ?? ''}</td>
        <td>${designators || ''}</td>
        <td>${it.row.qtyCheck}</td>
        <td>${it.row.libMatch}</td>
        <td>${decisionText}</td>
        <td>${igReason}</td>
      </tr>
`);
            });

            htmlParts.push(`
    </tbody>
  </table>
`);
          }
        });

        htmlParts.push(`
</body>
</html>
`);

        const reportHtml = htmlParts.join('');
        const result = await printHtmlDocument(reportHtml);
        if (result === 'external' || result === 'failed') {
          alert(getPrintMessage(result));
        }
      };

      return (
        <div className="h-full flex flex-col text-xs">
          <div className="flex-shrink-0 px-3 pt-2 pb-2 border-b border-gray-200 bg-white sticky top-0 z-10 space-y-2">
            <div className="flex items-start justify-between gap-2 flex-wrap">
              <div className="flex flex-col gap-0.5 min-w-0">
                <span className="text-gray-700 font-semibold">第 5 步 · 最终 BOM 预览</span>
                <span className="text-[11px] text-gray-500">
                  基于「物料匹配」「替代组验证」「替换对检查」三大功能中的处理决策生成最终 BOM 视图与导出结果，本页不再新增决策。
                </span>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  className={secondaryButtonClass}
                  onClick={exportFinalBOM}
                >
                  导出最终 BOM
                </button>
                <button
                  type="button"
                  className={successButtonClass}
                  onClick={exportOptimizeReport}
                >
                  导出 AI Check 报告
                </button>
              </div>
            </div>
            <div className="rounded-lg border border-sky-200 bg-sky-50/60 px-2.5 py-2 space-y-1.5">
              <div className="text-[11px] font-semibold text-sky-900">
                PLM 格式整理
              </div>
              <p className="text-[11px] text-sky-800/90 leading-snug">
                按「BOM转化PLM格式」规则将下方最终 BOM 行写入与「
                <code className="text-[10px] bg-white/80 px-1 rounded">BOM-TS5021493-导入模板wlgs.xls</code>
                」一致的列结构（内置表头，不发起网络请求），生成可导入 PLM 的 xlsx。
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex flex-col gap-0.5 text-[10px] text-gray-600">
                  <span>父项编码</span>
                  <input
                    type="text"
                    value={plmParentCode}
                    onChange={(e) => setPlmParentCode(e.target.value)}
                    placeholder="可选"
                    className="border border-gray-300 rounded-md px-2 py-1 text-xs w-36 bg-white"
                  />
                </label>
                <label className="flex flex-col gap-0.5 text-[10px] text-gray-600 min-w-[10rem] flex-1 max-w-xs">
                  <span>父项说明</span>
                  <input
                    type="text"
                    value={plmParentStdDesc}
                    onChange={(e) => setPlmParentStdDesc(e.target.value)}
                    placeholder="可选；wlgs 模板写入「父项名称」，有「父项标准描述」列时写入该列"
                    className="border border-gray-300 rounded-md px-2 py-1 text-xs w-full bg-white"
                  />
                </label>
                <button
                  type="button"
                  className={`${primaryButtonClass} mt-4 sm:mt-0`}
                  disabled={plmExporting}
                  onClick={exportPlmStandardBom}
                >
                  {plmExporting ? '生成中…' : '下载 PLM 标准 BOM'}
                </button>
              </div>
            </div>
            <div className="rounded-lg border border-gray-200 bg-slate-50 px-2.5 py-2">
              <div className="text-[11px] font-semibold text-gray-700 mb-1.5">
                全流程进度（已完成为绿色；第 5 步仅展示入口，暂不判定「已完成」）
              </div>
              <div className="flex flex-wrap gap-1.5">
                {bomWorkflowProgress.steps.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setActiveTab(s.tab)}
                    className={`text-[11px] px-2 py-0.5 rounded-md border font-medium transition ${
                      s.done
                        ? 'border-emerald-500 bg-emerald-50 text-emerald-800'
                        : s.trackCompletion === false
                        ? 'border-amber-200 bg-amber-50/90 text-amber-900'
                        : 'border-gray-200 bg-white text-gray-500'
                    }`}
                  >
                    第{s.order}步 {s.done ? '✓' : '○'} {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="flex-shrink-0 px-3 pt-2 pb-1 border-b bg-white text-[11px] text-gray-600 flex items-center gap-4">
            <span>INFO（待处理）：{pendingItems.length} 条</span>
            <span>
              已确认：{optimizeRows.filter((it) => it.status !== 'pending').length} /{' '}
              {optimizeRows.length}
            </span>
            <span>PASS 分组：{passGroups.length} 个</span>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-4">
            {/* INFO 组（待处理） */}
            {pendingItems.length > 0 && (
              <div className="border rounded-lg bg-blue-50/60 shadow-sm overflow-hidden">
                <button
                  type="button"
                  className="w-full px-4 py-3 border-b bg-blue-100 flex items-center justify-between rounded-t-lg"
                  onClick={() => setOptimizeInfoCollapsed((v) => !v)}
                >
                  <span className="text-[11px] font-semibold text-blue-800">
                    ℹ️ INFO 组（待处理） · {pendingItems.length} 条
                  </span>
                  <span className="text-[11px] text-blue-700">
                    {optimizeInfoCollapsed ? '展开' : '收起'}
                  </span>
                </button>
                {!optimizeInfoCollapsed && (
                  <div className="overflow-auto">
                        <table className="min-w-full table-fixed text-[11px]">
                          <thead className="bg-white">
                            <tr>
                              <th className="px-2 py-1 text-left w-28">物料代码</th>
                              <th className="px-2 py-1 text-left w-64">物料名称</th>
                          <th className="px-2 py-1 text-right w-12">数量</th>
                          <th className="px-2 py-1 text-left w-40">位号</th>
                          <th className="px-2 py-1 text-left w-32">数量/位号校验</th>
                          <th className="px-2 py-1 text-left w-40">物料库匹配</th>
                          <th className="px-2 py-1 text-left w-28">处理决策</th>
                        </tr>
                      </thead>
                      <tbody>
                        {groupByLabel(pendingItems).map(([label, items]) => {
                        const designatorsFull = (ds: string[]) => ds.join(', ');
                        const designatorsFolded = (ds: string[]) => {
                          const maxShown = 6;
                          const shown = ds.slice(0, maxShown);
                          const rest = ds.length > maxShown ? ds.length - maxShown : 0;
                          return (
                            (shown.join(', ') || '—') +
                            (rest > 0 ? `，等 ${rest} 个已折叠` : '')
                          );
                        };
                          return (
                            <React.Fragment key={label}>
                              <tr className="bg-blue-50/80">
                                <td
                                  className="px-2 py-1 text-[11px] text-blue-800 font-semibold"
                                  colSpan={8}
                                >
                                  分组/替代组：{label}
                                </td>
                              </tr>
                              {items.map((it) => (
                                <tr key={it.id} className="border-t border-blue-100">
                                  <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                    {it.row.code}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                    {it.row.name}
                                  </td>
                                  <td className="px-2 py-1 text-right whitespace-nowrap">
                                    {it.row.quantity}
                                  </td>
                                  <td
                                    className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis"
                                    title={designatorsFull(it.row.designators) || undefined}
                                  >
                                    {designatorsFolded(it.row.designators)}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                    {it.row.qtyCheck}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                    {it.row.libMatch}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap">
                                    <div className="flex flex-col gap-0.5 items-start">
                                      <span>
                                        {it.status === 'pending'
                                          ? '待定'
                                          : it.status === 'accepted'
                                          ? it.source === 'match'
                                            ? '新器件'
                                            : '接受'
                                          : '忽略'}
                                      </span>
                                      {it.status === 'ignored' && it.ignoreReason && (
                                        <span className="text-[11px] text-gray-600">
                                          忽略原因：{it.ignoreReason}
                                        </span>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </React.Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* USER DONE 组（在前序模块或本页已处理完成） */}
            {doneItems.length > 0 && (
              <div className="border rounded-lg bg-emerald-50/60 shadow-sm overflow-hidden">
                <button
                  type="button"
                  className="w-full px-4 py-3 border-b bg-emerald-100 flex items-center justify-between rounded-t-lg"
                  onClick={() => setOptimizeDoneCollapsed((v) => !v)}
                >
                  <span className="text-[11px] font-semibold text-emerald-800">
                    ✅ USER DONE 组（已处理） · {doneItems.length} 条
                  </span>
                  <span className="text-[11px] text-emerald-700">
                    {optimizeDoneCollapsed ? '展开' : '收起'}
                  </span>
                </button>
                {!optimizeDoneCollapsed && (
                  <div className="overflow-auto">
                        <table className="min-w-full table-fixed text-[11px]">
                          <thead className="bg-white">
                            <tr>
                              <th className="px-2 py-1 text-left w-28">物料代码</th>
                              <th className="px-2 py-1 text-left w-64">物料名称</th>
                          <th className="px-2 py-1 text-right w-12">数量</th>
                          <th className="px-2 py-1 text-left w-40">位号</th>
                          <th className="px-2 py-1 text-left w-32">数量/位号校验</th>
                          <th className="px-2 py-1 text-left w-40">物料库匹配</th>
                          <th className="px-2 py-1 text-left w-28">确认结果</th>
                          <th className="px-2 py-1 text-left w-40">忽略原因</th>
                        </tr>
                      </thead>
                      <tbody>
                        {groupByLabel(doneItems).map(([label, items]) => {
                          const designatorsFull = (ds: string[]) => ds.join(', ');
                          const designatorsFolded = (ds: string[]) => {
                            const maxShown = 6;
                            const shown = ds.slice(0, maxShown);
                            const rest = ds.length > maxShown ? ds.length - maxShown : 0;
                            return (
                              (shown.join(', ') || '—') +
                              (rest > 0 ? `，等 ${rest} 个已折叠` : '')
                            );
                          };
                          return (
                            <React.Fragment key={label}>
                              <tr className="bg-emerald-50/80">
                                <td
                                  className="px-2 py-1 text-[11px] text-emerald-800 font-semibold"
                                  colSpan={8}
                                >
                                  分组/替代组：{label}
                                </td>
                              </tr>
                              {items.map((it) => (
                                <tr key={it.id} className="border-t border-emerald-100">
                                  <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                    {it.row.code}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                    {it.row.name}
                                  </td>
                                  <td className="px-2 py-1 text-right whitespace-nowrap">
                                    {it.row.quantity}
                                  </td>
                                  <td
                                    className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis"
                                    title={designatorsFull(it.row.designators) || undefined}
                                  >
                                    {designatorsFolded(it.row.designators)}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                    {it.row.qtyCheck}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                    {it.row.libMatch}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap">
                                    {it.status === 'accepted'
                                      ? it.source === 'match'
                                        ? '新器件'
                                        : '接受'
                                      : '忽略'}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap overflow-hidden text-ellipsis">
                                    {it.ignoreReason || '—'}
                                  </td>
                                </tr>
                              ))}
                            </React.Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* PASS 分组列表（无优化项的分组/替代组） */}
            <div className="border rounded-lg bg-emerald-50 shadow-sm overflow-hidden">
              <button
                type="button"
                className="w-full px-4 py-3 border-b bg-emerald-100 flex items-center justify-between rounded-t-lg"
                onClick={() => setOptimizePassCollapsed((v) => !v)}
              >
                <span className="text-[11px] font-semibold text-emerald-800">
                  ✅ PASS 分组（无优化项） · {passGroups.length} 个
                </span>
                <span className="text-[11px] text-emerald-700">
                  {optimizePassCollapsed ? '展开' : '收起'}
                </span>
              </button>
              {!optimizePassCollapsed && (
                <div className="px-3 py-2 text-[11px] text-emerald-700">
                  {passGroups.length === 0 ? (
                    <div>当前暂无“完全 PASS”的替代组 / 替换对分组。</div>
                  ) : (
                    <table className="min-w-full table-fixed text-[11px] mt-1 border-t border-emerald-200">
                      <thead className="bg-emerald-50">
                        <tr>
                          <th className="px-2 py-1 text-left w-24">来源</th>
                          <th className="px-2 py-1 text-left">分组 / 替代组</th>
                          <th className="px-2 py-1 text-left w-64">说明</th>
                        </tr>
                      </thead>
                      <tbody>
                        {passGroups.map((pg, idx) => (
                          <tr key={idx} className="border-t border-emerald-100">
                            <td className="px-2 py-1">
                              {pg.source === 'match'
                                ? '物料匹配'
                                : pg.source === 'group'
                                ? '替代组验证'
                                : '替换对检查'}
                            </td>
                            <td className="px-2 py-1 overflow-hidden text-ellipsis">
                              {pg.label}
                            </td>
                            <td className="px-2 py-1 overflow-hidden text-ellipsis">
                              {pg.summary}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      );
    }
    return null;
  };

  if (collapsed) {
    return (
      <button
        onClick={onCollapseToggle}
        className="flex-shrink-0 self-center bg-sky-100 hover:bg-sky-200 text-sky-800 px-3 py-3 rounded-l-xl transition-colors shadow-md text-sm font-semibold flex items-center gap-1"
        title="展开 BOM 面板"
      >
        <span className="whitespace-nowrap">BOM 面板</span>
      </button>
    );
  }

  return (
    <div
      className={`bg-white flex flex-col relative transition-all duration-300 ${
        fullWidth ? 'w-full' : 'w-1/2'
      }`}
    >
      <button
        onClick={onCollapseToggle}
        className="absolute left-0 top-1/2 -translate-x-full -translate-y-1/2 z-10 bg-sky-100 hover:bg-sky-200 text-sky-800 px-4 py-2.5 rounded-l-xl transition-colors shadow-md flex items-center gap-2"
        title="收起 BOM 面板"
      >
        <span className="text-sm font-medium whitespace-nowrap">BOM 面板</span>
      </button>
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between border-b bg-gradient-to-r from-sky-50 to-cyan-50 flex-shrink-0 px-3 py-2">
          <div className="flex flex-wrap gap-2">
            <button className={tabNavBtnClass('import')} onClick={() => setActiveTab('import')}>
              ① 导入并生成
            </button>
            <button className={tabNavBtnClass('match')} onClick={() => setActiveTab('match')}>
              ② 物料匹配
            </button>
            <button className={tabNavBtnClass('group')} onClick={() => setActiveTab('group')}>
              ③ 替代组验证
            </button>
            <button
              className={tabNavBtnClass('replacement')}
              onClick={() => setActiveTab('replacement')}
            >
              ④ 替换对检查
            </button>
            <button className={tabNavBtnClass('optimize')} onClick={() => setActiveTab('optimize')}>
              ⑤ 最终 BOM 预览
            </button>
          </div>
          <Link
            to="/"
            className="text-sm font-semibold px-4 py-2.5 rounded-xl border border-emerald-300 bg-emerald-500 text-white hover:bg-emerald-600 shadow-sm transition"
            title="返回主页"
          >
            返回主页
          </Link>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">{renderTabContent()}</div>
      </div>
    </div>
  );
};

