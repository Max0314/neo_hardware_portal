"""
公告栏配置文件
"""
import os

# 获取项目根目录 - 动态获取，不依赖文件夹名称
_current_file_dir = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_current_file_dir)

# 公告栏存储配置 - 使用绝对路径
ANNOUNCEMENT_BASE_DIR = os.path.join(BASE_DIR, "data", "announcements")
ANNOUNCEMENT_TEMP_DIR = "temp"

# 公告栏分类配置
ANNOUNCEMENT_BOARDS = {
    'hardware': '硬件研发部',
    'circuit': '电路设计组', 
    'structure': '结构组',
    'packaging': '包装标签组',
    'testing': '测试组'
}

# 公告优先级
ANNOUNCEMENT_PRIORITY = {
    'low': '低',
    'normal': '普通', 
    'high': '高',
    'urgent': '紧急'
}

# 公告状态
ANNOUNCEMENT_STATUS = {
    'draft': '草稿',
    'pending': '待审核',
    'approved': '已发布',
    'rejected': '已拒绝'
}

# 公告管理权限
ANNOUNCEMENT_MANAGE_ROLES = ['admin', 'announcement_manager', 'management']
