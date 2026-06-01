import * as XLSX from 'xlsx';

export const CHAT_FILE_MAX_BYTES = 5 * 1024 * 1024; // 单文件 5MB
export const CHAT_DIGEST_MAX_CHARS = 120_000; // 多文件合并后截断长度

export interface ParsedChatFile {
  name: string;
  size: number;
  text: string;
  error?: string;
}

const TEXT_LIKE_EXT = new Set([
  'txt',
  'md',
  'json',
  'csv',
  'ts',
  'tsx',
  'js',
  'jsx',
  'mjs',
  'cjs',
  'py',
  'java',
  'go',
  'rs',
  'xml',
  'html',
  'htm',
  'css',
  'scss',
  'less',
  'yaml',
  'yml',
  'ini',
  'log',
  'sql',
  'sh',
  'bat',
  'ps1',
  'vue',
  'svelte',
]);

function extOf(file: File): string {
  const n = file.name;
  const dot = n.lastIndexOf('.');
  return dot >= 0 ? n.slice(dot + 1).toLowerCase() : '';
}

function readAsTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
    reader.onerror = () => reject(reader.error ?? new Error('读取失败'));
    reader.readAsText(file, 'UTF-8');
  });
}

function readAsArrayBuffer(file: File): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve(reader.result instanceof ArrayBuffer ? reader.result : new ArrayBuffer(0));
    reader.onerror = () => reject(reader.error ?? new Error('读取失败'));
    reader.readAsArrayBuffer(file);
  });
}

/** Windows 下 .txt 常为 application/octet-stream 或空 type，用抽样判断是否可作 UTF-8 文本 */
function looksLikeUtf8Text(s: string): boolean {
  if (!s.length) return true;
  const sample = s.slice(0, 8000);
  let bad = 0;
  for (let i = 0; i < sample.length; i++) {
    const c = sample.charCodeAt(i);
    if (c === 0) return false;
    if (c < 9 && c !== '\n'.charCodeAt(0) && c !== '\r'.charCodeAt(0) && c !== '\t'.charCodeAt(0))
      bad++;
  }
  return bad / sample.length < 0.02;
}

async function parseXlsx(arrayBuffer: ArrayBuffer, name: string): Promise<string> {
  const wb = XLSX.read(arrayBuffer, { type: 'array' });
  const parts: string[] = [];
  for (const sheetName of wb.SheetNames) {
    const sheet = wb.Sheets[sheetName];
    if (!sheet) continue;
    const csv = XLSX.utils.sheet_to_csv(sheet);
    parts.push(`【工作表: ${sheetName}】\n${csv}`);
  }
  return parts.join('\n\n') || `（Excel ${name} 中未读到单元格数据）`;
}

let pdfWorkerConfigured = false;

async function parsePdf(arrayBuffer: ArrayBuffer): Promise<string> {
  const pdfjsLib = await import('pdfjs-dist');
  if (!pdfWorkerConfigured) {
    const { default: workerUrl } = await import('pdfjs-dist/build/pdf.worker.min.mjs?url');
    pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;
    pdfWorkerConfigured = true;
  }
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  const chunks: string[] = [];
  for (let p = 1; p <= pdf.numPages; p++) {
    const page = await pdf.getPage(p);
    const tc = await page.getTextContent();
    const line = tc.items
      .map((item) =>
        'str' in item && typeof (item as { str: string }).str === 'string' ? (item as { str: string }).str : ''
      )
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();
    if (line) chunks.push(`[第${p}页] ${line}`);
  }
  return chunks.join('\n') || '（未能从 PDF 提取文本，可能是扫描件）';
}

async function parseDocx(arrayBuffer: ArrayBuffer): Promise<string> {
  const mammoth = (await import('mammoth')).default;
  const { value } = await mammoth.extractRawText({ arrayBuffer });
  return value.trim() || '（DOCX 中未提取到文本）';
}

/**
 * 浏览器端解析聊天附件（纯前端），供随用户消息一并发给后端 / DeepSeek 使用。
 * pdf.js、mammoth 仅在实际解析对应格式时动态加载，避免拖垮首屏或初始化失败。
 */
export async function parseChatFile(file: File): Promise<ParsedChatFile> {
  const name = file.name;
  const size = file.size;
  if (size > CHAT_FILE_MAX_BYTES) {
    return {
      name,
      size,
      text: '',
      error: `超过大小限制（最大 ${CHAT_FILE_MAX_BYTES / 1024 / 1024}MB）`,
    };
  }

  const ext = extOf(file);
  const mime = (file.type || '').toLowerCase();

  try {
    if (ext === 'xlsx' || ext === 'xls') {
      const buf = await readAsArrayBuffer(file);
      const text = await parseXlsx(buf, name);
      return { name, size, text };
    }
    if (ext === 'pdf' || mime === 'application/pdf') {
      const buf = await readAsArrayBuffer(file);
      const text = await parsePdf(buf);
      return { name, size, text };
    }
    if (ext === 'docx' || mime === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
      const buf = await readAsArrayBuffer(file);
      const text = await parseDocx(buf);
      return { name, size, text };
    }
    if (
      TEXT_LIKE_EXT.has(ext) ||
      mime.startsWith('text/') ||
      mime === 'application/json' ||
      mime === 'application/xml'
    ) {
      const text = (await readAsTextFile(file)).replace(/\u0000/g, '');
      return { name, size, text };
    }
    // 常见：.txt 被报告为 octet-stream 或 type 为空
    if (
      ext === 'txt' ||
      mime === 'application/octet-stream' ||
      mime === '' ||
      ext === ''
    ) {
      const text = (await readAsTextFile(file)).replace(/\u0000/g, '');
      if (looksLikeUtf8Text(text)) {
        return { name, size, text };
      }
      return {
        name,
        size,
        text: '',
        error:
          '无法作为 UTF-8 文本解码（可能是二进制文件）。请使用支持的格式或先转为 .txt',
      };
    }
    return {
      name,
      size,
      text: '',
      error: `不支持的类型（.${ext || '未知'} / ${mime || '无 MIME'}）。支持：文本、.pdf、.docx、.xlsx/.xls`,
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { name, size, text: '', error: `解析失败：${msg}` };
  }
}

export function buildAttachmentDigest(results: ParsedChatFile[]): string {
  const blocks: string[] = [];
  for (const r of results) {
    if (r.error) {
      blocks.push(`【文件】${r.name}\n错误：${r.error}`);
      continue;
    }
    const body = r.text.trim() || '（空内容）';
    blocks.push(`【文件】${r.name}（${(r.size / 1024).toFixed(1)} KB）\n${body}`);
  }
  let out = blocks.join('\n\n---\n\n');
  if (out.length > CHAT_DIGEST_MAX_CHARS) {
    out =
      out.slice(0, CHAT_DIGEST_MAX_CHARS) +
      `\n\n…（附件解析正文过长，已截断至约 ${CHAT_DIGEST_MAX_CHARS} 字符，请分次上传或减少内容）`;
  }
  return out;
}
