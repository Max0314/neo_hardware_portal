import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { X, FileText, History, RotateCcw, Save } from 'lucide-react';
import { apiUrl } from '@/utils/apiBase';
import type { SchematicAiModelOption, SchematicPromptHistoryItem } from '@/utils/schematicReview';
import { DEFAULT_SCHEMATIC_AI_ID } from '@/utils/schematicReview';

interface SchematicReviewPromptModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved?: (payload: { prompt: string; defaultAiId: string }) => void;
}

export const SchematicReviewPromptModal: React.FC<SchematicReviewPromptModalProps> = ({
  isOpen,
  onClose,
  onSaved,
}) => {
  const [prompt, setPrompt] = useState('');
  const [note, setNote] = useState('');
  const [history, setHistory] = useState<SchematicPromptHistoryItem[]>([]);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [defaultAiId, setDefaultAiId] = useState(DEFAULT_SCHEMATIC_AI_ID);
  const [availableModels, setAvailableModels] = useState<SchematicAiModelOption[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(apiUrl('/api/settings/schematic-review-prompt'), {
        withCredentials: true,
      });
      if (res.data?.success) {
        setPrompt(res.data.prompt || '');
        setDefaultAiId(res.data.default_ai_id || DEFAULT_SCHEMATIC_AI_ID);
        setAvailableModels(res.data.available_ai_models || []);
        setHistory(res.data.history || []);
        const current = (res.data.history || []).find((h: SchematicPromptHistoryItem) => h.is_current);
        setSelectedHistoryId(current?.id ?? null);
      } else {
        setError(res.data?.error || '加载失败');
      }
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? e.response?.data?.error || e.response?.data?.detail || e.message
        : String(e);
      setError(msg || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) void load();
  }, [isOpen, load]);

  const handleSave = async () => {
    if (!prompt.trim()) {
      setError('提示词不能为空');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await axios.put(
        apiUrl('/api/settings/schematic-review-prompt'),
        { prompt: prompt.trim(), note: note.trim(), default_ai_id: defaultAiId },
        { withCredentials: true }
      );
      if (res.data?.success) {
        setPrompt(res.data.prompt || prompt);
        const savedDefault = res.data.default_ai_id || defaultAiId;
        setDefaultAiId(savedDefault);
        setAvailableModels(res.data.available_ai_models || availableModels);
        setHistory(res.data.history || []);
        setNote('');
        const current = (res.data.history || []).find((h: SchematicPromptHistoryItem) => h.is_current);
        setSelectedHistoryId(current?.id ?? null);
        onSaved?.({ prompt: res.data.prompt || prompt, defaultAiId: savedDefault });
      } else {
        setError(res.data?.error || '保存失败');
      }
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? e.response?.data?.error || e.message
        : String(e);
      setError(msg || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleRestore = async (historyId: string) => {
    if (!window.confirm('确定恢复该历史版本为当前提示词？将自动备份当前版本。')) return;
    setRestoringId(historyId);
    setError(null);
    try {
      const res = await axios.post(
        apiUrl(`/api/settings/schematic-review-prompt/restore/${historyId}`),
        {},
        { withCredentials: true }
      );
      if (res.data?.success) {
        setPrompt(res.data.prompt || '');
        setHistory(res.data.history || []);
        const current = (res.data.history || []).find((h: SchematicPromptHistoryItem) => h.is_current);
        setSelectedHistoryId(current?.id ?? null);
        onSaved?.({ prompt: res.data.prompt || '', defaultAiId: res.data.default_ai_id || defaultAiId });
      } else {
        setError(res.data?.error || '恢复失败');
      }
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? e.response?.data?.error || e.message
        : String(e);
      setError(msg || '恢复失败');
    } finally {
      setRestoringId(null);
    }
  };

  const previewHistory = (item: SchematicPromptHistoryItem) => {
    setSelectedHistoryId(item.id);
    setPrompt(item.content);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-5xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div className="flex items-center gap-2">
            <FileText size={20} className="text-sky-600" />
            <h2 className="text-lg font-bold text-gray-800">原理图审核配置</h2>
          </div>
          <button type="button" onClick={onClose} className="p-2 hover:bg-gray-100 rounded-lg">
            <X size={20} />
          </button>
        </div>

        {error && (
          <div className="mx-5 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            {error}
          </div>
        )}

        <div className="flex-1 min-h-0 flex flex-col md:flex-row gap-0 overflow-hidden">
          <div className="flex-1 min-h-0 flex flex-col p-5 border-b md:border-b-0 md:border-r">
            <label className="text-sm font-semibold text-gray-700 mb-2">Step 1–4 默认 AI 模型</label>
            <select
              value={defaultAiId}
              onChange={(e) => setDefaultAiId(e.target.value)}
              disabled={loading || saving}
              className="mb-4 w-full px-3 py-2 border rounded-lg text-sm bg-white"
            >
              {(availableModels.length ? availableModels : [{ id: defaultAiId, name: defaultAiId, description: '' }]).map(
                (m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.description ? ` — ${m.description}` : ''}
                  </option>
                )
              )}
            </select>
            <p className="text-xs text-gray-500 mb-4">
              评审流程（Step 1–4）固定使用该模型；用户导出报告后（Step 5 自由聊天）方可自行切换 AI 伙伴。
            </p>
            <label className="text-sm font-semibold text-gray-700 mb-2">评审提示词</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={loading || saving}
              className="flex-1 min-h-[200px] w-full p-3 border rounded-lg font-mono text-xs leading-relaxed resize-none focus:ring-2 focus:ring-sky-500 focus:outline-none"
              placeholder="输入原理图 AI 评审提示词…"
            />
            <label className="text-sm font-medium text-gray-600 mt-3 mb-1">变更说明（可选）</label>
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={loading || saving}
              className="w-full px-3 py-2 border rounded-lg text-sm"
              placeholder="例如：增加 DDR 接口检查要求"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 border rounded-lg hover:bg-gray-50 text-sm"
              >
                关闭
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={loading || saving || !prompt.trim()}
                className="px-4 py-2 bg-sky-600 text-white rounded-lg hover:bg-sky-700 disabled:bg-gray-300 text-sm flex items-center gap-2"
              >
                <Save size={16} />
                {saving ? '保存中…' : '保存并备份'}
              </button>
            </div>
          </div>

          <div className="w-full md:w-80 flex flex-col min-h-0 bg-gray-50">
            <div className="px-4 py-3 border-b flex items-center gap-2 text-sm font-semibold text-gray-700">
              <History size={16} />
              历史版本
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-2">
              {loading ? (
                <p className="text-sm text-gray-500 p-2">加载中…</p>
              ) : history.length === 0 ? (
                <p className="text-sm text-gray-500 p-2">暂无历史记录，保存后将自动备份。</p>
              ) : (
                history.map((item) => (
                  <div
                    key={item.id}
                    className={`rounded-lg border p-2 text-xs cursor-pointer transition ${
                      selectedHistoryId === item.id
                        ? 'border-sky-400 bg-sky-50'
                        : 'border-gray-200 bg-white hover:border-gray-300'
                    }`}
                    onClick={() => previewHistory(item)}
                  >
                    <div className="flex items-center justify-between gap-1 mb-1">
                      <span className="font-medium text-gray-800 truncate">
                        {item.created_at
                          ? new Date(item.created_at).toLocaleString('zh-CN')
                          : '未知时间'}
                      </span>
                      {item.is_current && (
                        <span className="shrink-0 px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 text-[10px]">
                          当前
                        </span>
                      )}
                    </div>
                    {item.note && <div className="text-gray-500 mb-1">{item.note}</div>}
                    {item.created_by && (
                      <div className="text-gray-400 mb-1">by {item.created_by}</div>
                    )}
                    <div className="text-gray-600 line-clamp-2 font-mono">{item.content}</div>
                    {!item.is_current && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleRestore(item.id);
                        }}
                        disabled={restoringId === item.id}
                        className="mt-2 flex items-center gap-1 text-sky-700 hover:text-sky-900 disabled:opacity-50"
                      >
                        <RotateCcw size={12} />
                        {restoringId === item.id ? '恢复中…' : '恢复此版本'}
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
