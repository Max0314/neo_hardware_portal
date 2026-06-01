/**
 * 网表分析结果展示组件
 * 用于显示对比差异表格和分析结果表格
 */
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';

interface NetlistResultModalProps {
  isOpen: boolean;
  onClose: () => void;
  resultId?: string;
  resultType?: 'comparison' | 'analysis';
}

interface ComparisonResult {
  added_components: string[];
  removed_components: string[];
  changed_components: string[];
  added_nets: string[];
  removed_nets: string[];
  changed_nets: string[];
  components1: Record<string, any>;
  components2: Record<string, any>;
  nets1: Record<string, string[]>;
  nets2: Record<string, string[]>;
}

interface AnalysisResult {
  summary: {
    total_components: number;
    total_nets: number;
    component_types: Record<string, number>;
    power_nets: string[];
    differential_pairs: Array<{ positive: string; negative: string; base_name: string }>;
    interface_nets: Record<string, string[]>;
  };
  components: Array<{
    id: string;
    type: string;
    value: string;
    package: string;
    voltage_rating?: string;
    tolerance?: string;
    temp_tolerance?: string;
    pins: Record<string, string>;
  }>;
  nets: Array<{
    name: string;
    connections: string[];
    connection_count: number;
    type: string;
  }>;
  analysis: {
    component_analysis: any;
    net_analysis: any;
    potential_issues: Array<{
      type: string;
      component?: string;
      net?: string;
      severity: string;
      description: string;
    }>;
  };
}

