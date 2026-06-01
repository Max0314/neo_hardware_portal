/**
 * 历史记录下拉菜单组件
 * 显示在右上角
 */
import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import { History } from 'lucide-react';

interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

interface HistoryDropdownProps {
  onLoadConversation: (conversationId: string) => void;
}

export const HistoryDropdown: React.FC<HistoryDropdownProps> = ({
  onLoadConversation
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      loadConversations();
    }
  }, [isOpen]);

  // 点击外部关闭
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

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
        setIsOpen(false);
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
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="p-2 hover:bg-gray-100 rounded-lg transition"
        title="历史记录"
      >
        <History size={20} className="text-gray-600" />
      </button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-white border border-gray-200 rounded-lg shadow-xl z-50 max-h-96 overflow-hidden flex flex-col">
          {/* 头部 */}
          <div className="p-4 border-b bg-gray-50 flex justify-between items-center">
            <h3 className="font-semibold text-lg">历史对话</h3>
            <button
              onClick={loadConversations}
              className="px-2 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              刷新
            </button>
          </div>

          {/* 内容区域 */}
          <div className="flex-1 overflow-y-auto">
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
              <div className="p-2 space-y-2">
                {conversations.map((conv) => (
                  <div
                    key={conv.id}
                    onClick={() => handleLoadConversation(conv.id)}
                    className="p-3 border rounded-lg cursor-pointer transition hover:bg-blue-50 hover:border-blue-300"
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
        </div>
      )}
    </div>
  );
};
