/** 与后端/历史记录兼容：附件解析正文包在标记内，气泡可拆分展示 */
export const ATTACHMENT_BLOCK_START = '<<<ATTACHMENT_CONTEXT_START>>>';
export const ATTACHMENT_BLOCK_END = '<<<ATTACHMENT_CONTEXT_END>>>';

export function buildMessageWithAttachments(userText: string, attachmentDigest: string): string {
  const t = userText.trim();
  const d = attachmentDigest.trim();
  if (!d) return t;
  const block = `${ATTACHMENT_BLOCK_START}\n${d}\n${ATTACHMENT_BLOCK_END}`;
  if (!t) return block;
  return `${t}\n\n${block}`;
}

export function splitUserMessageContent(raw: string): { text: string; attachmentPart: string | null } {
  const i = raw.indexOf(ATTACHMENT_BLOCK_START);
  if (i === -1) return { text: raw, attachmentPart: null };
  const j = raw.indexOf(ATTACHMENT_BLOCK_END, i);
  if (j === -1) return { text: raw, attachmentPart: null };
  const text = raw.slice(0, i).trimEnd();
  const attachmentPart = raw.slice(i + ATTACHMENT_BLOCK_START.length, j).trim();
  return { text, attachmentPart };
}
