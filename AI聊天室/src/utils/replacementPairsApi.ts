import { apiUrl } from '@/utils/apiBase';
import type { ReplacementGroup } from '@/utils/replacementPairsStorage';

const API_BASE = '/api/material-db/replacement-groups';
const UNLOCK_CACHE_KEY = 'replacement_pairs_unlock';

type UnlockCache = { token: string; expiresAt: number };

function readUnlockCache(): UnlockCache | null {
  try {
    const raw = sessionStorage.getItem(UNLOCK_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as UnlockCache;
    if (!parsed?.token || !parsed?.expiresAt) return null;
    if (Date.now() / 1000 >= parsed.expiresAt) {
      sessionStorage.removeItem(UNLOCK_CACHE_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function writeUnlockCache(token: string, expiresAt: number) {
  sessionStorage.setItem(UNLOCK_CACHE_KEY, JSON.stringify({ token, expiresAt }));
}

export function getReplacementUnlockToken(): string | null {
  return readUnlockCache()?.token ?? null;
}

async function parseJson(res: Response): Promise<Record<string, unknown>> {
  try {
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return {};
  }
}

export async function fetchReplacementGroupsRemote(): Promise<{
  groups: ReplacementGroup[];
  passwordConfigured: boolean;
}> {
  const res = await fetch(apiUrl(API_BASE), { credentials: 'include' });
  const data = await parseJson(res);
  if (res.status === 401) throw new Error('请先登录管理系统');
  if (!res.ok || !data.success) {
    throw new Error(String(data.error || `加载替换对失败（HTTP ${res.status}）`));
  }
  return {
    groups: (data.groups as ReplacementGroup[]) || [],
    passwordConfigured: Boolean(data.passwordConfigured),
  };
}

export async function unlockReplacementPairs(password: string): Promise<string> {
  const res = await fetch(apiUrl(`${API_BASE}/unlock`), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  const data = await parseJson(res);
  if (!res.ok || !data.success) {
    throw new Error(String(data.error || '密码错误'));
  }
  const token = String(data.unlockToken || '');
  const expiresAt = Number(data.expiresAt || 0);
  if (token && expiresAt) writeUnlockCache(token, expiresAt);
  return token;
}

export async function setReplacementPairsPassword(password: string, oldPassword?: string): Promise<void> {
  const res = await fetch(apiUrl(`${API_BASE}/set-password`), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password, oldPassword: oldPassword || undefined }),
  });
  const data = await parseJson(res);
  if (!res.ok || !data.success) {
    throw new Error(String(data.error || '设置密码失败'));
  }
}

export async function saveReplacementGroupsRemote(groups: ReplacementGroup[], unlockToken?: string): Promise<void> {
  const token = unlockToken || getReplacementUnlockToken();
  const res = await fetch(apiUrl(API_BASE), {
    method: 'PUT',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'X-Material-Unlock-Token': token } : {}),
    },
    body: JSON.stringify({ groups, unlockToken: token }),
  });
  const data = await parseJson(res);
  if (!res.ok || !data.success) {
    if (data.needPassword || data.needSetupPassword) {
      sessionStorage.removeItem(UNLOCK_CACHE_KEY);
    }
    throw new Error(String(data.error || '保存替换对失败'));
  }
}

export async function migrateReplacementGroupsRemote(
  groups: ReplacementGroup[],
  password: string,
  unlockToken?: string
): Promise<number> {
  const token = unlockToken || getReplacementUnlockToken();
  const res = await fetch(apiUrl(`${API_BASE}/migrate`), {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'X-Material-Unlock-Token': token } : {}),
    },
    body: JSON.stringify({ groups, password, unlockToken: token }),
  });
  const data = await parseJson(res);
  if (!res.ok || !data.success) {
    throw new Error(String(data.error || '迁移替换对失败'));
  }
  return Number(data.migrated || groups.length);
}
