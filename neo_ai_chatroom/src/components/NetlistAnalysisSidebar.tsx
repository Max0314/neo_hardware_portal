/**
 * 网表分析侧边栏组件
 * 支持上传文件或粘贴内容进行网表对比和分析
 */
import React, { useState, useRef } from 'react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';
import { NetlistResultModal } from './NetlistResultModal';

interface NetlistAnalysisSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  mode: 'compare' | 'analyze'; // 对比模式或分析模式
}

export const NetlistAnalysisSidebar: React.FC<NetlistAnalysisSidebarProps> = ({
  isOpen,
  onClose,
  mode
}) => {
  const [netlist1, setNetlist1] = useState('');
  const [netlist2, setNetlist2] = useState('');
  const [netlist, setNetlist] = useState('');
  const [netlist1Name, setNetlist1Name] = useState('网表1');
  const [netlist2Name, setNetlist2Name] = useState('网表2');
  const [netlistName, setNetlistName] = useState('网表');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ id: string; type: 'comparison' | 'analysis' } | null>(null);
  const fileInput1Ref = useRef<HTMLInputElement>(null);
  const fileInput2Ref = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (file: File, setter: (content: string) => void, setName?: (name: string) => void) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      setter(content);
      if (setName) {
        setName(file.name.replace(/\.(asc|txt)$/i, ''));
      }
    };
    reader.onerror = () => {
      alert('文件读取失败');
    };
    reader.readAsText(file, 'UTF-8');
  };

  const handleCompare = async () => {
    if (!netlist1.trim() || !netlist2.trim()) {
      alert('请提供两个网表内容');
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(apiUrl('/api/netlist/compare'), {
        netlist1: netlist1,
        netlist2: netlist2,
        netlist1_name: netlist1Name,
        netlist2_name: netlist2Name
      });

      if (response.data.success) {
        setResult({ id: response.data.result_id, type: 'comparison' });
      } else {
        alert(`对比失败: ${response.data.error}`);
      }
    } catch (error: any) {
      console.error('对比失败:', error);
      alert(`对比失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyze = async () => {
    if (!netlist.trim()) {
      alert('请提供网表内容');
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(apiUrl('/api/netlist/analyze'), {
        netlist: netlist,
        netlist_name: netlistName
      });

      if (response.data.success) {
        setResult({ id: response.data.result_id, type: 'analysis' });
      } else {
        alert(`分析失败: ${response.data.error}`);
      }
    } catch (error: any) {
      console.error('分析失败:', error);
      alert(`分析失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setNetlist1('');
    setNetlist2('');
    setNetlist('');
    setNetlist1Name('网表1');
    setNetlist2Name('网表2');
    setNetlistName('网表');
    setResult(null);
  };

  if (!isOpen) return null;

  return (
    <>
      {/* 遮罩层 */}
      <div
        className="fixed inset-0 bg-black bg-opacity-50 z-40"
        onClick={onClose}
      />

      {/* 侧边栏 */}
      <div className="fixed right-0 top-0 h-full w-full max-w-4xl bg-white shadow-2xl z-50 flex flex-col">
        {/* 头部 */}
        <div className="bg-gradient-to-r from-blue-600 to-blue-800 text-white p-6 flex justify-between items-center">
          <div>
            <h2 className="text-2xl font-bold">
              {mode === 'compare' ? '网表对比' : '网表分析'}
            </h2>
            <p className="text-sm opacity-90 mt-1">
              {mode === 'compare' ? '上传或粘贴两个网表文件进行对比' : '上传或粘贴网表文件进行分析'}
            </p>
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
          {mode === 'compare' ? (
            <div className="space-y-6">
              {/* 网表1 */}
              <div className="border rounded-lg p-4">
                <div className="flex justify-between items-center mb-3">
                  <label className="font-semibold text-lg">网表 1</label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={netlist1Name}
                      onChange={(e) => setNetlist1Name(e.target.value)}
                      placeholder="网表名称"
                      className="px-3 py-1 border rounded text-sm"
                    />
                    <input
                      type="file"
                      ref={fileInput1Ref}
                      accept=".asc,.txt"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) {
                          handleFileUpload(file, setNetlist1, setNetlist1Name);
                        }
                      }}
                      className="hidden"
                    />
                    <button
                      onClick={() => fileInput1Ref.current?.click()}
                      className="px-3 py-1 bg-blue-500 text-white rounded text-sm hover:bg-blue-600"
                    >
                      上传文件
                    </button>
                  </div>
                </div>
                <textarea
                  value={netlist1}
                  onChange={(e) => setNetlist1(e.target.value)}
                  placeholder="粘贴第一个网表内容，或点击上传文件..."
                  className="w-full h-64 p-3 border rounded font-mono text-sm resize-none"
                />
              </div>

              {/* 网表2 */}
              <div className="border rounded-lg p-4">
                <div className="flex justify-between items-center mb-3">
                  <label className="font-semibold text-lg">网表 2</label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={netlist2Name}
                      onChange={(e) => setNetlist2Name(e.target.value)}
                      placeholder="网表名称"
                      className="px-3 py-1 border rounded text-sm"
                    />
                    <input
                      type="file"
                      ref={fileInput2Ref}
                      accept=".asc,.txt"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) {
                          handleFileUpload(file, setNetlist2, setNetlist2Name);
                        }
                      }}
                      className="hidden"
                    />
                    <button
                      onClick={() => fileInput2Ref.current?.click()}
                      className="px-3 py-1 bg-blue-500 text-white rounded text-sm hover:bg-blue-600"
                    >
                      上传文件
                    </button>
                  </div>
                </div>
                <textarea
                  value={netlist2}
                  onChange={(e) => setNetlist2(e.target.value)}
                  placeholder="粘贴第二个网表内容，或点击上传文件..."
                  className="w-full h-64 p-3 border rounded font-mono text-sm resize-none"
                />
              </div>
            </div>
          ) : (
            <div className="border rounded-lg p-4">
              <div className="flex justify-between items-center mb-3">
                <label className="font-semibold text-lg">网表内容</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={netlistName}
                    onChange={(e) => setNetlistName(e.target.value)}
                    placeholder="网表名称"
                    className="px-3 py-1 border rounded text-sm"
                  />
                  <input
                    type="file"
                    ref={fileInputRef}
                    accept=".asc,.txt"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        handleFileUpload(file, setNetlist, setNetlistName);
                      }
                    }}
                    className="hidden"
                  />
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="px-3 py-1 bg-blue-500 text-white rounded text-sm hover:bg-blue-600"
                  >
                    上传文件
                  </button>
                </div>
              </div>
              <textarea
                value={netlist}
                onChange={(e) => setNetlist(e.target.value)}
                placeholder="粘贴网表内容，或点击上传文件..."
                className="w-full h-96 p-3 border rounded font-mono text-sm resize-none"
              />
            </div>
          )}
        </div>

        {/* 底部操作栏 */}
        <div className="border-t p-4 bg-gray-50 flex justify-between items-center">
          <button
            onClick={handleClear}
            className="px-4 py-2 bg-gray-500 text-white rounded hover:bg-gray-600 transition"
          >
            清空
          </button>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 bg-gray-300 text-gray-700 rounded hover:bg-gray-400 transition"
            >
              取消
            </button>
            <button
              onClick={mode === 'compare' ? handleCompare : handleAnalyze}
              disabled={loading || (mode === 'compare' ? (!netlist1 || !netlist2) : !netlist)}
              className="px-6 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              {loading ? '处理中...' : mode === 'compare' ? '开始对比' : '开始分析'}
            </button>
          </div>
        </div>
      </div>

      {/* 结果详情模态框 */}
      {result && (
        <NetlistResultModal
          isOpen={!!result}
          onClose={() => setResult(null)}
          resultId={result.id}
          resultType={result.type}
        />
      )}
    </>
  );
};
