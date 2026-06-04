/**
 * 历史记录查询面板
 * 固定在右侧，显示历史对话和网表分析结果
 */
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import { NetlistResultModal } from './NetlistResultModal';
import { NetlistResultsTable } from './NetlistResultsTable';

interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

interface HistoryPanelProps {
  conversationId: string;
  onLoadConversation: (conversationId: string) => void;
}

export const HistoryPanel: React.FC<HistoryPanelProps> = ({
  onLoadConversation
}) => {
  const [activeTab, setActiveTab] = useState<'conversations' | 'netlist'>('conversations');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedConversation, setSelectedConversation] = useState<string | null>(null);
  const [, setShowNetlistTable] = useState(false);
  const [selectedNetlistResult, setSelectedNetlistResult] = useState<{id: string, type: 'comparison' | 'analysis'} | null>(null);

  // 加载对话列表
  useEffect(() => {
    if (activeTab === 'conversations') {
      loadConversations();
    }
  }, [activeTab]);

  const loadConversations = async () => {
    setLoading(true);
    try {
      const response = await axios.get(apiUrl('/api/conversations'));
      if (response.data.success) {
        setConversations(response.data.conversations || []);
      }
    } catch (error) {
      console.error('加载对话列表失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadConversation = async (convId: string) => {
    try {
      const response = await axios.get(apiUrl(`/api/conversations/${convId}/messages`));
      if (response.data.success) {
        onLoadConversation(convId);
        setSelectedConversation(convId);
      }
    } catch (error) {
      console.error('加载对话失败:', error);
      alert('加载对话失败');
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="flex flex-col h-full bg-white border-l">
      {/* 标签页头部 */}
      <div className="flex border-b bg-gray-50">
        <button
          onClick={() => setActiveTab('conversations')}
          className={`flex-1 px-4 py-3 font-semibold transition ${
            activeTab === 'conversations'
              ? 'bg-white border-b-2 border-blue-600 text-blue-600'
              : 'text-gray-600 hover:text-blue-600'
          }`}
        >
          历史对话
        </button>
        <button
          onClick={() => {
            setActiveTab('netlist');
            setShowNetlistTable(true);
          }}
          className={`flex-1 px-4 py-3 font-semibold transition ${
            activeTab === 'netlist'
              ? 'bg-white border-b-2 border-blue-600 text-blue-600'
              : 'text-gray-600 hover:text-blue-600'
          }`}
        >
          网表结果
        </button>
      </div>

      {/* 内容区域 */}
      <div className="flex-1 overflow-auto">
        {activeTab === 'conversations' ? (
          <div className="p-4">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold text-lg">对话列表</h3>
              <button
                onClick={loadConversations}
                className="px-3 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
              >
                刷新
              </button>
            </div>

            {loading ? (
              <div className="flex justify-center items-center h-32">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
              </div>
            ) : conversations.length === 0 ? (
              <div className="text-center text-gray-400 py-8">
                <div className="text-2xl mb-2">📝</div>
                <div>暂无历史对话</div>
              </div>
            ) : (
              <div className="space-y-2">
                {conversations.map((conv) => (
                  <div
                    key={conv.id}
                    onClick={() => handleLoadConversation(conv.id)}
                    className={`p-3 border rounded-lg cursor-pointer transition ${
                      selectedConversation === conv.id
                        ? 'bg-blue-50 border-blue-500'
                        : 'hover:bg-gray-50'
                    }`}
                  >
                    <div className="font-medium text-sm truncate">
                      {conv.title || `对话 ${conv.id.slice(0, 8)}`}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      {formatDate(conv.updated_at)}
                    </div>
                    {conv.message_count !== undefined && (
                      <div className="text-xs text-gray-400 mt-1">
                        {conv.message_count} 条消息
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="h-full overflow-auto">
            <NetlistResultsTable
              isOpen={true}
              onClose={() => {}}
              onViewDetails={(resultId) => {
                // 从结果类型判断
                const resultType = resultId.includes('compare') ? 'comparison' : 'analysis';
                setSelectedNetlistResult({ id: resultId, type: resultType });
              }}
            />
          </div>
        )}
      </div>

      {/* 网表结果详情模态框 */}
      {selectedNetlistResult && (
        <NetlistResultModal
          isOpen={!!selectedNetlistResult}
          onClose={() => setSelectedNetlistResult(null)}
          resultId={selectedNetlistResult.id}
          resultType={selectedNetlistResult.type}
        />
      )}
    </div>
  );
};
