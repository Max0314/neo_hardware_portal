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
