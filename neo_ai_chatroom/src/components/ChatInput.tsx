import React, { useState, useRef, useEffect } from 'react';
import { AIConfig, Message } from '@/types';
import { Send, X, CheckSquare, Square, Paperclip } from 'lucide-react';

export interface PendingAttachmentMeta {
  name: string;
  size: number;
}

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void | Promise<void>;
  selectedAIs: AIConfig[];
  quotedMessages?: Message[];  // 引用的消息列表
  onRemoveQuote?: (messageId: string) => void;  // 移除引用
  allMessages?: Message[];  // 所有消息（用于全选）
  onSelectAll?: (selected: boolean) => void;  // 全选/取消全选回调
  isAllSelected?: boolean;  // 是否全选
  /** 待发送附件（仅元信息展示，实际 File 在父组件） */
  pendingAttachments?: PendingAttachmentMeta[];
  onRemoveAttachment?: (index: number) => void;
  onFilesSelected?: (files: File[]) => void;
  isSubmitting?: boolean;
  /** 锁定输入（仍可展示区域，用于原理图审核导出前） */
  inputLocked?: boolean;
  inputLockedHint?: string;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  value,
  onChange,
  onSubmit,
  selectedAIs,
  quotedMessages = [],
  onRemoveQuote,
  allMessages = [],
  onSelectAll,
  isAllSelected = false,
  pendingAttachments = [],
  onRemoveAttachment,
  onFilesSelected,
  isSubmitting = false,
  inputLocked = false,
  inputLockedHint,
}) => {
  const [showMentionList, setShowMentionList] = useState(false);
  const [mentionSearch, setMentionSearch] = useState('');
  const [mentionIndex, setMentionIndex] = useState(-1);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mentionStartRef = useRef<number>(-1);

  const canSend = !inputLocked && Boolean(value.trim() || pendingAttachments.length > 0);

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value;
    onChange(text);

    // 检测@符号
    const cursorPos = e.target.selectionStart;
    const textBeforeCursor = text.substring(0, cursorPos);
    const atIndex = textBeforeCursor.lastIndexOf('@');

    if (atIndex !== -1) {
      const searchText = textBeforeCursor.substring(atIndex + 1);
      const hasSpace = searchText.includes(' ');

      if (!hasSpace) {
        mentionStartRef.current = atIndex;
        setMentionSearch(searchText);
        setShowMentionList(true);
      } else {
        setShowMentionList(false);
      }
    } else {
      setShowMentionList(false);
    }
  };

  // 过滤AI列表：显示所有可用的AI（包括未启用的），方便@它们
  const filteredAIs = selectedAIs.filter(ai =>
    ai.name.toLowerCase().includes(mentionSearch.toLowerCase())
  );

  const insertMention = (aiName: string) => {
    if (mentionStartRef.current !== -1) {
      const textBefore = value.substring(0, mentionStartRef.current);
      const textAfter = value.substring(textareaRef.current?.selectionStart || value.length);
      const newText = `${textBefore}@${aiName} ${textAfter}`;
      onChange(newText);
      setShowMentionList(false);
      mentionStartRef.current = -1;
      setTimeout(() => {
        textareaRef.current?.focus();
        const newPos = mentionStartRef.current + aiName.length + 2;
        textareaRef.current?.setSelectionRange(newPos, newPos);
      }, 0);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showMentionList && filteredAIs.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionIndex(prev => (prev < filteredAIs.length - 1 ? prev + 1 : prev));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionIndex(prev => (prev > 0 ? prev - 1 : -1));
      } else if (e.key === 'Enter' && mentionIndex >= 0) {
        e.preventDefault();
        insertMention(filteredAIs[mentionIndex].name);
      } else if (e.key === 'Escape') {
        setShowMentionList(false);
      }
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (canSend && !isSubmitting) void onSubmit();
    }
  };

  useEffect(() => {
    if (showMentionList) {
      setMentionIndex(0);
    }
  }, [showMentionList, mentionSearch]);

  // 计算可引用的消息数量（排除第一条）
  const quotableMessageCount = allMessages.length > 1 ? allMessages.length - 1 : 0;

  return (
    <div className="relative">
      {/* 全选控制栏 */}
      {quotableMessageCount > 0 && onSelectAll && (
        <div className="mb-2 flex items-center justify-between p-2 bg-blue-50 border border-blue-200 rounded-lg">
          <button
            onClick={() => onSelectAll(!isAllSelected)}
            className="flex items-center space-x-2 text-sm text-blue-700 hover:text-blue-800 transition"
          >
            {isAllSelected ? (
              <CheckSquare size={16} className="text-blue-600" />
            ) : (
              <Square size={16} />
            )}
            <span className="font-medium">
              {isAllSelected ? '取消全选' : `全选引用 (${quotableMessageCount}条)`}
            </span>
          </button>
          {quotedMessages.length > 0 && (
            <span className="text-xs text-blue-600">
              已选择 {quotedMessages.length} / {quotableMessageCount} 条
            </span>
          )}
        </div>
      )}

      {/* 显示引用的消息 */}
      {quotedMessages && quotedMessages.length > 0 && (
        <div className="mb-2 p-2 bg-gray-50 border border-gray-200 rounded-lg max-h-32 overflow-y-auto">
          <div className="text-xs text-gray-600 mb-1 font-medium">已引用 {quotedMessages.length} 条消息：</div>
          {quotedMessages.map((msg) => (
            <div key={msg.id} className="flex items-start justify-between mb-1 last:mb-0 p-1 bg-white rounded border border-gray-200">
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-gray-700 truncate">
                  {msg.sender === 'user' ? '👤 我' : `${msg.avatar} ${msg.name}`}
                </div>
                <div className="text-xs text-gray-500 line-clamp-2 mt-0.5">
                  {msg.content}
                </div>
              </div>
              {onRemoveQuote && (
                <button
                  onClick={() => onRemoveQuote(msg.id)}
                  className="ml-2 text-gray-400 hover:text-red-500 transition flex-shrink-0"
                  title="移除引用"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {onFilesSelected && (
        <div className="mb-2 flex flex-col gap-2 rounded-lg border border-amber-200 bg-amber-50/90 p-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-amber-900">
              附件预览（已选 {pendingAttachments.length} 个，发送时解析为文本）
            </span>
          </div>
          {pendingAttachments.length === 0 ? (
            <p className="text-xs text-amber-800/90">
            点击左侧回形针按钮选择文件；支持常见文本、PDF、Word、Excel 等（未列出的扩展名也可选，不支持的类型将在发送时提示）。
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {pendingAttachments.map((f, idx) => (
                <div
                  key={`${f.name}-${idx}-${f.size}`}
                  className="flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-1 text-xs text-gray-800 shadow-sm"
                >
                  <Paperclip size={12} className="text-amber-700 shrink-0" />
                  <span className="max-w-[min(100vw-8rem,280px)] truncate" title={f.name}>
                    {f.name}
                  </span>
                  <span className="text-gray-500 whitespace-nowrap">
                    ({f.size < 1024 ? `${f.size} B` : `${(f.size / 1024).toFixed(1)} KB`})
                  </span>
                  {onRemoveAttachment && (
                    <button
                      type="button"
                      onClick={() => onRemoveAttachment(idx)}
                      className="ml-1 text-gray-400 hover:text-red-600"
                      title="移除"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {inputLocked && (
        <div className="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {inputLockedHint || '请先完成报告导出后再输入消息或上传附件。'}
        </div>
      )}

      <div className="flex items-end space-x-2">
        {onFilesSelected && !inputLocked && (
          <label
            className={`relative flex h-[48px] w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 ${
              isSubmitting ? 'pointer-events-none opacity-50' : ''
            }`}
            title="添加附件（本地解析：文本 / PDF / Word / Excel）"
          >
            {/* 透明 input 铺满按钮：比 display:none 在 Electron/部分浏览器里更可靠 */}
            <input
              type="file"
              multiple
              disabled={isSubmitting}
              className="absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0"
              onChange={(e) => {
                // 必须先立刻复制 File 数组再清空 value：FileList 与 input 联动，清空后同一引用会变为空
                const arr = e.target.files?.length ? Array.from(e.target.files) : [];
                e.target.value = '';
                if (!arr.length) return;
                onFilesSelected(arr);
                if (import.meta.env.DEV) {
                  console.log(
                    '[ChatInput] 已选择文件',
                    arr.map((f) => ({ name: f.name, size: f.size, type: f.type || '(空type)' }))
                  );
                }
              }}
            />
            <span className="pointer-events-none relative z-0 flex items-center justify-center" aria-hidden>
              <Paperclip size={20} />
            </span>
            <span className="sr-only">选择要上传的文件</span>
          </label>
        )}
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={
              inputLocked
                ? '请先完成 Step 4 导出报告后再输入…'
                : '输入消息... 使用@可以指定AI回复；可点左侧回形针上传文件'
            }
            disabled={isSubmitting || inputLocked}
            className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none disabled:bg-gray-100"
            rows={1}
            style={{
              minHeight: '48px',
              maxHeight: '200px',
            }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement;
              target.style.height = 'auto';
              target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
            }}
          />

          {/* 提及建议列表 */}
          {showMentionList && filteredAIs.length > 0 && (
            <div className="absolute bottom-full mb-2 left-0 right-0 bg-white border rounded-lg shadow-lg max-h-48 overflow-y-auto z-10">
              {filteredAIs.map((ai, index) => (
                <div
                  key={ai.id}
                  className={`p-2 hover:bg-gray-100 cursor-pointer flex items-center space-x-2 ${
                    index === mentionIndex ? 'bg-blue-50' : ''
                  }`}
                  onClick={() => insertMention(ai.name)}
                  onMouseEnter={() => setMentionIndex(index)}
                >
                  <span className="text-xl">{ai.avatar}</span>
                  <span className="font-medium">{ai.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={() => void onSubmit()}
          disabled={!canSend || isSubmitting}
          className="px-4 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition flex items-center space-x-2"
        >
          <Send size={18} />
          <span>{isSubmitting ? '解析中…' : '发送'}</span>
        </button>
      </div>
    </div>
  );
};

