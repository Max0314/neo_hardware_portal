import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { X, History, Clock, ChevronRight } from 'lucide-react';
import {
  getSchematicReviewHistory,
  listSchematicReviewHistory,
  type SchematicReviewHistoryRecord,
  type SchematicReviewHistorySummary,
} from '@/utils/schematicReviewHistory';

interface SchematicReviewHistoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (record: SchematicReviewHistoryRecord) => void;
}

export const SchematicReviewHistoryModal: React.FC<SchematicReviewHistoryModalProps> = ({
  isOpen,
  onClose,
  onSelect,
}) => {
  const [records, setRecords] = useState<SchematicReviewHistorySummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRecords(await listSchematicReviewHistory());
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? e.response?.data?.error || e.message
        : e instanceof Error
          ? e.message
          : String(e);
      setError(msg || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) void load();
  }, [isOpen, load]);

  const handleSelect = async (id: string) => {
    setLoadingId(id);
    setError(null);
    try {
      const record = await getSchematicReviewHistory(id);
      onSelect(record);
      onClose();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg || '打开记录失败');
    } finally {
      setLoadingId(null);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div className="flex items-center gap-2">
            <History size={20} className="text-sky-600" />
            <h2 className="text-lg font-bold text-gray-800">评审历史记录</h2>
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

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading ? (
            <p className="text-sm text-gray-500 p-4 text-center">加载中…</p>
          ) : records.length === 0 ? (
            <p className="text-sm text-gray-500 p-4 text-center">
              暂无历史记录。完成 Step 4 导出报告后将自动保存。
            </p>
          ) : (
            records.map((r) => (
              <button
                key={r.id}
                type="button"
                disabled={loadingId === r.id}
                onClick={() => void handleSelect(r.id)}
                className="w-full text-left rounded-lg border border-gray-200 hover:border-sky-300 hover:bg-sky-50/50 p-3 transition disabled:opacity-60"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold text-gray-800 truncate">{r.title}</div>
                    <div className="flex items-center gap-1 text-[11px] text-gray-500 mt-1">
                      <Clock size={12} />
                      {r.created_at
                        ? new Date(r.created_at).toLocaleString('zh-CN')
                        : '未知时间'}
                    </div>
                    <div className="flex gap-2 mt-2 text-[11px] font-medium">
                      <span className="text-emerald-700">PASS {r.summary_pass}</span>
                      <span className="text-red-700">WARNING {r.summary_warning}</span>
                      <span className="text-sky-700">INFO {r.summary_info}</span>
                    </div>
                  </div>
                  <ChevronRight size={18} className="text-gray-400 shrink-0 mt-1" />
                </div>
              </button>
            ))
          )}
        </div>

        <div className="px-5 py-3 border-t flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 border rounded-lg hover:bg-gray-50 text-sm"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
};
