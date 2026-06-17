import { apiUrl } from '@/utils/apiBase';

/** @deprecated 仅用于从浏览器本地数据一次性迁移；读写请使用 fetchMaterialLibraries */
export const MATERIAL_DB_STORAGE_KEY = 'material_db_libraries';

export interface MaterialTable {
  fileName?: string;
  updatedAt?: string;
  data?: unknown[][];
}

export interface MaterialLibrary {
  id: string;
  name: string;
  prefix?: string;
  hasPassword?: boolean;
  currentTable?: MaterialTable | null;
  historyTables?: MaterialTable[];
  createdAt?: string;
  updatedAt?: string;
}

export type MaterialCodeRow = {
  libName: string;
  desc: string;
  groupLabel: string;
  sourceUpdatedAt?: string;
  raw: unknown[];
};

async function parseJsonResponse(res: Response): Promise<Record<string, unknown>> {
  try {
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** 从 MySQL（经 htmlsystm /api/material-db）加载全部物料库 */
export async function fetchMaterialLibraries(): Promise<MaterialLibrary[]> {
  const res = await fetch(apiUrl('/api/material-db/libraries'), { credentials: 'include' });
  const data = await parseJsonResponse(res);
  if (res.status === 401) {
    throw new Error('请先登录管理系统');
  }
  if (!res.ok || !data.success) {
    throw new Error(String(data.error || `加载物料库失败（HTTP ${res.status}）`));
  }
  return (data.libraries as MaterialLibrary[]) || [];
}

/** 物料代码 → 库内行（BOM 匹配、替代组校验等） */
export function buildCodeToMaterialRows(
  libs: MaterialLibrary[]
): Record<string, MaterialCodeRow[]> {
  const codeToRows: Record<string, MaterialCodeRow[]> = {};
  for (const lib of libs) {
    const libName = lib.name || '未命名物料库';
    const table = lib.currentTable;
    if (!table?.data || !Array.isArray(table.data) || table.data.length < 2) continue;
    const sourceUpdatedAt = table.updatedAt || lib.updatedAt || '';
    for (const row of table.data.slice(1)) {
      const r = row as unknown[];
      const code = r[0] != null ? String(r[0]).trim() : '';
      if (!code) continue;
      const desc = r[1] != null ? String(r[1]).trim() : '';
      const groupLabel = r[4] != null ? String(r[4]).trim() : '';
      if (!codeToRows[code]) codeToRows[code] = [];
      codeToRows[code].push({ libName, desc, groupLabel, sourceUpdatedAt, raw: r });
    }
  }
  for (const rows of Object.values(codeToRows)) {
    rows.sort((a, b) => {
      const bt = Date.parse(b.sourceUpdatedAt || '') || 0;
      const at = Date.parse(a.sourceUpdatedAt || '') || 0;
      if (bt !== at) return bt - at;
      const bClean = b.groupLabel && !b.groupLabel.includes(',');
      const aClean = a.groupLabel && !a.groupLabel.includes(',');
      if (bClean !== aClean) return bClean ? 1 : -1;
      return (a.libName || '').localeCompare(b.libName || '');
    });
  }
  return codeToRows;
}

/** 物料代码 → 替代组标签（BOM 导入时重写 groupKey） */
export function buildCodeToGroupLabel(libs: MaterialLibrary[]): Record<string, string> {
  const codeToGroup: Record<string, string> = {};
  const codeToRows = buildCodeToMaterialRows(libs);
  for (const [code, rows] of Object.entries(codeToRows)) {
    const group = rows.find((r) => r.groupLabel)?.groupLabel || '';
    if (group) codeToGroup[code] = group;
  }
  return codeToGroup;
}

/** 替换对管理页：物料代码列表与名称映射 */
export function extractMaterialCodesFromLibs(libs: MaterialLibrary[]): {
  codes: string[];
  codeToName: Record<string, string>;
} {
  const codes = new Set<string>();
  const codeToName: Record<string, string> = {};
  for (const lib of libs) {
    const table = lib.currentTable;
    if (!table?.data || !Array.isArray(table.data)) continue;
    for (const row of table.data.slice(1)) {
      const r = row as unknown[];
      const code = r[0] != null ? String(r[0]).trim() : '';
      const name = r[1] != null ? String(r[1]).trim() : '';
      if (!code) continue;
      codes.add(code);
      if (name) codeToName[code] = name;
    }
  }
  return {
    codes: Array.from(codes).sort((a, b) => a.localeCompare(b)),
    codeToName,
  };
}
