import React, { useState, useEffect } from 'react';
import { X, Trash2, Edit2, Save } from 'lucide-react';
import axios from 'axios';
import { apiUrl } from '@/utils/apiBase';

interface EventTriggerModalProps {
  isOpen: boolean;
  onClose: () => void;
  roleId: string;  // 完整AI ID，如 custom-deepseek-xxx 或 babata
  roleName: string;
}

/** 最大 Token 单次用量级别（从小到大） */
export const MAX_TOKENS_LEVELS = [
  { value: 2048, label: '2K（短回复）' },
  { value: 4096, label: '4K（中等）' },
  { value: 8192, label: '8K（较长）' },
  { value: 16384, label: '16K（长回复）' },
  { value: 32768, label: '32K' },
  { value: 65536, label: '64K' },
  { value: 131072, label: '128K' },
] as const;

interface EventTrigger {
  id?: string;
  keywords: string;
  eventType: string;
  eventParams?: any;
}

export const EventTriggerModal: React.FC<EventTriggerModalProps> = ({
  isOpen,
  onClose,
  roleId,
  roleName,
}) => {
  const [triggers, setTriggers] = useState<EventTrigger[]>([]);
  const [loading, setLoading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const baseAIId = (() => {
    if (roleId.startsWith('custom-')) {
      const parts = roleId.split('-', 3);
      return parts[1] || roleId;
    }
    return roleId;
  })();

  // 不同模型/供应商的 max_tokens 上限可能不同；DeepSeek 当前接入端点最大 8192
  const maxTokensLimit =
    baseAIId === 'deepseek' ||
    baseAIId === 'doubao' ||
    baseAIId?.startsWith('bailian-')
      ? 8192
      : 131072;
  const [aiList, setAiList] = useState<Array<{ id: string; name: string }>>([]);
  const [formData, setFormData] = useState<EventTrigger>({
    keywords: '',
    eventType: 'open_sidebar_compare',
    eventParams: { max_tokens: 8192 }
  });

  const effectiveMaxTokens =
    typeof formData.eventParams?.max_tokens === 'number'
      ? Math.min(Math.max(formData.eventParams.max_tokens, 1), maxTokensLimit)
      : Math.min(8192, maxTokensLimit);

  // 从完整AI ID中提取角色ID
  const extractRoleId = (fullId: string): string => {
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

  // 加载事件触发配置
  const loadTriggers = async () => {
    if (!roleIdForApi) return;
    
    try {
      setLoading(true);
      const response = await axios.get(
        apiUrl(`/api/custom-ai/${roleIdForApi}/knowledge`),
        {
          params: { query: '', top_k: 100 }
        }
      );
      
      const eventTriggers: EventTrigger[] = [];
      
      // 从知识库中提取有事件配置的条目
      if (response.data.qa_pairs && Array.isArray(response.data.qa_pairs)) {
        for (const qa of response.data.qa_pairs) {
          if (qa.event_config) {
            const keywords = qa.event_config.params?.keywords || [qa.keywords];
            const keywordsStr = Array.isArray(keywords) ? keywords.join(', ') : keywords;
            
            eventTriggers.push({
              id: qa.id,
              keywords: keywordsStr,
              eventType: qa.event_config.type,
              eventParams: { max_tokens: 8192, ...(qa.event_config.params || {}) }
            });
          }
        }
      }
      
      setTriggers(eventTriggers);
    } catch (error: any) {
      console.error('加载事件触发配置失败:', error);
      alert(`加载失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen && roleIdForApi) {
      loadTriggers();
    }
  }, [isOpen, roleIdForApi]);

  useEffect(() => {
    if (isOpen) {
      axios.get(apiUrl('/api/ais')).then((res) => {
        const list = (res.data.ais || []).map((ai: any) => ({ id: ai.id, name: ai.name }));
        setAiList(list);
      }).catch(() => setAiList([]));
    }
  }, [isOpen]);

  // 保存事件触发配置
  const handleSave = async () => {
    if (!formData.keywords.trim()) {
      alert('请输入触发关键词');
      return;
    }
    if (formData.eventType === 'prompt_review_chat' && !(formData.eventParams?.prompt ?? '').trim()) {
      alert('审核提示词对话需填写提示词内容');
      return;
    }

    if (!roleIdForApi) {
      alert('无效的角色ID');
      return;
    }

    setLoading(true);
    try {
      // 将关键词字符串转换为数组
      const keywords = formData.keywords.trim().split(/[,，\s]+/).filter(k => k.trim());
      const params: any = {
        keywords: keywords,
        max_tokens: formData.eventParams?.max_tokens ?? 8192
      };

      // 对于需要额外参数的事件类型
      if (formData.eventType === 'open_sidebar_tab') {
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
        const firstKeyword = keywords[0]?.toLowerCase();
        if (firstKeyword && tabMap[firstKeyword]) {
          params.tab = tabMap[firstKeyword];
        }
      }
      if (formData.eventType === 'prompt_review_chat') {
        params.prompt = (formData.eventParams?.prompt ?? '').trim();
      }
      const defaultAi = formData.eventParams?.default_response_ai;
      if (Array.isArray(defaultAi) && defaultAi.length > 0) {
        params.default_response_ai = defaultAi;
      }

      // 使用第一个关键词作为主关键词，答案使用默认值
      const mainKeyword = keywords[0] || '事件触发';
      const qaText = `${mainKeyword}|[事件触发]`;

      const requestData: any = {
        text: qaText,
        metadata: {},
        event_config: {
          type: formData.eventType,
          params: params
        }
      };

      const response = await axios.post(
        apiUrl(`/api/custom-ai/${roleIdForApi}/knowledge`),
        requestData
      );

      if (response.data.success) {
        setFormData({
          keywords: '',
          eventType: 'open_sidebar_compare',
          eventParams: { max_tokens: 8192 }
        });
        setEditingId(null);
        alert('添加成功！');
        loadTriggers();
      } else {
        alert(`添加失败: ${response.data.error || '未知错误'}`);
      }
    } catch (error: any) {
      console.error('保存事件触发配置失败:', error);
      alert(`保存失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 删除事件触发配置
  const handleDelete = async (trigger: EventTrigger) => {
    if (!confirm(`确定要删除事件触发配置"${trigger.keywords}"吗？`)) {
      return;
    }

    if (!roleIdForApi) {
      alert('无法删除：缺少角色ID');
      return;
    }

    setLoading(true);
    try {
      // 通过删除知识库条目来删除事件触发配置
      // 需要先获取该条目的完整信息
      const response = await axios.get(
        apiUrl(`/api/custom-ai/${roleIdForApi}/knowledge`),
        {
          params: { query: '', top_k: 100 }
        }
      );

      if (response.data.qa_pairs) {
        // 如果有ID，优先使用ID查找
        let qa = null;
        if (trigger.id) {
          qa = response.data.qa_pairs.find((qa: any) => qa.id === trigger.id);
        }
        
        // 如果通过ID找不到，尝试通过关键词和事件配置匹配
        if (!qa) {
          qa = response.data.qa_pairs.find((qa: any) => {
            if (!qa.event_config) return false;
            const qaKeywords = qa.event_config.params?.keywords || [];
            const triggerKeywords = trigger.keywords.split(/[,，\s]+/).map(k => k.trim());
            // 检查是否有共同的关键词
            return qaKeywords.some((k: string) => triggerKeywords.includes(k)) ||
                   qa.keywords === triggerKeywords[0];
          });
        }
        
        if (qa) {
          // 调用删除API，优先使用ID
          const deleteData: any = {};
          if (qa.id) {
            deleteData.id = qa.id;
          } else {
            deleteData.keywords = qa.keywords;
            deleteData.answer = qa.answer || '[事件触发]';
          }
          
          const deleteResponse = await axios.delete(
            apiUrl(`/api/custom-ai/${roleIdForApi}/knowledge`),
            {
              data: deleteData
            }
          );

          if (deleteResponse.data.success) {
            alert('删除成功！');
            loadTriggers();
          } else {
            alert(`删除失败: ${deleteResponse.data.error || '未知错误'}`);
          }
        } else {
          alert('未找到要删除的事件触发配置');
        }
      } else {
        alert('无法获取知识库数据');
      }
    } catch (error: any) {
      console.error('删除事件触发配置失败:', error);
      alert(`删除失败: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 开始编辑
  const handleEdit = (trigger: EventTrigger) => {
    setFormData({
      keywords: trigger.keywords,
      eventType: trigger.eventType,
      eventParams: trigger.eventParams || {}
    });
    setEditingId(trigger.id || null);
  };

  // 取消编辑
  const handleCancelEdit = () => {
    setFormData({
      keywords: '',
      eventType: 'open_sidebar_compare',
      eventParams: { max_tokens: 8192 }
    });
    setEditingId(null);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold">
            事件触发管理 - {roleName}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700"
          >
            <X size={24} />
          </button>
        </div>

        <div className="space-y-6">
          {/* 添加/编辑表单 */}
          <div className="border rounded-lg p-4 bg-gray-50">
            <h3 className="text-lg font-semibold mb-3">
              {editingId ? '编辑事件触发' : '添加事件触发'}
            </h3>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium mb-2">
                  触发关键词 <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={formData.keywords}
                  onChange={(e) => setFormData({ ...formData, keywords: e.target.value })}
                  placeholder="例如：原理图对比,网表对比（用逗号或空格分隔）"
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
                  value={formData.eventType}
                  onChange={(e) => setFormData({ ...formData, eventType: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg"
                >
                  <option value="open_sidebar_compare">打开对比功能</option>
                  <option value="open_sidebar_analyze">打开解析功能</option>
                  <option value="open_sidebar_review">打开AI评审</option>
                  <option value="open_sidebar_summary">打开评审总结</option>
                  <option value="open_sidebar_checklist">打开待检查项</option>
                  <option value="open_sidebar_tab">打开指定标签页</option>
                  <option value="open_game_tetris">打开俄罗斯方块游戏</option>
                  <option value="aggregate_review_summary">硬件分析结果聚合</option>
                  <option value="prompt_review_chat">审核提示词对话</option>
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

              <div>
                <label className="block text-sm font-medium mb-2">
                  最大 Token 单次用量
                </label>
                <select
                  value={effectiveMaxTokens}
                  onChange={(e) => {
                    const raw = parseInt(e.target.value, 10);
                    const next = Math.min(Math.max(raw, 1), maxTokensLimit);
                    setFormData({
                      ...formData,
                      eventParams: { ...(formData.eventParams || {}), max_tokens: next }
                    });
                  }}
                  className="w-full px-3 py-2 border rounded-lg"
                >
                  {MAX_TOKENS_LEVELS.map(({ value, label }) => {
                    const disabled = value > maxTokensLimit;
                    return (
                      <option key={value} value={value} disabled={disabled}>
                        {disabled ? `${label}（该模型上限 ${maxTokensLimit}）` : label}
                      </option>
                    );
                  })}
                </select>
                <div className="text-xs text-gray-500 mt-1">
                  控制 AI 单次回复的最大 token 数，避免过长回复中途截断
                </div>
              </div>

              {formData.eventType === 'prompt_review_chat' && (
                <div>
                  <label className="block text-sm font-medium mb-2">
                    提示词内容 <span className="text-red-500">*</span>
                  </label>
                  <textarea
                    value={formData.eventParams?.prompt ?? ''}
                    onChange={(e) => setFormData({
                      ...formData,
                      eventParams: { ...(formData.eventParams || {}), prompt: e.target.value }
                    })}
                    placeholder="输入触发后自动加在用户内容前的提示词（例如：网表分析规则、评审要求等）"
                    className="w-full px-3 py-2 border rounded-lg min-h-[120px] resize-y"
                    rows={5}
                  />
                  <div className="text-xs text-gray-500 mt-1">
                    触发该事件后会弹出输入框与文件上传，用户输入或上传的内容将自动拼接在此提示词后发送给 AI
                  </div>
                </div>
              )}

              <div>
                <label className="block text-sm font-medium mb-2">默认回复角色</label>
                <p className="text-xs text-gray-500 mb-2">
                  勾选后，触发该事件时由所选角色回复；不勾选则由当前活跃的、匹配度最高的 AI 回答。
                </p>
                <div className="flex flex-wrap gap-3">
                  {aiList.map((ai) => {
                    const checked = (formData.eventParams?.default_response_ai as string[] | undefined)?.includes(ai.id) ?? false;
                    return (
                      <label key={ai.id} className="inline-flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const prev = (formData.eventParams?.default_response_ai as string[] | undefined) || [];
                            const next = e.target.checked
                              ? [...prev, ai.id]
                              : prev.filter((id) => id !== ai.id);
                            setFormData({
                              ...formData,
                              eventParams: { ...(formData.eventParams || {}), default_response_ai: next }
                            });
                          }}
                          className="rounded border-gray-300"
                        />
                        <span className="text-sm">{ai.name}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              <div className="flex space-x-2">
                <button
                  onClick={editingId ? handleSave : handleSave}
                  disabled={loading || !formData.keywords.trim()}
                  className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
                >
                  <Save size={16} />
                  <span>{loading ? '保存中...' : (editingId ? '更新' : '添加')}</span>
                </button>
                {editingId && (
                  <button
                    onClick={handleCancelEdit}
                    className="px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400"
                  >
                    取消
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* 事件触发列表 */}
          <div>
            <h3 className="text-lg font-semibold mb-3">已有事件触发配置</h3>
            {loading && triggers.length === 0 ? (
              <div className="text-center py-8 text-gray-500">加载中...</div>
            ) : triggers.length === 0 ? (
              <div className="text-center py-8 text-gray-500">暂无事件触发配置</div>
            ) : (
              <div className="space-y-2">
                {triggers.map((trigger) => (
                  <div
                    key={trigger.id}
                    className="border rounded-lg p-4 flex items-center justify-between hover:bg-gray-50"
                  >
                    <div className="flex-1">
                      <div className="font-medium text-gray-900">
                        {trigger.keywords}
                      </div>
                      <div className="text-sm text-gray-500 mt-1">
                        事件类型: {
                          trigger.eventType === 'open_sidebar_compare' ? '打开对比功能' :
                          trigger.eventType === 'open_sidebar_analyze' ? '打开解析功能' :
                          trigger.eventType === 'open_sidebar_review' ? '打开AI评审' :
                          trigger.eventType === 'open_sidebar_summary' ? '打开评审总结' :
                          trigger.eventType === 'open_sidebar_checklist' ? '打开待检查项' :
                          trigger.eventType === 'open_sidebar_tab' ? '打开指定标签页' :
                          trigger.eventType === 'open_game_tetris' ? '打开俄罗斯方块游戏' :
                          trigger.eventType === 'aggregate_review_summary' ? '硬件分析结果聚合' :
                          trigger.eventType === 'prompt_review_chat' ? '审核提示词对话' :
                          trigger.eventType === 'bom_import' ? 'BOM导入' :
                          trigger.eventType === 'bom_material_match' ? '物料查询（BOM）' :
                          trigger.eventType === 'bom_cost_calc' ? 'BOM成本计算' :
                          trigger.eventType === 'bom_group_validate' ? '物料替代组验证' :
                          trigger.eventType === 'bom_replacement_check' ? '替换对检查' :
                          trigger.eventType === 'material_db_search' ? '物料库物料查询' :
                          trigger.eventType === 'execute_script' ? '执行后端脚本' :
                          trigger.eventType === 'send_message' ? '发送消息' :
                          trigger.eventType === 'call_api' ? '调用API' :
                          trigger.eventType === 'custom' ? '自定义事件' :
                          trigger.eventType
                        }
                      </div>
                      {typeof trigger.eventParams?.max_tokens === 'number' && (
                        <div className="text-xs text-gray-500 mt-0.5">
                          最大 Token: {trigger.eventParams.max_tokens >= 1000 ? `${trigger.eventParams.max_tokens / 1000}K` : trigger.eventParams.max_tokens}
                        </div>
                      )}
                      {Array.isArray(trigger.eventParams?.default_response_ai) && trigger.eventParams.default_response_ai.length > 0 && (
                        <div className="text-xs text-blue-600 mt-0.5">
                          默认回复: {trigger.eventParams.default_response_ai.map((id: string) => aiList.find(a => a.id === id)?.name || id).join('、')}
                        </div>
                      )}
                    </div>
                    <div className="flex space-x-2">
                      <button
                        onClick={() => handleEdit(trigger)}
                        className="p-2 text-blue-500 hover:bg-blue-50 rounded-lg"
                        title="编辑"
                      >
                        <Edit2 size={18} />
                      </button>
                      <button
                        onClick={() => handleDelete(trigger)}
                        className="p-2 text-red-500 hover:bg-red-50 rounded-lg"
                        title="删除"
                      >
                        <Trash2 size={18} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
