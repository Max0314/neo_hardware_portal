import React, { useState } from 'react';
import { Message } from '@/types';
import { formatTime } from '@/utils/format';
import { splitUserMessageContent } from '@/utils/chatAttachmentMarkers';
import { Copy, ThumbsUp, Reply, BookOpen, ChevronDown, ChevronUp, CheckSquare, Square, Paperclip } from 'lucide-react';

interface MessageBubbleProps {
  message: Message;
  onReact?: (messageId: string, emoji: string) => void;
  onReply?: (message: Message) => void;
  onCopy?: (content: string) => void;
  onSelectKnowledge?: (answer: string, messageId: string) => void;  // 选择知识库答案，传递消息ID
  onSaveToKnowledge?: (question: string, answer: string, messageId: string) => void;  // 保存到知识库
  onTriggerEvent?: (eventConfig: any, messageId: string) => void;  // 触发事件
  onSelectForQuote?: (messageId: string, selected: boolean) => void;  // 选择消息用于引用
  isSelectedForQuote?: boolean;  // 是否被选中用于引用
  isFirstMessage?: boolean;  // 是否是第一条消息
}

// 获取事件类型显示名称
const getEventTypeName = (eventType: string): string => {
  const typeMap: { [key: string]: string } = {
    'open_sidebar_compare': '打开对比功能',
    'open_sidebar_analyze': '打开解析功能',
    'open_sidebar_review': '打开AI评审',
    'open_sidebar_summary': '打开评审总结',
    'open_sidebar_checklist': '打开待检查项',
    'open_sidebar_tab': '打开指定标签页',
    'open_game_tetris': '打开俄罗斯方块',
    'aggregate_review_summary': '硬件分析结果聚合',
    'bom_import': 'BOM导入',
    'bom_material_match': '物料查询（BOM）',
    'bom_cost_calc': 'BOM成本计算',
    'bom_group_validate': '物料替代组验证',
    'bom_replacement_check': '替换对检查',
    'material_db_search': '物料库物料查询',
    'prompt_review_chat': '审核提示词对话',
    'execute_script': '执行脚本',
    'send_message': '发送消息',
    'call_api': '调用API',
    'custom': '自定义事件',
  };
  return typeMap[eventType] || eventType;
};

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  message,
  onReact,
  onReply,
  onCopy,
  onSelectKnowledge,
  onSaveToKnowledge,
  onTriggerEvent,
  onSelectForQuote,
  isSelectedForQuote = false,
  isFirstMessage = false,
}) => {
  const isUser = message.sender === 'user';
  const [isCollapsed, setIsCollapsed] = useState(message.isCollapsed ?? false);
  const [showAttachmentBody, setShowAttachmentBody] = useState(false);

  const userSplit = isUser ? splitUserMessageContent(message.content) : null;
  const userDisplayText = userSplit?.text ?? message.content;
  const userAttachmentBody = userSplit?.attachmentPart ?? null;

  const handleCopy = () => {
    if (onCopy) {
      onCopy(message.content);
      navigator.clipboard.writeText(message.content);
    }
  };

  const handleReply = () => {
    if (onReply) {
      onReply(message);
    }
  };

  const handleLike = () => {
    if (onReact) {
      onReact(message.id, '👍');
    }
  };

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4 group`}>
      {/* AI消息头像在左边 */}
      {!isUser && (
        <div className="flex-shrink-0 mr-3">
          <div className="w-10 h-10 rounded-full flex items-center justify-center bg-blue-100 text-xl">
            {message.avatar}
          </div>
        </div>
      )}

      <div className={`max-w-2xl ${isUser ? 'order-1' : 'order-2'}`}>
        {/* 引用选择复选框（非第一条消息） */}
        {!isFirstMessage && onSelectForQuote && (
          <div className={`flex items-center mb-2 ${isUser ? 'justify-end' : 'justify-start'}`}>
            <button
              onClick={() => onSelectForQuote(message.id, !isSelectedForQuote)}
              className={`flex items-center space-x-1 px-2 py-1 rounded text-xs transition ${
                isSelectedForQuote
                  ? 'bg-blue-100 text-blue-700 border border-blue-300'
                  : 'text-gray-500 hover:bg-gray-100 border border-gray-200'
              }`}
              title="选择引用"
            >
              {isSelectedForQuote ? (
                <CheckSquare size={14} className="text-blue-600" />
              ) : (
                <Square size={14} />
              )}
              <span>引用</span>
            </button>
          </div>
        )}

        {/* 发送者信息 */}
        <div className={`flex items-center mb-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
          {!isUser && (
            <span className="font-semibold mr-2 text-gray-700">{message.name}</span>
          )}
          <span className="text-xs text-gray-500">
            {formatTime(message.timestamp)}
          </span>
          {isUser && <span className="font-semibold ml-2 text-gray-700">{message.name}</span>}
        </div>

        {/* 折叠/展开按钮（AI消息且非思考状态） */}
        {!isUser && !message.isThinking && (
          <div className="flex items-center mb-1">
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="flex items-center space-x-1 text-xs text-gray-500 hover:text-gray-700 transition"
              title={isCollapsed ? '展开' : '折叠'}
            >
              {isCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
              <span>{isCollapsed ? '展开' : '折叠'}</span>
            </button>
          </div>
        )}

        {/* 消息内容 */}
        <div
          className={`
            rounded-2xl px-4 py-3 break-words relative
            ${isUser
              ? 'bg-blue-500 text-white rounded-tr-none'
              : 'bg-gray-100 text-gray-800 rounded-tl-none'
            }
            ${message.isThinking ? 'opacity-70' : ''}
            ${!isUser && isCollapsed ? 'max-h-20 overflow-hidden' : ''}
          `}
        >
          {message.isThinking ? (
            <div className="flex items-center space-x-1">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
              </div>
              <span className="ml-2 text-sm">正在思考...</span>
            </div>
          ) : (
            <>
              <div className={`whitespace-pre-wrap ${!isUser && isCollapsed ? 'line-clamp-3' : ''}`}>
                {isUser && userAttachmentBody ? (
                  <>
                    <div>{userDisplayText.trim() || '（未输入文字，已上传附件）'}</div>
                    {(message.attachmentFileNames?.length ?? 0) > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {message.attachmentFileNames!.map((n, i) => (
                          <span
                            key={`${n}-${i}`}
                            className="inline-flex items-center gap-1 rounded-md bg-blue-400/90 px-2 py-0.5 text-xs text-white"
                          >
                            <Paperclip size={12} />
                            {n}
                          </span>
                        ))}
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => setShowAttachmentBody(!showAttachmentBody)}
                      className="mt-2 text-xs underline opacity-90 hover:opacity-100"
                    >
                      {showAttachmentBody ? '收起附件解析正文' : '查看附件解析正文'}
                    </button>
                    {showAttachmentBody && (
                      <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-blue-600/30 p-2 text-left text-xs whitespace-pre-wrap break-words">
                        {userAttachmentBody}
                      </pre>
                    )}
                  </>
                ) : (
                  message.content
                )}
              </div>
              {!isUser && isCollapsed && (
                <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-gray-100 to-transparent pointer-events-none" />
              )}

              {/* 知识库答案的图片（巴巴塔） */}
              {!isUser && message.knowledgeImage && (
                <div className="mt-3">
                  {message.knowledgeImage.image_data ? (
                    <img 
                      src={`data:${message.knowledgeImage.image_type || 'image/png'};base64,${message.knowledgeImage.image_data}`}
                      alt="知识库图片"
                      className="max-w-full h-auto max-h-96 rounded-lg border"
                    />
                  ) : message.knowledgeImage.image_path ? (
                    <img 
                      src={message.knowledgeImage.image_path}
                      alt="知识库图片"
                      className="max-w-full h-auto max-h-96 rounded-lg border"
                    />
                  ) : null}
                </div>
              )}

              {/* 知识库匹配项选择按钮（巴巴塔） */}
              {!isUser && onSelectKnowledge && message.knowledgeMatches && message.knowledgeMatches.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <div className="text-xs text-gray-600 mb-2">请选择答案：</div>
                  <div className="flex flex-wrap gap-2">
                    {message.knowledgeMatches.map((match, index) => (
                      <button
                        key={index}
                        onClick={() => onSelectKnowledge?.(match.answer, message.id)}
                        className="px-3 py-2 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg text-sm text-left transition"
                        title={match.answer}
                      >
                        <div className="font-medium text-blue-700">{match.question}</div>
                        <div className="text-xs text-gray-500 mt-1 line-clamp-1">{match.answer}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 事件触发按钮（单个） */}
              {!isUser && onTriggerEvent && message.eventTrigger && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <div className="text-xs text-gray-600 mb-2">可用操作：</div>
                  <button
                    onClick={() => onTriggerEvent?.(message.eventTrigger!.event_config, message.id)}
                    className="px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg text-sm font-medium transition shadow-sm"
                  >
                    ⚡ {getEventTypeName(message.eventTrigger.event_config.type)}
                  </button>
                </div>
              )}

              {/* 事件触发按钮（多个） */}
              {!isUser && onTriggerEvent && message.eventTriggers && message.eventTriggers.length > 0 && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <div className="text-xs text-gray-600 mb-2">可用操作：</div>
                  <div className="flex flex-wrap gap-2">
                    {message.eventTriggers.map((trigger, index) => (
                      <button
                        key={index}
                        onClick={() => onTriggerEvent?.(trigger.event_config, message.id)}
                        className="px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg text-sm font-medium transition shadow-sm"
                      >
                        ⚡ {getEventTypeName(trigger.event_config.type)}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* @的角色信息（巴巴塔） */}
              {!isUser && message.mentionedRoles && message.mentionedRoles.length > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-200 text-xs text-blue-600">
                  📢 已@: {message.mentionedRoles.join('、')}
                </div>
              )}

              {/* 缓存命中信息 */}
              {!isUser && message.cacheInfo && message.cacheInfo.hitTokens > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-200 text-xs text-gray-500">
                  💾 缓存命中: {message.cacheInfo.hitRate.toFixed(1)}% 
                  ({message.cacheInfo.hitTokens.toLocaleString()} tokens命中, 
                  {message.cacheInfo.missTokens.toLocaleString()} tokens未命中)
                </div>
              )}

              {/* 消息状态 */}
              {isUser && (
                <div className="text-right mt-1 text-xs opacity-70">
                  {message.status === 'sending' && '发送中...'}
                  {message.status === 'sent' && '✓✓'}
                  {message.status === 'error' && '✗'}
                </div>
              )}

              {/* 保存到知识库按钮（仅AI消息且canSaveToKnowledge为true时显示） */}
              {!isUser && onSaveToKnowledge && message.canSaveToKnowledge && message.originalQuestion && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <button
                    onClick={() => {
                      if (onSaveToKnowledge && message.originalQuestion) {
                        onSaveToKnowledge(message.originalQuestion, message.content, message.id);
                      }
                    }}
                    className="px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg text-sm flex items-center gap-2 transition"
                  >
                    <BookOpen size={16} />
                    <span>保存到知识库</span>
                  </button>
                  <div className="text-xs text-gray-500 mt-1">
                    问题：{message.originalQuestion}
                  </div>
                </div>
              )}

              {/* 表情回应 */}
              {message.reactions && message.reactions.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {message.reactions.map((reaction, index) => (
                    <button
                      key={index}
                      className="text-xs bg-white bg-opacity-20 px-2 py-1 rounded-full hover:bg-opacity-30 transition"
                      onClick={() => onReact?.(message.id, reaction.emoji)}
                    >
                      {reaction.emoji} {reaction.count}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {/* 消息操作按钮 */}
        <div className={`flex space-x-2 mt-1 opacity-0 group-hover:opacity-100 transition ${isUser ? 'justify-end' : 'justify-start'}`}>
          {!isUser && (
            <>
              <button
                className="text-xs text-gray-500 hover:text-gray-700 flex items-center space-x-1"
                onClick={handleCopy}
                title="复制"
              >
                <Copy size={12} />
                <span>复制</span>
              </button>
              {onReply && (
                <button
                  className="text-xs text-gray-500 hover:text-gray-700 flex items-center space-x-1"
                  onClick={handleReply}
                  title="引用"
                >
                  <Reply size={12} />
                  <span>引用</span>
                </button>
              )}
              {onReact && (
                <button
                  className="text-xs text-gray-500 hover:text-gray-700 flex items-center space-x-1"
                  onClick={handleLike}
                  title="点赞"
                >
                  <ThumbsUp size={12} />
                  <span>赞</span>
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* 用户头像在右边 */}
      {isUser && (
        <div className="flex-shrink-0 ml-3 order-2">
          <div className="w-10 h-10 rounded-full flex items-center justify-center bg-green-100 text-xl">
            {message.avatar}
          </div>
        </div>
      )}
    </div>
  );
};

