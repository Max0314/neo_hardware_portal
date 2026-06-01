#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时通知模块
在每天的 8:00、12:30、17:30 对未完成阅读公告的人员发送阅读通知
"""
import os
import sys
import time
import threading
import datetime
from typing import List, Dict, Any, Optional
import urllib.parse
import json

# 跨平台文件锁支持
try:
    import fcntl  # Unix文件锁
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    # Windows平台使用 msvcrt
    try:
        import msvcrt
        HAS_MSVCRT = True
    except ImportError:
        HAS_MSVCRT = False

# 添加项目根目录到Python路径
_current_file_dir = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_current_file_dir)
sys.path.insert(0, BASE_DIR)

from server.config import DINGTALK_CONFIG, PUBLIC_BASE_URL
from server.dingtalk_notify_util import (
    get_dingtalk_access_token_unified,
    send_corpconversation_with_retry,
)
from server.logger import logger
from server.announcement_manager import AnnouncementManager
from server.todo_manager import TodoManager
from server.user_manager import UserManager
from server.system_config_manager import (
    get_config_manager, 
    CONFIG_KEY_SCHEDULED_NOTIFICATIONS_ENABLED,
    CONFIG_KEY_SCHEDULED_NOTIFICATIONS_TIMES
)


class ScheduledNotificationSender:
    """定时通知发送器"""
    
    def __init__(self):
        self.announcement_mgr = AnnouncementManager()
        self.todo_mgr = TodoManager()
        self.user_mgr = UserManager()
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.lock_file_path = None
        self.lock_file = None
        
        # 通知发送时间点（小时:分钟）- 默认值，可以从配置读取
        self.notification_times = [
            (8, 0),   # 8:00
            (12, 30), # 12:30
            (17, 30)  # 17:30
        ]
        
        # 初始化文件锁（用于多进程环境，确保只有一个进程执行定时任务）
        self._init_lock_file()
    
    def _init_lock_file(self):
        """初始化文件锁"""
        try:
            from server.config import DATA_DIR
            lock_dir = os.path.join(DATA_DIR, 'locks')
            os.makedirs(lock_dir, exist_ok=True)
            self.lock_file_path = os.path.join(lock_dir, 'scheduled_notifications.lock')
        except Exception as e:
            logger.warning(f"初始化文件锁失败: {e}，将使用进程锁")
            self.lock_file_path = None
    
    def _acquire_process_lock(self) -> bool:
        """尝试获取进程锁（防止多进程重复执行）
        
        Returns:
            是否成功获取锁
        """
        if not self.lock_file_path:
            return True  # 如果没有锁文件路径，允许执行（单进程环境）
        
        try:
            # 尝试打开锁文件
            self.lock_file = open(self.lock_file_path, 'w')
            # 尝试获取非阻塞排他锁
            try:
                if HAS_FCNTL:
                    # Unix/Linux平台
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif HAS_MSVCRT:
                    # Windows平台
                    msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    # 不支持文件锁的平台，使用简单的文件存在检查
                    if os.path.exists(self.lock_file_path):
                        # 检查锁文件是否过期（超过1小时认为过期）
                        try:
                            mtime = os.path.getmtime(self.lock_file_path)
                            if time.time() - mtime > 3600:
                                # 锁文件过期，删除它
                                os.remove(self.lock_file_path)
                            else:
                                # 锁文件有效，其他进程正在运行
                                self.lock_file.close()
                                self.lock_file = None
                                return False
                        except:
                            pass
                
                # 写入进程ID
                self.lock_file.write(str(os.getpid()))
                self.lock_file.flush()
                return True
            except (BlockingIOError, OSError):
                # 锁已被其他进程持有
                self.lock_file.close()
                self.lock_file = None
                return False
        except Exception as e:
            logger.warning(f"获取进程锁失败: {e}，将允许执行（可能在其他操作系统上）")
            if self.lock_file:
                try:
                    self.lock_file.close()
                except:
                    pass
                self.lock_file = None
            return True  # 出错时允许执行，避免完全无法运行
    
    def _release_process_lock(self):
        """释放进程锁"""
        if self.lock_file:
            try:
                if HAS_FCNTL:
                    # Unix/Linux平台
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                elif HAS_MSVCRT:
                    # Windows平台
                    msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                
                self.lock_file.close()
                self.lock_file = None
                # 删除锁文件
                if self.lock_file_path and os.path.exists(self.lock_file_path):
                    try:
                        os.remove(self.lock_file_path)
                    except:
                        pass
            except Exception as e:
                logger.warning(f"释放进程锁失败: {e}")
    
    def start(self):
        """启动定时任务"""
        if self.running:
            logger.warning("定时通知任务已在运行中")
            return
        
        # 尝试获取进程锁
        if not self._acquire_process_lock():
            logger.info("定时通知任务已在其他进程中运行，跳过启动")
            return
        
        with self.lock:
            self.running = True
            self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
            self.thread.start()
            logger.info("定时通知任务已启动")
    
    def stop(self):
        """停止定时任务"""
        with self.lock:
            self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        # 释放进程锁
        self._release_process_lock()
        logger.info("定时通知任务已停止")
    
    def _run_scheduler(self):
        """运行调度器主循环"""
        logger.info("定时通知调度器开始运行")
        
        while self.running:
            try:
                # 检查配置，如果功能被禁用，则跳过
                config_mgr = get_config_manager()
                enabled = config_mgr.get_config_bool(CONFIG_KEY_SCHEDULED_NOTIFICATIONS_ENABLED, default_value=True)
                
                if not enabled:
                    # 功能被禁用，等待一段时间后再次检查
                    time.sleep(300)  # 5分钟检查一次配置
                    continue
                
                # 从配置读取通知时间（如果配置了的话）
                try:
                    times_json = config_mgr.get_config(CONFIG_KEY_SCHEDULED_NOTIFICATIONS_TIMES)
                    if times_json:
                        times_list = json.loads(times_json)
                        if isinstance(times_list, list) and len(times_list) > 0:
                            notification_times = [(t.get('hour', 0), t.get('minute', 0)) for t in times_list if isinstance(t, dict)]
                            if notification_times:
                                self.notification_times = notification_times
                except Exception as e:
                    logger.debug(f"读取通知时间配置失败，使用默认值: {e}")
                
                now = datetime.datetime.now()
                current_time = (now.hour, now.minute)
                
                # 检查是否到了通知时间
                for notify_hour, notify_minute in self.notification_times:
                    if current_time == (notify_hour, notify_minute):
                        # 检查是否已经执行过（避免同一分钟内重复执行）
                        if not hasattr(self, '_last_execution') or \
                           self._last_execution != (now.date(), notify_hour, notify_minute):
                            logger.info(f"到达通知时间 {notify_hour:02d}:{notify_minute:02d}，开始发送未读公告通知")
                            self._send_pending_notifications()
                            self._last_execution = (now.date(), notify_hour, notify_minute)
                            # 执行后等待1分钟，避免重复执行
                            time.sleep(60)
                
                # 每分钟检查一次
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"定时通知调度器运行出错: {e}", exc_info=True)
                time.sleep(60)  # 出错后等待1分钟再继续
    
    def _send_pending_notifications(self):
        """发送待完成阅读的公告通知"""
        try:
            logger.info("=" * 60)
            logger.info("开始检查并发送未读公告通知")
            
            # 1. 获取所有已审批的公告
            announcements = self.announcement_mgr.get_announcements(status='approved', include_temp=False)
            logger.info(f"找到 {len(announcements)} 条已审批公告")
            
            if not announcements:
                logger.info("没有已审批的公告，跳过通知发送")
                return
            
            # 2. 获取钉钉访问令牌
            access_token = self._get_dingtalk_access_token()
            if not access_token:
                logger.error("获取钉钉访问令牌失败，无法发送通知")
                return
            
            # 3. 统计信息
            total_announcements = 0
            total_users_notified = 0
            total_failed = 0
            
            # 4. 遍历每个公告，检查未完成阅读的用户
            for announcement in announcements:
                announcement_id = announcement.get('id')
                title = announcement.get('title', '无标题')
                
                if not announcement_id:
                    continue
                
                # 获取该公告的所有待办记录
                todos = self.todo_mgr.get_all_todos(announcement_id)
                
                if not todos:
                    logger.debug(f"公告 {title} ({announcement_id}) 没有待办记录，跳过")
                    continue
                
                # 筛选未完成的用户
                pending_users = []
                for todo in todos:
                    status = todo.get('status', '未完成')
                    done = todo.get('done', False)
                    userid = todo.get('userid', '').strip()
                    
                    # 判断是否未完成：状态为"未完成"或done为False
                    if status not in ['已完成', 'done'] and not done and userid:
                        pending_users.append({
                            'userid': userid,
                            'unionid': todo.get('unionid', '').strip(),
                            'name': todo.get('name', ''),
                            'username': todo.get('username', '')
                        })
                
                if not pending_users:
                    logger.debug(f"公告 {title} ({announcement_id}) 所有用户已完成阅读，跳过")
                    continue
                
                # 记录待完成人数
                pending_count = len(pending_users)
                logger.info(f"公告 {title} ({announcement_id}) 有 {pending_count} 人未完成阅读")
                
                # 发送通知
                userids = [user['userid'] for user in pending_users if user['userid']]
                if userids:
                    total_announcements += 1
                    success_count, failed_count = self._send_notification_with_retry(
                        announcement_id=announcement_id,
                        title=title,
                        userids=userids,
                        access_token=access_token
                    )
                    total_users_notified += success_count
                    total_failed += failed_count
            
            # 5. 输出统计信息
            logger.info("=" * 60)
            logger.info(f"通知发送完成统计:")
            logger.info(f"  - 处理公告数: {total_announcements}")
            logger.info(f"  - 成功通知用户数: {total_users_notified}")
            logger.info(f"  - 失败用户数: {total_failed}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"发送待完成阅读公告通知时出错: {e}", exc_info=True)
    
    def _build_announcement_detail_url(self, announcement_id: str) -> str:
        """构建钉钉工作通知跳转链接。"""
        from server.dingtalk_url_util import build_announcement_detail_dingtalk_url
        base_url = (PUBLIC_BASE_URL or '').rstrip('/')
        if not base_url:
            logger.warning('PUBLIC_BASE_URL 未设置，工作通知跳转链接可能不完整')
        return build_announcement_detail_dingtalk_url(announcement_id, base_url)

    def _send_notification_with_retry(
        self,
        announcement_id: str,
        title: str,
        userids: List[str],
        access_token: str,
    ) -> tuple:
        """发送通知（共享 util 重试策略）。Returns: (成功数量, 失败数量)"""
        if not userids:
            return 0, 0

        detail_url_str = self._build_announcement_detail_url(announcement_id)
        text = f"请及时阅读公告：{title}"
        msg_content = {
            "msgtype": "link",
            "link": {
                "title": title,
                "text": text,
                "messageUrl": detail_url_str,
                "picUrl": "https://img.alicdn.com/imgextra/i1/O1CN01Kq8eYq1xWqJY5Y5Y5_!!6000000006441-2-tps-200-200.png",
            },
        }

        logger.info(f"定时发送阅读通知: 公告={title} ({announcement_id}), 用户数={len(userids)}")
        ok, err = send_corpconversation_with_retry(
            access_token,
            userids,
            msg_content,
            log_context=f" 定时 公告={announcement_id}",
        )
        if ok:
            return len(userids), 0
        logger.error(f"定时发送阅读通知失败: {err}")
        return 0, len(userids)

    def _get_dingtalk_access_token(self) -> Optional[str]:
        """获取钉钉访问令牌（与审批流程统一接口）。"""
        return get_dingtalk_access_token_unified()


# 全局单例
_notification_sender = None
_sender_lock = threading.Lock()


def get_notification_sender() -> ScheduledNotificationSender:
    """获取通知发送器单例"""
    global _notification_sender
    with _sender_lock:
        if _notification_sender is None:
            _notification_sender = ScheduledNotificationSender()
        return _notification_sender


def start_scheduled_notifications():
    """启动定时通知任务"""
    sender = get_notification_sender()
    sender.start()


def stop_scheduled_notifications():
    """停止定时通知任务"""
    sender = get_notification_sender()
    sender.stop()

