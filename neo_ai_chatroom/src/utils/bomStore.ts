export interface BOMItem {
  code: string;
  name?: string;
  /** 该行 BOM 数量 */
  quantity: number;
  /** 位号列表，例如 ['R1','R2'] */
  designators: string[];
  /** 替代组标识：通常为位号集合的规范化字符串 */
  groupKey?: string;
  /** BOM 源表中的 PLM 替代项目组编号；导出 PLM 时应原样保留 */
  substituteProjectGroup?: string;
}

export interface BOMState {
  items: BOMItem[];
  sourceFileName?: string;
  importedAt: string;
  /** 是否要求满足 REACH */
  reachRequired?: boolean;
  /** 是否要求满足 RoHS */
  rohsRequired?: boolean;
}

const BOM_STORAGE_KEY = 'bom_state';

export function saveBOM(state: BOMState): void {
  try {
    localStorage.setItem(BOM_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

export function loadBOM(): BOMState | null {
  try {
    const raw = localStorage.getItem(BOM_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as BOMState;
    if (!parsed || !Array.isArray(parsed.items)) return null;
    return parsed;
  } catch {
    return null;
  }
}

/** 根据位号数组生成稳定的替代组 key（位号集合一致则 key 一致） */
export function computeGroupKey(designators: string[]): string {
  const norm = (designators || [])
    .map((d) => d.trim())
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
  return norm.join(',');
}

/** 内部拼接片段：物料库替代组标签为空时的分组键标记（勿与真实替代组名冲突） */
export const BOM_NO_LIB_SUBSTITUTE_TAG_MARKER = '__no_lib_substitute_tag__';

type LibRowWithGroupLabel = { groupLabel: string };

/**
 * 物料匹配 / 替代组验证用的分组 key。
 * 物料在物料库中若无可读替代组标签（空白），则不与其它同类物料合并为同一「替代组」；
 * 有非空标签时仍按 BOM 的 groupKey（与物料库一致）合并。
 */
export function bomWorkflowGroupKey(
  item: BOMItem,
  codeToRows: Record<string, LibRowWithGroupLabel[]>
): string {
  const rows = codeToRows[item.code] || [];
  const hasLibSubstituteTag = rows.some((r) => (r.groupLabel || '').trim().length > 0);
  if (hasLibSubstituteTag) {
    return item.groupKey || item.code || '未分组';
  }
  return `${item.code}::${BOM_NO_LIB_SUBSTITUTE_TAG_MARKER}::${computeGroupKey(item.designators)}`;
}

/** 将内部分组 key 转为界面/聊天展示的替代组标题 */
export function formatBomWorkflowGroupDisplayLabel(
  internalKey: string,
  consensusLibLabel: string
): string {
  const trimmed = (consensusLibLabel || '').trim();
  if (trimmed) return trimmed;
  const needle = `::${BOM_NO_LIB_SUBSTITUTE_TAG_MARKER}::`;
  const idx = internalKey.indexOf(needle);
  if (idx !== -1) {
    const code = internalKey.slice(0, idx);
    return `${code}（物料库替代组标签为空）`;
  }
  return internalKey || '未分组';
}

/** 同位号替代组标签检查：空标签提示 */
export type BOMDesignatorEmptyTagIssue = {
  kind: 'empty_tag';
  designator: string;
  code: string;
};

/** 同位号替代组标签检查：多位号下标签不一致 */
export type BOMDesignatorTagConflictIssue = {
  kind: 'tag_conflict';
  designator: string;
  codes: string[];
  message: string;
};

export type BOMDesignatorTagIssue = BOMDesignatorEmptyTagIssue | BOMDesignatorTagConflictIssue;

type DesignatorMaterialEntry = {
  code: string;
  libMatched: boolean;
  groupLabel: string | null;
};

function resolveMaterialSubstituteTag(
  code: string,
  codeToRows: Record<string, { groupLabel: string }[]>
): { libMatched: boolean; groupLabel: string | null } {
  const rows = codeToRows[code] || [];
  if (!rows.length) {
    return { libMatched: false, groupLabel: null };
  }
  const label = (rows[0].groupLabel || '').trim();
  return { libMatched: true, groupLabel: label || null };
}

/**
 * 按位号检查替代组标签一致性（Step2 物料匹配用）。
 * 未在物料库命中的物料不参与替代组标签一致性比较（由物料库命中检查单独提示）；
 * 在库但替代组标签为空者不参与等同比较；全部在库但标签均为空时仅提示空标签。
 */
export function collectDesignatorSubstituteTagIssues(
  items: BOMItem[],
  codeToRows: Record<string, { groupLabel: string }[]>
): BOMDesignatorTagIssue[] {
  const byDesignator = new Map<string, DesignatorMaterialEntry[]>();

  for (const item of items) {
    const designators = (item.designators || []).map((d) => d.trim()).filter(Boolean);
    if (!designators.length) continue;
    const resolved = resolveMaterialSubstituteTag(item.code, codeToRows);
    for (const des of designators) {
      if (!byDesignator.has(des)) byDesignator.set(des, []);
      const list = byDesignator.get(des)!;
      if (!list.some((e) => e.code === item.code)) {
        list.push({ code: item.code, ...resolved });
      }
    }
  }

  const issues: BOMDesignatorTagIssue[] = [];

  for (const [designator, entries] of byDesignator) {
    for (const entry of entries) {
      if (entry.libMatched && !entry.groupLabel) {
        issues.push({ kind: 'empty_tag', designator, code: entry.code });
      }
    }

    if (entries.length < 2) continue;

    // 未命中物料库的不参与替代组标签一致性比较
    const libMatchedEntries = entries.filter((e) => e.libMatched);
    if (libMatchedEntries.length < 2) continue;

    const allLibEmpty = libMatchedEntries.every((e) => !e.groupLabel);
    if (allLibEmpty) continue;

    const withValidTag = libMatchedEntries.filter((e) => e.groupLabel);
    const libMatchedEmptyTag = libMatchedEntries.filter((e) => !e.groupLabel);
    const validTags = new Set(withValidTag.map((e) => e.groupLabel as string));

    const hasConflict =
      validTags.size > 1 ||
      (withValidTag.length > 0 && libMatchedEmptyTag.length > 0);

    if (hasConflict) {
      const codes = libMatchedEntries.map((e) => e.code);
      issues.push({
        kind: 'tag_conflict',
        designator,
        codes,
        message: `这${codes.length}种物料替代组标签不一致`,
      });
    }
  }

  return issues;
}

