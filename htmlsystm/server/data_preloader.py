#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据预加载模块
在服务器启动时将常用数据加载到内存，避免频繁的文件I/O操作
"""
import os
import threading
import time
import logging
from typing import Dict, Any, List, Optional
from server.logger import logger
from server.config import (
    PRELOAD_USERS, PRELOAD_ANNOUNCEMENTS, PRELOAD_DEPARTMENTS, PRELOAD_TODOS,
    MEMORY_CACHE_TTL, TODO_AUTO_SAVE_ENABLED, TODO_AUTO_SAVE_INTERVAL,
    HOT_CACHE_TTL, NORMAL_CACHE_TTL, DATA_DIR
)

class DataPreloader:
    """数据预加载器，将常用数据加载到内存"""
    
    def __init__(self):
        self.user_manager = None
        self.announcement_mgr = None
        self.department_mgr = None
        self.todo_mgr = None
        
        # 内存缓存
        self.users_cache = {}  # {key: (data, timestamp)}
        self.announcements_cache = {}  # {announcement_id: (data, timestamp)}
        self.departments_cache = {}  # {key: (data, timestamp)}
        self.todos_cache = {}  # {announcement_id: (data, timestamp)}
        
        # 待办数据修改标记（用于定期持久化）
        self.todos_dirty = set()  # {announcement_id} 标记哪些公告的待办数据被修改了
        self.todos_last_save_time = {}  # {announcement_id: timestamp} 记录最后保存时间
        
        self.cache_lock = threading.RLock()
        self.last_reload_time = {}  # 记录最后重新加载时间
        
        # 跨进程缓存同步标记文件路径
        self.cache_invalidation_marker = os.path.join(DATA_DIR, '.cache_invalidation_marker')
        self.todo_cache_invalidation_marker = os.path.join(DATA_DIR, '.todo_cache_invalidation_marker')
        
        # 初始化线程相关属性
        self.todo_save_thread = None
        self.stop_save_thread = threading.Event()
        
        # 健康检查相关
        self.health_check_thread = None
        self.stop_health_check = threading.Event()
        self.last_health_check_time = 0
        self.health_check_interval = 300  # 每5分钟检查一次
        
        # 启动定期保存线程
        self._start_auto_save_thread()
        
        # 启动健康检查线程
        self._start_health_check_thread()
        
    def set_managers(self, user_manager, announcement_mgr, department_mgr, todo_mgr):
        """设置管理器实例"""
        self.user_manager = user_manager
        self.announcement_mgr = announcement_mgr
        self.department_mgr = department_mgr
        self.todo_mgr = todo_mgr
        
        logger.info(f"[DEBUG] 预加载器设置管理器: user_manager={user_manager is not None}, announcement_mgr={announcement_mgr is not None}, department_mgr={department_mgr is not None}, todo_mgr={todo_mgr is not None}")
        
        # 启动待办数据自动保存线程（如果启用）
        if TODO_AUTO_SAVE_ENABLED and self.todo_mgr:
            self._start_todo_auto_save_thread()
    
    def _start_auto_save_thread(self):
        """启动定期保存线程"""
        def auto_save_worker():
            """后台线程：定期保存修改的待办数据到文件"""
            while True:
                try:
                    time.sleep(TODO_AUTO_SAVE_INTERVAL)
                    self._save_dirty_todos()
                except Exception as e:
                    logger.error(f"定期保存待办数据时发生错误: {e}", exc_info=True)
        
        save_thread = threading.Thread(target=auto_save_worker, daemon=True, name="TodoAutoSave")
        save_thread.start()
        logger.info(f"已启动待办数据自动保存线程（间隔: {TODO_AUTO_SAVE_INTERVAL}秒）")
    
    def _start_health_check_thread(self):
        """启动健康检查线程"""
        def health_check_worker():
            """后台线程：定期检查预加载器健康状态，自动恢复异常缓存"""
            while not self.stop_health_check.is_set():
                try:
                    time.sleep(self.health_check_interval)
                    self._perform_health_check()
                except Exception as e:
                    logger.error(f"健康检查线程发生错误: {e}", exc_info=True)
        
        self.health_check_thread = threading.Thread(target=health_check_worker, daemon=True, name="PreloaderHealthCheck")
        self.health_check_thread.start()
        logger.info(f"已启动预加载器健康检查线程（间隔: {self.health_check_interval}秒）")
    
    def _perform_health_check(self):
        """执行健康检查，检测缓存是否异常并自动恢复"""
        try:
            current_time = time.time()
            self.last_health_check_time = current_time
            
            # 检查公告缓存
            if PRELOAD_ANNOUNCEMENTS and self.announcement_mgr:
                with self.cache_lock:
                    cache_count = len(self.announcements_cache)
                
                # 如果缓存为空或数量异常少，尝试从文件检查
                if cache_count <= 2:
                    try:
                        # 从文件获取公告数量（快速检查）
                        file_announcements = self.announcement_mgr.get_announcements(status='approved', include_temp=False)
                        file_count = len(file_announcements) if file_announcements else 0
                        
                        # 如果文件中有更多公告，说明缓存异常，需要恢复
                        if file_count > cache_count + 2:
                            logger.warning(f"健康检查：检测到公告缓存异常（缓存: {cache_count} 条，文件: {file_count} 条），开始恢复...")
                            try:
                                self._preload_announcements()
                                logger.info(f"健康检查：公告缓存已恢复（从 {cache_count} 条恢复到 {len(self.announcements_cache)} 条）")
                            except Exception as e:
                                logger.error(f"健康检查：恢复公告缓存失败: {e}", exc_info=True)
                    except Exception as e:
                        logger.debug(f"健康检查：检查公告缓存时出错: {e}")
            
            # 检查待办缓存（可选）
            if PRELOAD_TODOS and self.todo_mgr:
                with self.cache_lock:
                    todo_cache_count = len(self.todos_cache)
                # 如果待办缓存为空，尝试重新加载（但不强制，因为待办数据可能确实为空）
                if todo_cache_count == 0:
                    logger.debug("健康检查：待办缓存为空，尝试重新加载...")
                    try:
                        self._preload_todos()
                    except Exception as e:
                        logger.debug(f"健康检查：重新加载待办缓存失败: {e}")
        except Exception as e:
            logger.error(f"健康检查执行失败: {e}", exc_info=True)
    
    def _save_dirty_todos(self):
        """保存所有标记为dirty的待办数据到Excel文件"""
        if not self.todo_mgr:
            return
        
        with self.cache_lock:
            if not self.todos_dirty:
                return  # 没有需要保存的数据
            
            dirty_list = list(self.todos_dirty)
            self.todos_dirty.clear()  # 先清空，避免重复保存
        
        # 在锁外保存文件，避免长时间持有锁
        saved_count = 0
        failed_count = 0
        
        for announcement_id in dirty_list:
            try:
                if announcement_id in self.todos_cache:
                    todos, _ = self.todos_cache[announcement_id]
                    # 将内存数据写回Excel文件
                    success = self.todo_mgr.save_todos_to_file(announcement_id, todos)
                    if success:
                        saved_count += 1
                        with self.cache_lock:
                            self.todos_last_save_time[announcement_id] = time.time()
                        logger.debug(f"自动保存待办数据到文件: announcement_id={announcement_id}, count={len(todos)}")
                    else:
                        failed_count += 1
                        # 保存失败，重新标记为dirty
                        with self.cache_lock:
                            self.todos_dirty.add(announcement_id)
            except Exception as e:
                logger.error(f"保存待办数据到文件失败: announcement_id={announcement_id}, error={e}", exc_info=True)
                failed_count += 1
                # 保存失败，重新标记为dirty
                with self.cache_lock:
                    self.todos_dirty.add(announcement_id)
        
        if saved_count > 0:
            logger.info(f"定期保存待办数据完成: 成功={saved_count}, 失败={failed_count}")
    
    def mark_todos_dirty(self, announcement_id: str):
        """标记待办数据为已修改（需要保存）
        
        Args:
            announcement_id: 公告ID
        """
        with self.cache_lock:
            self.todos_dirty.add(announcement_id)
    
    def preload_all(self, user_manager=None, announcement_mgr=None, department_mgr=None, todo_mgr=None):
        """预加载所有数据到内存"""
        # 如果提供了管理器实例，使用它们
        if user_manager:
            self.user_manager = user_manager
        if announcement_mgr:
            self.announcement_mgr = announcement_mgr
        if department_mgr:
            self.department_mgr = department_mgr
        if todo_mgr:
            self.todo_mgr = todo_mgr
        
        logger.info("=" * 60)
        logger.info("🔄 开始预加载数据到内存...")
        logger.info("=" * 60)
        
        start_time = time.time()
        
        if PRELOAD_USERS and self.user_manager:
            self._preload_users()
        
        if PRELOAD_DEPARTMENTS and self.department_mgr:
            self._preload_departments()
        
        if PRELOAD_ANNOUNCEMENTS and self.announcement_mgr:
            self._preload_announcements()
        
        if PRELOAD_TODOS and self.todo_mgr:
            self._preload_todos()
        
        elapsed_time = time.time() - start_time
        logger.info("=" * 60)
        logger.info(f"✅ 数据预加载完成，耗时 {elapsed_time:.2f} 秒")
        logger.info(f"   - 用户数据: {len(self.users_cache)} 条")
        logger.info(f"   - 公告数据: {len(self.announcements_cache)} 条")
        logger.info(f"   - 部门数据: {len(self.departments_cache)} 条")
        logger.info(f"   - 待办数据: {len(self.todos_cache)} 条")
        logger.info("=" * 60)
    
    def _preload_users(self):
        """预加载用户数据"""
        try:
            logger.info("📋 预加载用户数据...")
            users = self.user_manager.get_all_users()
            with self.cache_lock:
                self.users_cache['all_users'] = (users, time.time())
                self.users_cache['active_users'] = (
                    [u for u in users if u.get('status') == 'active'],
                    time.time()
                )
            logger.info(f"   ✅ 已加载 {len(users)} 个用户到内存")
        except Exception as e:
            logger.error(f"   ❌ 预加载用户数据失败: {e}", exc_info=True)
    
    def _preload_announcements(self):
        """预加载公告数据"""
        try:
            logger.info("📋 预加载公告数据...")
            if not self.announcement_mgr:
                logger.warning("公告管理器未设置，无法预加载公告数据")
                return
            
            # 只加载已审批的公告（status='approved'）
            announcements = self.announcement_mgr.get_announcements(status='approved', include_temp=False)
            with self.cache_lock:
                # 清空旧缓存
                self.announcements_cache.clear()
                # 加载新数据
                for ann in announcements:
                    ann_id = ann.get('id')
                    if ann_id:
                        self.announcements_cache[ann_id] = (ann, time.time())
            logger.info(f"   ✅ 已加载 {len(announcements)} 条公告到内存")
        except Exception as e:
            logger.error(f"   ❌ 预加载公告数据失败: {e}", exc_info=True)
            # 即使加载失败，也确保缓存字典存在（即使为空）
            with self.cache_lock:
                if not hasattr(self, 'announcements_cache') or self.announcements_cache is None:
                    self.announcements_cache = {}
    
    def _preload_departments(self):
        """预加载部门数据"""
        try:
            logger.info("📋 预加载部门数据...")
            # 使用正确的方法名
            departments = self.department_mgr.get_departments()
            with self.cache_lock:
                self.departments_cache['all_departments'] = (departments, time.time())
            logger.info(f"   ✅ 已加载 {len(departments)} 个部门到内存")
        except Exception as e:
            logger.error(f"   ❌ 预加载部门数据失败: {e}", exc_info=True)
    
    def _preload_todos(self):
        """预加载待办数据（按公告ID组织）
        
        重要：加载所有待办Excel文件，包括temp目录中的公告，确保所有待办数据都在内存中
        同时，为所有已存在的公告ID创建空缓存条目，避免后续从文件加载
        """
        try:
            logger.info("📋 预加载待办数据...")
            import glob
            from server.config import DATA_DIR
            
            # 直接扫描todos目录下的所有Excel文件，确保加载所有待办数据
            todos_dir = os.path.join(DATA_DIR, 'todos')
            if not os.path.exists(todos_dir):
                logger.warning(f"待办目录不存在: {todos_dir}")
                # 即使目录不存在，也要为所有公告创建空缓存条目
                self._preload_empty_todos_for_announcements()
                return
            
            todo_files = glob.glob(os.path.join(todos_dir, 'announcement_*_todos.xlsx'))
            logger.info(f"找到 {len(todo_files)} 个待办Excel文件")
            
            todo_count = 0
            loaded_announcements = set()
            
            for file_path in todo_files:
                try:
                    # 从文件名提取announcement_id
                    filename = os.path.basename(file_path)
                    # 格式: announcement_{announcement_id}_todos.xlsx
                    if filename.startswith('announcement_') and filename.endswith('_todos.xlsx'):
                        ann_id = filename[13:-11]  # 提取中间的ID部分（修正：_todos.xlsx是11个字符）
                        if ann_id and self.todo_mgr:
                            todos = self.todo_mgr.get_all_todos(ann_id)
                            # 即使todos为空，也要缓存（避免后续从文件加载）
                            with self.cache_lock:
                                self.todos_cache[ann_id] = (todos, time.time())
                            if todos:
                                todo_count += len(todos)
                                logger.debug(f"从文件 {filename} 加载了 {len(todos)} 条待办数据")
                            else:
                                logger.warning(f"从文件 {filename} 加载了 0 条待办数据（文件可能为空或格式不正确，announcement_id={ann_id}）")
                            loaded_announcements.add(ann_id)
                except Exception as e:
                    logger.warning(f"加载待办文件失败: {file_path}, 错误: {e}", exc_info=True)
                    continue
            
            # 为所有已存在的公告创建空缓存条目（避免后续从文件加载）
            self._preload_empty_todos_for_announcements(loaded_announcements)
            
            logger.info(f"   ✅ 已加载 {todo_count} 条待办数据到内存（{len(self.todos_cache)} 个公告的缓存条目）")
        except Exception as e:
            logger.error(f"   ❌ 预加载待办数据失败: {e}", exc_info=True)
    
    def _preload_empty_todos_for_announcements(self, exclude_ids=None):
        """为所有公告创建空待办缓存条目（避免后续从文件加载）
        
        Args:
            exclude_ids: 已加载的公告ID集合，这些不需要再创建空缓存
        """
        if exclude_ids is None:
            exclude_ids = set()
        
        try:
            # 从公告缓存中获取所有公告ID
            with self.cache_lock:
                announcement_ids = set(self.announcements_cache.keys())
            
            # 为没有待办文件的公告创建空缓存条目
            for ann_id in announcement_ids:
                if ann_id not in exclude_ids and ann_id not in self.todos_cache:
                    with self.cache_lock:
                        self.todos_cache[ann_id] = ([], time.time())
        except Exception as e:
            # 如果获取公告列表失败，不影响主流程
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"为公告创建空待办缓存失败: {e}")
    
    def get_users(self, status=None, force_reload=False):
        """从内存缓存获取用户数据
        
        跨进程缓存同步：检查标记文件，如果标记文件比缓存新，则重新加载缓存。
        
        Args:
            status: 用户状态过滤（'active' 或其他）
            force_reload: 是否强制重新加载（忽略缓存）
        """
        # 检查跨进程缓存失效标记（在锁外检查，避免长时间持有锁）
        marker_mtime = None
        user_marker = os.path.join(DATA_DIR, '.user_cache_invalidation_marker')
        if os.path.exists(user_marker):
            try:
                marker_mtime = os.path.getmtime(user_marker)
            except Exception:
                pass  # 文件可能被删除，忽略错误
        
        with self.cache_lock:
            if status == 'active':
                cache_key = 'active_users'
            else:
                cache_key = 'all_users'
            
            # 检查缓存是否需要重新加载（跨进程同步）
            cache_needs_reload = False
            if marker_mtime:
                cache_timestamp = 0
                if cache_key in self.users_cache:
                    _, cache_timestamp = self.users_cache[cache_key]
                # 如果标记文件比缓存新0.5秒以上，需要重新加载
                if marker_mtime > cache_timestamp + 0.5:
                    cache_needs_reload = True
                    logger.debug(f"检测到用户缓存失效标记（跨进程同步），标记时间: {marker_mtime}, 缓存时间: {cache_timestamp}")
            
            if cache_needs_reload:
                # 跨进程缓存失效，清除缓存，强制重新加载
                self.users_cache.pop(cache_key, None)
                logger.debug(f"已清除用户缓存（跨进程同步）: cache_key={cache_key}")
            
            # 如果强制重新加载，清除缓存
            if force_reload:
                self.users_cache.pop(cache_key, None)
                logger.info(f"强制重新加载用户数据（忽略缓存）")
            
            if cache_key in self.users_cache and not force_reload:
                data, timestamp = self.users_cache[cache_key]
                cache_ttl = NORMAL_CACHE_TTL
                if time.time() - timestamp < cache_ttl:
                    return data
            stale_cached = self.users_cache.get(cache_key)

        # 在锁外加载，避免 get_all_users 阻塞其它请求的 auth/check
        users = None
        if self.user_manager:
            try:
                users = self.user_manager.get_all_users()
                if status == 'active':
                    users = [u for u in users if u.get('status') == 'active']
            except Exception as e:
                logger.error(f"重新加载用户数据失败: {e}", exc_info=True)
                users = None
        else:
            try:
                from server.main import HardwareRDBHandler
                if hasattr(HardwareRDBHandler, '_user_manager') and HardwareRDBHandler._user_manager:
                    self.user_manager = HardwareRDBHandler._user_manager
                    users = self.user_manager.get_all_users()
                    if status == 'active':
                        users = [u for u in users if u.get('status') == 'active']
            except Exception as e:
                logger.error(f"从HardwareRDBHandler重新加载用户数据失败: {e}", exc_info=True)
                users = None

        with self.cache_lock:
            if users is not None:
                self.users_cache[cache_key] = (users, time.time())
                logger.info(f"重新加载用户数据: {len(users)} 个用户（状态={status or 'all'}）")
                return users
            if stale_cached:
                data, _ = stale_cached
                return data
            return []
    
    def get_announcement(self, announcement_id: str):
        """从内存缓存获取公告数据"""
        with self.cache_lock:
            if announcement_id in self.announcements_cache:
                data, timestamp = self.announcements_cache[announcement_id]
                # 阶段1优化：根据公告创建时间判断是否为热点数据
                cache_ttl = NORMAL_CACHE_TTL
                if data:
                    created_time = data.get('created_time') or data.get('create_time')
                    if created_time:
                        try:
                            from datetime import datetime
                            if isinstance(created_time, str):
                                created_dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                            else:
                                created_dt = created_time
                            days_old = (datetime.now() - created_dt.replace(tzinfo=None)).days
                            if days_old <= 30:  # 最近30天的公告使用热点缓存TTL
                                cache_ttl = HOT_CACHE_TTL
                        except Exception:
                            pass  # 解析失败，使用默认TTL
                if time.time() - timestamp < cache_ttl:
                    return data
            
            # 缓存过期或不存在，重新加载
            if self.announcement_mgr:
                ann = self.announcement_mgr.get_announcement(announcement_id)
                if ann:
                    self.announcements_cache[announcement_id] = (ann, time.time())
                return ann
            return None
    
    def get_announcements_cached(self, status: Optional[str] = None):
        """从内存缓存获取公告列表
        
        重要：当查询approved状态的公告时，只返回正式目录中的approved版本，
        不包含temp目录中的pending副本（编辑已发布公告时创建）。
        这样可以确保已发布公告在再次提交审核后，主页仍然显示原版本。
        
        跨进程缓存同步：检查标记文件，如果标记文件比缓存新，则重新加载缓存。
        改进：确保即使缓存为空或加载失败，也能从文件读取数据。
        """
        # 检查跨进程缓存失效标记（在锁外检查，避免长时间持有锁）
        marker_mtime = None
        if os.path.exists(self.cache_invalidation_marker):
            try:
                marker_mtime = os.path.getmtime(self.cache_invalidation_marker)
            except Exception:
                pass  # 文件可能被删除，忽略错误
        
        with self.cache_lock:
            # 获取所有缓存的公告
            cached_announcements = []
            current_time = time.time()
            cache_needs_reload = False
            last_reload_time = self.last_reload_time.get('announcements', 0)
            
            # 检查缓存是否需要重新加载（跨进程同步）
            # 改进：避免过于频繁的重新加载（至少间隔1秒）
            if marker_mtime and (current_time - last_reload_time) > 1.0:
                # 检查缓存中最早的timestamp
                oldest_timestamp = current_time
                if self.announcements_cache:
                    oldest_timestamp = min(timestamp for _, (_, timestamp) in self.announcements_cache.items())
                # 如果标记文件比缓存新，需要重新加载
                # 改进：增加时间差阈值，避免过于频繁的重新加载
                # 注意：如果缓存为空（oldest_timestamp == current_time），不触发重新加载
                if self.announcements_cache and marker_mtime > oldest_timestamp + 0.5:  # 标记文件必须比缓存新0.5秒以上
                    cache_needs_reload = True
                    logger.debug(f"检测到缓存失效标记（跨进程同步），标记时间: {marker_mtime}, 缓存时间: {oldest_timestamp}")
            
            if cache_needs_reload:
                # 跨进程缓存失效，重新加载
                logger.info("检测到跨进程缓存失效标记，重新加载公告缓存")
                if self.announcement_mgr:
                    try:
                        self._preload_announcements()
                        self.last_reload_time['announcements'] = current_time
                    except Exception as e:
                        logger.error(f"重新加载公告缓存失败: {e}", exc_info=True)
                        # 即使加载失败，也继续使用现有缓存
            
            for ann_id, (ann_data, timestamp) in self.announcements_cache.items():
                # 阶段1优化：根据公告创建时间判断是否为热点数据
                cache_ttl = NORMAL_CACHE_TTL
                if ann_data:
                    created_time = ann_data.get('created_time') or ann_data.get('create_time')
                    if created_time:
                        try:
                            from datetime import datetime
                            if isinstance(created_time, str):
                                created_dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                            else:
                                created_dt = created_time
                            days_old = (datetime.now() - created_dt.replace(tzinfo=None)).days
                            if days_old <= 30:  # 最近30天的公告使用热点缓存TTL
                                cache_ttl = HOT_CACHE_TTL
                        except Exception:
                            pass  # 解析失败，使用默认TTL
                if current_time - timestamp < cache_ttl:
                    cached_announcements.append(ann_data)
            
            # 如果缓存为空，尝试重新加载（但只尝试一次，避免无限循环）
            if not cached_announcements and self.announcement_mgr:
                # 检查是否刚刚尝试过加载（避免频繁重试）
                if (current_time - last_reload_time) > 5.0:  # 至少间隔5秒
                    logger.warning("公告缓存为空，尝试重新加载")
                    try:
                        # 重新预加载（只加载approved状态的公告，不包含temp目录）
                        self._preload_announcements()
                        self.last_reload_time['announcements'] = current_time
                        # 重新获取
                        for ann_id, (ann_data, timestamp) in self.announcements_cache.items():
                            cached_announcements.append(ann_data)
                    except Exception as e:
                        logger.error(f"重新加载公告缓存失败: {e}", exc_info=True)
                        # 即使加载失败，也返回空列表（调用者会从文件读取）
            
            # 按状态过滤
            if status:
                cached_announcements = [a for a in cached_announcements if a.get('status') == status]
            
            return cached_announcements
    
    def get_departments(self):
        """从内存缓存获取部门数据
        
        跨进程缓存同步：检查标记文件，如果标记文件比缓存新，则重新加载缓存。
        """
        # 检查跨进程缓存失效标记（在锁外检查，避免长时间持有锁）
        marker_mtime = None
        dept_marker = os.path.join(DATA_DIR, '.department_cache_invalidation_marker')
        if os.path.exists(dept_marker):
            try:
                marker_mtime = os.path.getmtime(dept_marker)
            except Exception:
                pass  # 文件可能被删除，忽略错误
        
        with self.cache_lock:
            # 检查缓存是否需要重新加载（跨进程同步）
            cache_needs_reload = False
            if marker_mtime:
                cache_timestamp = 0
                if 'all_departments' in self.departments_cache:
                    _, cache_timestamp = self.departments_cache['all_departments']
                # 如果标记文件比缓存新0.5秒以上，需要重新加载
                if marker_mtime > cache_timestamp + 0.5:
                    cache_needs_reload = True
                    logger.debug(f"检测到部门缓存失效标记（跨进程同步），标记时间: {marker_mtime}, 缓存时间: {cache_timestamp}")
            
            if cache_needs_reload:
                # 跨进程缓存失效，清除缓存，强制重新加载
                self.departments_cache.pop('all_departments', None)
                logger.debug("已清除部门缓存（跨进程同步）")
            
            if 'all_departments' in self.departments_cache:
                data, timestamp = self.departments_cache['all_departments']
                # 阶段1优化：部门数据使用普通缓存TTL
                cache_ttl = NORMAL_CACHE_TTL
                if time.time() - timestamp < cache_ttl:
                    return data
            
            # 缓存过期或不存在，重新加载
            if self.department_mgr:
                departments = self.department_mgr.get_departments()
                self.departments_cache['all_departments'] = (departments, time.time())
                return departments
            return []
    
    def _get_todo_invalidation_marker_time(self) -> Optional[float]:
        """获取待办缓存跨进程失效标记时间（优先 version 文件）。"""
        try:
            from server.cache_sync import check_cache_invalidation
            marker_time = check_cache_invalidation('todos')
            if marker_time is not None:
                return marker_time
        except Exception:
            pass
        if os.path.exists(self.todo_cache_invalidation_marker):
            try:
                return os.path.getmtime(self.todo_cache_invalidation_marker)
            except Exception:
                pass
        return None
    
    def get_todos(self, announcement_id: str):
        """从内存缓存获取待办数据
        
        重要：在高并发场景下，应该通过预加载确保所有数据都在缓存中
        如果缓存中不存在或过期，尝试从文件加载（作为后备方案）
        
        跨进程缓存同步：检查标记文件，如果标记文件比缓存新，则重新加载缓存。
        """
        marker_mtime = self._get_todo_invalidation_marker_time()
        
        with self.cache_lock:
            cache_needs_reload = False
            
            if marker_mtime:
                cache_timestamp = 0
                if announcement_id in self.todos_cache:
                    _, cache_timestamp = self.todos_cache[announcement_id]
                if marker_mtime > cache_timestamp:
                    cache_needs_reload = True
                    logger.debug(f"检测到待办缓存失效标记（跨进程同步），标记时间: {marker_mtime}, 缓存时间: {cache_timestamp}, announcement_id={announcement_id}")
            
            if cache_needs_reload:
                old_cache = self.todos_cache.pop(announcement_id, None)
                logger.debug(f"已清除待办缓存（跨进程同步）: announcement_id={announcement_id}")
                needs_file_reload = True
                old_cache_data = old_cache[0] if old_cache else None
            else:
                needs_file_reload = False
                old_cache_data = None
            
            if announcement_id in self.todos_cache:
                data, timestamp = self.todos_cache[announcement_id]
                cache_ttl = NORMAL_CACHE_TTL
                if time.time() - timestamp < cache_ttl:
                    return data
                del self.todos_cache[announcement_id]
                needs_file_reload = True
            
            if needs_file_reload or announcement_id not in self.todos_cache:
                pass
        
        if needs_file_reload or announcement_id not in self.todos_cache:
            if self.todo_mgr:
                try:
                    todos = self.todo_mgr.get_all_todos(announcement_id)
                    if todos is not None:
                        # 重新缓存加载的数据，使用当前时间戳确保缓存是最新的
                        with self.cache_lock:
                            self.todos_cache[announcement_id] = (todos, time.time())
                        logger.debug(f"从文件重新加载待办数据并更新缓存: announcement_id={announcement_id}, count={len(todos)}")
                        return todos
                    else:
                        # 如果返回None，使用旧缓存（如果存在）
                        if old_cache_data is not None:
                            logger.warning(f"从文件加载待办数据返回None，使用旧缓存: announcement_id={announcement_id}")
                            with self.cache_lock:
                                self.todos_cache[announcement_id] = (old_cache_data, time.time())
                            return old_cache_data
                        else:
                            # 如果返回None且无旧缓存，不要创建空缓存条目，而是返回空列表
                            # 这样下次请求时会再次尝试加载，而不是一直返回空列表
                            logger.warning(f"从文件加载待办数据返回None，且无旧缓存: announcement_id={announcement_id}")
                            return []
                except Exception as e:
                    logger.warning(f"从文件加载待办数据失败: announcement_id={announcement_id}, error={e}")
                    # 如果重新加载失败，使用旧缓存（如果存在）
                    if old_cache_data is not None:
                        with self.cache_lock:
                            self.todos_cache[announcement_id] = (old_cache_data, time.time())
                        logger.debug(f"使用旧缓存（重新加载失败）: announcement_id={announcement_id}")
                        return old_cache_data
                    else:
                        # 加载失败且无旧缓存时，不要创建空缓存条目，而是返回空列表
                        # 这样下次请求时会再次尝试加载，而不是一直返回空列表
                        # 但是，如果这是第一次加载（缓存不存在），可以创建一个空缓存条目，避免频繁重试
                        with self.cache_lock:
                            # 只有在缓存确实不存在时才创建空缓存条目（避免频繁重试）
                            if announcement_id not in self.todos_cache:
                                self.todos_cache[announcement_id] = ([], time.time())
                                logger.debug(f"创建空缓存条目（首次加载失败）: announcement_id={announcement_id}")
                        return []
            
            # 没有todo_mgr，返回空列表
            return []
        
        # 如果执行到这里，说明缓存存在且有效（不应该发生，因为上面已经return了）
        # 但为了安全，再次检查
        with self.cache_lock:
            if announcement_id in self.todos_cache:
                data, timestamp = self.todos_cache[announcement_id]
                return data
        
        # 如果缓存不存在，返回空列表
        return []
    
    def get_todos_for_announcement_cached(self, announcement_id: str):
        """从内存缓存获取某个公告的所有待办数据（别名方法，兼容性）"""
        return self.get_todos(announcement_id)
    
    def get_user_todo_status_cached(self, announcement_id: str, userid: str):
        """从内存缓存获取某个用户在某个公告的待办状态
        
        重要：只从内存缓存查找，不读取文件
        如果缓存中不存在，返回None（由调用方决定是否回退到文件读取）
        
        跨进程缓存同步：检查标记文件，如果标记文件比缓存新，则重新加载缓存。
        """
        marker_mtime = self._get_todo_invalidation_marker_time()
        userid_str = str(userid).strip()
        with self.cache_lock:
            cache_needs_reload = False
            
            # 检查缓存是否需要重新加载（跨进程同步）
            if marker_mtime:
                # 检查该公告的缓存timestamp
                cache_timestamp = 0
                if announcement_id in self.todos_cache:
                    _, cache_timestamp = self.todos_cache[announcement_id]
                # 如果标记文件比缓存新，需要重新加载
                if marker_mtime > cache_timestamp:
                    cache_needs_reload = True
                    logger.debug(f"检测到待办缓存失效标记（跨进程同步），标记时间: {marker_mtime}, 缓存时间: {cache_timestamp}, announcement_id={announcement_id}")
            
            if cache_needs_reload:
                # 跨进程缓存失效，清除该公告的缓存，强制从文件重新加载
                # 注意：不能在锁内调用文件操作，需要在锁外重新加载
                old_cache = self.todos_cache.pop(announcement_id, None)
                logger.debug(f"已清除待办缓存（跨进程同步）: announcement_id={announcement_id}")
                # 标记需要从文件重新加载（在锁外进行，避免死锁）
                needs_file_reload = True
                # 保存旧缓存作为后备（如果重新加载失败，可以使用旧缓存）
                old_cache_data = old_cache[0] if old_cache else None
            else:
                needs_file_reload = False
                old_cache_data = None
            
            if announcement_id in self.todos_cache:
                data, timestamp = self.todos_cache[announcement_id]
                # 不检查缓存是否过期，直接使用缓存数据（因为更新时会更新时间戳）
                # 这样可以确保更新后的数据立即生效
                # 从缓存的待办列表中查找匹配的用户
                for todo in data:
                    todo_userid = str(todo.get('userid', '')).strip()
                    if todo_userid == userid_str:
                        return todo
            # 缓存中不存在，返回None（不自动加载文件，避免在高并发时造成性能问题）
            # 但是，如果需要重新加载，在锁外进行
            if needs_file_reload:
                pass
        
        # 在锁外从文件重新加载（避免死锁）
        if needs_file_reload:
            if self.todo_mgr:
                try:
                    todos = self.todo_mgr.get_all_todos(announcement_id)
                    if todos is not None:
                        # 重新缓存加载的数据
                        with self.cache_lock:
                            self.todos_cache[announcement_id] = (todos, time.time())
                        logger.debug(f"从文件重新加载待办数据并更新缓存（跨进程同步）: announcement_id={announcement_id}, count={len(todos)}")
                        # 从新加载的数据中查找用户
                        for todo in todos:
                            todo_userid = str(todo.get('userid', '')).strip()
                            if todo_userid == userid_str:
                                return todo
                    else:
                        # 如果返回None，使用旧缓存（如果存在）
                        if old_cache_data:
                            logger.warning(f"从文件重新加载待办数据返回None，使用旧缓存: announcement_id={announcement_id}")
                            with self.cache_lock:
                                self.todos_cache[announcement_id] = (old_cache_data, time.time())
                            # 从旧缓存中查找用户
                            for todo in old_cache_data:
                                todo_userid = str(todo.get('userid', '')).strip()
                                if todo_userid == userid_str:
                                    return todo
                        else:
                            logger.warning(f"从文件重新加载待办数据返回None，且无旧缓存: announcement_id={announcement_id}")
                except Exception as e:
                    logger.warning(f"从文件重新加载待办数据失败（跨进程同步）: announcement_id={announcement_id}, error={e}")
                    # 如果重新加载失败，使用旧缓存（如果存在）
                    if old_cache_data:
                        with self.cache_lock:
                            self.todos_cache[announcement_id] = (old_cache_data, time.time())
                        logger.debug(f"使用旧缓存（重新加载失败）: announcement_id={announcement_id}")
                        # 从旧缓存中查找用户
                        for todo in old_cache_data:
                            todo_userid = str(todo.get('userid', '')).strip()
                            if todo_userid == userid_str:
                                return todo
        
        # 缓存中不存在，返回None（不自动加载文件，避免在高并发时造成性能问题）
        return None
    
    def mark_todos_dirty(self, announcement_id: str):
        """标记待办数据为已修改（需要保存到文件）
        
        Args:
            announcement_id: 公告ID
        """
        with self.cache_lock:
            self.todos_dirty.add(announcement_id)
            logger.debug(f"标记待办数据为已修改: announcement_id={announcement_id}")
    
    def _start_todo_auto_save_thread(self):
        """启动待办数据自动保存线程"""
        if hasattr(self, 'todo_save_thread') and self.todo_save_thread and self.todo_save_thread.is_alive():
            logger.warning("待办数据自动保存线程已在运行")
            return
        
        def auto_save_worker():
            """自动保存工作线程"""
            logger.info(f"待办数据自动保存线程已启动，保存间隔: {TODO_AUTO_SAVE_INTERVAL}秒")
            while not self.stop_save_thread.is_set():
                try:
                    # 等待指定时间或收到停止信号
                    if self.stop_save_thread.wait(TODO_AUTO_SAVE_INTERVAL):
                        # 收到停止信号
                        break
                    
                    # 检查是否有需要保存的待办数据
                    dirty_announcements = []
                    with self.cache_lock:
                        if self.todos_dirty:
                            dirty_announcements = list(self.todos_dirty)
                            self.todos_dirty.clear()  # 清空dirty集合
                    
                    if dirty_announcements:
                        logger.info(f"开始自动保存 {len(dirty_announcements)} 个公告的待办数据...")
                        saved_count = 0
                        failed_count = 0
                        
                        for announcement_id in dirty_announcements:
                            try:
                                # 从内存缓存获取待办数据
                                if announcement_id in self.todos_cache:
                                    todos, _ = self.todos_cache[announcement_id]
                                    # 保存到文件
                                    if self.todo_mgr and self.todo_mgr.save_todos_to_file(announcement_id, todos):
                                        saved_count += 1
                                        logger.debug(f"自动保存待办数据成功: announcement_id={announcement_id}")
                                    else:
                                        failed_count += 1
                                        logger.warning(f"自动保存待办数据失败: announcement_id={announcement_id}")
                            except Exception as e:
                                failed_count += 1
                                logger.error(f"自动保存待办数据时发生错误: announcement_id={announcement_id}, error={e}", exc_info=True)
                        
                        if saved_count > 0:
                            logger.info(f"自动保存完成: 成功 {saved_count} 个，失败 {failed_count} 个")
                        else:
                            logger.debug("没有需要保存的待办数据")
                    
                except Exception as e:
                    logger.error(f"待办数据自动保存线程发生错误: {e}", exc_info=True)
                    # 发生错误时等待一段时间再继续
                    time.sleep(5)
            
            logger.info("待办数据自动保存线程已停止")
        
        self.todo_save_thread = threading.Thread(target=auto_save_worker, daemon=True, name="TodoAutoSave")
        self.todo_save_thread.start()
    
    def stop_todo_auto_save(self):
        """停止待办数据自动保存线程"""
        if self.todo_save_thread and self.todo_save_thread.is_alive():
            logger.info("正在停止待办数据自动保存线程...")
            self.stop_save_thread.set()
            self.todo_save_thread.join(timeout=10)
            if self.todo_save_thread.is_alive():
                logger.warning("待办数据自动保存线程未能及时停止")
            else:
                logger.info("待办数据自动保存线程已停止")
    
    def force_save_dirty_todos(self):
        """强制保存所有dirty的待办数据到文件（立即保存，不等待定时器）
        
        用于服务器关闭前确保数据不丢失
        """
        dirty_announcements = []
        with self.cache_lock:
            if self.todos_dirty:
                dirty_announcements = list(self.todos_dirty)
                self.todos_dirty.clear()
        
        if dirty_announcements:
            logger.info(f"强制保存 {len(dirty_announcements)} 个公告的待办数据...")
            saved_count = 0
            failed_count = 0
            
            for announcement_id in dirty_announcements:
                try:
                    if announcement_id in self.todos_cache:
                        todos, _ = self.todos_cache[announcement_id]
                        if self.todo_mgr and self.todo_mgr.save_todos_to_file(announcement_id, todos):
                            saved_count += 1
                        else:
                            failed_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.error(f"强制保存待办数据失败: announcement_id={announcement_id}, error={e}")
            
            logger.info(f"强制保存完成: 成功 {saved_count} 个，失败 {failed_count} 个")
        else:
            logger.debug("没有需要强制保存的待办数据")
    
    def invalidate_cache(self, cache_type: str, key: str = None, max_retries=3, retry_delay=0.1):
        """使缓存失效（带重试机制），支持跨进程缓存同步
        
        Args:
            cache_type: 缓存类型（'users', 'announcements', 'departments', 'todos'）
            key: 缓存键（可选，如果提供则只清除该键的缓存）
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
        """
        import time
        # logger已经在模块顶部导入，这里不需要重新导入
        last_error = None
        for attempt in range(max_retries):
            try:
                # 使用CacheSyncManager统一处理跨进程缓存失效
                try:
                    from server.cache_sync import invalidate_cache as sync_invalidate
                    sync_invalidate(cache_type)
                    logger.debug(f"已通知所有进程缓存失效: cache_type={cache_type}")
                except Exception as e:
                    logger.warning(f"通知跨进程缓存失效失败: {e}")
                    # 继续执行本地缓存清除，使用旧的标记文件方法作为后备
                    if cache_type == 'announcements':
                        self._touch_cache_invalidation_marker()
                    elif cache_type == 'todos':
                        self._touch_todo_cache_invalidation_marker()
                
                with self.cache_lock:
                    if cache_type == 'users':
                        if key:
                            self.users_cache.pop(key, None)
                        else:
                            # 清除所有用户缓存，包括all_users和active_users
                            self.users_cache.clear()
                            # 确保清除后，下次get_users会重新加载
                            logger.info(f"已清除用户缓存，下次访问将从数据库重新加载")
                    elif cache_type == 'announcements':
                        if key:
                            self.announcements_cache.pop(key, None)
                        else:
                            self.announcements_cache.clear()
                    elif cache_type == 'departments':
                        self.departments_cache.clear()
                    elif cache_type == 'todos':
                        if key:
                            self.todos_cache.pop(key, None)
                        else:
                            self.todos_cache.clear()
                
                # 如果执行到这里，说明清除成功
                if attempt > 0:
                    logger.info(f"缓存清除成功（第{attempt + 1}次尝试）: cache_type={cache_type}, key={key}")
                return True
                
            except Exception as e:
                last_error = e
                logger.warning(f"清除缓存失败（第{attempt + 1}次尝试）: cache_type={cache_type}, key={key}, error={e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        
        # 所有重试都失败
        logger.error(f"清除缓存失败（已重试{max_retries}次）: cache_type={cache_type}, key={key}, error={last_error}")
        return False
    
    def schedule_users_reload(self, delay: float = 0.05) -> None:
        """后台刷新用户缓存，避免在改密/更新用户 API 中同步加载全表阻塞 worker。"""
        def _job():
            try:
                if delay > 0:
                    time.sleep(delay)
                self.get_users(force_reload=True)
                self.get_users(status='active', force_reload=True)
            except Exception as e:
                logger.warning(f"后台刷新用户缓存失败: {e}", exc_info=True)

        threading.Thread(
            target=_job,
            daemon=True,
            name='users-cache-reload',
        ).start()

    def _touch_cache_invalidation_marker(self):
        """创建或更新缓存失效标记文件（用于跨进程缓存同步）
        
        当某个worker进程清除公告缓存时，通过touch这个标记文件来通知
        其他worker进程在下一次读取时重新加载缓存。
        """
        try:
            # 确保DATA_DIR存在
            os.makedirs(DATA_DIR, exist_ok=True)
            # Touch标记文件（如果不存在则创建，如果存在则更新修改时间）
            with open(self.cache_invalidation_marker, 'a'):
                os.utime(self.cache_invalidation_marker, None)
            logger.debug(f"已创建/更新缓存失效标记文件: {self.cache_invalidation_marker}")
        except Exception as e:
            logger.warning(f"创建缓存失效标记文件失败: {e}")
    
    def _touch_todo_cache_invalidation_marker(self):
        """创建或更新待办缓存失效标记文件（用于跨进程缓存同步）
        
        当某个worker进程清除待办缓存时，通过touch这个标记文件来通知
        其他worker进程在下一次读取时重新加载缓存。
        """
        try:
            # 确保DATA_DIR存在
            os.makedirs(DATA_DIR, exist_ok=True)
            # Touch标记文件（如果不存在则创建，如果存在则更新修改时间）
            with open(self.todo_cache_invalidation_marker, 'a'):
                os.utime(self.todo_cache_invalidation_marker, None)
            logger.debug(f"已创建/更新待办缓存失效标记文件: {self.todo_cache_invalidation_marker}")
        except Exception as e:
            logger.warning(f"创建待办缓存失效标记文件失败: {e}")
    
    def reload_cache(self, cache_type: str, max_retries=3, retry_delay=0.1):
        """重新加载缓存（带重试机制）
        
        Args:
            cache_type: 缓存类型（'users', 'announcements', 'departments', 'todos'）
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
        """
        import time
        from server.logger import logger
        last_error = None
        for attempt in range(max_retries):
            try:
                if cache_type == 'users' and PRELOAD_USERS:
                    self._preload_users()
                elif cache_type == 'announcements' and PRELOAD_ANNOUNCEMENTS:
                    self._preload_announcements()
                    try:
                        from server.cache_sync import update_local_version
                        update_local_version('announcements')
                    except Exception:
                        pass
                elif cache_type == 'departments' and PRELOAD_DEPARTMENTS:
                    self._preload_departments()
                elif cache_type == 'todos' and PRELOAD_TODOS:
                    self._preload_todos()
                
                # 如果执行到这里，说明重新加载成功
                if attempt > 0:
                    logger.info(f"缓存重新加载成功（第{attempt + 1}次尝试）: cache_type={cache_type}")
                return True
                
            except Exception as e:
                last_error = e
                logger.warning(f"重新加载缓存失败（第{attempt + 1}次尝试）: cache_type={cache_type}, error={e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        
        # 所有重试都失败
        logger.error(f"重新加载缓存失败（已重试{max_retries}次）: cache_type={cache_type}, error={last_error}")
        return False

# 全局数据预加载器实例
_data_preloader = None
_preloader_lock = threading.Lock()

def get_data_preloader() -> Optional[DataPreloader]:
    """获取数据预加载器实例（单例模式）"""
    global _data_preloader
    if _data_preloader is None:
        with _preloader_lock:
            if _data_preloader is None:
                _data_preloader = DataPreloader()
    return _data_preloader
