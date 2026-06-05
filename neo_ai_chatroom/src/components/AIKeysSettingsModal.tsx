import React, { useCallback, useEffect, useState } from 'react';
import { X, KeyRound, Eye, EyeOff, Trash2, Shield } from 'lucide-react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';

export interface AIKeyProviderStatus {
  id: string;
  name: string;
  description: string;
  env_var: string;
  configured: boolean;
  source: 'vault' | 'env' | 'none';
  hint: string;
}

interface AIKeysSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved?: () => void;
}

function SourceBadge({ source }: { source: AIKeyProviderStatus['source'] }) {
  if (source === 'vault') {
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800">
        已加密保存
      </span>
    );
  }
  if (source === 'env') {
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-800">
        环境变量
      </span>
    );
  }
  return (
    <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
      未配置
    </span>
  );
}

export const AIKeysSettingsModal: React.FC<AIKeysSettingsModalProps> = ({
  isOpen,
  onClose,
  onSaved,
}) => {
  const [providers, setProviders] = useState<AIKeyProviderStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [draftKeys, setDraftKeys] = useState<Record<string, string>>({});
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  const loadProviders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(apiUrl('/api/settings/ai-keys'), {
        withCredentials: true,
      });
      if (res.data?.success) {
        setProviders(res.data.providers || []);
      } else {
        setError('加载配置失败');
      }
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? e.response?.data?.detail || e.response?.data?.error || e.message
        : String(e);
      setError(msg || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      setDraftKeys({});
      setShowKey({});
      loadProviders();
    }
  }, [isOpen, loadProviders]);

  if (!isOpen) return null;

  const handleSave = async (providerId: string) => {
    const key = (draftKeys[providerId] || '').trim();
    if (!key) {
      alert('请输入 API Key');
      return;
    }
    setSavingId(providerId);
    setError(null);
    try {
      const res = await axios.put(
        apiUrl(`/api/settings/ai-keys/${providerId}`),
        { api_key: key },
        { withCredentials: true, headers: { 'Content-Type': 'application/json' } }
      );
      if (res.data?.success) {
        setDraftKeys((prev) => ({ ...prev, [providerId]: '' }));
        await loadProviders();
        onSaved?.();
      } else {
        alert(res.data?.error || '保存失败');
      }
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? e.response?.data?.error || e.message
        : String(e);
      alert(msg || '保存失败');
    } finally {
      setSavingId(null);
    }
  };

  const handleClear = async (providerId: string, name: string) => {
    if (
      !window.confirm(
        `确定删除已保存的「${name}」密钥？\n删除后将仅使用服务器环境变量（若有）。`
      )
    ) {
      return;
    }
    setSavingId(providerId);
    try {
      await axios.delete(apiUrl(`/api/settings/ai-keys/${providerId}`), {
        withCredentials: true,
      });
      setDraftKeys((prev) => ({ ...prev, [providerId]: '' }));
      await loadProviders();
      onSaved?.();
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? e.response?.data?.error || e.message
        : String(e);
      alert(msg || '删除失败');
    } finally {
      setSavingId(null);
    }
  };

  return (
    <MotionlessModalBackdrop onClose={onClose}>
      <div className="flex items-center justify-between border-b px-5 py-4 shrink-0">
        <div className="flex items-center gap-2">
          <KeyRound className="text-indigo-600" size={22} />
          <div>
            <h2 className="text-lg font-semibold text-gray-900">AI API 密钥</h2>
            <p className="text-xs text-gray-500">DeepSeek、百炼 (DashScope)、豆包、OpenAI 等</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded hover:bg-gray-100 text-gray-500"
          aria-label="关闭"
        >
          <X size={20} />
        </button>
      </div>

      <div className="px-5 py-3 bg-amber-50 border-b border-amber-100 text-sm text-amber-900 flex gap-2 shrink-0">
        <Shield className="shrink-0 mt-0.5" size={16} />
        <p>
          密钥在服务端使用 Fernet 加密后存入数据库，接口不会返回明文。输入框为密码类型。
          仍可使用 Docker 根目录 <code className="text-xs bg-amber-100 px-1 rounded">.env</code>{' '}
          环境变量；界面保存的密钥优先于环境变量。
        </p>
      </div>

      {error && (
        <p className="px-5 py-2 text-sm text-red-600 bg-red-50 shrink-0">{error}</p>
      )}

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 min-h-0">
        {loading ? (
          <p className="text-gray-500 text-sm text-center py-8">加载中…</p>
        ) : (
          providers.map((p) => (
            <div key={p.id} className="border rounded-lg p-4 space-y-3">
              <MotionlessProviderHeader provider={p} />
              {p.configured && p.hint && (
                <p className="text-xs text-gray-500">
                  当前：{p.hint}
                  {p.source === 'env' && (
                    <span className="ml-1">（{p.env_var}）</span>
                  )}
                </p>
              )}
              <MotionlessProviderKeyRow
                draft={draftKeys[p.id] || ''}
                visible={!!showKey[p.id]}
                saving={savingId === p.id}
                canDeleteVault={p.source === 'vault'}
                onDraftChange={(v: string) =>
                  setDraftKeys((prev) => ({ ...prev, [p.id]: v }))
                }
                onToggleVisible={() =>
                  setShowKey((prev) => ({ ...prev, [p.id]: !prev[p.id] }))
                }
                onSave={() => handleSave(p.id)}
                onClear={() => handleClear(p.id, p.name)}
              />
            </div>
          ))
        )}
      </div>

      <div className="border-t px-5 py-3 flex justify-end shrink-0">
        <button
          type="button"
          onClick={onClose}
          className="px-4 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50"
        >
          关闭
        </button>
      </div>
    </MotionlessModalBackdrop>
  );
};