export const NetlistResultModal: React.FC<NetlistResultModalProps> = ({
  isOpen,
  onClose,
  resultId,
  resultType: propResultType
}) => {
  const [loading, setLoading] = useState(false);
  const [comparisonData, setComparisonData] = useState<ComparisonResult | null>(null);
  const [analysisData, setAnalysisData] = useState<AnalysisResult | null>(null);
  const [activeTab, setActiveTab] = useState<'components' | 'nets' | 'details'>('components');
  const [showSame, setShowSame] = useState(false);
  const [detectedType, setDetectedType] = useState<'comparison' | 'analysis' | undefined>(propResultType);

  useEffect(() => {
    if (isOpen && resultId) {
      loadResult();
    }
  }, [isOpen, resultId]);

  const loadResult = async () => {
    if (!resultId) return;
    
    setLoading(true);
    try {
      const response = await axios.get(apiUrl(`/api/netlist/result/${resultId}`));
      if (response.data.success) {
        const data = response.data.data;
        if (data.type === 'comparison') {
          setComparisonData(data.result);
          setDetectedType('comparison');
        } else if (data.type === 'analysis') {
          setAnalysisData(data.result);
          setDetectedType('analysis');
        }
      }
    } catch (error) {
      console.error('加载结果失败:', error);
      alert('加载结果失败');
    } finally {
      setLoading(false);
    }
  };

  const currentResultType = propResultType || detectedType;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-7xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* 头部 */}
        <div className="bg-gradient-to-r from-blue-600 to-blue-800 text-white p-6 flex justify-between items-center">
          <div>
            <h2 className="text-2xl font-bold">
              {currentResultType === 'comparison' ? '网表对比结果' : '网表分析结果'}
            </h2>
            {resultId && <p className="text-sm opacity-90 mt-1">结果ID: {resultId}</p>}
          </div>
          <button
            onClick={onClose}
            className="text-white hover:bg-white hover:bg-opacity-20 rounded-full p-2 transition"
          >
            ✕
          </button>
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-auto p-6">
          {loading ? (
            <div className="flex justify-center items-center h-64">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
            </div>
          ) : currentResultType === 'comparison' && comparisonData ? (
            <ComparisonView data={comparisonData} activeTab={activeTab} setActiveTab={setActiveTab} showSame={showSame} setShowSame={setShowSame} />
          ) : currentResultType === 'analysis' && analysisData ? (
            <AnalysisView data={analysisData} />
          ) : (
            <div className="text-center text-gray-500 py-12">
              暂无数据
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// 对比视图组件
const ComparisonView: React.FC<{
  data: ComparisonResult;
  activeTab: string;
  setActiveTab: (tab: 'components' | 'nets' | 'details') => void;
  showSame: boolean;
  setShowSame: (show: boolean) => void;
}> = ({ data, activeTab, setActiveTab, showSame, setShowSame }) => {
  // 统计信息
  const stats = {
    total1: Object.keys(data.components1).length,
    total2: Object.keys(data.components2).length,
    added: data.added_components.length,
    removed: data.removed_components.length,
    changed: data.changed_components.length,
    addedNets: data.added_nets.length,
    removedNets: data.removed_nets.length,
    changedNets: data.changed_nets.length,
  };

  return (
    <div>
      {/* 统计摘要 */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-blue-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-600">{stats.total1}</div>
          <div className="text-sm text-gray-600">网表1元件总数</div>
        </div>
        <div className="bg-blue-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-600">{stats.total2}</div>
          <div className="text-sm text-gray-600">网表2元件总数</div>
        </div>
        <div className="bg-green-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-green-600">{stats.added}</div>
          <div className="text-sm text-gray-600">新增元件</div>
        </div>
        <div className="bg-red-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-red-600">{stats.removed}</div>
          <div className="text-sm text-gray-600">移除元件</div>
        </div>
      </div>

      {/* 标签页 */}
      <div className="border-b mb-4">
        <div className="flex space-x-4">
          <button
            onClick={() => setActiveTab('components')}
            className={`px-4 py-2 font-semibold ${
              activeTab === 'components'
                ? 'border-b-2 border-blue-600 text-blue-600'
                : 'text-gray-600 hover:text-blue-600'
            }`}
          >
            元件差异
          </button>
          <button
            onClick={() => setActiveTab('nets')}
            className={`px-4 py-2 font-semibold ${
              activeTab === 'nets'
                ? 'border-b-2 border-blue-600 text-blue-600'
                : 'text-gray-600 hover:text-blue-600'
            }`}
          >
            网络连接差异
          </button>
        </div>
      </div>

      {/* 元件差异表格 */}
      {activeTab === 'components' && (
        <div className="grid grid-cols-2 gap-6">
          <div>
            <div className="flex justify-between items-center mb-2">
              <h3 className="font-semibold">网表1的元件</h3>
              <button
                onClick={() => setShowSame(!showSame)}
                className="text-sm text-blue-600 hover:underline"
              >
                {showSame ? '隐藏' : '显示'}相同元件
              </button>
            </div>
            <div className="border rounded-lg overflow-auto max-h-96">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-2 text-left">元件</th>
                    <th className="px-3 py-2 text-left">类型</th>
                    <th className="px-3 py-2 text-left">值</th>
                    <th className="px-3 py-2 text-left">封装</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.components1).map(([id, comp]) => {
                    const isRemoved = data.removed_components.includes(id);
                    const isChanged = data.changed_components.includes(id);
                    const isSame = !isRemoved && !isChanged;
                    
                    if (!showSame && isSame) return null;
                    
                    return (
                      <tr
                        key={id}
                        className={`${
                          isRemoved
                            ? 'bg-red-50'
                            : isChanged
                            ? 'bg-yellow-50'
                            : 'bg-gray-50'
                        }`}
                      >
                        <td className="px-3 py-2">{id}</td>
                        <td className="px-3 py-2">{comp.type}</td>
                        <td className="px-3 py-2">{comp.value}</td>
                        <td className="px-3 py-2">{comp.package}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <div className="flex justify-between items-center mb-2">
              <h3 className="font-semibold">网表2的元件</h3>
              <button
                onClick={() => setShowSame(!showSame)}
                className="text-sm text-blue-600 hover:underline"
              >
                {showSame ? '隐藏' : '显示'}相同元件
              </button>
            </div>
            <div className="border rounded-lg overflow-auto max-h-96">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-2 text-left">元件</th>
                    <th className="px-3 py-2 text-left">类型</th>
                    <th className="px-3 py-2 text-left">值</th>
                    <th className="px-3 py-2 text-left">封装</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.components2).map(([id, comp]) => {
                    const isAdded = data.added_components.includes(id);
                    const isChanged = data.changed_components.includes(id);
                    const isSame = !isAdded && !isChanged;
                    
                    if (!showSame && isSame) return null;
                    
                    return (
                      <tr
                        key={id}
                        className={`${
                          isAdded
                            ? 'bg-green-50'
                            : isChanged
                            ? 'bg-yellow-50'
                            : 'bg-gray-50'
                        }`}
                      >
                        <td className="px-3 py-2">{id}</td>
                        <td className="px-3 py-2">{comp.type}</td>
                        <td className="px-3 py-2">{comp.value}</td>
                        <td className="px-3 py-2">{comp.package}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 网络差异表格 */}
      {activeTab === 'nets' && (
        <div className="grid grid-cols-2 gap-6">
          <div>
            <h3 className="font-semibold mb-2">网表1的网络连接</h3>
            <div className="border rounded-lg overflow-auto max-h-96">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-2 text-left">网络</th>
                    <th className="px-3 py-2 text-left">连接元件</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.nets1).map(([net, conns]) => {
                    const isRemoved = data.removed_nets.includes(net);
                    const isChanged = data.changed_nets.includes(net);
                    const isSame = !isRemoved && !isChanged;
                    
                    if (!showSame && isSame) return null;
                    
                    return (
                      <tr
                        key={net}
                        className={`${
                          isRemoved
                            ? 'bg-red-50'
                            : isChanged
                            ? 'bg-yellow-50'
                            : 'bg-gray-50'
                        }`}
                      >
                        <td className="px-3 py-2 font-medium">{net}</td>
                        <td className="px-3 py-2">{conns.join(', ')}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <h3 className="font-semibold mb-2">网表2的网络连接</h3>
            <div className="border rounded-lg overflow-auto max-h-96">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-2 text-left">网络</th>
                    <th className="px-3 py-2 text-left">连接元件</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.nets2).map(([net, conns]) => {
                    const isAdded = data.added_nets.includes(net);
                    const isChanged = data.changed_nets.includes(net);
                    const isSame = !isAdded && !isChanged;
                    
                    if (!showSame && isSame) return null;
                    
                    return (
                      <tr
                        key={net}
                        className={`${
                          isAdded
                            ? 'bg-green-50'
                            : isChanged
                            ? 'bg-yellow-50'
                            : 'bg-gray-50'
                        }`}
                      >
                        <td className="px-3 py-2 font-medium">{net}</td>
                        <td className="px-3 py-2">{conns.join(', ')}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// 分析视图组件
const AnalysisView: React.FC<{ data: AnalysisResult }> = ({ data }) => {
  return (
    <div>
      {/* 统计摘要 */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-blue-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-600">{data.summary.total_components}</div>
          <div className="text-sm text-gray-600">总元件数</div>
        </div>
        <div className="bg-blue-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-blue-600">{data.summary.total_nets}</div>
          <div className="text-sm text-gray-600">总网络数</div>
        </div>
        <div className="bg-green-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-green-600">{data.summary.power_nets.length}</div>
          <div className="text-sm text-gray-600">电源网络</div>
        </div>
        <div className="bg-purple-50 p-4 rounded-lg text-center">
          <div className="text-2xl font-bold text-purple-600">{data.summary.differential_pairs.length}</div>
          <div className="text-sm text-gray-600">差分对</div>
        </div>
      </div>

      {/* 元件类型统计 */}
      <div className="mb-6">
        <h3 className="font-semibold mb-2">元件类型统计</h3>
        <div className="flex flex-wrap gap-2">
          {Object.entries(data.summary.component_types).map(([type, count]) => (
            <span key={type} className="bg-gray-100 px-3 py-1 rounded">
              {type}: {count}
            </span>
          ))}
        </div>
      </div>

      {/* 元件列表表格 */}
      <div className="mb-6">
        <h3 className="font-semibold mb-2">元件列表</h3>
        <div className="border rounded-lg overflow-auto max-h-96">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-3 py-2 text-left">元件</th>
                <th className="px-3 py-2 text-left">类型</th>
                <th className="px-3 py-2 text-left">值</th>
                <th className="px-3 py-2 text-left">封装</th>
                <th className="px-3 py-2 text-left">耐压</th>
                <th className="px-3 py-2 text-left">精度</th>
              </tr>
            </thead>
            <tbody>
              {data.components.map((comp) => (
                <tr key={comp.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">{comp.id}</td>
                  <td className="px-3 py-2">{comp.type}</td>
                  <td className="px-3 py-2">{comp.value}</td>
                  <td className="px-3 py-2">{comp.package}</td>
                  <td className="px-3 py-2">{comp.voltage_rating || '-'}</td>
                  <td className="px-3 py-2">{comp.tolerance || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 潜在问题 */}
      {data.analysis.potential_issues.length > 0 && (
        <div className="mb-6">
          <h3 className="font-semibold mb-2">潜在问题</h3>
          <div className="space-y-2">
            {data.analysis.potential_issues.map((issue, idx) => (
              <div
                key={idx}
                className={`p-3 rounded ${
                  issue.severity === 'high'
                    ? 'bg-red-50 border-l-4 border-red-500'
                    : issue.severity === 'medium'
                    ? 'bg-yellow-50 border-l-4 border-yellow-500'
                    : 'bg-blue-50 border-l-4 border-blue-500'
                }`}
              >
                <div className="font-medium">{issue.description}</div>
                {issue.component && (
                  <div className="text-sm text-gray-600 mt-1">元件: {issue.component}</div>
                )}
                {issue.net && (
                  <div className="text-sm text-gray-600 mt-1">网络: {issue.net}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
