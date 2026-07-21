import React, { useState } from 'react';
import { AIConfig } from '@/types';
import { ChevronDown, Check, Trash2, BookOpen, Zap } from 'lucide-react';

interface AISelectorProps {
  ais: AIConfig[];
  onChange: (ai: AIConfig[]) => void;
  onDelete?: (aiId: string) => void;
  onManageKnowledge?: (aiId: string, aiName: string) => void;
  onManageEventTrigger?: (aiId: string, aiName: string) => void;
  /** 锁定选择（原理图审核 Step1–4） */
  locked?: boolean;
  lockedLabel?: string;
  lockedHint?: string;
}

export const AISelector: React.FC<AISelectorProps> = ({
  ais,
  onChange,
  onDelete,
  onManageKnowledge,
  onManageEventTrigger,
  locked = false,
  lockedLabel,
  lockedHint,
}) => {
  const [isOpen, setIsOpen] = useState(false);

  const enabledAis = ais.filter((a) => a.enabled);
  const lockedDisplay =
    lockedLabel ||
    (enabledAis.length === 1
      ? enabledAis[0].name
      : enabledAis.map((a) => a.name).join('、') || '未配置');

  if (locked) {
    return (
      <div
        className="flex items-center space-x-2 px-3 py-2 bg-gray-100 rounded-lg text-sm text-gray-700 cursor-default"
        title={lockedHint || '完成报告导出后可自由选择 AI 模型'}
      >
        <span>🤖</span>
        <span className="max-w-[12rem] truncate">AI伙伴：{lockedDisplay}</span>
      </div>
    );
  }

  const toggleAI = (aiId: string) => {
    const updated = ais.map(ai =>
      ai.id === aiId ? { ...ai, enabled: !ai.enabled } : ai
    );
    
    // 检查是否有其他AI被启用（除了巴巴塔）
    const hasOtherEnabledAI = updated.some(ai => ai.id !== 'babata' && ai.enabled);
    const babataAI = updated.find(ai => ai.id === 'babata');
    const isBabataBeingDisabled = aiId === 'babata' && !babataAI?.enabled;
    
    // 如果尝试禁用巴巴塔，且没有其他AI被启用，不允许禁用
    if (isBabataBeingDisabled && !hasOtherEnabledAI) {
      // 保持巴巴塔启用状态
      const finalUpdated = updated.map(ai => {
        if (ai.id === 'babata') {
          return { ...ai, enabled: true };
        }
        return ai;
      });
      onChange(finalUpdated);
      return;
    }
    
    // 如果禁用的是其他AI，且没有其他AI被启用，自动启用巴巴塔
    if (aiId !== 'babata' && !hasOtherEnabledAI) {
      const finalUpdated = updated.map(ai => {
        if (ai.id === 'babata') {
          return { ...ai, enabled: true };
        }
        return ai;
      });
      onChange(finalUpdated);
      return;
    }
    
    // 其他情况正常切换
    onChange(updated);
  };

  const selectAll = () => {
    onChange(ais.map(ai => ({ ...ai, enabled: true })));
  };

  const enabledCount = ais.filter(a => a.enabled).length;

  return (
    <div className="relative">
      <button
        className="flex items-center space-x-2 px-3 py-2 bg-gray-100 rounded-lg hover:bg-gray-200 transition"
        onClick={() => setIsOpen(!isOpen)}
      >
        <span>🤖</span>
        <span>AI伙伴 ({enabledCount})</span>
        <ChevronDown size={16} className={`transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute top-full mt-2 right-0 w-64 bg-white border rounded-lg shadow-lg z-20">
            <div className="p-3 border-b">
              <div className="flex justify-between items-center">
                <span className="font-semibold">选择AI助手</span>
                <button
                  className="text-sm text-blue-500 hover:text-blue-600"
                  onClick={selectAll}
                >
                  全选
                </button>
              </div>
            </div>

            <div className="p-2 max-h-64 overflow-y-auto">
              {ais.map(ai => (
                <label
                  key={ai.id}
                  className="flex items-center p-2 hover:bg-gray-50 rounded cursor-pointer"
                >
                  <div className="relative mr-3">
                    <input
                      type="checkbox"
                      checked={ai.enabled}
                      onChange={() => toggleAI(ai.id)}
                      className="sr-only"
                    />
                    <div
                      className={`w-5 h-5 border-2 rounded flex items-center justify-center ${
                        ai.enabled
                          ? 'bg-blue-500 border-blue-500'
                          : 'border-gray-300'
                      }`}
                    >
                      {ai.enabled && <Check size={14} className="text-white" />}
                    </div>
                  </div>
                  <span className="text-xl mr-2">{ai.avatar}</span>
                  <div className="flex-1">
                    <div className="font-medium flex items-center space-x-2">
                      <span>{ai.name}</span>
                      {ai.isCustom && (
                        <span className="text-xs bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded">自定义</span>
                      )}
                    </div>
                    {ai.description && (
                      <div className="text-xs text-gray-500">{ai.description}</div>
                    )}
                    {/* 思考模式（DeepSeek / AI Token Plan） */}
                    {(ai.baseAI === 'deepseek' ||
                      (ai.baseAI?.startsWith('bailian-') && ai.supportsReasoning)) && (
                      <label className="flex items-center space-x-1 mt-1 text-xs text-gray-600">
                        <input
                          type="checkbox"
                          checked={ai.enableReasoning || false}
                          onChange={(e) => {
                            e.stopPropagation();
                            const updated = ais.map(a =>
                              a.id === ai.id ? { ...a, enableReasoning: e.target.checked } : a
                            );
                            onChange(updated);
                          }}
                          className="w-3 h-3"
                          onClick={(e) => e.stopPropagation()}
                        />
                        <span>思考模式</span>
                      </label>
                    )}
                  </div>
                  <div className="flex items-center space-x-2">
                    {ai.costPerToken && (
                      <span className="text-xs text-gray-400">
                        ${ai.costPerToken}/1K
                      </span>
                    )}
                    {/* 知识库管理按钮（巴巴塔和自定义角色） */}
                    {(ai.id === 'babata' || ai.isCustom) && onManageKnowledge && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onManageKnowledge(ai.id, ai.name);
                        }}
                        className="p-1.5 text-blue-500 hover:bg-blue-50 rounded transition"
                        title="管理知识库"
                      >
                        <BookOpen size={14} />
                      </button>
                    )}
                    {/* 事件触发管理按钮（巴巴塔和自定义角色） */}
                    {(ai.id === 'babata' || ai.isCustom) && onManageEventTrigger && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onManageEventTrigger(ai.id, ai.name);
                        }}
                        className="p-1.5 text-purple-500 hover:bg-purple-50 rounded transition"
                        title="管理事件触发"
                      >
                        <Zap size={14} />
                      </button>
                    )}
                    {/* 删除按钮（仅自定义角色） */}
                    {ai.isCustom && onDelete && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (window.confirm(`确定要删除角色"${ai.name}"吗？此操作不可恢复。`)) {
                            onDelete(ai.id);
                          }
                        }}
                        className="p-1.5 text-red-500 hover:bg-red-50 rounded transition"
                        title="删除角色"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </label>
              ))}
            </div>

            <div className="p-3 border-t text-xs text-gray-500">
              已选 {enabledCount} 个AI
            </div>
          </div>
        </>
      )}
    </div>
  );
};

