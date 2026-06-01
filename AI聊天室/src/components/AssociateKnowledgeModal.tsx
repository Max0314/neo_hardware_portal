import React, { useState, useEffect } from 'react';
import { X, Link2, Trash2 } from 'lucide-react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';

interface KnowledgeItem {
  id: string;
  original_role_id: string;
  original_role_name: string;
  knowledge_type: string;
  knowledge_path: string;
  deleted_at: string;
}

interface AssociateKnowledgeModalProps {
  isOpen: boolean;
  onClose: () => void;
  roleId: string;  // 完整AI ID，如 custom-deepseek-xxx
  roleName: string;
  onAssociate?: () => void;
}

export const AssociateKnowledgeModal: React.FC<AssociateKnowledgeModalProps> = ({
  isOpen,
  onClose,
  roleId,
  roleName,
  onAssociate,
}) => {
  const [recycleBinItems, setRecycleBinItems] = useState<KnowledgeItem[]>([]);
  const [associatedItems, setAssociatedItems] = useState<KnowledgeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [associatingId, setAssociatingId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && roleId) {
      loadData();
    }
  }, [isOpen, roleId]);

  const extractRoleId = (fullId: string): string => {
    // 从 custom-{base_ai}-{role_id} 格式中提取 role_id
    const parts = fullId.split('-');
    if (parts.length >= 3) {
      return parts.slice(2).join('-');
    }
    return '';
  };

  const loadData = async () => {
    setLoading(true);
    const roleIdForApi = extractRoleId(roleId);
    
    try {
      // 加载回收站中的知识库
      const recycleResponse = await axios.get(apiUrl('/api/recycle-bin'));
      setRecycleBinItems(recycleResponse.data.items || []);

      // 加载已关联的知识库
      if (roleIdForApi) {
        const associateResponse = await axios.get(
          apiUrl(`/api/custom-ai/${roleIdForApi}/associated-knowledge`)
        );
        setAssociatedItems(associateResponse.data.knowledge_bases || []);
      }
    } catch (error) {
      console.error('加载数据失败:', error);
      alert('加载数据失败');
    } finally {
      setLoading(false);
    }
  };

  const handleAssociate = async (knowledgeId: string) => {
    const roleIdForApi = extractRoleId(roleId);
    if (!roleIdForApi) {
      alert('无效的角色ID');
      return;
    }

    setAssociatingId(knowledgeId);
    try {
      await axios.post(
        apiUrl(`/api/custom-ai/${roleIdForApi}/associate-knowledge`),
        { knowledge_id: knowledgeId }
      );
      alert('关联成功！');
      loadData();
      if (onAssociate) {
        onAssociate();
      }
    } catch (error: any) {
      console.error('关联失败:', error);
      alert(`关联失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setAssociatingId(null);
    }
  };

  const handleRemoveAssociation = async (knowledgeId: string) => {
    if (!window.confirm('确定要取消关联此知识库吗？')) {
      return;
    }

    const roleIdForApi = extractRoleId(roleId);
    if (!roleIdForApi) {
      alert('无效的角色ID');
      return;
    }

    setRemovingId(knowledgeId);
    try {
      await axios.delete(
        apiUrl(`/api/custom-ai/${roleIdForApi}/associated-knowledge/${knowledgeId}`)
      );
      alert('取消关联成功！');
      loadData();
      if (onAssociate) {
        onAssociate();
      }
    } catch (error: any) {
      console.error('取消关联失败:', error);
      alert(`取消关联失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setRemovingId(null);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-4xl max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold">关联知识库 - {roleName}</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700"
          >
            <X size={24} />
          </button>
        </div>

        {loading ? (
          <div className="text-center py-8">加载中...</div>
        ) : (
          <div className="space-y-6">
            {/* 已关联的知识库 */}
            <div>
              <h3 className="font-medium text-lg mb-3">已关联的知识库</h3>
              {associatedItems.length === 0 ? (
                <div className="text-center py-4 text-gray-500 border rounded-lg">
                  暂无关联的知识库
                </div>
              ) : (
                <div className="space-y-2">
                  {associatedItems.map((item) => (
                    <div
                      key={item.id}
                      className="border rounded-lg p-3 flex justify-between items-center hover:bg-gray-50"
                    >
                      <div>
                        <div className="font-medium">{item.original_role_name}</div>
                        <div className="text-sm text-gray-500">
                          {item.knowledge_type === 'simple' ? '简单知识库' : '向量知识库'}
                        </div>
                      </div>
                      <button
                        onClick={() => handleRemoveAssociation(item.id)}
                        disabled={removingId === item.id}
                        className="px-3 py-1 bg-red-500 text-white rounded text-sm hover:bg-red-600 disabled:bg-gray-300"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 可关联的知识库（回收站中的） */}
            <div>
              <h3 className="font-medium text-lg mb-3">可关联的知识库（来自回收站）</h3>
              {recycleBinItems.length === 0 ? (
                <div className="text-center py-4 text-gray-500 border rounded-lg">
                  回收站中没有可关联的知识库
                </div>
              ) : (
                <div className="space-y-2">
                  {recycleBinItems
                    .filter(item => !associatedItems.some(assoc => assoc.id === item.id))
                    .map((item) => (
                      <div
                        key={item.id}
                        className="border rounded-lg p-3 flex justify-between items-center hover:bg-gray-50"
                      >
                        <div>
                          <div className="font-medium">{item.original_role_name}</div>
                          <div className="text-sm text-gray-500">
                            {item.knowledge_type === 'simple' ? '简单知识库' : '向量知识库'}
                          </div>
                          <div className="text-xs text-gray-400">
                            删除时间: {new Date(item.deleted_at).toLocaleString('zh-CN')}
                          </div>
                        </div>
                        <button
                          onClick={() => handleAssociate(item.id)}
                          disabled={associatingId === item.id}
                          className="px-3 py-1 bg-blue-500 text-white rounded text-sm hover:bg-blue-600 disabled:bg-gray-300 flex items-center space-x-1"
                        >
                          <Link2 size={14} />
                          <span>关联</span>
                        </button>
                      </div>
                    ))}
                </div>
              )}
            </div>
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

