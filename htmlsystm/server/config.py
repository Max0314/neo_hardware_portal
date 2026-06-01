#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统配置文件
包含服务器配置、路径配置、物料库配置等
"""
import os
import sys

# ==================== 基础配置 ====================
HOST = '0.0.0.0'  # 监听所有网络接口
# 端口配置：优先从环境变量读取，否则使用默认值8000
# 可以通过环境变量 SERVER_PORT 或 PORT 设置端口
PORT = int(os.getenv('SERVER_PORT') or os.getenv('PORT') or 8000)  # 服务器端口

# 性能优化配置（性能翻4倍）
ENABLE_GZIP = True  # 启用GZIP压缩
ENABLE_CACHE = True  # 启用HTTP缓存
CACHE_MAX_AGE = 3600  # 缓存最大年龄（秒）
MAX_WORKERS = 8000  # 最大工作线程数（支持8000人同时使用，性能翻4倍）
REQUEST_TIMEOUT = 60  # 请求超时时间（秒）- 增加到60秒，支持高并发场景

# 高并发优化配置（性能翻4倍）
MAX_CONNECTIONS = 20000  # 最大并发连接数（翻4倍：5000 -> 20000）
CONNECTION_QUEUE_SIZE = 4000  # 连接队列大小（翻4倍：1000 -> 4000）
THREAD_POOL_SIZE = 2000  # 线程池大小（用于异步任务，翻4倍：500 -> 2000）
CACHE_SIZE = 40000  # 缓存条目数量上限（翻4倍：10000 -> 40000）
FILE_READ_BUFFER_SIZE = 262144  # 文件读取缓冲区大小（字节，256KB，翻4倍：64KB -> 256KB）
EXCEL_READ_TIMEOUT = 5  # Excel文件读取超时（秒）

# 网络传输优化配置（充分利用1000MB带宽，性能翻4倍）
GZIP_COMPRESSION_LEVEL = 6  # GZIP压缩级别（1-9，6是性能和压缩比的平衡）
CHUNK_SIZE = 4194304  # 数据传输块大小（4MB，翻4倍，充分利用带宽）
SEND_BUFFER_SIZE = 4194304  # 发送缓冲区大小（4MB，翻4倍）
RECV_BUFFER_SIZE = 4194304  # 接收缓冲区大小（4MB，翻4倍）
MAX_RESPONSE_SIZE = 41943040  # 最大响应大小（40MB，翻4倍）

# 内存预加载配置（性能翻4倍优化）
PRELOAD_USERS = True  # 启动时预加载用户数据到内存
PRELOAD_ANNOUNCEMENTS = True  # 启动时预加载公告数据到内存
PRELOAD_DEPARTMENTS = True  # 启动时预加载部门数据到内存
PRELOAD_TODOS = True  # 启动时预加载待办数据到内存
MEMORY_CACHE_TTL = 600  # 内存缓存TTL（秒，10分钟，翻倍以提升缓存命中率）

# 缓存TTL优化配置（阶段1优化）
HOT_CACHE_TTL = 300  # 热点数据缓存TTL（秒，5分钟）- 最近30天公告等
NORMAL_CACHE_TTL = 600  # 普通数据缓存TTL（秒，10分钟）- 用户、部门等

# 异步预加载配置（阶段2优化）
ASYNC_PRELOAD = True  # 是否启用异步预加载（True=非阻塞，False=阻塞）

# 待办数据自动保存配置
TODO_AUTO_SAVE_ENABLED = True  # 是否启用待办数据自动保存
TODO_AUTO_SAVE_INTERVAL = 300  # 自动保存间隔（秒，默认300秒=5分钟）

# 分页配置
ANNOUNCEMENT_PAGE_SIZE = 10  # 公告列表每页显示数量（默认10条）
ANNOUNCEMENT_MAX_PAGE_SIZE = 100  # 最大每页显示数量（防止恶意请求）

# 附件配置
MAX_ATTACHMENT_SIZE = 104857600  # 最大附件大小（100MB，单位：字节）
MAX_ATTACHMENTS_PER_ANNOUNCEMENT = 10  # 每个公告最大附件数量

# 允许上传的安全附件扩展名（小写，含点号）
ALLOWED_ATTACHMENT_EXTENSIONS = [
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.csv', '.md',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
    '.zip', '.rar', '.7z',
    '.dwg', '.dxf', '.step', '.stp',
]

# 明确禁止的危险扩展名
BLOCKED_ATTACHMENT_EXTENSIONS = [
    '.exe', '.bat', '.cmd', '.sh', '.ps1', '.js', '.html', '.htm',
    '.svg', '.php', '.msi', '.dll', '.vbs', '.scr', '.com', '.jar',
]

# ==================== 文件路径配置 ====================
# 动态获取路径，不依赖文件夹名称
# 获取当前文件所在目录（server目录）
_current_file_dir = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录（server的父目录）
BASE_DIR = os.path.dirname(_current_file_dir)

# 仅在调试模式下打印路径信息
if os.getenv('DEBUG', '').lower() in ('1', 'true', 'yes'):
    print(f"[DEBUG] 系统路径初始化: BASE_DIR={BASE_DIR}")

DATA_DIR = os.path.join(BASE_DIR, 'data')
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

# 数据库配置
DB_PATH = os.path.join(DATA_DIR, 'material.db')

# MySQL配置（已完全迁移到MySQL，不再支持SQLite）
USE_MYSQL = True  # 强制使用MySQL
USE_TODO_MYSQL = True  # 是否使用MySQL存储待办数据（True=MySQL，False=Excel）
MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'port': int(os.getenv('MYSQL_PORT', 3306)),
    'user': os.getenv('MYSQL_USER', 'htmlsystm_user'),
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQL_DATABASE', 'htmlsystm'),
    'charset': 'utf8mb4',
    'autocommit': False,
    'pool_size': 10,  # 连接池大小
    'pool_reset_session': True,
    'pool_recycle': 3600,  # 连接回收时间（秒）
}

# Excel 配置
LIBRARY_DIR = os.path.join(DATA_DIR, 'libraries')
PENDING_DIR = os.path.join(DATA_DIR, 'pending')
MODIFICATION_DIR = os.path.join(DATA_DIR, 'modifications')

# ==================== 目录初始化 ====================
def ensure_directories():
    """确保所有必要的目录存在"""
    directories = [
        DATA_DIR,
        UPLOAD_DIR,
        STATIC_DIR,
        TEMPLATE_DIR,
        LIBRARY_DIR,
        PENDING_DIR,
        MODIFICATION_DIR
    ]
    for dir_path in directories:
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError as e:
            print(f"警告: 无法创建目录 {dir_path}: {e}")

# 自动初始化目录
ensure_directories()

# 物料库配置
LIBRARY_CONFIG = {
    'capacitor': {
        'name': '电容库',
        'manager_role': 'capacitor_manager'
    },
    'resistor': {
        'name': '电阻库', 
        'manager_role': 'resistor_manager'
    },
    'inductor': {
        'name': '电感库',
        'manager_role': 'inductor_manager'
    },
    'memory': {
        'name': '存储器库',
        'manager_role': 'memory_manager'
    },
    'ic': {
        'name': 'IC库',
        'manager_role': 'ic_manager'
    },
    'BOSA': {
        'name': 'BOSA库',
        'manager_role': 'bosa_manager'
    }
}

# 价格显示权限
PRICE_VISIBLE_ROLES = ['admin', 'manager', 'cost', 'purchase']

# 物料状态
MATERIAL_STATUS = {
    'pending': '待审批',
    'approved': '已批准',
    'rejected': '已拒绝'
}

# 修改申请类型
MODIFICATION_TYPE = {
    'add': '新增物料',
    'update': '修改属性',
    'delete': '删除物料'
}

# ==================== 用户相关配置 ====================
# 部门选项
DEPARTMENT_OPTIONS = {
    'hardware_rd': '硬件研发部',
    'purchase': '采购',
    'cost': '成本',
    'management': '管理组'
}

# 岗位身份（账号管理 / 注册，仅两种；旧数据中的 circuit 等仍保留在库内作兼容展示）
JOB_POSITION_OPTIONS = {
    'user': '普通用户',
    'manager': '管理者',
}

# 历史岗位键 -> 新岗位键（展示与编辑表单回显）
LEGACY_JOB_POSITION_MAP = {
    'management': 'manager',
    'circuit': 'user',
    'structure': 'user',
    'packaging': 'user',
    'testing': 'user',
}

# 用户状态
USER_STATUS_ACTIVE = 'active'
USER_STATUS_DISABLED = 'disabled'
USER_STATUS_PENDING = 'pending'
USER_STATUS_REJECTED = 'rejected'

# 禁用/删除仍持有物料库权限的用户时，若请求未带 library_handoff_user_id，可回退到该用户（数字 ID 或用户名）
DEFAULT_LIBRARY_HANDOFF_USER_ID = (os.getenv('DEFAULT_LIBRARY_HANDOFF_USER_ID') or '').strip()

# ==================== 钉钉应用配置 ====================
# 钉钉应用凭证（从钉钉开放平台获取）
DINGTALK_CONFIG = {
    'app_id': '867d9bdd-2786-4983-82e3-3f614ef75dd6',  # App ID
    'agent_id': '4118967622G',  # AgentId
    'corp_id': 'dingb7b711325c4be8aa35c2f4657eb6378f',  # 企业ID (CorpId)
    'client_id': 'dingtgmzjxwfn4ilrk0b',  # Client ID (原 AppKey)
    'client_secret': (os.getenv('DINGTALK_CLIENT_SECRET') or '').strip(),
    
    # 钉钉API地址
    'api_base_url': 'https://oapi.dingtalk.com',
    'oauth2_token_url': 'https://api.dingtalk.com/v1.0/oauth2/{corp_id}/token',  # OAuth2获取token (新API)
    'sns_api_url': 'https://oapi.dingtalk.com/sns/getuserinfo_bycode',  # 小程序免登
    'gettoken_url': 'https://oapi.dingtalk.com/gettoken',  # 获取access_token (旧API)
    'userinfo_url': 'https://oapi.dingtalk.com/topapi/v2/user/getuserinfo',  # 获取用户信息（企业内部应用）
    'user_detail_url': 'https://oapi.dingtalk.com/topapi/v2/user/get',  # 获取用户详情
}

# 钉钉知识库（可通过环境变量覆盖；空字符串视为未配置，回退默认值）
DINGTALK_WORKSPACE_ID = (os.getenv('DINGTALK_WORKSPACE_ID') or 'NK8M2SXGMoON35ad').strip()
DINGTALK_DOC_PARENT_NODE_ID = (os.getenv('DINGTALK_DOC_PARENT_NODE_ID') or '6LeBq413JAeRN2dkiRNAkpwMJDOnGvpb').strip()
DINGTALK_DOC_OPERATOR_UNIONID = (os.getenv('DINGTALK_DOC_OPERATOR_UNIONID') or '').strip()

# 对外访问根 URL（工作通知、钉钉跳转链接）
def _normalize_public_base_url(raw: str) -> str:
    u = (raw or '').strip().rstrip('/')
    if u.upper().startswith('HTTPS://'):
        return 'https://' + u[8:]
    if u.upper().startswith('HTTP://'):
        return 'http://' + u[7:]
    return u


PUBLIC_BASE_URL = _normalize_public_base_url(os.getenv('PUBLIC_BASE_URL') or '')

# 钉钉工作通知重试（阅读通知、定时补发）
DINGTALK_NOTIFY_MAX_RETRIES = int(os.getenv('DINGTALK_NOTIFY_MAX_RETRIES', '6'))
DINGTALK_NOTIFY_RETRY_BASE_SEC = float(os.getenv('DINGTALK_NOTIFY_RETRY_BASE_SEC', '3'))


def _parse_dept_id_list(raw: str) -> list:
    """解析逗号分隔的钉钉部门 dept_id 列表（支持中英文逗号）。"""
    ids = []
    for part in (raw or '').replace('，', ',').split(','):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


# 钉钉用户同步范围：根部门 dept_id 列表；空则回退按名称查找「硬件研发部」
DINGTALK_SYNC_DEPARTMENT_IDS = _parse_dept_id_list(os.getenv('DINGTALK_SYNC_DEPARTMENT_IDS', ''))


def get_dingtalk_agent_id_numeric() -> int:
    """企业内部应用 AgentId（去掉配置中的 G 后缀）。"""
    raw = str(DINGTALK_CONFIG.get('agent_id', '') or '').strip()
    if raw.endswith('G'):
        raw = raw[:-1]
    try:
        return int(raw) if raw else 4118967622
    except ValueError:
        return 4118967622


# ==================== 公告审批配置 ====================
# 审批人配置：支持配置多个审批人或角色
# 配置方式：
# 1. 按角色：['management', 'admin'] - 所有管理组和管理员
# 2. 按用户ID：['userid1', 'userid2'] - 指定用户
# 3. 按title：['硬件研发部部长'] - 指定title
# 4. 混合配置：支持同时配置多种方式
ANNOUNCEMENT_APPROVERS = {
    # 默认审批人配置（优先级从高到低）
    'roles': ['management', 'admin'],  # 管理组和管理员可以审批
    'titles': ['硬件研发部部长'],  # title包含"硬件研发部部长"的用户
    'userids': [],  # 可以指定具体的userid列表
    # 是否启用自动查找硬件研发部部长（兼容旧逻辑）
    'auto_find_dept_heads': True,
}

# ==================== 历史版本管理配置 ====================
# 每个公告保留的历史版本数量（超过数量自动删除最旧版本）
MAX_VERSION_HISTORY = 10

# ==================== 待办任务配置 ====================
# 待办任务创建失败时的重试次数
TODO_CREATE_RETRY_COUNT = 3
# 待办任务创建失败时的重试间隔（秒）
TODO_CREATE_RETRY_INTERVAL = 2
# 待办任务状态同步失败时的重试次数
TODO_SYNC_RETRY_COUNT = 3
# 待办任务状态同步失败时的重试间隔（秒）
TODO_SYNC_RETRY_INTERVAL = 2

# ==================== 回收站配置 ====================
# 是否启用回收站（软删除）
ENABLE_RECYCLE_BIN = True
# 回收站保留天数（超过天数自动清理）
RECYCLE_BIN_RETENTION_DAYS = 30

# 检查钉钉配置是否完整
def check_dingtalk_config():
    """检查钉钉配置是否完整"""
    if not DINGTALK_CONFIG.get('client_secret'):
        return False, '未配置 Client Secret，请在环境变量 DINGTALK_CLIENT_SECRET 中设置，或在 config.py 中直接配置'
    return True, None
