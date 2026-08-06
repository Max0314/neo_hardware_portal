import React, { useState } from 'react';
import { X } from 'lucide-react';

interface CustomAIModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (config: {
    name: string;
    avatar: string;
    baseAI: string;
    rolePrompt: string;
    description: string;
  }) => void;
}

const baseAIOptions = [
  { id: 'deepseek', name: 'DeepSeek', avatar: '🧠' },
  { id: 'bailian-deepseekv4', name: 'TokenPlan-deepseek-v4-pro', avatar: '🔮' },
  { id: 'bailian-deepseekv4flash', name: 'TokenPlan-deepseek-v4-flash', avatar: '⚡' },
  { id: 'bailian-deepseekv32', name: 'TokenPlan-deepseek-v3.2', avatar: '🧠' },
  { id: 'bailian-qwen37plus', name: 'TokenPlan-qwen3.7-plus', avatar: '🌟' },
  { id: 'bailian-qwen37max', name: 'TokenPlan-qwen3.7-max', avatar: '✨' },
  { id: 'bailian-qwen36plus', name: 'TokenPlan-qwen3.6-plus', avatar: '🚀' },
  { id: 'bailian-qwen36flash', name: 'TokenPlan-qwen3.6-flash', avatar: '💨' },
  { id: 'bailian-kimik27code', name: 'TokenPlan-kimi-k2.7-code', avatar: '💻' },
  { id: 'bailian-kimik26', name: 'TokenPlan-kimi-k2.6', avatar: '🌙' },
  { id: 'bailian-kimik25', name: 'TokenPlan-kimi-k2.5', avatar: '🌙' },
  { id: 'bailian-glm52', name: 'TokenPlan-glm-5.2', avatar: '🔷' },
  { id: 'bailian-glm51', name: 'TokenPlan-glm-5.1', avatar: '🔹' },
  { id: 'bailian-glm5', name: 'TokenPlan-glm-5', avatar: '💠' },
  { id: 'bailian-minimaxm25', name: 'TokenPlan-MiniMax-M2.5', avatar: '🎵' },
  { id: 'doubao', name: '豆包 SEED Mini', avatar: '🔥' },
  { id: 'gpt-4', name: 'ChatGPT', avatar: '🤖' },
  { id: 'claude-3', name: 'Claude', avatar: '👽' },
];

const roleTemplates = [
  {
    name: '秘书助手',
    prompt: '你是一位专业、高效的秘书助手。你擅长整理信息、安排日程、处理文档，总是以礼貌、专业的方式回复。',
    avatar: '📋'
  },
  {
    name: '硬件专家',
    prompt: '你是一位资深的硬件工程师和专家。你精通各种计算机硬件、电子设备、电路设计，能够提供专业的技术建议和解决方案。',
    avatar: '🔧'
  },
  {
    name: '编程导师',
    prompt: '你是一位经验丰富的编程导师。你擅长解释编程概念、代码审查、调试问题，能够用清晰易懂的方式教学。',
    avatar: '💻'
  },
  {
    name: '产品经理',
    prompt: '你是一位资深的产品经理。你擅长需求分析、产品规划、用户体验设计，能够从用户和商业角度思考问题。',
    avatar: '📊'
  },
];

export const CustomAIModal: React.FC<CustomAIModalProps> = ({
  isOpen,
  onClose,
  onSave,
}) => {
  const [name, setName] = useState('');
  const [avatar, setAvatar] = useState('🤖');
  const [baseAI, setBaseAI] = useState('deepseek');
  const [rolePrompt, setRolePrompt] = useState('');
  const [description, setDescription] = useState('');

  if (!isOpen) return null;

  const handleTemplateClick = (template: typeof roleTemplates[0]) => {
    setName(template.name);
    setAvatar(template.avatar);
    setRolePrompt(template.prompt);
    setDescription(template.name);
  };

  const handleSave = () => {
    if (!name || !rolePrompt) {
      alert('请填写名称和角色设定');
      return;
    }
    onSave({ name, avatar, baseAI, rolePrompt, description });
    // 重置表单
    setName('');
    setAvatar('🤖');
    setBaseAI('deepseek');
    setRolePrompt('');
    setDescription('');
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold">创建自定义AI角色</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700"
          >
            <X size={24} />
          </button>
        </div>

        <div className="space-y-4">
          {/* 快速模板 */}
          <div>
            <label className="block text-sm font-medium mb-2">快速模板</label>
            <div className="grid grid-cols-2 gap-2">
              {roleTemplates.map((template, index) => (
                <button
                  key={index}
                  onClick={() => handleTemplateClick(template)}
                  className="p-3 border rounded-lg hover:bg-gray-50 text-left"
                >
                  <div className="flex items-center space-x-2">
                    <span className="text-2xl">{template.avatar}</span>
                    <span className="font-medium">{template.name}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* 角色名称 */}
          <div>
            <label className="block text-sm font-medium mb-2">
              角色名称 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：我的秘书"
              className="w-full px-3 py-2 border rounded-lg"
            />
          </div>

          {/* 头像 */}
          <div>
            <label className="block text-sm font-medium mb-2">头像（Emoji）</label>
            <input
              type="text"
              value={avatar}
              onChange={(e) => setAvatar(e.target.value)}
              placeholder="🤖"
              className="w-full px-3 py-2 border rounded-lg"
              maxLength={2}
            />
          </div>

          {/* 基础AI */}
          <div>
            <label className="block text-sm font-medium mb-2">
              基础AI <span className="text-red-500">*</span>
            </label>
            <select
              value={baseAI}
              onChange={(e) => setBaseAI(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg"
            >
              {baseAIOptions.map(ai => (
                <option key={ai.id} value={ai.id}>
                  {ai.avatar} {ai.name}
                </option>
              ))}
            </select>
          </div>

          {/* 角色设定 */}
          <div>
            <label className="block text-sm font-medium mb-2">
              角色设定（System Prompt）<span className="text-red-500">*</span>
            </label>
            <textarea
              value={rolePrompt}
              onChange={(e) => setRolePrompt(e.target.value)}
              placeholder="描述这个AI的角色、能力和行为特点..."
              className="w-full px-3 py-2 border rounded-lg"
              rows={4}
            />
            <p className="text-xs text-gray-500 mt-1">
              这个设定会影响AI的回复风格和专业领域
            </p>
          </div>

          {/* 描述 */}
          <div>
            <label className="block text-sm font-medium mb-2">描述（可选）</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简短描述这个AI的用途"
              className="w-full px-3 py-2 border rounded-lg"
            />
          </div>
        </div>

        <div className="flex justify-end space-x-2 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 border rounded-lg hover:bg-gray-50"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
          >
            创建
          </button>
        </div>
      </div>
    </div>
  );
};

