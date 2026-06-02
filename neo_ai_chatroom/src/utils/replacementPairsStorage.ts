/**
 * 替换组内一项：物料代码 + 物料名称（可选）
 */
export interface ReplacementItem {
  code: string;
  name?: string;
}

/**
 * 替换组：一组物料互为可替换关系。
 * 若 BOM 中存在组内任一物料 A，则其替代组应包含组内全部物料 B,C,D...；反之若存在 B 则需包含 A,C,D...
 */
export interface ReplacementGroup {
  id: string;
  /** 本组内所有可互相替换的物料（代码+名称） */
  materialItems: ReplacementItem[];
  /** 管理备注 */
  remark?: string;
  createdAt?: string;
  updatedAt?: string;
}

export const REPLACEMENT_PAIRS_STORAGE_KEY = 'bom_replacement_pairs';
export const REPLACEMENT_GROUPS_STORAGE_KEY = 'bom_replacement_groups';

function uuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function normalizeItems(items: ReplacementItem[]): ReplacementItem[] {
  return items
    .map((it) => ({ code: (it.code || '').trim(), name: (it.name || '').trim() || undefined }))
    .filter((it) => it.code.length > 0);
}

/** 兼容旧结构：仅有 materialCodes 的组转为 materialItems */
function migrateGroup(g: any): ReplacementGroup {
  if (g.materialItems && Array.isArray(g.materialItems)) {
    return {
      ...g,
      materialItems: normalizeItems(g.materialItems),
    };
  }
  if (g.materialCodes && Array.isArray(g.materialCodes)) {
    return {
      ...g,
      materialItems: (g.materialCodes as string[]).map((c: string) => ({ code: String(c).trim(), name: undefined })),
      materialCodes: undefined,
    };
  }
  return g;
}

/** 从服务器加载替换组（失败时回退 localStorage） */
export async function loadReplacementGroupsAsync(): Promise<{
  groups: ReplacementGroup[];
  passwordConfigured: boolean;
  fromServer: boolean;
}> {
  try {
    const { fetchReplacementGroupsRemote } = await import('@/utils/replacementPairsApi');
    const remote = await fetchReplacementGroupsRemote();
    return { ...remote, fromServer: true };
  } catch {
    return {
      groups: loadReplacementGroups(),
      passwordConfigured: false,
      fromServer: false,
    };
  }
}

export function loadReplacementGroups(): ReplacementGroup[] {
  try {
    const raw =
      typeof window !== 'undefined' ? window.localStorage.getItem(REPLACEMENT_GROUPS_STORAGE_KEY) : null;
    const list = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(list)) return [];
    return list.map(migrateGroup);
  } catch {
    return [];
  }
}

export function saveReplacementGroups(groups: ReplacementGroup[]): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(REPLACEMENT_GROUPS_STORAGE_KEY, JSON.stringify(groups));
}

export function addReplacementGroup(items: ReplacementItem[], remark?: string): ReplacementGroup {
  const groups = loadReplacementGroups();
  const normalized = normalizeItems(items);
  const now = new Date().toISOString();
  const group: ReplacementGroup = {
    id: uuid(),
    materialItems: normalized,
    remark: remark?.trim() || undefined,
    createdAt: now,
    updatedAt: now,
  };
  groups.push(group);
  saveReplacementGroups(groups);
  return group;
}

export function updateReplacementGroup(
  id: string,
  payload: { materialItems?: ReplacementItem[]; remark?: string }
): ReplacementGroup | null {
  const groups = loadReplacementGroups();
  const idx = groups.findIndex((g) => g.id === id);
  if (idx < 0) return null;
  if (payload.materialItems != null) {
    groups[idx].materialItems = normalizeItems(payload.materialItems);
  }
  if (payload.remark !== undefined) {
    groups[idx].remark = payload.remark.trim() || undefined;
  }
  groups[idx].updatedAt = new Date().toISOString();
  saveReplacementGroups(groups);
  return groups[idx];
}

export function removeReplacementGroup(id: string): void {
  const groups = loadReplacementGroups().filter((g) => g.id !== id);
  saveReplacementGroups(groups);
}

/** 查出包含指定物料代码的替换组 */
export function getReplacementGroupsContainingCode(code: string): ReplacementGroup[] {
  const c = code.trim();
  return loadReplacementGroups().filter((g) => g.materialItems.some((it) => it.code === c));
}

// ---------- 兼容旧 1对1 接口 -----------
/** @deprecated 使用 ReplacementGroup */
export interface ReplacementPair {
  id: string;
  fromCode: string;
  toCode: string;
  createdAt?: string;
}

export function loadReplacementPairs(): ReplacementPair[] {
  try {
    const raw =
      typeof window !== 'undefined' ? window.localStorage.getItem(REPLACEMENT_PAIRS_STORAGE_KEY) : null;
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}
