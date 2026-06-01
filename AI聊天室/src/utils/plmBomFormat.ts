import * as XLSX from 'xlsx';

/**
 * 与 `BOM_TOOL/BOM-TS5021493-导入模板wlgs.xls` 首行表头完全一致（含单元格内换行）。
 * 内嵌表头以避免运行时 fetch 模板资源——在企业网络 / 安全浏览器环境下 fetch 常被拦截并误报无关域名错误。
 */
export const PLM_TEMPLATE_HEADERS: string[] = [
  '序号',
  '父项编码',
  '父项名称',
  '子项编码',
  '子项名称',
  '子项数量',
  '子项单位',
  '位号',
  '是否\n安全件',
  '是否\n关键件',
  'BOM插装方式',
  '特殊获取',
  '备注',
  '替代项目组',
  '替代策略',
  '优先级/替代配额',
];

export function formatSubstituteGroupNumber(num: number): string {
  if (num <= 99) {
    return String(num);
  }
  const offset = num - 100;
  const letterIndex = Math.floor(offset / 9);
  const digit = (offset % 9) + 1;
  const letter = String.fromCharCode(65 + letterIndex);
  return letter + digit;
}

function normalizeHeader(h: string | undefined | null): string {
  return String(h || '')
    .trim()
    .replace(/\s+/g, '')
    .replace(/\uFF0F/g, '/');
}

export interface PlmSourceRow {
  itemCode: string;
  itemName: string;
  quantity: string | number;
  /** 与 HTML 工具「位号」列一致：仅用英文逗号拼接，不含空格 */
  reference: string;
}

/** PLM 位号列：多个位号仅用英文逗号连接（无逗号后空格、无首尾空格） */
export function formatDesignatorsForPlm(designators: string[]): string {
  return (designators || [])
    .map((d) => String(d ?? '').trim())
    .filter(Boolean)
    .join(',');
}

/** 将任意分隔的位号串规范为 PLM 要求的逗号分隔（去掉逗号两侧空格） */
export function normalizePlmReferenceString(reference: string): string {
  return String(reference ?? '')
    .split(/[,，;；\s]+/)
    .map((d) => d.trim())
    .filter(Boolean)
    .join(',');
}

export interface PlmConvertOptions {
  parentCode: string;
  /** 对应模板「父项标准描述」 */
  parentStandardDesc: string;
}

type PlmRow = Record<string, string | number>;

/**
 * 将简化的 BOM 行转为 PLM 模板列（与 `BOM转化PLM格式.html` 的 convertToPLMFormat 一致）
 */
export function convertRowsToPlmFormat(
  bomRows: PlmSourceRow[],
  templateHeaders: string[],
  opts: PlmConvertOptions
): PlmRow[] {
  const parentCode = (opts.parentCode || '').trim();
  const parentName = (opts.parentStandardDesc || '').trim();
  const hasParentStdDescCol = templateHeaders.some(
    (h) => normalizeHeader(h) === '父项标准描述'
  );

  const referenceCount = new Map<string, number>();
  for (const row of bomRows) {
    const reference = normalizePlmReferenceString(String(row.reference || ''));
    if (reference) {
      referenceCount.set(reference, (referenceCount.get(reference) || 0) + 1);
    }
  }

  const substituteGroupMap = new Map<string, number>();
  let substituteGroupCounter = 1;
  for (const [reference, count] of referenceCount) {
    if (count > 1) {
      substituteGroupMap.set(reference, substituteGroupCounter++);
    }
  }

  const groupPrioritySet = new Map<number, boolean>();
  let sequenceNumber = 1;
  const convertedData: PlmRow[] = [];

  for (const row of bomRows) {
    const itemCode = row.itemCode || '';
    const itemName = row.itemName || '';
    const quantity = row.quantity ?? '';
    const reference = normalizePlmReferenceString(String(row.reference || ''));

    const hasSubstituteGroup = substituteGroupMap.has(reference);
    const rawGroupNumber = hasSubstituteGroup ? substituteGroupMap.get(reference)! : null;
    const substituteGroupFormatted = rawGroupNumber
      ? formatSubstituteGroupNumber(rawGroupNumber)
      : '';

    let priority: number | string = '';
    if (hasSubstituteGroup) {
      if (!groupPrioritySet.has(rawGroupNumber!)) {
        priority = 100;
        groupPrioritySet.set(rawGroupNumber!, true);
      } else {
        priority = 0;
      }
    }

    const newRow: PlmRow = {};
    for (const header of templateHeaders) {
      let value: string | number = '';
      const nh = normalizeHeader(header);

      if (nh === '序号') {
        value = sequenceNumber++;
      } else if (nh === '父项编码') {
        value = parentCode;
      } else if (nh === '父项名称') {
        // wlgs 模板仅有「父项名称」无「父项标准描述」，父项说明写入本列
        value = hasParentStdDescCol ? '' : parentName;
      } else if (nh === '父项标准描述') {
        value = parentName;
      } else if (nh === '子项编码') {
        value = itemCode;
      } else if (nh === '子项名称') {
        value = itemName;
      } else if (nh === '子项标准描述') {
        value = itemName;
      } else if (nh === '子项数量') {
        value = quantity as string | number;
      } else if (nh === '子项单位') {
        value = 'PCS';
      } else if (nh === '位号') {
        value = reference;
      } else if (nh === '是否安全件') {
        value = 'False';
      } else if (nh === '是否关键件') {
        value = 'False';
      } else if (nh === '替代项目组') {
        value = substituteGroupFormatted;
      } else if (nh.includes('替代项目组')) {
        value = substituteGroupFormatted;
      } else if (nh === '替代策略') {
        value = hasSubstituteGroup ? '1' : '';
      } else if (nh.includes('优先级')) {
        value = priority;
      } else {
        value = '';
      }
      newRow[header] = value;
    }
    convertedData.push(newRow);
  }

  const substituteGroupKeys = templateHeaders.filter((h) =>
    normalizeHeader(h).includes('替代项目组')
  );
  const priorityKeys = templateHeaders.filter((h) => normalizeHeader(h).includes('优先级'));

  if (substituteGroupKeys.length && priorityKeys.length) {
    let substituteGroupKey = substituteGroupKeys[0];
    let bestNonEmpty = -1;
    for (const k of substituteGroupKeys) {
      let nonEmpty = 0;
      for (const r of convertedData) {
        const v = String(r[k] ?? '').trim();
        if (v !== '') nonEmpty++;
      }
      if (nonEmpty > bestNonEmpty) {
        bestNonEmpty = nonEmpty;
        substituteGroupKey = k;
      }
    }
    const firstSeen = new Set<string>();
    for (const row of convertedData) {
      const g = String(row[substituteGroupKey] ?? '').trim();
      if (g !== '') {
        if (!firstSeen.has(g)) {
          firstSeen.add(g);
          for (const pk of priorityKeys) {
            row[pk] = 100;
          }
        } else {
          for (const pk of priorityKeys) {
            row[pk] = 0;
          }
        }
      } else {
        for (const pk of priorityKeys) {
          row[pk] = '';
        }
      }
    }
  }

  return convertedData;
}

export function writePlmXlsxFile(
  templateHeaders: string[],
  convertedRows: PlmRow[],
  fileName: string,
  sheetName = 'PLM格式BOM'
): void {
  const wsData: (string | number)[][] = [templateHeaders];
  for (const row of convertedRows) {
    wsData.push(templateHeaders.map((h) => row[h] ?? ''));
  }
  const ws = XLSX.utils.aoa_to_sheet(wsData);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, sheetName);
  XLSX.writeFile(wb, fileName);
}
