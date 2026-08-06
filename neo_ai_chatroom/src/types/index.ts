export interface Message {
  id: string;
  sender: 'user' | 'ai';
  aiModel?: string;  // 标识哪个AI
  avatar: string;
  name: string;
  content: string;
  timestamp: Date;
  status: 'sending' | 'sent' | 'error';
  reactions?: Reaction[];
  isThinking?: boolean;
  cacheInfo?: {
    hitTokens: number;
    missTokens: number;
    hitRate: number;
  };
  mentionedRoles?: string[];  // @的角色列表（巴巴塔使用）
  knowledgeMatches?: Array<{  // 知识库匹配项（巴巴塔使用）
    score: number;
    question: string;
    answer: string;
    image_data?: string;
    image_path?: string;
    image_type?: string;
  }> | null;
  knowledgeImage?: {  // 知识库答案的图片（巴巴塔使用）
    image_data?: string;
    image_path?: string;
    image_type?: string;
  };
  canSaveToKnowledge?: boolean;  // 是否可以保存到知识库
  originalQuestion?: string;  // 原始问题（用于保存到知识库）
  eventTrigger?: {  // 事件触发配置（单个）
    event_config: any;
    keywords: string;
    match_id?: string;
  };
  eventTriggers?: Array<{  // 事件触发配置（多个）
    event_config: any;
    keywords: string;
    match_id?: string;
  }>;
  quotedMessage?: Message;  // 引用的消息
  isCollapsed?: boolean;  // 是否折叠
  /** 用户消息随附文件名（展示用，与 <<<ATTACHMENT_CONTEXT>>> 块对应） */
  attachmentFileNames?: string[];
}

export interface Reaction {
  emoji: string;
  users: string[];
  count: number;
}

// 角色身份配置
export interface RoleIdentity {
  title?: string;
  company?: string;
  yearsOfExperience?: number;
  personality?: string;
}

// 专业能力配置
export interface RoleExpertise {
  primarySkills?: string[];
  secondarySkills?: string[];
  limitations?: string[];
}

// 沟通风格配置
export interface RoleCommunication {
  tone?: string;
  formalityLevel?: number;  // 0-1
  responseSpeed?: string;
  useFormalities?: boolean;
  signaturePhrases?: string[];
}

// 完整角色配置
export interface RoleConfig {
  identity?: RoleIdentity;
  expertise?: RoleExpertise;
  communication?: RoleCommunication;
  shouldDo?: string[];
  shouldNotDo?: string[];
  examples?: Array<{
    user: string;
    assistant: string;
  }>;
}

export interface AIConfig {
  id: string;
  name: string;
  avatar: string;
  enabled: boolean;
  description?: string;
  costPerToken?: number;
  apiKey?: string;
  baseAI?: string;  // 基础AI类型：deepseek, gpt-4, claude-3等
  rolePrompt?: string;  // 角色设定（system prompt）
  roleConfig?: RoleConfig;  // 详细角色配置
  isCustom?: boolean;  // 是否为自定义角色
  enableReasoning?: boolean;  // 思考模式（DeepSeek / AI Token Plan 等）
  supportsReasoning?: boolean;  // 是否支持思考模式开关
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: Date;
  updatedAt: Date;
  messageCount: number;
}

