import React, { useState, useEffect } from 'react';
import { ListOrdered, X } from 'lucide-react';
import { getEventFlows, addSOP, type EventFlowForSOP } from '@/utils/sopStorage';

interface BuildSOPModalProps {
  onClose: () => void;
  onSaved: () => void;
}

export function BuildSOPModal({ onClose, onSaved }: BuildSOPModalProps) {
  const [flows, setFlows] = useState<EventFlowForSOP[]>([]);
  const [selectedFlowId, setSelectedFlowId] = useState<string>('');
  const [sopName, setSopName] = useState('');

  useEffect(() => {
    setFlows(getEventFlows());
  }, []);

  const selectedFlow = flows.find((f) => f.id === selectedFlowId);

  const handleSubmit = () => {
    const name = sopName.trim() || selectedFlow?.name || '未命名 SOP';
    if (!selectedFlowId || !selectedFlow) return;
    addSOP({
      name,
      eventFlowId: selectedFlow.id,
      eventFlowName: selectedFlow.name,
    });
    onSaved();
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-xl max-w-md w-full max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-semibold text-gray-800 flex items-center gap-2">
            <ListOrdered size={20} />
            构建 SOP
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="p-2 text-gray-500 hover:bg-gray-100 rounded-lg transition"
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>
        <p className="text-sm text-gray-500 px-4 pt-2">
          选择AI工作室中已创建的事件流，命名后将作为 SOP 默认添加到主页，可在主页点击进入。
        </p>
        <div className="p-4 space-y-4 flex-1 overflow-y-auto">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">选择事件流</label>
            {flows.length === 0 ? (
              <div className="text-sm text-gray-500 py-4 border border-dashed border-gray-200 rounded-lg text-center">
                暂无事件流，请先在左侧创建并保存事件流后再构建 SOP。
              </div>
            ) : (
              <select
                value={selectedFlowId}
                onChange={(e) => setSelectedFlowId(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="">请选择…</option>
                {flows.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}（{f.steps.length} 步）
                  </option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">SOP 名称（显示在主页）</label>
            <input
              type="text"
              value={sopName}
              onChange={(e) => setSopName(e.target.value)}
              placeholder={selectedFlow ? selectedFlow.name : '输入名称'}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 p-4 border-t bg-gray-50 rounded-b-xl">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-100 transition text-sm"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!selectedFlowId || !selectedFlow}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition text-sm font-medium"
          >
            确定并添加至主页
          </button>
        </div>
      </div>
    </div>
  );
}
