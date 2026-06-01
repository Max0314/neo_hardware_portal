import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import { Message, AIConfig } from '@/types';
import { MessageBubble } from './MessageBubble';
import { AISelector } from './AISelector';
import { ChatInput } from './ChatInput';
import { CustomAIModal } from './CustomAIModal';
import { KnowledgeBaseModal } from './KnowledgeBaseModal';
import { EventTriggerModal } from './EventTriggerModal';
import { PromptReviewInputModal } from './PromptReviewInputModal';
import { TetrisGame } from './TetrisGame';
import { RecycleBinModal } from './RecycleBinModal';
import { NetlistResultsTable } from './NetlistResultsTable';
import { NetlistResultModal } from './NetlistResultModal';
import { NetlistAnalysisSidebar } from './NetlistAnalysisSidebar';
import { HistoryDropdown } from './HistoryDropdown';
import { NetlistResultsPanel } from './NetlistResultsPanel';
import {
  BOMPanel,
  type BOMMatchGroup,
  type BOMGroupValidateGroup,
  type BOMReplacementCheckGroup,
  type BOMDesignatorTagIssue,
} from './BOMPanel';
import { EventFlowPanel } from './EventFlowPanel';
import { BuildSOPModal } from './BuildSOPModal';
import { wsClient } from '@/api/websocket';
import { v4 as uuidv4 } from 'uuid';
import { calculateTokens } from '@/utils/format';
import { getSOPById } from '@/utils/sopStorage';
import {
  loadBOM,
  bomWorkflowGroupKey,
  formatBomWorkflowGroupDisplayLabel,
  BOM_NO_LIB_SUBSTITUTE_TAG_MARKER,
  collectDesignatorSubstituteTagIssues,
  type BOMState,
  type BOMItem,
} from '@/utils/bomStore';
import {
  fetchMaterialLibraries,
  buildCodeToMaterialRows,
} from '@/utils/materialDb';
import { loadReplacementGroupsAsync } from '@/utils/replacementPairsStorage';
import { buildMessageWithAttachments } from '@/utils/chatAttachmentMarkers';
import { apiUrl, getWsUrl } from '@/utils/apiBase';
import { buildAttachmentDigest, parseChatFile } from '@/utils/chatFileParse';
import { Plus, Trash2, ChevronLeft, ChevronRight, Home, ListOrdered, Database, BarChart3, KeyRound, FileText } from 'lucide-react';
import { AIKeysSettingsModal } from './AIKeysSettingsModal';
import axios from 'axios';
import type { AuthMeResponse, AuthMeUser } from '@/utils/authDisplay';
import { canManageModelConfig } from '@/utils/rolePermissions';
import {
  getSchematicReviewPrompt,
  buildReportSummaryText,
  parseSchematicReviewJson,
  applySchematicAiSelection,
  DEFAULT_SCHEMATIC_AI_ID,
  mergeSchematicReviewJson,
  isSchematicReviewComplete,
  buildSchematicContinuationPrompt,
  SCHEMATIC_MAX_OUTPUT_TOKENS,
  SCHEMATIC_REVIEW_MAX_ROUNDS,
} from '@/utils/schematicReview';
import {
  parseHistoryAiReviewEntries,
  type SchematicReviewHistoryRecord,
} from '@/utils/schematicReviewHistory';
import type { SchematicCheckDispositionMap } from '@/utils/schematicReview';
import { SchematicReviewPromptModal } from './SchematicReviewPromptModal';

interface GroupChatRoomProps {
  /** 页面标题，默认「AI工作室」。用于 BOM AI check 等复用的会议室 */
  title?: string;
  /** 模式：default / bom / schematic（原理图 AI 审核） */
  mode?: 'default' | 'bom' | 'schematic';
}

