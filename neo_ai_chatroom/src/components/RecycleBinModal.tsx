import React, { useState, useEffect } from 'react';
import { X, Trash2, RotateCcw } from 'lucide-react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';

interface RecycleBinItem {
  id: string;
  original_role_id: string;
  original_role_name: string;
  knowledge_type: string;
  knowledge_path: string;
  deleted_at: string;
}

interface RecycleBinModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRestore?: () => void;
}

export const RecycleBinModal: React.FC<RecycleBinModalProps> = ({
  isOpen,
  onClose,
  onRestore,
}) => {
  const [items, setItems] = useState<RecycleBinItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [restoreTargetRoleId, setRestoreTargetRoleId] = useState<string>('');
  const [availableRoles, setAvailableRoles] = useState<Array<{id: string, name: string}>>([]);

  useEffect(() => {
    if (isOpen) {
      loadRecycleBin();
      loadAvailableRoles();
    }
  }, [isOpen]);

  const loadRecycleBin = async () => {
    setLoading(true);
    try {
      const response = await axios.get(apiUrl('/api/recycle-bin'));
      setItems(response.data.items || []);
    } catch (error) {
      console.error('加载回收站失败:', error);
      alert('加载回收站失败');
    } finally {
      setLoading(false);
    }
  };

  const loadAvailableRoles = async () => {
    try {
      const response = await axios.get(apiUrl('/api/ais'));
      const customRoles = (response.data.ais || [])
        .filter((ai: any) => ai.isCustom)
        .map((ai: any) => {
          // 从 custom-{base_ai}-{role_id} 格式中提取 role_id
          const parts = ai.id.split('-');
          if (parts.length >= 3) {
            return {
              id: parts.slice(2).join('-'),
              name: ai.name
            };
          }
          return null;
        })
        .filter((r: any) => r !== null);
      setAvailableRoles(customRoles);
    } catch (error) {
      console.error('加载角色列表失败:', error);
    }
  };

  const handleRestore = async (knowledgeId: string) => {
    if (!restoreTargetRoleId) {
      alert('请选择要恢复到的角色');
      return;
    }

    if (!window.confirm('确定要将此知识库恢复到选定的角色吗？')) {
      return;
    }

    setRestoringId(knowledgeId);
    try {
      await axios.post(apiUrl(`/api/recycle-bin/${knowledgeId}/restore`), {
        role_id: restoreTargetRoleId
      });
      alert('恢复成功！');
      loadRecycleBin();
      if (onRestore) {
        onRestore();
      }
    } catch (error: any) {
      console.error('恢复失败:', error);
      alert(`恢复失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setRestoringId(null);
      setRestoreTargetRoleId('');
    }
  };

  const handlePermanentDelete = async (knowledgeId: string) => {
    if (!window.confirm('确定要永久删除此知识库吗？此操作不可恢复！')) {
      return;
    }

    setDeletingId(knowledgeId);
    try {
      await axios.delete(apiUrl(`/api/recycle-bin/${knowledgeId}`));
      alert('删除成功！');
      loadRecycleBin();
    } catch (error: any) {
      console.error('删除失败:', error);
      alert(`删除失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setDeletingId(null);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-4xl max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold">知识回收站</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700"
          >
            <X size={24} />
          </button>
        </div>

        {loading ? (
          <div className="text-center py-8">加载中...</div>
        ) : items.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            回收站为空
          </div>
        ) : (
          <div className="space-y-4">
            {items.map((item) => (
              <div
                key={item.id}
                className="border rounded-lg p-4 hover:bg-gray-50"
              >
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="font-medium text-lg">
                      {item.original_role_name}
                    </div>
                    <div className="text-sm text-gray-500 mt-1">
                      原角色ID: {item.original_role_id}
                    </div>
                    <div className="text-sm text-gray-500">
                      知识库类型: {item.knowledge_type === 'simple' ? '简单知识库' : '向量知识库'}
                    </div>
                    <div className="text-sm text-gray-500">
                      删除时间: {new Date(item.deleted_at).toLocaleString('zh-CN')}
                    </div>
                  </div>
                  <div className="flex space-x-2">
                    <div className="flex flex-col space-y-2">
                      <select
                        value={restoreTargetRoleId}
                        onChange={(e) => setRestoreTargetRoleId(e.target.value)}
                        className="px-3 py-1 border rounded text-sm"
                        disabled={restoringId === item.id}
                      >
                        <option value="">选择恢复到的角色</option>
                        {availableRoles.map((role) => (
                          <option key={role.id} value={role.id}>
                            {role.name}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => handleRestore(item.id)}
                        disabled={!restoreTargetRoleId || restoringId === item.id}
                        className="px-3 py-1 bg-blue-500 text-white rounded text-sm hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center space-x-1"
                      >
                        <RotateCcw size={14} />
                        <span>恢复</span>
                      </button>
                    </div>
                    <button
                      onClick={() => handlePermanentDelete(item.id)}
                      disabled={deletingId === item.id}
                      className="px-3 py-1 bg-red-500 text-white rounded text-sm hover:bg-red-600 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center space-x-1"
                    >
                      <Trash2 size={14} />
                      <span>永久删除</span>
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 border rounded-lg hover:bg-gray-50"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
};

