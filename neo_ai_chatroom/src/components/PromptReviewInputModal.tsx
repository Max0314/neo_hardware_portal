import React, { useState, useRef } from 'react';
import { X, Upload, Send } from 'lucide-react';

interface PromptReviewInputModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** 触发时自动加在用户内容前的提示词 */
  prompt: string;
  /** 提交时传入：提示词 + 用户输入/文件内容的完整文本 */
  onSubmit: (fullContent: string) => void;
}

export const PromptReviewInputModal: React.FC<PromptReviewInputModalProps> = ({
  isOpen,
  onClose,
  prompt,
  onSubmit,
}) => {
  const [inputText, setInputText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = (ev.target?.result as string) || '';
      setInputText((prev) => (prev ? prev + '\n\n' + text : text));
      setFileName(file.name);
    };
    reader.readAsText(file, 'UTF-8');
    e.target.value = '';
  };

  const handleSubmit = () => {
    const trimmed = inputText.trim();
    if (!trimmed) {
      return;
    }
    const fullContent = prompt.trim() ? `${prompt.trim()}\n\n${trimmed}` : trimmed;
    onSubmit(fullContent);
    setInputText('');
    setFileName(null);
    onClose();
  };

  const handleClose = () => {
    setInputText('');
    setFileName(null);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[60]">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex justify-between items-center px-4 py-3 border-b">
          <h3 className="text-lg font-semibold">审核提示词对话 - 输入内容</h3>
          <button
            type="button"
            onClick={handleClose}
            className="text-gray-500 hover:text-gray-700 p-1 rounded"
          >
            <X size={20} />
          </button>
        </div>
        <div className="px-4 py-3 flex-1 overflow-hidden flex flex-col min-h-0">
          <p className="text-sm text-gray-500 mb-2">
            下方内容将自动在已配置的提示词后发送给 AI。可粘贴文本或上传文件（将按文本读取）。
          </p>
          <div className="flex-1 flex flex-col min-h-0">
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="在此粘贴或输入要审核的内容……"
              className="w-full flex-1 min-h-[200px] px-3 py-2 border rounded-lg resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              rows={10}
            />
            {fileName && (
              <div className="mt-2 text-sm text-gray-500">
                已加载文件: {fileName}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3 mt-3">
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.json,.csv,.log,.md,.xml,.html,.htm"
              onChange={handleFileChange}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 text-sm"
            >
              <Upload size={16} />
              上传文件
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!inputText.trim()}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed text-sm"
            >
              <Send size={16} />
              发送给 AI
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