function MotionlessModalBackdrop({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <MotionlessModalBackdropDiv onClose={onClose}>{children}</MotionlessModalBackdropDiv>
  );
}

function MotionlessModalBackdropDiv({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function MotionlessProviderHeader({ provider: p }: { provider: AIKeyProviderStatus }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div>
        <div className="font-medium text-gray-900">{p.name}</div>
        <p className="text-xs text-gray-500">{p.description}</p>
      </div>
      <SourceBadge source={p.source} />
    </div>
  );
}

function MotionlessProviderKeyRow({
  draft,
  visible,
  saving,
  canDeleteVault,
  onDraftChange,
  onToggleVisible,
  onSave,
  onClear,
}: {
  draft: string;
  visible: boolean;
  saving: boolean;
  canDeleteVault: boolean;
  onDraftChange: (v: string) => void;
  onToggleVisible: () => void;
  onSave: () => void;
  onClear: () => void;
}) {
  return (
    <div className="flex flex-col sm:flex-row gap-2">
      <div className="flex-1 relative">
        <input
          type={visible ? 'text' : 'password'}
          autoComplete="new-password"
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder="输入新 API Key（不会显示已保存的明文）"
          className="w-full border rounded-lg pl-3 pr-10 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
        />
        <button
          type="button"
          onClick={onToggleVisible}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
          tabIndex={-1}
          aria-label={visible ? '隐藏' : '显示'}
        >
          {visible ? <EyeOff size={18} /> : <Eye size={18} />}
        </button>
      </div>
      <div className="flex gap-2 shrink-0">
        <button
          type="button"
          disabled={saving}
          onClick={onSave}
          className="px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? '保存中…' : '保存'}
        </button>
        {canDeleteVault && (
          <button
            type="button"
            disabled={saving}
            onClick={onClear}
            className="px-3 py-2 text-sm rounded-lg border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50 flex items-center gap-1"
            title="删除加密库中的密钥"
          >
            <Trash2 size={16} />
            删除
          </button>
        )}
      </div>
    </div>
  );
}
