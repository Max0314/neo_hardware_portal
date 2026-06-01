/**
 * 网表分析结果列表表格组件
 * 类似todo collection.html的表格展示
 */
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import { NetlistResultModal } from './NetlistResultModal';

interface NetlistResult {
  id: string;
  type: 'comparison' | 'analysis';
  netlist1_name?: string;
  netlist2_name?: string;
  netlist_name?: string;
  created_at: string;
}

export const NetlistResultsTable: React.FC<{
  isOpen: boolean;
  onClose?: () => void;
  onViewDetails?: (resultId: string) => void;
  isModal?: boolean; // 明确指定是否是模态框模式
}> = ({ isOpen, onClose, onViewDetails, isModal: isModalProp }) => {
  const [results, setResults] = useState<NetlistResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedResult, setSelectedResult] = useState<{ id: string; type: 'comparison' | 'analysis' } | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadResults();
    }
  }, [isOpen]);

  const loadResults = async () => {
    setLoading(true);
    try {
      const response = await axios.get(apiUrl('/api/netlist/results'));
      if (response.data.success) {
        setResults(response.data.results);
      }
    } catch (error) {
      console.error('加载结果列表失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const deleteResult = async (resultId: string) => {
    if (!confirm('确定要删除这个结果吗？')) return;
    
    try {
      await axios.delete(apiUrl(`/api/netlist/result/${resultId}`));
      loadResults();
    } catch (error) {
      console.error('删除失败:', error);
      alert('删除失败');
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN');
  };

  if (!isOpen) return null;

  // 判断是否在模态框中显示（明确指定或通过onClose判断）
  const isModal = isModalProp !== undefined ? isModalProp : !!onClose;

  const content = (
    <>
      {/* 头部 */}
      {isModal && (
        <div className="bg-gradient-to-r from-blue-600 to-blue-800 text-white p-6 flex justify-between items-center">
          <h2 className="text-2xl font-bold">网表分析结果列表</h2>
          {onClose && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (onClose) onClose();
              }}
              className="text-white hover:bg-white hover:bg-opacity-20 rounded-full p-2 transition"
            >
              ✕
            </button>
          )}
        </div>
      )}

      {/* 内容区域 */}
      <div className={`${isModal ? 'flex-1 overflow-auto p-6' : 'p-6'}`}>
            {loading ? (
              <div className="flex justify-center items-center h-64">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
              </div>
            ) : results.length === 0 ? (
              <div className="text-center text-gray-500 py-12">
                暂无结果
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      <th className="px-4 py-3 text-left border-b font-semibold">类型</th>
                      <th className="px-4 py-3 text-left border-b font-semibold">名称</th>
                      <th className="px-4 py-3 text-left border-b font-semibold">创建时间</th>
                      <th className="px-4 py-3 text-left border-b font-semibold">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((result) => (
                      <tr
                        key={result.id}
                        className="hover:bg-gray-50 cursor-pointer"
                        onClick={() => setSelectedResult({ id: result.id, type: result.type })}
                      >
                        <td className="px-4 py-3 border-b">
                          <span
                            className={`px-2 py-1 rounded text-sm font-medium ${
                              result.type === 'comparison'
                                ? 'bg-blue-100 text-blue-800'
                                : 'bg-green-100 text-green-800'
                            }`}
                          >
                            {result.type === 'comparison' ? '对比' : '分析'}
                          </span>
                        </td>
                        <td className="px-4 py-3 border-b">
                          {result.type === 'comparison'
                            ? `${result.netlist1_name} vs ${result.netlist2_name}`
                            : result.netlist_name || '网表'}
                        </td>
                        <td className="px-4 py-3 border-b text-sm text-gray-600">
                          {formatDate(result.created_at)}
                        </td>
                        <td className="px-4 py-3 border-b">
                          <div className="flex space-x-2">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                if (onViewDetails) {
                                  onViewDetails(result.id);
                                } else {
                                  setSelectedResult({ id: result.id, type: result.type });
                                }
                              }}
                              className="text-blue-600 hover:underline text-sm"
                            >
                              查看
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                deleteResult(result.id);
                              }}
                              className="text-red-600 hover:underline text-sm"
                            >
                              删除
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
    </>
  );

  // 如果是模态框模式，包装在遮罩层中
  if (isModal) {
    return (
      <>
        <div 
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          onClick={(e) => {
            // 点击遮罩层关闭
            if (e.target === e.currentTarget && onClose) {
              onClose();
            }
          }}
        >
          <div 
            className="bg-white rounded-lg shadow-xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {content}
          </div>
        </div>

        {/* 结果详情模态框 */}
        {selectedResult && (
          <NetlistResultModal
            isOpen={!!selectedResult}
            onClose={() => setSelectedResult(null)}
            resultId={selectedResult.id}
            resultType={selectedResult.type}
          />
        )}
      </>
    );
  }

  // 直接显示内容（用于右侧面板）
  return (
    <>
      <div className="flex flex-col h-full">
        {/* 头部 */}
        <div className="p-6 border-b bg-gradient-to-r from-blue-600 to-blue-800 text-white flex-shrink-0">
          <h2 className="text-2xl font-bold">网表分析结果</h2>
          <p className="text-sm opacity-90 mt-1">查看所有网表对比和分析结果</p>
        </div>
        <div className="flex-1 overflow-auto">
          {content}
        </div>
      </div>

      {/* 结果详情模态框 */}
      {selectedResult && (
        <NetlistResultModal
          isOpen={!!selectedResult}
          onClose={() => setSelectedResult(null)}
          resultId={selectedResult.id}
          resultType={selectedResult.type}
        />
      )}
    </>
  );
};
