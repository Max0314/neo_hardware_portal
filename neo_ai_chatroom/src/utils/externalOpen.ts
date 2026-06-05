type DingTalkOpenLink = {
  biz?: {
    util?: {
      openLink?: (options: { url: string; onSuccess?: () => void; onFail?: () => void }) => void;
    };
  };
};

export type ExternalOpenResult = 'dingtalk' | 'window' | 'copied' | 'failed';

export function isDingTalkBrowser(): boolean {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent.toLowerCase();
  return ua.includes('dingtalk') || ua.includes('aliapp(dingtalk');
}

export function getCurrentPageUrl(): string {
  if (typeof window === 'undefined') return '';
  return window.location.href;
}

async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the textarea fallback.
  }

  try {
    const input = document.createElement('textarea');
    input.value = text;
    input.setAttribute('readonly', 'readonly');
    input.style.position = 'fixed';
    input.style.left = '-9999px';
    input.style.top = '0';
    document.body.appendChild(input);
    input.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(input);
    return ok;
  } catch {
    return false;
  }
}

function openWithDingTalk(url: string): Promise<boolean> {
  const dd = (window as unknown as { dd?: DingTalkOpenLink }).dd;
  const openLink = dd?.biz?.util?.openLink;
  if (!openLink) return Promise.resolve(false);

  return new Promise((resolve) => {
    try {
      openLink({
        url,
        onSuccess: () => resolve(true),
        onFail: () => resolve(false),
      });
      window.setTimeout(() => resolve(true), 800);
    } catch {
      resolve(false);
    }
  });
}

export async function openUrlExternally(url: string): Promise<ExternalOpenResult> {
  if (!url) return 'failed';

  if (isDingTalkBrowser() && typeof window !== 'undefined') {
    const openedByDingTalk = await openWithDingTalk(url);
    if (openedByDingTalk) return 'dingtalk';
  }

  try {
    const win = window.open(url, '_blank', 'noopener,noreferrer');
    if (win) {
      win.opener = null;
      return 'window';
    }
  } catch {
    // Continue to copy fallback.
  }

  return (await copyText(url)) ? 'copied' : 'failed';
}

export function getExternalOpenMessage(result: ExternalOpenResult): string {
  switch (result) {
    case 'dingtalk':
      return '已尝试用外部浏览器打开当前页面。';
    case 'window':
      return '已在新窗口打开当前页面。';
    case 'copied':
      return '无法直接打开外部浏览器，已复制链接，请粘贴到系统浏览器打开。';
    default:
      return '无法打开外部浏览器，请手动复制当前页面链接到系统浏览器打开。';
  }
}

export async function openCurrentPageExternally(): Promise<ExternalOpenResult> {
  return openUrlExternally(getCurrentPageUrl());
}

export type PrintResult = 'printed' | 'window' | 'external' | 'failed';

/**
 * 通过隐藏 iframe 打印一段完整 HTML（含 <html>/<head>/<body>）。
 * 之所以用 iframe 而不是 window.open：钉钉内置浏览器（webview）通常禁用/拦截
 * 弹出新标签页，导致旧逻辑里 window.open + window.print() 无法调起打印机；
 * 而同页内的隐藏 iframe 调 contentWindow.print() 在钉钉 webview 与普通浏览器中都可用。
 * 返回 true 表示已成功调起打印对话框。
 */
function printViaIframe(html: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (typeof document === 'undefined') {
      resolve(false);
      return;
    }

    let settled = false;
    let printed = false;
    const iframe = document.createElement('iframe');
    iframe.setAttribute('aria-hidden', 'true');
    iframe.style.cssText =
      'position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0;pointer-events:none;';

    const removeLater = () => {
      window.setTimeout(() => {
        if (iframe.parentNode) iframe.parentNode.removeChild(iframe);
      }, 2000);
    };

    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true;
      resolve(ok);
      if (ok) {
        removeLater();
      } else if (iframe.parentNode) {
        iframe.parentNode.removeChild(iframe);
      }
    };

    const doPrint = () => {
      if (printed || settled) return;
      const win = iframe.contentWindow;
      if (!win) {
        finish(false);
        return;
      }
      printed = true;
      try {
        win.focus();
        win.print();
        finish(true);
      } catch {
        finish(false);
      }
    };

    // 给样式/图片留出渲染时间后再打印。
    iframe.onload = () => window.setTimeout(doPrint, 300);

    try {
      document.body.appendChild(iframe);
      const doc = iframe.contentWindow?.document;
      if (!doc) {
        finish(false);
        return;
      }
      doc.open();
      doc.write(html);
      doc.close();
    } catch {
      finish(false);
      return;
    }

    // 兜底：部分 webview 不触发 iframe.onload，超时后仍尝试打印。
    window.setTimeout(doPrint, 1200);
  });
}

/**
 * 打印/导出一段完整 HTML 报告，优先在当前页面内（兼容钉钉内置浏览器）调起打印，
 * 失败时依次回退：新窗口打印 → 跳转外部浏览器打开当前页面。
 */
export async function printHtmlDocument(html: string): Promise<PrintResult> {
  if (!html || typeof window === 'undefined') return 'failed';

  // 1) 首选：隐藏 iframe 打印（钉钉 webview 也支持）
  if (await printViaIframe(html)) return 'printed';

  // 2) 回退：新窗口打印（桌面浏览器允许弹窗时）
  try {
    const win = window.open('', '_blank');
    if (win) {
      win.document.open();
      win.document.write(html);
      win.document.close();
      win.focus();
      window.setTimeout(() => {
        try {
          win.print();
        } catch {
          // 忽略：用户可在新窗口手动打印
        }
      }, 300);
      return 'window';
    }
  } catch {
    // 继续回退到外部浏览器
  }

  // 3) 最后：跳外部浏览器打开当前页面，由用户在系统浏览器中打印
  const ext = await openCurrentPageExternally();
  return ext === 'failed' ? 'failed' : 'external';
}

export function getPrintMessage(result: PrintResult): string {
  switch (result) {
    case 'printed':
    case 'window':
      return '已调起打印，请在弹出的打印对话框中选择“打印”或“另存为 PDF”。';
    case 'external':
      return '当前环境无法直接调起打印，已尝试用外部浏览器打开当前页面，请在浏览器中打印。';
    default:
      return '无法调起打印，请手动复制当前页面链接到系统浏览器打开后再打印。';
  }
}
