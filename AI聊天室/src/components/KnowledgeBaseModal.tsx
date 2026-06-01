import React, { useState, useRef } from 'react';
import { X, Upload, Plus, Trash2, FileText } from 'lucide-react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';

interface KnowledgeBaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  roleId: string;  // 完整AI ID，如 custom-deepseek-xxx
  roleName: string;
}

interface KnowledgeItem {
  id?: string;
  text: string;
  metadata?: {
    category?: string;
    question?: string;
    answer?: string;
    [key: string]: any;
  };
  image_data?: string;  // Base64编码的图片
  image_path?: string;  // 图片文件路径
  image_type?: string;  // 图片类型
  event_config?: {
    type: string;
    params?: any;
  };
}

export const KnowledgeBaseModal: React.FC<KnowledgeBaseModalProps> = ({
  isOpen,
  onClose,
  roleId,
  roleName,
}) => {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [knowledgeList, setKnowledgeList] = useState<KnowledgeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [enableEvent, setEnableEvent] = useState(false);
  const [eventType, setEventType] = useState('open_sidebar_compare');
  const [eventKeywords, setEventKeywords] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  // 从完整AI ID中提取角色ID
  const extractRoleId = (fullId: string): string => {
    // 巴巴塔直接返回
    if (fullId === 'babata') {
      return 'babata';
    }
    if (!fullId.startsWith('custom-')) {
      return '';
    }
    const withoutPrefix = fullId.substring(7);
    const firstDashIndex = withoutPrefix.indexOf('-');
    if (firstDashIndex === -1) {
      return '';
    }
    return withoutPrefix.substring(firstDashIndex + 1);
  };

  const roleIdForApi = extractRoleId(roleId);

  // 加载知识库内容
  const loadKnowledge = async () => {
    if (!roleIdForApi) return;
    
    try {
      // 获取所有知识（使用空查询）
      const response = await axios.get(
        apiUrl(`/api/custom-ai/${roleIdForApi}/knowledge`),
        {
          params: { query: '', top_k: 100 }
        }
      );
      
      const items: KnowledgeItem[] = [];
      
      // 优先使用qa_pairs（问答对格式）
      if (response.data.qa_pairs && Array.isArray(response.data.qa_pairs)) {
        for (const qa of response.data.qa_pairs) {
          items.push({
            id: qa.id,
            text: `${qa.keywords}|${qa.answer}`,
            metadata: { 
              question: qa.keywords, 
              answer: qa.answer,
              ...qa.metadata 
            },
            image_data: qa.image_data,
            image_path: qa.image_path,
            image_type: qa.image_type,
            event_config: qa.event_config
          });
        }
      }
      
      // 如果没有qa_pairs，尝试从results解析
      if (items.length === 0 && response.data.results && Array.isArray(response.data.results)) {
        for (const text of response.data.results) {
          if (text.includes('|')) {
            const parts = text.split('|', 2);
            if (parts.length === 2) {
              items.push({
                text: `${parts[0]}|${parts[1]}`,
                metadata: { question: parts[0].trim(), answer: parts[1].trim() }
              });
            } else {
              items.push({ text, metadata: {} });
            }
          } else {
            items.push({ text, metadata: {} });
          }
        }
      }
      
      setKnowledgeList(items);
    } catch (error) {
      console.error('加载知识库失败:', error);
      setKnowledgeList([]);
    }
  };
  
  // 删除知识条目
  const handleDeleteKnowledge = async (item: KnowledgeItem) => {
    if (!roleIdForApi) return;
    
    const questionText = item.metadata?.question || (item.text.includes('|') ? item.text.split('|')[0].trim() : '');
    const answerText = item.metadata?.answer || (item.text.includes('|') ? item.text.split('|')[1]?.trim() : '');
    
    if (!questionText && !item.text) {
      alert('无法识别要删除的内容');
      return;
    }
    
    if (!window.confirm('确定要删除这条知识吗？')) {
      return;
    }
    
    try {
      const response = await axios.delete(
        apiUrl(`/api/custom-ai/${roleIdForApi}/knowledge`),
        {
          data: {
            keywords: questionText || item.text,
            answer: answerText || undefined,
            text: questionText ? undefined : item.text
          }
        }
      );
      
      if (response.data.success) {
        alert('删除成功！');
        loadKnowledge(); // 重新加载列表
      } else {
        alert(`删除失败: ${response.data.error || '未知错误'}`);
      }
    } catch (error: any) {
      console.error('删除知识失败:', error);
      alert(`删除失败: ${error.response?.data?.error || error.message}`);
    }
  };

  React.useEffect(() => {
    if (isOpen && roleIdForApi) {
      loadKnowledge();
    }
  }, [isOpen, roleIdForApi]);

  // 将图片文件转换为Base64
  const convertImageToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (event) => {
        const result = event.target?.result;
        if (!result || typeof result !== 'string') {
          reject(new Error('图片读取失败：结果不是字符串'));
          return;
        }
        // 移除data:image/...;base64,前缀，只保留Base64数据
        const parts = result.split(',');
        if (parts.length < 2) {
          reject(new Error('图片格式错误：无法解析Base64数据'));
          return;
        }
        const base64 = parts[1];
        if (!base64 || base64.length === 0) {
          reject(new Error('图片数据为空'));
          return;
        }
        console.log('[图片转换] Base64长度:', base64.length, '文件类型:', file.type);
        resolve(base64);
      };
      reader.onerror = (error) => {
        console.error('[图片转换] 读取错误:', error);
        reject(new Error('图片读取失败'));
      };
      reader.onabort = () => {
        reject(new Error('图片读取被中断'));
      };
      reader.readAsDataURL(file);
    });
  };

  // 处理图片选择
  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) {
      setImageFile(null);
      setImagePreview(null);
      return;
    }

    // 检查文件类型
    if (!file.type.startsWith('image/')) {
      alert('请选择图片文件');
      setImageFile(null);
      setImagePreview(null);
      if (imageInputRef.current) {
        imageInputRef.current.value = '';
      }
      return;
    }

    // 检查文件大小（限制5MB）
    if (file.size > 5 * 1024 * 1024) {
      alert('图片大小不能超过5MB');
      setImageFile(null);
      setImagePreview(null);
      if (imageInputRef.current) {
        imageInputRef.current.value = '';
      }
      return;
    }

    setImageFile(file);
    
    // 创建预览
    const reader = new FileReader();
    reader.onload = (event) => {
      const result = event.target?.result;
      if (result && typeof result === 'string') {
        console.log('[图片预览] 预览URL长度:', result.length);
        console.log('[图片预览] 预览URL前100字符:', result.substring(0, 100));
        setImagePreview(result);
      } else {
        console.error('[图片预览] 读取失败: 结果不是字符串', result);
        alert('图片预览失败，请重试');
        setImageFile(null);
        setImagePreview(null);
        if (imageInputRef.current) {
          imageInputRef.current.value = '';
        }
      }
    };
    reader.onerror = (error) => {
      console.error('[图片预览] 读取错误:', error);
      alert('图片读取失败，请重试');
      setImageFile(null);
      setImagePreview(null);
      if (imageInputRef.current) {
        imageInputRef.current.value = '';
      }
    };
    reader.onabort = () => {
      console.warn('[图片预览] 读取被中断');
      setImageFile(null);
      setImagePreview(null);
    };
    reader.readAsDataURL(file);
  };

  // 手动添加知识（问答对格式，支持图片）或事件触发
  const handleAddManual = async () => {
    if (!roleIdForApi) {
      alert('无效的角色ID');
      return;
    }

    // 检查是否有问答对或事件配置
    const hasQAPair = question.trim() && answer.trim();
    const hasEvent = enableEvent && eventType;
    
    if (!hasQAPair && !hasEvent) {
      alert('请至少填写问答对或启用事件触发');
      return;
    }

    setLoading(true);
    try {
      // 准备请求数据
      const requestData: any = {
        text: '',
        metadata: {}
      };

      // 如果有问答对
      if (hasQAPair) {
        // 使用问答对格式：问题|答案
        requestData.text = `${question.trim()}|${answer.trim()}`;
      } else {
        // 只有事件触发，使用关键词作为问题，答案可以为空或提示信息
        const keywords = eventKeywords.trim() || '事件触发';
        requestData.text = `${keywords}|[事件触发]`;
      }

      // 如果有事件配置
      if (hasEvent) {
        // 将关键词字符串转换为参数对象
        const keywords = eventKeywords.trim().split(/[,，\s]+/).filter(k => k.trim());
        const params: any = {};
        
        // 如果有关键词，添加到参数中
        if (keywords.length > 0) {
          params.keywords = keywords;
        }
        
        // 对于需要额外参数的事件类型，可以在这里添加
        if (eventType === 'open_sidebar_tab') {
          // 从关键词中提取tab名称（如果第一个关键词是tab名称）
          if (keywords.length > 0) {
            const tabMap: { [key: string]: string } = {
              '对比': 'comparison',
              'comparison': 'comparison',
              '解析': 'analysis',
              'analysis': 'analysis',
              '评审': 'review',
              'review': 'review',
              '总结': 'summary',
              'summary': 'summary',
              '检查': 'checklist',
              'checklist': 'checklist',
            };
            const firstKeyword = keywords[0].toLowerCase();
            if (tabMap[firstKeyword]) {
              params.tab = tabMap[firstKeyword];
            }
          }
        }
        
        requestData.event_config = {
          type: eventType,
          params: params
        };
      }

      // 如果有图片，转换为Base64
      if (imageFile) {
        try {
          const base64Image = await convertImageToBase64(imageFile);
          requestData.image_data = base64Image;
          requestData.image_type = imageFile.type;
        } catch (error) {
          console.error('图片转换失败:', error);
          alert('图片处理失败，请重试');
          setLoading(false);
          return;
        }
      }

      const response = await axios.post(
        apiUrl(`/api/custom-ai/${roleIdForApi}/knowledge`),
        requestData
      );

      if (response.data.success) {
        setQuestion('');
        setAnswer('');
        setImageFile(null);
        setImagePreview(null);
        setEnableEvent(false);
        setEventType('open_sidebar_compare');
        setEventKeywords('');
        if (imageInputRef.current) {
          imageInputRef.current.value = '';
        }
        alert('添加成功！');
        loadKnowledge(); // 重新加载列表
      } else {
        alert(`添加失败: ${response.data.error || '未知错误'}`);
      }
    } catch (error: any) {
      console.error('添加知识失败:', error);
      alert(`添加失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 处理文件上传
  const handleFileUpload = async (file: File) => {
    if (!roleIdForApi) {
      alert('无效的角色ID');
      return;
    }

    setUploading(true);
    try {
      const fileContent = await readFileContent(file);
      const knowledgeItems = parseFileContent(fileContent, file.name);

      if (knowledgeItems.length === 0) {
        alert('文件中没有找到有效的知识内容');
        setUploading(false);
        return;
      }

      // 批量添加
      let successCount = 0;
      let failCount = 0;

      for (const item of knowledgeItems) {
        try {
          const response = await axios.post(
            apiUrl(`/api/custom-ai/${roleIdForApi}/knowledge`),
            {
              text: item.text,
              metadata: item.metadata || {}
            }
          );
          if (response.data.success) {
            successCount++;
          } else {
            failCount++;
          }
        } catch (error) {
          failCount++;
        }
      }

      alert(`导入完成：成功 ${successCount} 条，失败 ${failCount} 条`);
      loadKnowledge(); // 重新加载列表
    } catch (error: any) {
      console.error('文件处理失败:', error);
      alert(`文件处理失败: ${error.message}`);
    } finally {
      setUploading(false);
    }
  };

  // 读取文件内容
  const readFileContent = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        resolve(e.target?.result as string);
      };
      reader.onerror = reject;
      reader.readAsText(file, 'UTF-8');
    });
  };

  // 解析文件内容
  const parseFileContent = (content: string, fileName: string): KnowledgeItem[] => {
    const items: KnowledgeItem[] = [];

    if (fileName.endsWith('.json')) {
      // JSON格式
      try {
        const data = JSON.parse(content);
        if (Array.isArray(data)) {
          for (const item of data) {
            if (typeof item === 'string') {
              items.push({ text: item });
            } else if (item.text) {
              items.push({
                text: item.text,
                metadata: item.metadata || {}
              });
            }
          }
        }
      } catch (error) {
        throw new Error('JSON格式错误');
      }
    } else {
      // TXT格式（每行一条）
      const lines = content.split('\n');
      for (const line of lines) {
        const trimmed = line.trim();
        // 跳过空行和注释
        if (trimmed && !trimmed.startsWith('#')) {
          items.push({ text: trimmed });
        }
      }
    }

    return items;
  };

  // 文件选择处理
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // 检查文件类型
    const validTypes = ['.txt', '.json', 'text/plain', 'application/json'];
    const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));
    const isValidType = validTypes.some(type => 
      file.name.toLowerCase().endsWith(type) || file.type.includes(type)
    );

    if (!isValidType) {
      alert('只支持 TXT 和 JSON 文件');
      return;
    }

    // 检查文件大小（限制10MB）
    if (file.size > 10 * 1024 * 1024) {
      alert('文件大小不能超过10MB');
      return;
    }

    handleFileUpload(file);
    
    // 清空文件选择
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold">
            管理知识库 - {roleName}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700"
          >
            <X size={24} />
          </button>
        </div>

        <div className="space-y-6">
          {/* 手动输入 - 问答对格式 */}
          <div>
            <h3 className="text-lg font-semibold mb-3">添加问答对（可选）</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium mb-2">
                  问题（关键词）
                </label>
                <input
                  type="text"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="例如：PCIe 3.0 的带宽"
                  className="w-full px-3 py-2 border rounded-lg"
                />
                <div className="text-xs text-gray-500 mt-1">
                  提示：输入用户可能问到的关键词或问题（可选，如果只配置事件触发可以不填）
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">
                  答案
                </label>
                <textarea
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  placeholder="例如：PCIe 3.0 接口的带宽为 8 GT/s，每个通道提供约 1 GB/s 的带宽"
                  className="w-full px-3 py-2 border rounded-lg"
                  rows={3}
                />
                <div className="text-xs text-gray-500 mt-1">
                  提示：输入完整的答案，巴巴塔会直接返回这个答案（可选，如果只配置事件触发可以不填）
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">
                  图片（可选）
                </label>
                <input
                  ref={imageInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleImageSelect}
                  className="w-full px-3 py-2 border rounded-lg"
                />
                {imagePreview && (
                  <div className="mt-2">
                    <img 
                      src={imagePreview} 
                      alt="预览" 
                      className="max-w-full h-auto max-h-48 rounded-lg border"
                      onError={(e) => {
                        console.error('[图片预览] 图片加载失败:', e);
                        alert('图片预览失败，可能是图片文件损坏');
                        setImageFile(null);
                        setImagePreview(null);
                        if (imageInputRef.current) {
                          imageInputRef.current.value = '';
                        }
                      }}
                      onLoad={() => {
                        console.log('[图片预览] 图片加载成功');
                      }}
                    />
                    <button
                      onClick={() => {
                        setImageFile(null);
                        setImagePreview(null);
                        if (imageInputRef.current) {
                          imageInputRef.current.value = '';
                        }
                      }}
                      className="mt-2 text-sm text-red-500 hover:text-red-700"
                    >
                      移除图片
                    </button>
                  </div>
                )}
                <div className="text-xs text-gray-500 mt-1">
                  支持 JPG、PNG、GIF 等格式，最大 5MB
                </div>
              </div>
              
              {/* 事件触发配置 - 独立功能 */}
              <div className="border-t pt-3">
                <h4 className="text-md font-semibold mb-3">事件触发配置（可选）</h4>
                <div className="flex items-center mb-3">
                  <input
                    type="checkbox"
                    id="enable-event"
                    checked={enableEvent}
                    onChange={(e) => setEnableEvent(e.target.checked)}
                    className="mr-2"
                  />
                  <label htmlFor="enable-event" className="text-sm font-medium">
                    启用事件触发（匹配到关键词时自动执行）
                  </label>
                </div>
                
                {enableEvent && (
                  <div className="space-y-3 pl-6 border-l-2 border-blue-200">
                    <div>
                      <label className="block text-sm font-medium mb-2">
                        触发关键词 <span className="text-red-500">*</span>
                      </label>
                      <input
                        type="text"
                        value={eventKeywords}
                        onChange={(e) => setEventKeywords(e.target.value)}
                        placeholder='例如：原理图对比,网表对比（用逗号或空格分隔）'
                        className="w-full px-3 py-2 border rounded-lg"
                      />
                      <div className="text-xs text-gray-500 mt-1">
                        输入触发事件时匹配的关键词，多个关键词用逗号或空格分隔
                      </div>
                    </div>
                    
                    <div>
                      <label className="block text-sm font-medium mb-2">
                        事件类型 <span className="text-red-500">*</span>
                      </label>
                      <select
                        value={eventType}
                        onChange={(e) => setEventType(e.target.value)}
                        className="w-full px-3 py-2 border rounded-lg"
                      >
                        <option value="open_sidebar_compare">打开对比功能</option>
                        <option value="open_sidebar_analyze">打开解析功能</option>
                        <option value="open_sidebar_review">打开AI评审</option>
                        <option value="open_sidebar_summary">打开评审总结</option>
                        <option value="open_sidebar_checklist">打开待检查项</option>
                        <option value="open_sidebar_tab">打开指定标签页</option>
                        <option value="bom_import">BOM导入</option>
                        <option value="bom_material_match">物料查询（BOM）</option>
                        <option value="bom_cost_calc">BOM成本计算</option>
                        <option value="bom_group_validate">物料替代组验证</option>
                        <option value="bom_replacement_check">替换对检查</option>
                        <option value="material_db_search">物料库物料查询</option>
                        <option value="execute_script">执行后端脚本</option>
                        <option value="send_message">发送消息</option>
                        <option value="call_api">调用API</option>
                        <option value="custom">自定义事件</option>
                      </select>
                    </div>
                  </div>
                )}
              </div>
              
              <button
                onClick={handleAddManual}
                disabled={loading || (!question.trim() && !answer.trim() && !enableEvent)}
                className="w-full px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
              >
                <Plus size={16} />
                <span>{loading ? '添加中...' : '添加'}</span>
              </button>
            </div>
          </div>

          {/* 文件上传 */}
          <div>
            <h3 className="text-lg font-semibold mb-3">批量导入知识</h3>
            <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center">
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.json,text/plain,application/json"
                onChange={handleFileSelect}
                className="hidden"
                id="knowledge-file-input"
              />
              <label
                htmlFor="knowledge-file-input"
                className="cursor-pointer flex flex-col items-center space-y-3"
              >
                <Upload size={32} className="text-gray-400" />
                <div>
                  <span className="text-blue-500 hover:text-blue-600">
                    点击选择文件
                  </span>
                  <span className="text-gray-500"> 或拖拽文件到此处</span>
                </div>
                <div className="text-xs text-gray-400">
                  支持 TXT 和 JSON 格式，最大 10MB
                </div>
              </label>
              {uploading && (
                <div className="mt-4 text-blue-500">
                  正在导入，请稍候...
                </div>
              )}
            </div>

            {/* 文件格式说明 */}
            <div className="mt-4 p-3 bg-gray-50 rounded-lg text-sm">
              <div className="font-semibold mb-2">文件格式说明：</div>
              <div className="space-y-1">
                <div><strong>TXT格式：</strong>每行一个问答对，格式为"问题|答案"，以#开头的行为注释</div>
                <div className="text-xs text-gray-600 mt-1">示例：PCIe 3.0 的带宽|PCIe 3.0 接口的带宽为 8 GT/s</div>
                <div className="mt-2"><strong>JSON格式：</strong>数组格式，每项包含 text（格式为"问题|答案"）和 metadata</div>
              </div>
            </div>
          </div>

          {/* 知识库列表 */}
          {knowledgeList.length > 0 && (
            <div>
              <h3 className="text-lg font-semibold mb-3">
                已有知识 ({knowledgeList.length} 条)
              </h3>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {knowledgeList.map((item, index) => {
                  // 解析问答对格式
                  let questionText = '';
                  let answerText = '';
                  
                  if (item.metadata?.question && item.metadata?.answer) {
                    questionText = item.metadata.question;
                    answerText = item.metadata.answer;
                  } else if (item.text.includes('|')) {
                    const parts = item.text.split('|', 2);
                    questionText = parts[0] || '';
                    answerText = parts[1] || '';
                  } else {
                    questionText = item.text;
                    answerText = '';
                  }
                  
                  // 构建图片URL（Base64或文件路径）
                  const imageUrl = item.image_data 
                    ? `data:${item.image_type || 'image/png'};base64,${item.image_data}`
                    : item.image_path || null;
                  
                  return (
                    <div
                      key={index}
                      className="p-3 bg-gray-50 rounded-lg flex items-start justify-between group hover:bg-gray-100 transition"
                    >
                      <div className="flex-1">
                        <div className="text-sm font-semibold text-blue-600 mb-1">
                          问：{questionText}
                        </div>
                        {answerText && (
                          <div className="text-sm text-gray-700 mt-1">
                            答：{answerText}
                          </div>
                        )}
                        {!answerText && (
                          <div className="text-sm text-gray-500 mt-1 italic">
                            {item.text}
                          </div>
                        )}
                        {imageUrl && (
                          <div className="mt-2">
                            <img 
                              src={imageUrl} 
                              alt="知识库图片" 
                              className="max-w-full h-auto max-h-48 rounded-lg border"
                            />
                          </div>
                        )}
                      </div>
                      <button
                        onClick={() => handleDeleteKnowledge(item)}
                        className="ml-3 p-1.5 text-red-500 hover:bg-red-100 rounded-full transition opacity-0 group-hover:opacity-100"
                        title="删除此条目"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end space-x-2 mt-6">
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