export const GroupChatRoom: React.FC<GroupChatRoomProps> = ({ title = 'AI工作室', mode = 'default' }) => {
  const isSchematic = mode === 'schematic';
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [selectedAIs, setSelectedAIs] = useState<AIConfig[]>([]);
  const [conversationId] = useState<string>(uuidv4());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [totalTokens, setTotalTokens] = useState(0);
  const [showCustomModal, setShowCustomModal] = useState(false);
  const [showAIKeysModal, setShowAIKeysModal] = useState(false);
  const [showSchematicPromptModal, setShowSchematicPromptModal] = useState(false);
  const [showKnowledgeModal, setShowKnowledgeModal] = useState(false);
  const [selectedRoleForKnowledge, setSelectedRoleForKnowledge] = useState<{id: string, name: string} | null>(null);
  const [showEventTriggerModal, setShowEventTriggerModal] = useState(false);
  const [selectedRoleForEventTrigger, setSelectedRoleForEventTrigger] = useState<{id: string, name: string} | null>(null);
  const [showRecycleBin, setShowRecycleBin] = useState(false);
  const [showNetlistResults, setShowNetlistResults] = useState(false);
  const [selectedNetlistResult, setSelectedNetlistResult] = useState<{id: string, type: 'comparison' | 'analysis'} | null>(null);
  const [showNetlistSidebar, setShowNetlistSidebar] = useState(false);
  const [netlistSidebarMode, setNetlistSidebarMode] = useState<'compare' | 'analyze'>('compare');
  const [currentConversationId, setCurrentConversationId] = useState<string>(conversationId);
  const [panelResultId, setPanelResultId] = useState<string | null>(null);
  const [panelResultType, setPanelResultType] = useState<'comparison' | 'analysis' | null>(null);
  const [isRightPanelCollapsed, setIsRightPanelCollapsed] = useState(false);
  const [showTetrisGame, setShowTetrisGame] = useState(false);
  const [selectedQuotedMessages, setSelectedQuotedMessages] = useState<Set<string>>(new Set());  // 选中的引用消息ID集合
  const [showPromptReviewModal, setShowPromptReviewModal] = useState(false);
  const [promptReviewPrompt, setPromptReviewPrompt] = useState('');
  const [promptReviewMessageId, setPromptReviewMessageId] = useState<string | null>(null);
  const [promptReviewDefaultAIIds, setPromptReviewDefaultAIIds] = useState<string[] | undefined>(undefined);
  const [promptReviewMaxTokens, setPromptReviewMaxTokens] = useState<number | undefined>(undefined);
  // 物料库物料查询：事件触发后给用户一个输入查询词的地方
  const [showMaterialSearchModal, setShowMaterialSearchModal] = useState(false);
  const [materialSearchQuery, setMaterialSearchQuery] = useState('');
  const [materialSearchMessageId, setMaterialSearchMessageId] = useState<string | null>(null);
  const [isLeftPanelCollapsed, setIsLeftPanelCollapsed] = useState(false);
  const [isSopMode, setIsSopMode] = useState(false);
  const [showBuildSOPModal, setShowBuildSOPModal] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const sopIdFromUrl = searchParams.get('sop');
  const sopFromUrl = sopIdFromUrl ? getSOPById(sopIdFromUrl) : undefined;
  const flowStepResponseCallbackRef = useRef<((content: string) => void) | null>(null);
  /** 从聊天中识别并收集的 AI 评审结果（网表分析/接口检查等 JSON），用于右侧 AI评审 栏 */
  const [aiReviewEntries, setAiReviewEntries] = useState<Array<{ id: string; content: string; parsed: any; timestamp: Date; aiName: string }>>([]);
  /** 硬件分析结果聚合（网表解析 + AI 评审 JSON），展示在右侧评审总结 */
  const [aggregatedReviewSummary, setAggregatedReviewSummary] = useState<any>(null);
  const [bomMatchGroups, setBomMatchGroups] = useState<BOMMatchGroup[] | null>(null);
  const [bomMatchDesignatorIssues, setBomMatchDesignatorIssues] = useState<BOMDesignatorTagIssue[] | null>(null);
  const [bomGroupValidateResult, setBomGroupValidateResult] = useState<BOMGroupValidateGroup[] | null>(null);
  const [bomReplacementCheckResult, setBomReplacementCheckResult] = useState<BOMReplacementCheckGroup[] | null>(null);
  /** 待随下一条用户消息发送的本地文件（纯前端解析后加入上下文） */
  const [pendingChatFiles, setPendingChatFiles] = useState<File[]>([]);
  const [isAttachmentSubmitting, setIsAttachmentSubmitting] = useState(false);
  /** 选文件后立即提示（与教程中「上传成功」反馈一致） */
  const [attachmentPickNotice, setAttachmentPickNotice] = useState<string | null>(null);
  /** 原理图 AI 审核：Step4 导出后解锁聊天输入 */
  const [reviewExported, setReviewExported] = useState(false);
  /** 原理图 AI 审核：点击「发送 AI 评审」后展开聊天栏（导出前只读） */
  const [chatPanelExpanded, setChatPanelExpanded] = useState(false);
  const [cleanedNetlistText, setCleanedNetlistText] = useState('');
  const [cleanConfirmed, setCleanConfirmed] = useState(false);
  const [reviewPrompt, setReviewPrompt] = useState(() => getSchematicReviewPrompt());
  const [aiReviewRunning, setAiReviewRunning] = useState(false);
  const [aiReviewRound, setAiReviewRound] = useState(0);
  const schematicAiReviewPendingRef = useRef(false);
  const schematicContinuationLoopRef = useRef(false);
  const schematicFinishReasonsRef = useRef<Record<string, string>>({});
  const schematicCatalogAisRef = useRef<AIConfig[]>([]);
  const [schematicDefaultAiId, setSchematicDefaultAiId] = useState(DEFAULT_SCHEMATIC_AI_ID);
  const [schematicDefaultAiName, setSchematicDefaultAiName] = useState('百炼-deepseekV4');
  const [schematicHistoryViewMode, setSchematicHistoryViewMode] = useState(false);
  const [viewingHistoryTitle, setViewingHistoryTitle] = useState<string | null>(null);
  const [schematicHistoryDispositions, setSchematicHistoryDispositions] =
    useState<SchematicCheckDispositionMap>({});
  const [sessionUser, setSessionUser] = useState<AuthMeUser | null>(null);
  const chatSectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isSchematic && sopIdFromUrl) {
      navigate('/', { replace: true });
    }
  }, [isSchematic, sopIdFromUrl, navigate]);

  useEffect(() => {
    if (!isSchematic) return;
    axios
      .get<AuthMeResponse>(apiUrl('/api/auth/me'), { withCredentials: true })
      .then((res) => {
        if (res.data?.authenticated && res.data.user) setSessionUser(res.data.user);
        else setSessionUser(null);
      })
      .catch(() => setSessionUser(null));
  }, [isSchematic]);

  useEffect(() => {
    if (sopIdFromUrl && !isSchematic) {
      setIsSopMode(true);
      setIsRightPanelCollapsed(false);
      setSelectedQuotedMessages(new Set());
      setPendingChatFiles([]);
      setAttachmentPickNotice(null);
    } else {
      setIsSopMode(false);
    }
  }, [sopIdFromUrl, isSchematic]);

  useEffect(() => {
    if (isSchematic) {
      setIsRightPanelCollapsed(false);
    }
  }, [isSchematic]);

  const runBomMaterialMatch = useCallback(async () => {
    try {
      const bom: BOMState | null = typeof window !== 'undefined' ? loadBOM() : null;
      if (!bom || !bom.items.length) {
        setMessages((prev) => [
          ...prev,
          {
            id: uuidv4(),
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: '巴巴塔',
            content: '当前尚未导入 BOM，请先在右侧 BOM 面板完成 BOM 导入与生成。',
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
          },
        ]);
        return;
      }
      const libs = await fetchMaterialLibraries();
      if (!libs.length) {
        setMessages((prev) => [
          ...prev,
          {
            id: uuidv4(),
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: '巴巴塔',
            content: '物料库中尚未创建任何物料库，请先在「BOM AI检查匹配物料库查询管理」中维护物料。',
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
          },
        ]);
        return;
      }
      const codeToRows = buildCodeToMaterialRows(libs);
      const designatorIssues = collectDesignatorSubstituteTagIssues(bom.items, codeToRows);

      const conflictByCode = new Map<string, Extract<BOMDesignatorTagIssue, { kind: 'tag_conflict' }>[]>();
      const emptyByCode = new Map<string, Extract<BOMDesignatorTagIssue, { kind: 'empty_tag' }>[]>();
      for (const issue of designatorIssues) {
        if (issue.kind === 'tag_conflict') {
          for (const code of issue.codes) {
            if (!conflictByCode.has(code)) conflictByCode.set(code, []);
            conflictByCode.get(code)!.push(issue);
          }
        } else {
          if (!emptyByCode.has(issue.code)) emptyByCode.set(issue.code, []);
          emptyByCode.get(issue.code)!.push(issue);
        }
      }

      const groupMap: Record<string, BOMItem[]> = {};
      for (const item of bom.items) {
        const key = bomWorkflowGroupKey(item, codeToRows);
        if (!groupMap[key]) groupMap[key] = [];
        groupMap[key].push(item);
      }

      const groupKeys = Object.keys(groupMap).sort((a, b) => a.localeCompare(b));
      const lines: string[] = [];
      lines.push('🔍 **BOM 物料匹配结果**');
      lines.push('');
      if (designatorIssues.length > 0) {
        lines.push('**同位号替代组标签检查**');
        for (const issue of designatorIssues) {
          if (issue.kind === 'tag_conflict') {
            lines.push(
              `- ⚠️ 位号 ${issue.designator}：${issue.message}（${issue.codes.join(', ')}）`
            );
          } else {
            lines.push(
              `- ⚠️ 位号 ${issue.designator} · 物料 ${issue.code}：物料库此物料替代组标签为空`
            );
          }
        }
        lines.push('');
      }
      const newGroups: BOMMatchGroup[] = [];
      for (const gKey of groupKeys) {
        const items = groupMap[gKey];
        const allDes = Array.from(
          new Set(items.flatMap((i) => i.designators || []).map((d) => d.trim()).filter(Boolean))
        ).sort((a, b) => a.localeCompare(b));

        const rowStatuses: {
          item: BOMItem;
          qtyOk: boolean;
        }[] = items.map((it) => ({
          item: it,
          qtyOk: (it.quantity || 0) === (it.designators?.length || 0),
        }));

        const labels = new Set<string>();
        const missingInLib: string[] = [];
        for (const it of items) {
          const rows = codeToRows[it.code] || [];
          if (!rows.length) {
            missingInLib.push(it.code);
            continue;
          }
          for (const r of rows) {
            if (r.groupLabel) labels.add(r.groupLabel);
          }
        }

        // 这里只做简单的标签汇总展示，不再在“物料匹配”阶段判定标签冲突问题
        const consensusLibLabel = labels.size === 1 ? Array.from(labels)[0] : '';
        const isNoLibSplit = gKey.includes(BOM_NO_LIB_SUBSTITUTE_TAG_MARKER);
        const structuralLabel =
          consensusLibLabel || (isNoLibSplit || gKey.includes(',') ? '' : gKey);
        const finalGroupLabel = formatBomWorkflowGroupDisplayLabel(
          gKey,
          consensusLibLabel || structuralLabel
        );
        const labelSummary =
          labels.size > 0
            ? `替代组标签：${Array.from(labels).join(', ')}`
            : isNoLibSplit
            ? '替代组标签：无（物料库为空，未与其它空白标签物料合并为同一组）'
            : '替代组标签：未知';

        const groupIssues: string[] = [];
        if (rowStatuses.some((s) => !s.qtyOk)) {
          groupIssues.push('部分物料的数量与位号个数不一致');
        }
        if (missingInLib.length) {
          groupIssues.push(`物料库中未匹配到物料：${missingInLib.join(', ')}`);
        }

        let badge: '🟥' | '🟨' | '🟢' = '🟢';
        if (rowStatuses.some((s) => !s.qtyOk)) {
          badge = '🟥';
        } else if (missingInLib.length) {
          badge = '🟨';
        }

        lines.push(`${badge} **替代组 ${finalGroupLabel}**`);
        lines.push(`- ${labelSummary}`);
        lines.push(`- 位号（${allDes.length} 个）：${allDes.join(', ') || '—'}`);
        if (groupIssues.length) {
          lines.push(`- 检查结果：${groupIssues.join('；')}`);
        } else {
          lines.push('- 检查结果：通过');
        }
        lines.push('');
        lines.push('| 物料代码 | 物料名称 | 数量 | 位号 | 数量/位号校验 | 物料库匹配 |');
        lines.push('| --- | --- | --- | --- | --- | --- |');
        const groupRows: BOMMatchGroup['rows'] = [];
        for (const { item, qtyOk } of rowStatuses) {
          const rows = codeToRows[item.code] || [];
          const first = rows[0];
          const libDesc = first?.desc || '';
          const libLabel = first?.groupLabel || '';
          const qtyCheck = qtyOk ? '✅ 一致' : `❌ 不一致（数量=${item.quantity}, 位号数=${item.designators?.length || 0}）`;
          const libMatch =
            rows.length === 0
              ? '⚠️ 未在物料库中找到'
              : `✅ ${rows[0].libName}${libLabel ? ` · 组：${libLabel}` : ''}`;
          const name = item.name || libDesc || '—';
          const designators = item.designators || [];
          lines.push(
            `| ${item.code} | ${name} | ${item.quantity} | ${designators.join(', ')} | ${qtyCheck} | ${libMatch} |`
          );
          groupRows.push({
            code: item.code,
            name,
            quantity: item.quantity,
            designators,
            qtyCheck,
            libMatch,
          });
        }
        lines.push('');
        newGroups.push({
          label: finalGroupLabel,
          badge,
          labelSummary,
          issues: groupIssues,
          designators: allDes,
          rows: groupRows,
        });
      }

      for (const group of newGroups) {
        const addedIssues = new Set<string>();
        let hasTagConflict = false;
        for (const row of group.rows) {
          for (const conflict of conflictByCode.get(row.code) || []) {
            hasTagConflict = true;
            const msg = `位号 ${conflict.designator}：${conflict.message}`;
            if (!addedIssues.has(msg)) {
              group.issues.push(msg);
              addedIssues.add(msg);
            }
          }
          for (const empty of emptyByCode.get(row.code) || []) {
            const msg = `位号 ${empty.designator} · 物料 ${empty.code}：物料库此物料替代组标签为空`;
            if (!addedIssues.has(msg)) {
              group.issues.push(msg);
              addedIssues.add(msg);
            }
          }
        }
        if (hasTagConflict && group.badge === '🟢') {
          group.badge = '🟨';
        }
      }

      setMessages((prev) => [
        ...prev,
        {
          id: uuidv4(),
          sender: 'ai',
          aiModel: 'babata',
          avatar: '🤖',
          name: '巴巴塔',
          content: lines.join('\n'),
          timestamp: new Date(),
          status: 'sent',
          isThinking: false,
        },
      ]);
      setBomMatchGroups(newGroups);
      setBomMatchDesignatorIssues(designatorIssues);
    } catch (e: any) {
      console.error('BOM 物料匹配失败', e);
      setMessages((prev) => [
        ...prev,
        {
          id: uuidv4(),
          sender: 'ai',
          aiModel: 'babata',
          avatar: '🤖',
          name: '巴巴塔',
          content: `BOM 物料匹配失败：${e?.message || String(e)}`,
          timestamp: new Date(),
          status: 'sent',
          isThinking: false,
        },
      ]);
    }
  }, []);

  const runBomGroupValidate = useCallback(async () => {
    try {
      const bom: BOMState | null = typeof window !== 'undefined' ? loadBOM() : null;
      if (!bom || !bom.items.length) {
        setMessages((prev) => [
          ...prev,
          {
            id: uuidv4(),
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: '巴巴塔',
            content: '当前尚未导入 BOM，请先在右侧 BOM 面板完成 BOM 导入与生成，并执行物料匹配。',
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
          },
        ]);
        return;
      }
      const libs = await fetchMaterialLibraries();
      if (!libs.length) {
        setMessages((prev) => [
          ...prev,
          {
            id: uuidv4(),
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: '巴巴塔',
            content: '物料库中尚未创建任何物料库，请先在「BOM AI检查匹配物料库查询管理」中维护物料。',
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
          },
        ]);
        return;
      }
      const codeToRows = buildCodeToMaterialRows(libs);
      const groupLabelToCodes: Record<string, Set<string>> = {};
      for (const [code, rows] of Object.entries(codeToRows)) {
        for (const row of rows) {
          const groupLabel = row.groupLabel;
          const r = row.raw as unknown[];
          const preferStatusRaw = r[5] != null ? String(r[5]).trim() : '';
          const preferStatusNorm = preferStatusRaw.replace(/\s+/g, '').toLowerCase();
          const isPreferredOrAvailable =
            preferStatusNorm.includes('优选') || preferStatusNorm.includes('可用');
          if (groupLabel && isPreferredOrAvailable) {
            if (!groupLabelToCodes[groupLabel]) {
              groupLabelToCodes[groupLabel] = new Set<string>();
            }
            groupLabelToCodes[groupLabel].add(code);
          }
        }
      }

      const groupMap: Record<string, BOMItem[]> = {};
      for (const item of bom.items) {
        const key = bomWorkflowGroupKey(item, codeToRows);
        if (!groupMap[key]) groupMap[key] = [];
        groupMap[key].push(item);
      }

      const groupKeys = Object.keys(groupMap).sort((a, b) => a.localeCompare(b));
      const validateGroups: BOMGroupValidateGroup[] = [];
      const lines: string[] = [];
      lines.push('📋 **替代组验证结果**');
      lines.push('');
      lines.push('基于物料匹配：① 同组物料在物料库中的替代组标签是否一致；② 物料库中同替代组物料是否均在 BOM 中，缺失项标红 INFO。');
      lines.push('');

      for (const gKey of groupKeys) {
        const items = groupMap[gKey];
        const labels = new Set<string>();
        for (const it of items) {
          const rows = codeToRows[it.code] || [];
          for (const r of rows) {
            if (r.groupLabel) labels.add(r.groupLabel);
          }
        }
        const hasLabelConflict = labels.size > 1;
        const libLabel = labels.size === 1 ? Array.from(labels)[0] : undefined;
        const finalGroupLabel = formatBomWorkflowGroupDisplayLabel(gKey, libLabel || '');

        let missingInBom: BOMGroupValidateGroup['missingInBom'] = [];
        if (libLabel && !hasLabelConflict) {
          const libCodes = Array.from(groupLabelToCodes[libLabel] || []);
          const bomCodes = new Set(items.map((it) => it.code));
          const missingCodes = libCodes.filter((c) => !bomCodes.has(c));
          for (const code of missingCodes) {
            const rows = codeToRows[code] || [];
            const first = rows[0];
            missingInBom.push({
              code,
              name: first?.desc || '—',
              libName: first?.libName || '—',
              groupLabel: libLabel,
            });
          }
        }

        const rowStatuses = items.map((it) => ({
          item: it,
          qtyOk: (it.quantity || 0) === (it.designators?.length || 0),
        }));
        const groupRows: BOMMatchGroup['rows'] = [];
        for (const { item, qtyOk } of rowStatuses) {
          const rows = codeToRows[item.code] || [];
          const first = rows[0];
          const libDesc = first?.desc || '';
          const libLabelVal = first?.groupLabel || '';
          const qtyCheck = qtyOk ? '✅ 一致' : `❌ 不一致（数量=${item.quantity}, 位号数=${item.designators?.length || 0}）`;
          const libMatch =
            rows.length === 0
              ? '⚠️ 未在物料库中找到'
              : `✅ ${rows[0].libName}${libLabelVal ? ` · 组：${libLabelVal}` : ''}`;
          const name = item.name || libDesc || '—';
          groupRows.push({
            code: item.code,
            name,
            quantity: item.quantity,
            designators: item.designators || [],
            qtyCheck,
            libMatch,
          });
        }

        validateGroups.push({
          label: finalGroupLabel,
          labelConsistent: !hasLabelConflict,
          labelConflictMessage: hasLabelConflict ? '同一替代组中物料在物料库中的替代组标签不一致' : undefined,
          libLabel,
          missingInBom,
          rows: groupRows,
        });

        lines.push(`**替代组 ${finalGroupLabel}**`);
        if (hasLabelConflict) {
          lines.push(`- ⚠️ 替代组标签不一致：${Array.from(labels).join(', ')}`);
        } else if (libLabel) {
          lines.push(`- 替代组标签一致：${libLabel}`);
        } else if (gKey.includes(BOM_NO_LIB_SUBSTITUTE_TAG_MARKER)) {
          lines.push(`- 物料库替代组标签为空，本组单独校验（不与其它空白标签物料合并为同一替代组）`);
        }
        if (missingInBom.length > 0) {
          lines.push(`- 🔴 INFO：BOM 中未包含的同替代组物料（建议加入）：${missingInBom.map((m) => m.code).join(', ')}`);
        }
        lines.push('');
      }

      setBomGroupValidateResult(validateGroups);
      setMessages((prev) => [
        ...prev,
        {
          id: uuidv4(),
          sender: 'ai',
          aiModel: 'babata',
          avatar: '🤖',
          name: '巴巴塔',
          content: lines.join('\n'),
          timestamp: new Date(),
          status: 'sent',
          isThinking: false,
        },
      ]);
    } catch (e: any) {
      console.error('替代组验证失败', e);
      setMessages((prev) => [
        ...prev,
        {
          id: uuidv4(),
          sender: 'ai',
          aiModel: 'babata',
          avatar: '🤖',
          name: '巴巴塔',
          content: `替代组验证失败：${e?.message || String(e)}`,
          timestamp: new Date(),
          status: 'sent',
          isThinking: false,
        },
      ]);
    }
  }, []);

  const runBomReplacementCheck = useCallback(async () => {
    try {
      const bom: BOMState | null = typeof window !== 'undefined' ? loadBOM() : null;
      if (!bom || !bom.items.length) {
        setMessages((prev) => [
          ...prev,
          {
            id: uuidv4(),
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: '巴巴塔',
            content: '当前尚未导入 BOM，请先在右侧 BOM 面板完成 BOM 导入与生成。',
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
          },
        ]);
        return;
      }

      const { groups } = await loadReplacementGroupsAsync();
      if (!groups.length) {
        setMessages((prev) => [
          ...prev,
          {
            id: uuidv4(),
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: '巴巴塔',
            content: '当前尚未在「替换对管理」中维护任何替换组，请先补充替换对配置后再执行检查。',
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
          },
        ]);
        return;
      }

      const bomItemsByCode: Record<string, BOMItem[]> = {};
      for (const item of bom.items) {
        if (!bomItemsByCode[item.code]) bomItemsByCode[item.code] = [];
        bomItemsByCode[item.code].push(item);
      }
      const bomCodeSet = new Set(Object.keys(bomItemsByCode));

      const results: BOMReplacementCheckGroup[] = [];
      const lines: string[] = [];
      lines.push('🔁 **替换对检查结果**');
      lines.push('');
      lines.push('规则：若 BOM 中出现了某个替换对里的任一物料，则该替换组内其他物料也应在 BOM 中体现；缺失项以 INFO 标记，建议人工评估是否需要补充到 BOM。');
      lines.push('');

      for (const g of groups) {
        const items = g.materialItems || [];
        if (!items.length) continue;
        const hasAnyInBom = items.some((it) => bomCodeSet.has(it.code));
        if (!hasAnyInBom) continue;

        const checkItems = items.map((it) => {
          const bomRows = bomItemsByCode[it.code] || [];
          const inBom = bomRows.length > 0;
          const quantity = bomRows.reduce((sum, r) => sum + (r.quantity || 0), 0);
          const desSet = new Set<string>();
          for (const r of bomRows) {
            for (const d of r.designators || []) {
              const t = d.trim();
              if (t) desSet.add(t);
            }
          }
          const bomDesignators = Array.from(desSet).sort((a, b) => a.localeCompare(b));
          return {
            code: it.code,
            name: it.name,
            inBom,
            bomQuantity: inBom ? quantity : undefined,
            bomDesignators: inBom ? bomDesignators : undefined,
          };
        });

        const missing = checkItems.filter((it) => !it.inBom);
        const present = checkItems.filter((it) => it.inBom);

        results.push({
          id: g.id,
          remark: g.remark,
          items: checkItems,
        });

        const groupLabel = checkItems.map((it) => (it.name ? `${it.code}(${it.name})` : it.code)).join(' / ');
        lines.push(`**替换组：${groupLabel}**`);
        if (g.remark) {
          lines.push(`- 备注：${g.remark}`);
        }
        lines.push(`- BOM 中已出现物料：${present.length ? present.map((it) => it.code).join(', ') : '无'}`);
        if (missing.length) {
          lines.push(`- 🔶 INFO：替换对中有 ${missing.length} 个物料未在 BOM 中出现：${missing.map((it) => it.code).join(', ')}`);
        } else {
          lines.push('- ✅ 检查结果：该替换组内物料均已在 BOM 中出现');
        }
        lines.push('');
      }

      if (!results.length) {
        setMessages((prev) => [
          ...prev,
          {
            id: uuidv4(),
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: '巴巴塔',
            content: '当前 BOM 中未命中任何替换对中的物料，本次替换对检查整体视为通过。',
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
          },
        ]);
        setBomReplacementCheckResult([
          {
            id: '__all_pass__',
            remark: '本次替换对检查：当前 BOM 中未命中任何替换对中的物料，整体通过。',
            items: [],
          },
        ]);
        return;
      }

      setBomReplacementCheckResult(results);
      setMessages((prev) => [
        ...prev,
        {
          id: uuidv4(),
          sender: 'ai',
          aiModel: 'babata',
          avatar: '🤖',
          name: '巴巴塔',
          content: lines.join('\n'),
          timestamp: new Date(),
          status: 'sent',
          isThinking: false,
        },
      ]);
    } catch (e: any) {
      console.error('替换对检查失败', e);
      setMessages((prev) => [
        ...prev,
        {
          id: uuidv4(),
          sender: 'ai',
          aiModel: 'babata',
          avatar: '🤖',
          name: '巴巴塔',
          content: `替换对检查失败：${e?.message || String(e)}`,
          timestamp: new Date(),
          status: 'sent',
          isThinking: false,
        },
      ]);
    }
  }, []);

  // 处理事件触发（使用useCallback确保可以在组件内访问）
  const handleEventTrigger = useCallback((eventResult: any) => {
    const eventType = eventResult.event_type;
    const result = eventResult.result || {};
    
    console.log('[事件触发]', eventType, result);
    
    if (eventType === 'aggregate_review_summary') {
      const aiReviews = aiReviewEntries.map((e) => ({
        parsed: e.parsed,
        aiName: e.aiName,
        timestamp: e.timestamp,
        id: e.id,
      }));
      const parsedParts = aiReviews.map((e) => e.parsed).filter(Boolean);
      const mergedReview = parsedParts.length ? mergeSchematicReviewJson(parsedParts) : null;
      const netlistId = panelResultType === 'analysis' ? panelResultId : null;
      const apply = (netlistData: any) => {
        setAggregatedReviewSummary({
          netlist: netlistData,
          aiReviews,
          mergedReview,
          aggregatedAt: new Date().toISOString(),
        });
        setIsRightPanelCollapsed(false);
      };
      if (netlistId) {
        axios.get(apiUrl(`/api/netlist/result/${netlistId}`)).then((res) => {
          if (res.data.success && res.data.data) {
            const netlistData = res.data.data.type === 'analysis' ? res.data.data.result : null;
            apply(netlistData);
          }
        }).catch(() => {
          apply(null);
        });
      } else {
        apply(null);
      }
      return;
    }

    if (eventType === 'bom_material_match') {
      runBomMaterialMatch();
      return;
    }

    if (eventType === 'bom_group_validate') {
      runBomGroupValidate();
      return;
    }

    if (eventType === 'bom_replacement_check') {
      runBomReplacementCheck();
      return;
    }

    if (eventType === 'material_db_search') {
      void (async () => {
      try {
        const libs = await fetchMaterialLibraries();
        if (!libs.length) {
          setMessages((prev) => [
            ...prev,
            {
              id: uuidv4(),
              sender: 'ai',
              aiModel: 'babata',
              avatar: '🤖',
              name: '巴巴塔',
              content: '物料库中尚未创建任何物料库，请先在「BOM AI检查匹配物料库查询管理」中维护物料。',
              timestamp: new Date(),
              status: 'sent',
              isThinking: false,
            },
          ]);
          return;
        }
        const keywordsRaw: string =
          (typeof result.keywords === 'string' && result.keywords) ||
          (Array.isArray(result.keywords) ? result.keywords.join(' ') : '') ||
          (typeof result.query === 'string' ? result.query : '');
        const kwList = (keywordsRaw || '')
          .split(/[,，\s]+/)
          .map((s: string) => s.trim())
          .filter(Boolean)
          .map((s: string) => s.toLowerCase());

        const matches: {
          libName: string;
          code: string;
          desc: string;
          pads: string;
          price: string;
          group: string;
          status: string;
          remark: string;
        }[] = [];

        for (const lib of libs) {
          const libName = lib.name || '未命名物料库';
          const table = lib.currentTable;
          if (!table || !Array.isArray(table.data) || table.data.length < 2) continue;
          const rows = table.data.slice(1);
          for (const row of rows) {
            const [code, desc, pads, price, group, status, remark] = row as any[];
            const text = (
              (code || '') +
              ' ' +
              (desc || '') +
              ' ' +
              (pads || '') +
              ' ' +
              (group || '') +
              ' ' +
              (remark || '')
            )
              .toString()
              .toLowerCase();
            const ok = kwList.length === 0 ? true : kwList.every((kw) => text.includes(kw));
            if (!ok) continue;
            matches.push({
              libName,
              code: code || '',
              desc: desc || '',
              pads: pads || '',
              price: price || '',
              group: group || '',
              status: status || '',
              remark: remark || '',
            });
          }
        }

        const totalLibs = libs.length;
        const totalMatches = matches.length;
        if (!totalMatches) {
          const tip =
            kwList.length === 0
              ? '未在物料库中找到物料数据，请确认已在物料数据库里导入当前表。'
              : `在物料库中未找到匹配「${keywordsRaw}」的物料。`;
          setMessages((prev) => [
            ...prev,
            {
              id: uuidv4(),
              sender: 'ai',
              aiModel: 'babata',
              avatar: '🤖',
              name: '巴巴塔',
              content: tip,
              timestamp: new Date(),
              status: 'sent',
              isThinking: false,
            },
          ]);
          return;
        }

        const maxShow = 50;
        const lines: string[] = [];
        lines.push(
          `📦 物料库物料查询结果：共 **${totalMatches}** 条，来自 **${totalLibs}** 个物料库${
            keywordsRaw ? `（关键词：${keywordsRaw}）` : ''
          }。`
        );
        lines.push('');
        lines.push('只展示前 ' + maxShow + ' 条：');
        lines.push('');
        const header = '| 物料库 | 物料代码 | 描述 | pads库物料描述 | 单价 | 替代组 | 优选 | 备注 |';
        const sep = '| --- | --- | --- | --- | --- | --- | --- | --- |';
        lines.push(header);
        lines.push(sep);
        for (const m of matches.slice(0, maxShow)) {
          const esc = (s: string) =>
            (s || '').replace(/\|/g, '/').replace(/\r?\n/g, ' ').slice(0, 80);
          lines.push(
            `| ${esc(m.libName)} | ${esc(m.code)} | ${esc(m.desc)} | ${esc(
              m.pads
            )} | ${esc(m.price)} | ${esc(m.group)} | ${esc(m.status)} | ${esc(m.remark)} |`
          );
        }
        if (totalMatches > maxShow) {
          lines.push('');
          lines.push(`… 其余 ${totalMatches - maxShow} 条可在物料数据库页面中继续查看。`);
        }

        setMessages((prev) => [
          ...prev,
          {
            id: uuidv4(),
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: '巴巴塔',
            content: lines.join('\n'),
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
          },
        ]);
      } catch (e: any) {
        console.error('物料库物料查询失败', e);
        setMessages((prev) => [
          ...prev,
          {
            id: uuidv4(),
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: '巴巴塔',
            content: `物料库物料查询失败：${e?.message || String(e)}`,
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
          },
        ]);
      }
      })();
      return;
    }
    
    if (eventType === 'open_sidebar_compare') {
      setIsRightPanelCollapsed(false);
    } else if (eventType === 'open_sidebar_analyze') {
      setIsRightPanelCollapsed(false);
    } else if (eventType === 'open_sidebar_review') {
      setIsRightPanelCollapsed(false);
    } else if (eventType === 'open_sidebar_summary') {
      setIsRightPanelCollapsed(false);
    } else if (eventType === 'open_sidebar_checklist') {
      setIsRightPanelCollapsed(false);
    } else if (eventType === 'open_sidebar_tab' && result.tab) {
      setIsRightPanelCollapsed(false);
    } else if (eventType === 'open_game_tetris') {
      setShowTetrisGame(true);
    }
  }, [aiReviewEntries, panelResultId, panelResultType]);

  const canManageModels = canManageModelConfig(sessionUser);

  const runAggregateReview = useCallback(() => {
    const aiReviews = aiReviewEntries.map((e) => ({
      parsed: e.parsed,
      aiName: e.aiName,
      timestamp: e.timestamp,
      id: e.id,
    }));
    const parsedParts = aiReviews.map((e) => e.parsed).filter(Boolean);
    const mergedReview = parsedParts.length ? mergeSchematicReviewJson(parsedParts) : null;
    const netlistId = panelResultType === 'analysis' ? panelResultId : null;
    const applySummary = (netlistData: any) => {
      setAggregatedReviewSummary({
        netlist: netlistData,
        aiReviews,
        mergedReview,
        aggregatedAt: new Date().toISOString(),
      });
    };
    if (netlistId) {
      axios.get(apiUrl(`/api/netlist/result/${netlistId}`)).then((res) => {
        const netlistData =
          res.data.success && res.data.data?.type === 'analysis' ? res.data.data.result : null;
        applySummary(netlistData);
      }).catch(() => {
        applySummary(null);
      });
    } else {
      applySummary(null);
    }
  }, [aiReviewEntries, panelResultId, panelResultType]);

  useEffect(() => {
    if (!isSchematic || aiReviewEntries.length === 0) return;
    if (schematicContinuationLoopRef.current) return;
    runAggregateReview();
    if (schematicAiReviewPendingRef.current) {
      schematicAiReviewPendingRef.current = false;
      setAiReviewRunning(false);
    }
  }, [isSchematic, aiReviewEntries.length, runAggregateReview]);

  const loadAIs = useCallback(async () => {
    try {
      const response = await axios.get(apiUrl('/api/ais'), { withCredentials: true });
      let ais = response.data.ais.map((ai: any) => ({
        ...ai,
        enableReasoning:
          ai.id === 'deepseek'
            ? (ai.enableReasoning ?? false)
            : ai.baseAI?.startsWith('bailian-')
              ? (ai.enableReasoning ?? ai.supportsReasoning ?? false)
              : ai.enableReasoning,
      }));

      if (isSchematic) {
        let defaultId = schematicDefaultAiId;
        let defaultName = schematicDefaultAiName;
        try {
          const settingsRes = await axios.get(apiUrl('/api/settings/schematic-review-prompt'), {
            withCredentials: true,
          });
          if (settingsRes.data?.success) {
            if (settingsRes.data.prompt) setReviewPrompt(settingsRes.data.prompt);
            defaultId = settingsRes.data.default_ai_id || DEFAULT_SCHEMATIC_AI_ID;
            defaultName =
              settingsRes.data.default_ai_name ||
              ais.find((a: AIConfig) => a.id === defaultId)?.name ||
              defaultId;
            setSchematicDefaultAiId(defaultId);
            setSchematicDefaultAiName(defaultName);
          }
        } catch {
          setReviewPrompt(getSchematicReviewPrompt());
        }
        ais = ais.filter((ai: any) => ai.id !== 'babata');
        schematicCatalogAisRef.current = ais;
        setSelectedAIs((prev) =>
          applySchematicAiSelection(ais, defaultId, reviewExported, reviewExported ? prev : undefined)
        );
        return;
      }

      const hasOtherEnabledAI = ais.some((ai: any) => ai.id !== 'babata' && ai.enabled);
      const updatedAIs = ais.map((ai: any) => {
        if (ai.id === 'babata') {
          return { ...ai, enabled: !hasOtherEnabledAI };
        }
        return ai;
      });

      setSelectedAIs(updatedAIs);
    } catch (error) {
      console.error('加载AI列表失败:', error);
      if (isSchematic) {
        schematicCatalogAisRef.current = [
          {
            id: DEFAULT_SCHEMATIC_AI_ID,
            name: '百炼-deepseekV4',
            avatar: '🔮',
            enabled: true,
            description: '百炼 DeepSeek V4 Pro',
            baseAI: DEFAULT_SCHEMATIC_AI_ID,
            isCustom: false,
          },
        ];
        setSelectedAIs(
          applySchematicAiSelection(
            schematicCatalogAisRef.current,
            schematicDefaultAiId,
            reviewExported
          )
        );
      } else {
        setSelectedAIs([
          { id: 'babata', name: '巴巴塔', avatar: '🤖', enabled: true, description: '智能助手', baseAI: 'babata', isCustom: false },
          { id: 'deepseek', name: 'DeepSeek', avatar: '🧠', enabled: false, description: 'DeepSeek V3.2', baseAI: 'deepseek', isCustom: false },
        ]);
      }
    }
  }, [isSchematic, reviewExported, schematicDefaultAiId, schematicDefaultAiName]);

  useEffect(() => {
    if (!isSchematic || schematicCatalogAisRef.current.length === 0) return;
    setSelectedAIs((prev) =>
      applySchematicAiSelection(
        schematicCatalogAisRef.current,
        schematicDefaultAiId,
        reviewExported,
        reviewExported ? prev : undefined
      )
    );
  }, [isSchematic, reviewExported, schematicDefaultAiId]);

  useEffect(() => {
    loadAIs();
  }, [loadAIs]);

  const schematicAiSelectorLocked = isSchematic && !reviewExported;

  const applySchematicHistoryRecord = useCallback((record: SchematicReviewHistoryRecord) => {
    const payload = record.payload || {};
    setSchematicHistoryViewMode(true);
    setViewingHistoryTitle(record.title || '历史评审');
    setPanelResultId(record.netlist_result_id || null);
    setPanelResultType('analysis');
    setAggregatedReviewSummary(payload.aggregated_review_summary ?? null);
    setAiReviewEntries(parseHistoryAiReviewEntries(payload.ai_review_entries || []));
    setCleanedNetlistText(payload.cleaned_netlist_text || '');
    setCleanConfirmed(true);
    setReviewExported(true);
    setSchematicHistoryDispositions(payload.check_dispositions || {});
    setIsRightPanelCollapsed(false);
    if (payload.default_ai_name) {
      setSchematicDefaultAiName(payload.default_ai_name);
    }
  }, []);

  const handleStartNewSchematicReview = useCallback(() => {
    setSchematicHistoryViewMode(false);
    setViewingHistoryTitle(null);
    setSchematicHistoryDispositions({});
    setAggregatedReviewSummary(null);
    setAiReviewEntries([]);
    setReviewExported(false);
    setCleanConfirmed(false);
    setCleanedNetlistText('');
    setPanelResultId(null);
    setPanelResultType(null);
    setChatPanelExpanded(false);
  }, []);

  const registerAiReviewFromContent = useCallback(
    (content: string, messageId: string, aiModel: string) => {
      const parsed = parseSchematicReviewJson(content);
      if (!parsed) return false;
      const aiName =
        selectedAIs.find((a: AIConfig) => a.id === aiModel)?.name ?? aiModel ?? 'AI';
      setAiReviewEntries((prev) => {
        if (prev.some((e) => e.id === messageId)) return prev;
        return [
          ...prev,
          {
            id: messageId || `review-${Date.now()}`,
            content,
            parsed,
            timestamp: new Date(),
            aiName,
          },
        ];
      });
      setIsRightPanelCollapsed(false);
      return true;
    },
    [selectedAIs]
  );

  useEffect(() => {
    const wsUrl = import.meta.env.VITE_WS_URL || getWsUrl();
    if (!wsClient.isConnected()) {
      wsClient.connect(wsUrl);
    }

    // 定义事件处理函数
    const handleAIThinking = (data: any) => {
      setMessages(prev => {
        // 使用后端返回的message_id作为唯一标识
        const messageId = data.message_id || `${data.ai_model}-thinking-${Date.now()}`;
        const existing = prev.find(m => m.id === messageId);
        if (existing) return prev;
        
        const ai = selectedAIs.find(a => a.id === data.ai_model);
        if (!ai) return prev;

        return [...prev, {
          id: messageId,
          sender: 'ai',
          aiModel: data.ai_model,
          avatar: ai.avatar,
          name: ai.name,
          content: '正在思考...',
          timestamp: new Date(),
          status: 'sending',
          isThinking: true,
        }];
      });
    };

    const handleAIResponse = (data: any) => {
      if (flowStepResponseCallbackRef.current) {
        const cb = flowStepResponseCallbackRef.current;
        flowStepResponseCallbackRef.current = null;
        setTimeout(() => cb(data.content || ''), 0);
      }
      const content = data.content || '';
      if (content && data.message_id) {
        registerAiReviewFromContent(content, data.message_id, data.ai_model || '');
      }
      setMessages(prev => {
        // 使用后端返回的message_id来精确匹配消息
        const messageId = data.message_id;
        if (!messageId) {
          console.warn('收到AI回复但没有message_id:', data);
          return prev;
        }
        
        // 处理巴巴塔消息（原理图审核模式不展示）
        if (data.ai_model === 'babata') {
          if (isSchematic) {
            return prev;
          }
          // 获取管理员名称（默认巴巴塔）
          const adminName = '巴巴塔'; // 可以从配置中获取
          
          // 检查是否是网表对比/评审请求（触发侧边栏）
          if (data.content.includes('原理图对比') || data.content.includes('网表对比')) {
            setTimeout(() => {
              setNetlistSidebarMode('compare');
              setShowNetlistSidebar(true);
            }, 500);
          } else if (data.content.includes('原理图评审') || data.content.includes('网表评审')) {
            setTimeout(() => {
              setNetlistSidebarMode('analyze');
              setShowNetlistSidebar(true);
            }, 500);
          }
          
          // 检查消息中是否包含结果ID
          const resultIdMatch = data.content.match(/结果ID:\s*([a-f0-9-]+)/i);
          if (resultIdMatch) {
            const resultId = resultIdMatch[1];
            const isComparison = data.content.includes('对比');
            // 右侧栏已移除「对比结果」，仅自动打开解析类结果
            if (!isComparison) {
              setPanelResultId(resultId);
              setPanelResultType('analysis');
            }
          }
          
          return [...prev, {
            id: messageId,
            sender: 'ai',
            aiModel: 'babata',
            avatar: '🤖',
            name: adminName,
            content: data.content,
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
            mentionedRoles: data.mentioned_roles || [], // @的角色列表
            knowledgeMatches: data.knowledge_matches || null, // 知识库匹配项
            knowledgeImage: data.knowledge_image || undefined, // 知识库答案的图片
            eventTrigger: data.event_trigger || undefined, // 事件触发配置（单个）
            eventTriggers: data.event_triggers || undefined, // 事件触发配置（多个）
          }];
        }
        
        // 查找对应的消息并更新
        const messageIndex = prev.findIndex(msg => msg.id === messageId);
        if (messageIndex === -1) {
          // 如果找不到thinking消息，可能是新消息，直接添加
          const ai = selectedAIs.find(a => a.id === data.ai_model);
          if (ai) {
          return [...prev, {
            id: messageId,
            sender: 'ai',
            aiModel: data.ai_model,
            avatar: ai.avatar,
            name: ai.name,
            content: data.content,
            timestamp: new Date(),
            status: 'sent',
            isThinking: false,
            cacheInfo: data.cache_info ? {
              hitTokens: data.cache_info.hit_tokens,
              missTokens: data.cache_info.miss_tokens,
              hitRate: data.cache_info.hit_rate,
            } : undefined,
            canSaveToKnowledge: data.can_save_to_knowledge || false,
            originalQuestion: data.original_question || undefined,
          }];
          }
          return prev;
        }
        
        // 更新找到的消息
        const updated = [...prev];
        updated[messageIndex] = {
          ...updated[messageIndex],
          content: data.content,
          status: 'sent',
          isThinking: false,
          cacheInfo: data.cache_info ? {
            hitTokens: data.cache_info.hit_tokens,
            missTokens: data.cache_info.miss_tokens,
            hitRate: data.cache_info.hit_rate,
          } : undefined,
          canSaveToKnowledge: data.can_save_to_knowledge || false,
          originalQuestion: data.original_question || undefined,
          eventTrigger: data.event_trigger || undefined,
          eventTriggers: data.event_triggers || undefined,
        };
        if (data.finish_reason && data.message_id) {
          schematicFinishReasonsRef.current[data.message_id] = data.finish_reason;
        }
        
        return updated;
      });
    };

    const handleAIStream = (data: any) => {
      const messageId = data.message_id;
      if (!messageId) {
        console.warn('收到AI流式片段但没有message_id:', data);
        return;
      }
      setMessages(prev => {
        const idx = prev.findIndex(m => m.id === messageId);
        if (idx === -1) {
          return prev;
        }
        const updated = [...prev];
        const cur = updated[idx];
        const newContent = data.content || cur.content;
        // 有内容时 isThinking=false，显示流式输出；无内容时保持思考状态
        updated[idx] = {
          ...cur,
          content: newContent,
          status: 'sending',
          isThinking: !newContent || !newContent.trim(),
        };
        return updated;
      });
    };

    const handleAIError = (data: any) => {
      setMessages(prev => {
        // 使用后端返回的message_id来精确匹配消息
        const messageId = data.message_id;
        if (!messageId) {
          console.warn('收到AI错误但没有message_id:', data);
          return prev;
        }
        
        const messageIndex = prev.findIndex(msg => msg.id === messageId);
        if (messageIndex === -1) {
          return prev;
        }
        
        const updated = [...prev];
        updated[messageIndex] = {
          ...updated[messageIndex],
          content: `请求失败: ${data.error}`,
          status: 'error',
          isThinking: false,
        };
        return updated;
      });
    };

    // 注册事件监听
    wsClient.on('ai_thinking', handleAIThinking);
    wsClient.on('ai_response', handleAIResponse);
    wsClient.on('ai_error', handleAIError);
    wsClient.on('ai_stream', handleAIStream);

    // 清理函数
    return () => {
      wsClient.off('ai_thinking', handleAIThinking);
      wsClient.off('ai_response', handleAIResponse);
      wsClient.off('ai_error', handleAIError);
      wsClient.off('ai_stream', handleAIStream);
    };
    }, [selectedAIs, isSchematic, registerAiReviewFromContent]);

  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    const onComplete = () => {
      if (schematicContinuationLoopRef.current) return;
      if (schematicAiReviewPendingRef.current) {
        schematicAiReviewPendingRef.current = false;
        setAiReviewRunning(false);
      }
      if (isSchematic) {
        window.setTimeout(() => {
          const recent = [...messagesRef.current].reverse().slice(0, 8);
          for (const msg of recent) {
            if (msg.sender === 'ai' && msg.aiModel !== 'babata' && msg.content?.trim()) {
              registerAiReviewFromContent(msg.content, msg.id, msg.aiModel || '');
            }
          }
        }, 50);
      }
    };
    wsClient.on('group_message_complete', onComplete);
    return () => wsClient.off('group_message_complete', onComplete);
  }, [isSchematic, registerAiReviewFromContent]);

  useEffect(() => {
    const tokens = messages.reduce((sum, msg) => {
      return sum + calculateTokens(msg.content);
    }, 0);
    setTotalTokens(tokens);
  }, [messages]);

  useEffect(() => {
    // 自动滚动到底部
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 解析@提及的AI
  const parseMentionedAIs = (text: string): string[] => {
    const mentionedAIs: string[] = [];
    // 匹配所有@AI名称的模式
    const mentionRegex = /@(\S+)/g;
    let match;
    while ((match = mentionRegex.exec(text)) !== null) {
      const mentionedName = match[1].trim();
      // 查找匹配的AI（支持部分匹配）
      const matchedAI = selectedAIs.find(ai => 
        ai.name.toLowerCase() === mentionedName.toLowerCase() ||
        ai.name.toLowerCase().startsWith(mentionedName.toLowerCase())
      );
      if (matchedAI) {
        mentionedAIs.push(matchedAI.id);
      }
    }
    return mentionedAIs;
  };

  const handleSendMessage = async (
    customText?: string,
    options?: {
      skipEventTriggers?: boolean;
      targetAIIds?: string[];
      maxTokens?: number;
      schematicReview?: boolean;
      schematicPhase?: 'pre_export' | 'post_export';
    }
  ) => {
    const messageText = customText ?? inputText;
    const filesToAttach = customText !== undefined ? [] : [...pendingChatFiles];
    if (!messageText.trim() && filesToAttach.length === 0) return;

    let outgoingContent = messageText;
    let attachmentNames: string[] | undefined;

    if (filesToAttach.length > 0) {
      setIsAttachmentSubmitting(true);
      try {
        attachmentNames = filesToAttach.map((f) => f.name);
        const parsed = await Promise.all(filesToAttach.map((f) => parseChatFile(f)));
        const digest = buildAttachmentDigest(parsed);
        outgoingContent = buildMessageWithAttachments(messageText, digest);
        setPendingChatFiles([]);
      } finally {
        setIsAttachmentSubmitting(false);
      }
    }

    const userMsg: Message = {
      id: uuidv4(),
      sender: 'user',
      avatar: '👤',
      name: '我',
      content: outgoingContent,
      timestamp: new Date(),
      status: 'sent',
      ...(attachmentNames?.length ? { attachmentFileNames: attachmentNames } : {}),
    };

    setMessages(prev => [...prev, userMsg]);

    // 获取引用的消息ID列表
    const quotedMessageIds = Array.from(selectedQuotedMessages);
    
    // 发送消息后清空引用选择
    setSelectedQuotedMessages(new Set());

    // 检查是否有@提及（仅以用户输入框文字为准，不含附件解析块）
    const mentionedAIIds = parseMentionedAIs(messageText);
    
    // 确定要发送的AI列表
    let targetAIs: AIConfig[];
    if (options?.targetAIIds && options.targetAIIds.length > 0) {
      // 事件触发指定了默认回复角色：只发给这些角色
      targetAIs = selectedAIs.filter(ai => options.targetAIIds!.includes(ai.id));
      if (targetAIs.length === 0) {
        targetAIs = selectedAIs.filter(ai => ai.enabled);
      }
    } else if (mentionedAIIds.length > 0) {
      // 如果有@提及，只发送给被@的AI
      targetAIs = selectedAIs.filter(ai => mentionedAIIds.includes(ai.id));
      if (targetAIs.length === 0) {
        alert(`未找到被@的AI，消息将发送给所有选中的AI`);
        targetAIs = selectedAIs.filter(ai => ai.enabled);
      }
    } else {
      // 如果没有@提及，发送给所有选中的AI
      targetAIs = selectedAIs.filter(ai => ai.enabled);
    }

    if (isSchematic && !reviewExported) {
      const locked = selectedAIs.filter((ai) => ai.id === schematicDefaultAiId);
      targetAIs = locked.length > 0 ? locked : targetAIs.slice(0, 1);
    }
    
    // 检查WebSocket连接状态
    if (!wsClient.isConnected()) {
      console.warn('WebSocket未连接，尝试重新连接...');
      const wsUrl = import.meta.env.VITE_WS_URL || getWsUrl();
      wsClient.connect(wsUrl);
      // 等待连接建立（最多等待2秒）
      let retries = 0;
      while (!wsClient.isConnected() && retries < 20) {
        await new Promise(resolve => setTimeout(resolve, 100));
        retries++;
      }
      if (!wsClient.isConnected()) {
        alert('WebSocket连接失败，请刷新页面重试');
        return;
      }
    }
    
    // 从消息内容中移除@提及标记（可选，或者保留让AI知道是@它的）
    // 这里我们保留@标记，让AI知道是被@的
    
    wsClient.send('group_message', {
      conversation_id: conversationId,
      message: outgoingContent,
      selected_ais: targetAIs.map(ai => ({
        id: ai.id,
        name: ai.name,
        enabled: ai.enabled,
        rolePrompt: ai.rolePrompt,
        enableReasoning: ai.enableReasoning || false,
      })),
      quoted_message_ids: quotedMessageIds.length > 0 ? quotedMessageIds : undefined,
      skip_event_triggers: options?.skipEventTriggers === true,
      event_max_tokens: options?.maxTokens,
      skip_babata: isSchematic,
      context_mode: isSchematic ? 'schematic' : undefined,
      schematic_phase:
        options?.schematicPhase ??
        (isSchematic && !reviewExported ? 'pre_export' : undefined),
      review_context:
        isSchematic && reviewExported && aggregatedReviewSummary
          ? {
              cleanedNetlist: cleanedNetlistText,
              reportSummary: buildReportSummaryText(aggregatedReviewSummary),
            }
          : undefined,
    });

    // 只有在没有使用自定义文本时才清空输入框
    if (!customText) {
      setInputText('');
    }
  };

  const waitForGroupMessageComplete = useCallback(
    () =>
      new Promise<void>((resolve) => {
        const handler = () => {
          wsClient.off('group_message_complete', handler);
          resolve();
        };
        wsClient.on('group_message_complete', handler);
      }),
    []
  );

  const runSchematicAiReview = useCallback(
    async (payload: { prompt: string; netlist: string }) => {
      setChatPanelExpanded(true);
      setAiReviewRunning(true);
      schematicContinuationLoopRef.current = true;
      const priorParsed: any[] = [];
      const sessionEntries: Array<{
        id: string;
        content: string;
        parsed: any;
        timestamp: Date;
        aiName: string;
      }> = [];
      let message = `${payload.prompt.trim()}\n\n${payload.netlist.trim()}`;

      try {
        for (let round = 1; round <= SCHEMATIC_REVIEW_MAX_ROUNDS; round++) {
          setAiReviewRound(round);
          schematicAiReviewPendingRef.current = true;

          await handleSendMessage(message, {
            skipEventTriggers: true,
            schematicReview: true,
            schematicPhase: 'pre_export',
            maxTokens: SCHEMATIC_MAX_OUTPUT_TOKENS,
          });

          await waitForGroupMessageComplete();
          schematicAiReviewPendingRef.current = false;

          await new Promise((r) => window.setTimeout(r, 80));

          const recent = [...messagesRef.current].reverse();
          const aiMsg = recent.find(
            (m) => m.sender === 'ai' && m.aiModel !== 'babata' && m.content?.trim()
          );
          if (!aiMsg?.content) break;

          const parsed = parseSchematicReviewJson(aiMsg.content);
          const finishReason = schematicFinishReasonsRef.current[aiMsg.id];

          if (parsed) {
            priorParsed.push(parsed);
            const aiName =
              selectedAIs.find((a) => a.id === aiMsg.aiModel)?.name ?? aiMsg.aiModel ?? 'AI';
            const entry = {
              id: aiMsg.id,
              content: aiMsg.content,
              parsed,
              timestamp: new Date(),
              aiName,
            };
            sessionEntries.push(entry);
            setAiReviewEntries((prev) => {
              if (prev.some((e) => e.id === aiMsg.id)) return prev;
              return [...prev, entry];
            });
          }

          const complete =
            parsed &&
            isSchematicReviewComplete(parsed) &&
            finishReason !== 'length';

          if (complete) break;
          if (round >= SCHEMATIC_REVIEW_MAX_ROUNDS) break;

          message = buildSchematicContinuationPrompt(priorParsed, round + 1);
        }

        if (priorParsed.length > 0) {
          const mergedReview = mergeSchematicReviewJson(priorParsed);
          const aiReviews = sessionEntries.map((e) => ({
            parsed: e.parsed,
            aiName: e.aiName,
            timestamp: e.timestamp,
            id: e.id,
          }));
          const netlistId = panelResultType === 'analysis' ? panelResultId : null;
          const applySummary = (netlistData: any) => {
            setAggregatedReviewSummary({
              netlist: netlistData,
              aiReviews,
              mergedReview,
              aggregatedAt: new Date().toISOString(),
            });
            setIsRightPanelCollapsed(false);
          };
          if (netlistId) {
            try {
              const res = await axios.get(apiUrl(`/api/netlist/result/${netlistId}`));
              const netlistData =
                res.data.success && res.data.data?.type === 'analysis' ? res.data.data.result : null;
              applySummary(netlistData);
            } catch {
              applySummary(null);
            }
          } else {
            applySummary(null);
          }
        }
      } finally {
        schematicContinuationLoopRef.current = false;
        setAiReviewRunning(false);
        setAiReviewRound(0);
      }
    },
    [
      handleSendMessage,
      waitForGroupMessageComplete,
      selectedAIs,
      panelResultId,
      panelResultType,
    ]
  );

  const handleReaction = (messageId: string, emoji: string) => {
    setMessages(prev => prev.map(msg => {
      if (msg.id === messageId) {
        const reactions = msg.reactions || [];
        const existingReaction = reactions.find(r => r.emoji === emoji);
        
        if (existingReaction) {
          return {
            ...msg,
            reactions: reactions.map(r =>
              r.emoji === emoji
                ? { ...r, count: r.count + 1 }
                : r
            ),
          };
        } else {
          return {
            ...msg,
            reactions: [...reactions, { emoji, users: [], count: 1 }],
          };
        }
      }
      return msg;
    }));
  };

  const handleReply = (message: Message) => {
    setInputText(`@${message.name} ${message.content}\n`);
  };

  const handleCopy = (content: string) => {
    navigator.clipboard.writeText(content);
  };

  const handleSaveToKnowledge = async (question: string, answer: string, messageId: string) => {
    try {
      const response = await fetch(apiUrl('/api/custom-ai/babata/knowledge'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          text: `${question}|${answer}`,  // 格式：问题|答案
          metadata: {
            source: 'ai_learning',
            message_id: messageId,
          }
        }),
      });

      if (response.status === 401) {
        const here = window.location.pathname + window.location.search
        window.location.href = '/login?redirect=' + encodeURIComponent(here)
        return
      }

      const data = await response.json();
      if (data.success) {
        alert('已保存到知识库！');
        // 可选：更新消息状态，隐藏保存按钮
        setMessages(prev => prev.map(msg => 
          msg.id === messageId 
            ? { ...msg, canSaveToKnowledge: false } 
            : msg
        ));
      } else {
        alert(`保存失败：${data.error || '未知错误'}`);
      }
    } catch (error) {
      console.error('保存到知识库失败:', error);
      alert('保存到知识库失败，请重试');
    }
  };

  const handleMention = (aiName: string) => {
    // 可以在这里处理提及逻辑
    console.log('提及:', aiName);
  };

  const handleCreateCustomAI = async (config: {
    name: string;
    avatar: string;
    baseAI: string;
    rolePrompt: string;
    description: string;
  }) => {
    try {
      console.log('创建自定义AI，发送数据:', config);
      
      const response = await axios.post(apiUrl('/api/custom-ai'), config, {
        headers: {
          'Content-Type': 'application/json',
        },
        timeout: 10000, // 10秒超时
      });
      
      console.log('创建响应:', response.data);
      
      if (response.data.success) {
        // 重新加载AI列表
        const aiResponse = await axios.get(apiUrl('/api/ais'));
        const ais = aiResponse.data.ais.map((ai: any) => ({
          ...ai,
          enabled: selectedAIs.find(a => a.id === ai.id)?.enabled || false,
        }));
        setSelectedAIs(ais);
        alert('创建成功！');
      } else {
        alert(`创建失败: ${response.data.error || '未知错误'}`);
      }
    } catch (error: any) {
      console.error('创建自定义AI失败:', error);
      console.error('错误详情:', error.response?.data);
      const errorMessage = error.response?.data?.error || error.message || '创建失败，请检查后端服务';
      alert(`创建失败: ${errorMessage}`);
    }
  };

  const handleDeleteCustomAI = async (aiId: string) => {
    try {
      console.log('删除自定义AI，完整ID:', aiId);
      
      // 从AI ID中提取角色ID（格式：custom-{base_ai}-{role_id}）
      // 例如：custom-deepseek-d0bbab7a-7efe-4d43-8d1e-49581264d6ff
      // 需要提取：d0bbab7a-7efe-4d43-8d1e-49581264d6ff
      
      if (!aiId.startsWith('custom-')) {
        alert('无效的角色ID格式');
        return;
      }
      
      // 移除 "custom-" 前缀
      const withoutPrefix = aiId.substring(7); // "custom-".length = 7
      
      // 找到第一个 "-" 后的部分（base_ai后面的部分）
      const firstDashIndex = withoutPrefix.indexOf('-');
      if (firstDashIndex === -1) {
        alert('无效的角色ID格式');
        return;
      }
      
      // 提取角色ID（base_ai后面的所有部分）
      const roleId = withoutPrefix.substring(firstDashIndex + 1);
      console.log('提取的角色ID:', roleId);
      
      if (!roleId) {
        alert('无法提取角色ID');
        return;
      }
      
      const response = await axios.delete(apiUrl(`/api/custom-ai/${roleId}`), {
        timeout: 10000,
      });
      
      console.log('删除响应:', response.data);
      
      if (response.data.success) {
        // 重新加载AI列表
        const aiResponse = await axios.get(apiUrl('/api/ais'));
        const ais = aiResponse.data.ais.map((ai: any) => ({
          ...ai,
          enabled: selectedAIs.find(a => a.id === ai.id)?.enabled || false,
        }));
        setSelectedAIs(ais);
        alert('删除成功！');
      } else {
        alert(`删除失败: ${response.data.error || '未知错误'}`);
      }
    } catch (error: any) {
      console.error('删除自定义AI失败:', error);
      console.error('错误详情:', error.response?.data);
      const errorMessage = error.response?.data?.error || error.message || '删除失败，请检查后端服务';
      alert(`删除失败: ${errorMessage}`);
    }
  };

  const handleLoadConversation = async (convId: string) => {
    try {
      const response = await axios.get(apiUrl(`/api/conversations/${convId}/messages`));
      if (response.data.success) {
        const loadedMessages = response.data.messages.map((msg: any) => ({
          id: msg.id,
          sender: msg.role === 'user' ? 'user' : 'ai',
          aiModel: msg.ai_model || 'unknown',
          avatar: msg.role === 'user' ? '👤' : '🤖',
          name: msg.role === 'user' ? '用户' : (msg.ai_model || 'AI'),
          content: msg.content,
          timestamp: new Date(msg.created_at),
          status: msg.status || 'sent',
          isThinking: false,
        }));
        setMessages(loadedMessages);
        setCurrentConversationId(convId);
      }
    } catch (error) {
      console.error('加载对话失败:', error);
      alert('加载对话失败');
    }
  };

  return (
    <div className="flex h-screen bg-gray-50 flex-col">
      {isSchematic && !chatPanelExpanded && (
        <div className="flex items-center justify-between p-4 border-b bg-white shadow-sm flex-shrink-0">
          <div className="flex items-center gap-3">
            <Link
              to="/"
              className="p-2 hover:bg-gray-100 rounded-lg transition text-gray-600 hover:text-gray-800"
              title="返回主页"
            >
              <Home size={20} />
            </Link>
            <h1 className="text-xl font-bold text-gray-800 truncate">{title}</h1>
          </div>
          <div className="flex items-center space-x-4 shrink-0">
            <AISelector
              ais={selectedAIs}
              onChange={setSelectedAIs}
              locked={schematicAiSelectorLocked}
              lockedLabel={schematicDefaultAiName}
              lockedHint="Step 1–4 使用系统默认模型；导出报告后可自由选择"
            />
            {canManageModels && (
              <>
                <button
                  onClick={() => setShowSchematicPromptModal(true)}
                  className="flex items-center space-x-1 px-3 py-2 bg-sky-600 text-white rounded-lg hover:bg-sky-700 transition"
                  title="配置默认 AI 模型、评审提示词与历史版本"
                >
                  <FileText size={16} />
                  <span>审核配置</span>
                </button>
                <button
                  onClick={() => setShowAIKeysModal(true)}
                  className="flex items-center space-x-1 px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition"
                  title="配置各 AI 的 API 密钥"
                >
                  <KeyRound size={16} />
                  <span>API 密钥</span>
                </button>
              </>
            )}
          </div>
        </div>
      )}
    <div className="flex flex-1 min-h-0">
      {mode !== 'bom' && !isSopMode && !isSchematic && (
        <>
          {/* 左侧：事件流（SOP 执行页不显示左侧栏） */}
          <div className={`bg-white flex flex-col relative transition-all duration-300 border-r ${isLeftPanelCollapsed ? 'w-0 overflow-hidden' : 'w-80 min-w-0'}`}>
            {!isLeftPanelCollapsed && (
              <>
                <button
                  onClick={() => setIsLeftPanelCollapsed(true)}
                  className="absolute right-0 top-1/2 translate-x-full -translate-y-1/2 z-10 bg-gray-200 hover:bg-gray-300 text-gray-700 px-2 py-3 rounded-r-lg transition-colors shadow-md text-sm font-medium"
                  title="收起事件流"
                >
                  <ChevronRight size={16} />
                </button>
                <div className="flex-shrink-0 p-3 border-b bg-gray-50">
                  <button
                    onClick={() => setShowBuildSOPModal(true)}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition text-sm font-medium"
                    title="选择事件流构建为 SOP，并添加到主页"
                  >
                    <ListOrdered size={16} />
                    构建 SOP
                  </button>
                </div>
                <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
                    <EventFlowPanel
                      initialEventFlowId={sopFromUrl?.eventFlowId ?? null}
                      onSendFlowStep={(content, options) => handleSendMessage(content, { skipEventTriggers: true, targetAIIds: options?.targetAIIds, maxTokens: options?.maxTokens })}
                      onTriggerNonChatEvent={(eventType, params) => {
                        handleEventTrigger({ success: true, event_type: eventType, result: params });
                      }}
                      registerStepResponseCallback={(cb) => {
                        flowStepResponseCallbackRef.current = cb;
                      }}
                      onShowResultInChat={(content, resultId, resultType) => {
                        const msg: Message = {
                          id: uuidv4(),
                          sender: 'ai',
                          aiModel: 'babata',
                          avatar: '🤖',
                          name: '巴巴塔',
                          content,
                          timestamp: new Date(),
                          status: 'sent',
                          isThinking: false,
                        };
                        setMessages((prev) => [...prev, msg]);
                        setPanelResultId(resultId);
                        setPanelResultType(resultType);
                        setIsRightPanelCollapsed(false);
                      }}
                    />
                </div>
              </>
            )}
          </div>
          {isLeftPanelCollapsed && (
            <button
              onClick={() => setIsLeftPanelCollapsed(false)}
              className="flex-shrink-0 self-center bg-gray-200 hover:bg-gray-300 text-gray-700 px-2 py-3 rounded-r-lg transition-colors shadow-md text-sm font-medium flex items-center gap-1"
              title="展开事件流"
            >
              <ChevronLeft size={16} />
              <span className="whitespace-nowrap">事件流</span>
            </button>
          )}
        </>
      )}

      {/* 中间：聊天区域（BOM 隐藏；原理图默认折叠，AI 评审后展开） */}
      {mode !== 'bom' && (!isSchematic || chatPanelExpanded) && (
      <div
        ref={chatSectionRef}
        className={`flex flex-col min-w-0 border-r transition-all duration-300 ${
          isSopMode ? 'w-1/3 flex-shrink-0' : 'flex-1'
        }`}
      >
        {/* 顶部工具栏 */}
        <div className="flex items-center justify-between p-4 border-b bg-white shadow-sm">
          <div className="flex items-center gap-3">
            {!isSopMode && (
              <Link
                to="/"
                className="p-2 hover:bg-gray-100 rounded-lg transition text-gray-600 hover:text-gray-800"
                title="返回主页"
              >
                <Home size={20} />
              </Link>
            )}
            <h1 className="text-xl font-bold text-gray-800 truncate">
              {isSopMode && sopFromUrl ? sopFromUrl.name : title}
            </h1>
            {isSopMode && (
              <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium whitespace-nowrap shrink-0">
                SOP · 聊天与历史
              </span>
            )}
            {isSchematic && (
              <span
                className={`px-2 py-1 rounded-full text-xs font-medium whitespace-nowrap shrink-0 ${
                  reviewExported
                    ? 'bg-emerald-100 text-emerald-800'
                    : 'bg-amber-100 text-amber-800'
                }`}
              >
                {reviewExported ? '已解锁对话' : '只读 · 导出报告后可输入'}
              </span>
            )}
          </div>
          <div className="flex items-center space-x-4 shrink-0">
            {isSopMode ? (
              <>
                <HistoryDropdown onLoadConversation={handleLoadConversation} />
                <Link
                  to="/"
                  className="px-3 py-2 border border-blue-400 text-blue-700 rounded-lg hover:bg-blue-50 transition text-sm font-medium"
                >
                  返回主页
                </Link>
              </>
            ) : isSchematic ? (
              <>
                <AISelector
                  ais={selectedAIs}
                  onChange={setSelectedAIs}
                  onDelete={canManageModels ? handleDeleteCustomAI : undefined}
                  locked={schematicAiSelectorLocked}
                  lockedLabel={schematicDefaultAiName}
                  lockedHint="Step 1–4 使用系统默认模型；导出报告后可自由选择"
                />
                {canManageModels && (
                  <>
                    <button
                      onClick={() => setShowSchematicPromptModal(true)}
                      className="flex items-center space-x-1 px-3 py-2 bg-sky-600 text-white rounded-lg hover:bg-sky-700 transition"
                      title="配置默认 AI 模型、评审提示词与历史版本"
                    >
                      <FileText size={16} />
                      <span>审核配置</span>
                    </button>
                    <button
                      onClick={() => setShowAIKeysModal(true)}
                      className="flex items-center space-x-1 px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition"
                      title="配置各 AI 的 API 密钥（加密存储）"
                    >
                      <KeyRound size={16} />
                      <span>API 密钥</span>
                    </button>
                  </>
                )}
              </>
            ) : (
              <>
            <AISelector 
              ais={selectedAIs} 
              onChange={setSelectedAIs}
              onDelete={handleDeleteCustomAI}
              onManageKnowledge={(aiId, aiName) => {
                // 支持巴巴塔和自定义角色的知识库管理
                setSelectedRoleForKnowledge({ id: aiId, name: aiName });
                setShowKnowledgeModal(true);
              }}
              onManageEventTrigger={(aiId, aiName) => {
                // 支持巴巴塔和自定义角色的事件触发管理
                setSelectedRoleForEventTrigger({ id: aiId, name: aiName });
                setShowEventTriggerModal(true);
              }}
            />
            <button
              onClick={() => setShowAIKeysModal(true)}
              className="flex items-center space-x-1 px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition"
              title="配置各 AI 的 API 密钥（加密存储）"
            >
              <KeyRound size={16} />
              <span>API 密钥</span>
            </button>
            <button
              onClick={() => setShowCustomModal(true)}
              className="flex items-center space-x-1 px-3 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition"
              title="创建自定义AI角色"
            >
              <Plus size={16} />
              <span>创建角色</span>
            </button>
            <button
              onClick={() => setShowRecycleBin(true)}
              className="flex items-center space-x-1 px-3 py-2 bg-gray-500 text-white rounded-lg hover:bg-gray-600 transition"
              title="知识回收站"
            >
              <Trash2 size={16} />
              <span>回收站</span>
            </button>
            <a
              href={`${import.meta.env.BASE_URL}systm_tool/物料数据库.html`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center space-x-1 px-3 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition"
              title="在新页面打开 BOM 物料库管理工具"
            >
              <Database size={16} />
              <span>物料库管理</span>
            </a>
            <HistoryDropdown onLoadConversation={handleLoadConversation} />
            <Link
              to="/dashboard"
              className="flex items-center space-x-1 px-3 py-2 bg-slate-600 text-white rounded-lg hover:bg-slate-700 transition"
              title="评审效能看板"
            >
              <BarChart3 size={16} />
              <span>评审看板</span>
            </Link>
              </>
            )}
          </div>
        </div>

        {/* 消息列表 */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-gray-400">
              <div className="text-center">
                <div className="text-4xl mb-4">💬</div>
                {isSchematic ? (
                  <>
                    <div>报告已导出，可与 AI 继续讨论原理图问题（可选）</div>
                    <div className="text-sm mt-2">支持上传 txt、pdf、docx 等文件作为附件</div>
                  </>
                ) : (
                  <>
                    <div>开始你的AI群聊之旅吧！</div>
                    <div className="text-sm mt-2">选择AI助手，输入消息，开始对话</div>
                  </>
                )}
              </div>
            </div>
          )}
          {messages.map((msg, index) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              isFirstMessage={index === 0}
              isSelectedForQuote={isSopMode ? false : selectedQuotedMessages.has(msg.id)}
              onReact={isSopMode ? undefined : handleReaction}
              onReply={isSopMode ? undefined : handleReply}
              onCopy={handleCopy}
              onSaveToKnowledge={isSopMode ? undefined : handleSaveToKnowledge}
              onSelectForQuote={
                isSopMode
                  ? undefined
                  : (messageId, selected) => {
                      setSelectedQuotedMessages((prev) => {
                        const newSet = new Set(prev);
                        if (selected) newSet.add(messageId);
                        else newSet.delete(messageId);
                        return newSet;
                      });
                    }
              }
              onSelectKnowledge={
                isSopMode
                  ? undefined
                  : (answer, messageId) => {
                      const babataReply: Message = {
                        id: uuidv4(),
                        sender: 'ai',
                        aiModel: 'babata',
                        avatar: '🤖',
                        name: '巴巴塔',
                        content: answer,
                        timestamp: new Date(),
                        status: 'sent',
                        isThinking: false,
                      };
                      setMessages((prev) => {
                        const updated = prev.map((m) =>
                          m.id === messageId ? { ...m, knowledgeMatches: undefined } : m
                        );
                        return [...updated, babataReply];
                      });
                    }
              }
              onTriggerEvent={
                isSopMode
                  ? undefined
                  : (eventConfig, messageId) => {
                      const eventType = eventConfig.type || eventConfig.event_type;
                      if (eventType === 'prompt_review_chat') {
                        const prompt = (eventConfig.params?.prompt ?? '').trim();
                        const defaultAi = eventConfig.params?.default_response_ai;
                        const maxTokens = eventConfig.params?.max_tokens;
                        setPromptReviewPrompt(prompt);
                        setPromptReviewMessageId(messageId);
                        setPromptReviewDefaultAIIds(
                          Array.isArray(defaultAi) && defaultAi.length > 0 ? defaultAi : undefined
                        );
                        setPromptReviewMaxTokens(typeof maxTokens === 'number' ? maxTokens : undefined);
                        setShowPromptReviewModal(true);
                        return;
                      }
                      if (eventType === 'material_db_search') {
                        const defaultKw =
                          (eventConfig.params?.keywords &&
                            (Array.isArray(eventConfig.params.keywords)
                              ? eventConfig.params.keywords.join(' ')
                              : String(eventConfig.params.keywords))) ||
                          '';
                        setMaterialSearchQuery(defaultKw);
                        setMaterialSearchMessageId(messageId);
                        setShowMaterialSearchModal(true);
                        return;
                      }
                      console.log('[前端事件触发]', eventConfig);
                      handleEventTrigger({
                        success: true,
                        event_type: eventType,
                        result: eventConfig.params || eventConfig.result || {},
                      });
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === messageId ? { ...m, eventTrigger: undefined, eventTriggers: undefined } : m
                        )
                      );
                    }
              }
            />
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入区域（SOP 模式下可直接在聊天栏输入） */}
        <div className="border-t bg-white p-4">
          {attachmentPickNotice && (
            <div className="mb-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-900">
              {attachmentPickNotice}
            </div>
          )}
          <ChatInput
            value={inputText}
            onChange={setInputText}
            onSubmit={() => handleSendMessage()}
            selectedAIs={selectedAIs}
            pendingAttachments={pendingChatFiles.map((f) => ({ name: f.name, size: f.size }))}
            onRemoveAttachment={(index) =>
              setPendingChatFiles((prev) => prev.filter((_, i) => i !== index))
            }
            onFilesSelected={
              isSopMode || (isSchematic && !reviewExported)
                ? undefined
                : (files) => {
                    if (!files.length) return;
                    const pickedNames = files.map((f) => f.name).join('、');
                    setPendingChatFiles((prev) => [...prev, ...files].slice(0, 12));
                    setAttachmentPickNotice(
                      `已选择 ${files.length} 个文件：${pickedNames}（见下方「附件预览」，点击发送后解析并提交给 AI）`
                    );
                    window.setTimeout(() => setAttachmentPickNotice(null), 8000);
                  }
            }
            isSubmitting={isAttachmentSubmitting}
            inputLocked={isSchematic && !reviewExported}
            inputLockedHint="请先完成 Step 4 导出报告后再输入消息或上传附件。"
            quotedMessages={
              isSopMode ? [] : messages.filter((msg) => selectedQuotedMessages.has(msg.id))
            }
            onRemoveQuote={
              isSopMode
                ? undefined
                : (messageId) => {
                    setSelectedQuotedMessages((prev) => {
                      const newSet = new Set(prev);
                      newSet.delete(messageId);
                      return newSet;
                    });
                  }
            }
            allMessages={isSopMode ? [] : messages}
            onSelectAll={
              isSopMode
                ? undefined
                : (selected) => {
                    if (selected) {
                      const allIds = new Set(messages.slice(1).map((msg) => msg.id));
                      setSelectedQuotedMessages(allIds);
                    } else {
                      setSelectedQuotedMessages(new Set());
                    }
                  }
            }
            isAllSelected={
              !isSopMode &&
              messages.length > 1 &&
              messages.slice(1).every((msg) => selectedQuotedMessages.has(msg.id))
            }
          />

          {/* 底部状态栏 */}
          <div className="flex justify-between items-center mt-2 text-sm text-gray-500">
            <div className="flex items-center space-x-2">
              <span>当前在线AI:</span>
              {selectedAIs
                .filter(ai => ai.enabled)
                .map(ai => (
                  <span key={ai.id} className="flex items-center">
                    <span className="mr-1">{ai.avatar}</span>
                    {ai.name}
                  </span>
                ))}
            </div>
            <span>总计Token: {totalTokens.toLocaleString()}</span>
          </div>
        </div>
      </div>
      )}

      {/* 右侧：结果记录 / BOM 面板 */}
      {mode === 'bom' ? (
        <BOMPanel
          collapsed={isRightPanelCollapsed}
          onCollapseToggle={() => setIsRightPanelCollapsed(!isRightPanelCollapsed)}
          matchGroups={bomMatchGroups}
          matchDesignatorIssues={bomMatchDesignatorIssues}
          onRunMatch={runBomMaterialMatch}
          onAutoMatch={runBomMaterialMatch}
          groupValidateGroups={bomGroupValidateResult}
          onRunGroupValidate={runBomGroupValidate}
          replacementCheckGroups={bomReplacementCheckResult}
          onRunReplacementCheck={runBomReplacementCheck}
          fullWidth={mode === 'bom'}
        />
      ) : (
        <>
          <div
            className={`bg-white flex flex-col relative transition-all duration-300 min-w-0 ${
              isSchematic
                ? chatPanelExpanded
                  ? isRightPanelCollapsed
                    ? 'w-0 overflow-hidden'
                    : 'w-1/2'
                  : 'w-full flex-1'
                : isSopMode
                  ? 'w-2/3 flex-shrink-0'
                  : isRightPanelCollapsed
                    ? 'w-0 overflow-hidden'
                    : 'w-1/2'
            }`}
          >
            {(!isRightPanelCollapsed || isSopMode || (isSchematic && !chatPanelExpanded)) && (
              <>
                {!isSopMode && !isSchematic && (
                  <button
                    type="button"
                    onClick={() => setIsRightPanelCollapsed(true)}
                    className="absolute left-0 top-1/2 -translate-x-full -translate-y-1/2 z-10 bg-gray-200 hover:bg-gray-300 text-gray-700 px-3 py-2 rounded-l-lg transition-colors shadow-md flex items-center gap-2"
                    title="收缩右侧边栏"
                  >
                    <span className="text-sm font-medium whitespace-nowrap">结果记录</span>
                    <ChevronRight size={16} />
                  </button>
                )}
                {isSchematic && chatPanelExpanded && !isRightPanelCollapsed && (
                  <button
                    type="button"
                    onClick={() => setIsRightPanelCollapsed(true)}
                    className="absolute left-0 top-1/2 -translate-x-full -translate-y-1/2 z-10 bg-sky-100 hover:bg-sky-200 text-sky-800 px-3 py-2 rounded-l-xl transition-colors shadow-md flex items-center gap-2"
                    title="收起评审面板"
                  >
                    <span className="text-sm font-medium whitespace-nowrap">评审面板</span>
                    <ChevronRight size={16} />
                  </button>
                )}
                <div className="flex-1 min-h-0 overflow-hidden">
                  <NetlistResultsPanel
                    readOnly={false}
                    schematicMode={isSchematic}
                    selectedResultId={panelResultId}
                    resultType={panelResultType}
                    onResultSelected={(id, type) => {
                      setPanelResultId(id);
                      setPanelResultType(type);
                    }}
                    aiReviewEntries={aiReviewEntries}
                    aggregatedReviewSummary={aggregatedReviewSummary}
                    onClearAggregatedSummary={() => setAggregatedReviewSummary(null)}
                    cleanedNetlistText={cleanedNetlistText}
                    onCleanedNetlistChange={setCleanedNetlistText}
                    cleanConfirmed={cleanConfirmed}
                    onCleanConfirmed={setCleanConfirmed}
                    reviewExported={reviewExported}
                    onReviewExported={() => setReviewExported(true)}
                    onRunAiReview={runSchematicAiReview}
                    aiReviewRunning={aiReviewRunning}
                    aiReviewRound={aiReviewRound}
                    onOpenChat={() => {
                      setChatPanelExpanded(true);
                      chatSectionRef.current?.scrollIntoView({ behavior: 'smooth' });
                    }}
                    canManagePrompt={canManageModels}
                    onOpenPromptSettings={
                      canManageModels ? () => setShowSchematicPromptModal(true) : undefined
                    }
                    reviewPrompt={reviewPrompt}
                    defaultAiName={schematicDefaultAiName}
                    historyViewMode={schematicHistoryViewMode}
                    viewingHistoryTitle={viewingHistoryTitle}
                    historyDispositions={schematicHistoryDispositions}
                    onApplyHistoryRecord={applySchematicHistoryRecord}
                    onStartNewReview={handleStartNewSchematicReview}
                  />
                </div>
              </>
            )}
          </div>
          {!isSopMode && !isSchematic && isRightPanelCollapsed && (
            <button
              type="button"
              onClick={() => setIsRightPanelCollapsed(false)}
              className="flex-shrink-0 self-center bg-gray-200 hover:bg-gray-300 text-gray-700 px-2 py-3 rounded-l-lg transition-colors shadow-md text-sm font-medium flex items-center gap-1"
              title="展开结果记录"
            >
              <ChevronLeft size={16} />
              <span className="whitespace-nowrap">结果记录</span>
            </button>
          )}
          {isSchematic && chatPanelExpanded && isRightPanelCollapsed && (
            <button
              type="button"
              onClick={() => setIsRightPanelCollapsed(false)}
              className="flex-shrink-0 self-center bg-sky-100 hover:bg-sky-200 text-sky-800 px-2 py-3 rounded-l-xl transition-colors shadow-md text-sm font-medium flex items-center gap-1"
              title="展开评审面板"
            >
              <ChevronLeft size={16} />
              <span className="whitespace-nowrap">评审面板</span>
            </button>
          )}
        </>
      )}

      {/* 自定义AI模态框 */}
      <CustomAIModal
        isOpen={showCustomModal}
        onClose={() => setShowCustomModal(false)}
        onSave={handleCreateCustomAI}
      />

      <AIKeysSettingsModal
        isOpen={showAIKeysModal}
        onClose={() => setShowAIKeysModal(false)}
        onSaved={loadAIs}
      />

      <SchematicReviewPromptModal
        isOpen={showSchematicPromptModal}
        onClose={() => setShowSchematicPromptModal(false)}
        onSaved={({ prompt, defaultAiId }) => {
          setReviewPrompt(prompt);
          setSchematicDefaultAiId(defaultAiId);
          const name =
            schematicCatalogAisRef.current.find((a) => a.id === defaultAiId)?.name || defaultAiId;
          setSchematicDefaultAiName(name);
          if (!reviewExported && schematicCatalogAisRef.current.length > 0) {
            setSelectedAIs(
              applySchematicAiSelection(schematicCatalogAisRef.current, defaultAiId, false)
            );
          }
        }}
      />

      {/* 构建 SOP 弹窗：选择事件流 → 命名 → 添加到主页 */}
      {showBuildSOPModal && (
        <BuildSOPModal
          onClose={() => setShowBuildSOPModal(false)}
          onSaved={() => setShowBuildSOPModal(false)}
        />
      )}
      
      {selectedRoleForKnowledge && (
        <KnowledgeBaseModal
          isOpen={showKnowledgeModal}
          onClose={() => {
            setShowKnowledgeModal(false);
            setSelectedRoleForKnowledge(null);
          }}
          roleId={selectedRoleForKnowledge.id}
          roleName={selectedRoleForKnowledge.name}
        />
      )}

      {selectedRoleForEventTrigger && (
        <EventTriggerModal
          isOpen={showEventTriggerModal}
          onClose={() => {
            setShowEventTriggerModal(false);
            setSelectedRoleForEventTrigger(null);
          }}
          roleId={selectedRoleForEventTrigger.id}
          roleName={selectedRoleForEventTrigger.name}
        />
      )}

      {/* 审核提示词对话 - 输入/上传内容后自动加提示词发送给 AI */}
      <PromptReviewInputModal
        isOpen={showPromptReviewModal}
        onClose={() => {
          setShowPromptReviewModal(false);
          setPromptReviewPrompt('');
          setPromptReviewMessageId(null);
          setPromptReviewDefaultAIIds(undefined);
          setPromptReviewMaxTokens(undefined);
        }}
        prompt={promptReviewPrompt}
        onSubmit={(fullContent) => {
          handleSendMessage(fullContent, {
            skipEventTriggers: true,
            targetAIIds: promptReviewDefaultAIIds,
            maxTokens: promptReviewMaxTokens,
          });
          const mid = promptReviewMessageId;
          setShowPromptReviewModal(false);
          setPromptReviewPrompt('');
          setPromptReviewMessageId(null);
          setPromptReviewDefaultAIIds(undefined);
          setPromptReviewMaxTokens(undefined);
          if (mid) {
            setMessages(prev => prev.map(m =>
              m.id === mid ? { ...m, eventTrigger: undefined, eventTriggers: undefined } : m
            ));
          }
        }}
      />

      {/* 物料库物料查询：事件触发后弹出输入框，让用户输入/修改查询关键词 */}
      {showMaterialSearchModal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-4">
            <h3 className="text-lg font-semibold text-gray-800 mb-2">物料库物料查询</h3>
            <p className="text-xs text-gray-500 mb-3">
              可输入物料代码、规格关键字等；支持多个关键词，用空格或逗号分隔。将从当前物料数据库中查询匹配的物料并显示到对话框中。
            </p>
            <textarea
              value={materialSearchQuery}
              onChange={(e) => setMaterialSearchQuery(e.target.value)}
              className="w-full border rounded-lg p-2 min-h-[80px] text-sm"
              placeholder="例如：0402 10k 1% 或直接留空以查看所有物料（仅展示前若干条）"
            />
            <div className="flex justify-end gap-2 mt-3">
              <button
                type="button"
                className="px-3 py-1.5 border rounded-lg text-sm"
                onClick={() => {
                  setShowMaterialSearchModal(false);
                  setMaterialSearchQuery('');
                  setMaterialSearchMessageId(null);
                }}
              >
                取消
              </button>
              <button
                type="button"
                disabled={!materialSearchQuery.trim() && !materialSearchQuery.trim() === ''}
                className="px-3 py-1.5 bg-blue-500 text-white rounded-lg text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={() => {
                  const q = materialSearchQuery.trim();
                  const eventResult = {
                    event_type: 'material_db_search',
                    result: { query: q, keywords: q },
                  };
                  handleEventTrigger(eventResult);
                  const mid = materialSearchMessageId;
                  setShowMaterialSearchModal(false);
                  setMaterialSearchQuery('');
                  setMaterialSearchMessageId(null);
                  if (mid) {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === mid ? { ...m, eventTrigger: undefined, eventTriggers: undefined } : m
                      )
                    );
                  }
                }}
              >
                开始查询
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 俄罗斯方块游戏 */}
      <TetrisGame
        isOpen={showTetrisGame}
        onClose={() => setShowTetrisGame(false)}
      />

      {/* 回收站模态框 */}
      <RecycleBinModal
        isOpen={showRecycleBin}
        onClose={() => setShowRecycleBin(false)}
        onRestore={() => {
          // 恢复后刷新AI列表
          const loadAIs = async () => {
            try {
              const response = await axios.get(apiUrl('/api/ais'));
              const ais = response.data.ais.map((ai: any) => ({
                ...ai,
                enabled: selectedAIs.find(s => s.id === ai.id)?.enabled || false,
              }));
              setSelectedAIs(ais);
            } catch (error) {
              console.error('加载AI列表失败:', error);
            }
          };
          loadAIs();
        }}
      />

      {/* 网表结果列表 */}
        <NetlistResultsTable
          isOpen={showNetlistResults}
          isModal={true}
          onClose={() => setShowNetlistResults(false)}
      />

      {/* 网表分析侧边栏（覆盖层） */}
      {showNetlistSidebar && (
        <div className="fixed inset-0 z-50">
          <NetlistAnalysisSidebar
            isOpen={showNetlistSidebar}
            onClose={() => setShowNetlistSidebar(false)}
            mode={netlistSidebarMode}
          />
        </div>
      )}

      {/* 网表结果详情模态框 */}
      {selectedNetlistResult && (
        <NetlistResultModal
          isOpen={!!selectedNetlistResult}
          onClose={() => setSelectedNetlistResult(null)}
          resultId={selectedNetlistResult.id}
          resultType={selectedNetlistResult.type}
        />
      )}

    </div>
    </div>
  );
};

