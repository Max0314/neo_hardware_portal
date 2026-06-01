#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一级公告栏（子公告栏）管理模块
负责一级公告栏的创建、查询、更新和删除
"""
# 已迁移到MySQL，不再使用sqlite3
import os
import threading
import shutil
import stat
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from server.database import Database
from server.announcement_config import ANNOUNCEMENT_BOARDS
from server.announcement_manager import AnnouncementManager

class BoardManager:
    """
    一级公告栏管理类，负责一级公告栏的数据库操作。
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(BoardManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.db = Database()
            self._initialized = True
            # 只在调试模式下打印初始化信息
            if os.getenv('DEBUG', '').lower() in ('1', 'true', 'yes'):
                print("BoardManager 初始化完成。")

    def get_all_boards(self) -> List[Dict[str, any]]:
        """
        获取所有一级公告栏（从数据库读取）。
        Returns:
            List[Dict[str, any]]: 一级公告栏列表
        """
        boards = []
        with self.db.get_cursor() as cursor:
            cursor.execute('''
                SELECT board_id, name, description, display_order
                FROM primary_boards
                WHERE board_id != 'all'
                ORDER BY display_order ASC, id ASC
            ''')
            
            for row in cursor.fetchall():
                boards.append({
                    'id': row['board_id'],
                    'name': row['name'],
                    'description': row['description'] or f"{row['name']}公告栏"
                })
        
        return boards

    def get_board(self, board_id: str) -> Optional[Dict[str, any]]:
        """
        获取单个一级公告栏详情。
        """
        with self.db.get_cursor() as cursor:
            cursor.execute('''
                SELECT board_id, name, description, display_order
                FROM primary_boards
                WHERE board_id = %s
            ''', (board_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    'id': row['board_id'],
                    'name': row['name'],
                    'description': row['description'] or f"{row['name']}公告栏"
                }
        return None

    def create_board(self, board_id: str, name: str, description: Optional[str] = None, display_order: int = 0) -> Tuple[bool, str]:
        """
        创建新的一级公告栏（改进版本 - 完整初始化）。
        
        流程（逆删除流程）：
        1. 检查公告栏是否已存在
        2. 创建文件目录
        3. 在事务中插入数据库记录
        4. 创建默认二级公告栏
        
        注意：所有操作在事务中，确保原子性
        """
        import logging
        logger = logging.getLogger('hardware_rdb')
        
        if not board_id or not name:
            return False, "公告栏ID和名称不能为空"
        
        if board_id == 'all':
            return False, "不能使用 'all' 作为公告栏ID"
        
        logger.info(f"[BoardManager] 开始创建一级公告栏: {board_id}, name={name}")
        
        try:
            # 步骤1: 检查公告栏是否已存在
            with self.db.get_cursor() as cursor:
                cursor.execute('SELECT id FROM primary_boards WHERE board_id = %s', (board_id,))
                if cursor.fetchone():
                    logger.warning(f"[BoardManager] 公告栏已存在: {board_id}")
                    return False, "公告栏ID已存在"
            
            # 步骤2: 创建文件目录结构（逆删除流程）
            # 删除时删除的是整个 board_path 目录及其所有内容
            # 创建时需要确保完整的目录结构存在
            from server.announcement_manager import AnnouncementManager
            announcement_mgr = AnnouncementManager()
            
            # 确保基础目录结构存在（base_dir 和 temp_dir）
            # 这会调用 _ensure_directories()，确保所有必要的目录都已创建
            try:
                announcement_mgr._ensure_directories()
                logger.info(f"[BoardManager] 基础目录结构已确保存在")
            except Exception as e:
                logger.warning(f"[BoardManager] 确保基础目录结构时出错（继续执行）: {e}")
            
            # 创建公告栏目录
            board_path = os.path.join(announcement_mgr.base_dir, board_id)
            
            try:
                logger.info(f"[BoardManager] 创建公告栏目录: {board_path}")
                os.makedirs(board_path, exist_ok=True)
                
                # 验证目录是否创建成功
                if not os.path.exists(board_path):
                    logger.error(f"[BoardManager] 目录创建失败: {board_path}")
                    return False, "创建公告栏目录失败"
                
                # 验证目录是否可写
                if not os.access(board_path, os.W_OK):
                    logger.warning(f"[BoardManager] 目录不可写: {board_path}")
                    # 尝试修复权限
                    try:
                        os.chmod(board_path, 0o755)
                    except:
                        pass
                
                logger.info(f"[BoardManager] 目录创建成功: {board_path}")
            except Exception as e:
                logger.error(f"[BoardManager] 创建目录失败: {e}", exc_info=True)
                return False, f"创建公告栏目录失败: {str(e)}"
            
            # 步骤3: 在事务中插入数据库记录
            logger.info(f"[BoardManager] 开始插入数据库记录")
            with self.db.get_cursor() as cursor:
                # 确保外键约束已启用
                # MySQL自动支持外键约束，无需PRAGMA
                
                # 插入一级公告栏
                cursor.execute('''
                    INSERT INTO primary_boards (board_id, name, description, display_order)
                    VALUES (%s, %s, %s, %s)
                ''', (board_id, name, description or f"{name}公告栏", display_order))
                
                inserted_count = cursor.rowcount
                if inserted_count == 0:
                    logger.warning(f"[BoardManager] 数据库插入失败")
                    return False, "创建公告栏失败"
                
                logger.info(f"[BoardManager] 数据库记录已插入，inserted_count={inserted_count}")
                
                # 步骤4: 在同一个事务中创建默认二级公告栏
                # 注意：直接在同一个事务中插入，避免嵌套事务导致的锁等待问题
                logger.info(f"[BoardManager] 检查默认二级公告栏是否存在: parent={board_id}")
                cursor.execute('''
                    SELECT id FROM sub_boards 
                    WHERE parent_board_id = %s AND sub_board_id = 'default'
                ''', (board_id,))
                
                existing = cursor.fetchone()
                if not existing:
                    # 在同一个事务中直接插入默认二级公告栏
                    logger.info(f"[BoardManager] 开始创建默认二级公告栏: parent={board_id}")
                    try:
                        cursor.execute('''
                            INSERT INTO sub_boards (parent_board_id, sub_board_id, name, description, display_order)
                            VALUES (%s, %s, %s, %s, %s)
                        ''', (board_id, 'default', '默认', '显示该公告栏下的所有公告', 0))
                        sub_inserted = cursor.rowcount
                        logger.info(f"[BoardManager] 默认二级公告栏插入完成，rowcount={sub_inserted}")
                        if sub_inserted > 0:
                            logger.info(f"[BoardManager] 默认二级公告栏创建成功")
                        else:
                            logger.warning(f"[BoardManager] 默认二级公告栏插入失败，rowcount=0")
                    except Exception as e:
                        logger.warning(f"[BoardManager] 默认二级公告栏已存在或创建失败（IntegrityError）: {e}")
                        # 默认二级公告栏创建失败不影响一级公告栏的创建
                    except Exception as e:
                        logger.warning(f"[BoardManager] 创建默认二级公告栏时出错: {e}", exc_info=True)
                        # 默认二级公告栏创建失败不影响一级公告栏的创建
                else:
                    logger.info(f"[BoardManager] 默认二级公告栏已存在（id={existing['id']}），跳过创建")
                
                logger.info(f"[BoardManager] 事务即将提交...")
            
            logger.info(f"[BoardManager] 创建一级公告栏完成: {board_id}")
            return True, "公告栏创建成功，已自动创建默认二级公告栏"
            
        except Exception as e:
            logger.error(f"[BoardManager] 创建一级公告栏异常: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            
            # 如果数据库插入成功但后续失败，尝试清理
            try:
                from server.announcement_manager import AnnouncementManager
                announcement_mgr = AnnouncementManager()
                board_path = os.path.join(announcement_mgr.base_dir, board_id)
                if os.path.exists(board_path):
                    import shutil
                    shutil.rmtree(board_path)
                    logger.info(f"[BoardManager] 已清理创建失败的目录: {board_path}")
            except:
                pass
            
            return False, f"创建失败: {str(e)}"

    def update_board(self, board_id: str, name: Optional[str] = None, description: Optional[str] = None, display_order: Optional[int] = None) -> Tuple[bool, str]:
        """
        更新一级公告栏信息。
        """
        try:
            with self.db.get_cursor() as cursor:
                # 检查是否存在
                cursor.execute('SELECT id FROM primary_boards WHERE board_id = %s', (board_id,))
                if not cursor.fetchone():
                    return False, "公告栏不存在"
                
                # 构建更新语句
                updates = []
                params = []
                
                if name is not None:
                    updates.append('name = %s')
                    params.append(name)
                
                if description is not None:
                    updates.append('description = %s')
                    params.append(description)
                
                if display_order is not None:
                    updates.append('display_order = %s')
                    params.append(display_order)
                
                if not updates:
                    return False, "没有需要更新的字段"
                
                updates.append('updated_time = CURRENT_TIMESTAMP')
                params.append(board_id)
                
                cursor.execute(f'''
                    UPDATE primary_boards
                    SET {', '.join(updates)}
                    WHERE board_id = %s
                ''', params)
                
                return True, "公告栏更新成功"
        except Exception as e:
            return False, f"更新失败: {str(e)}"

    def delete_board(self, board_id: str) -> Tuple[bool, str]:
        """
        删除一级公告栏（改进版本 - 自动删除公告）。
        
        流程：
        1. 快速检查公告栏是否存在
        2. 检测公告栏中的公告，如果存在则先删除所有公告
        3. 在事务中删除数据库记录（外键约束会自动级联删除二级公告栏）
        4. 删除文件目录（如果数据库删除成功）
        
        注意：文件删除在数据库提交后进行，如果失败不影响数据库操作
        """
        import logging
        logger = logging.getLogger('hardware_rdb')
        
        if board_id == 'all':
            return False, "不能删除 'all' 公告栏"
        
        logger.info(f"[BoardManager] 开始删除一级公告栏: {board_id}")
        
        try:
            # 步骤1: 快速检查公告栏是否存在
            with self.db.get_cursor() as cursor:
                cursor.execute('SELECT id FROM primary_boards WHERE board_id = %s', (board_id,))
                if not cursor.fetchone():
                    logger.warning(f"[BoardManager] 公告栏不存在: {board_id}")
                    return False, "公告栏不存在"
            
            # 步骤2: 检测并删除公告栏中的公告
            announcement_mgr = AnnouncementManager()
            board_path = os.path.join(announcement_mgr.base_dir, board_id)
            
            deleted_announcements = 0
            if os.path.exists(board_path):
                try:
                    items = os.listdir(board_path)
                    logger.info(f"[BoardManager] 检测到公告栏目录中有 {len(items)} 个项目")
                    
                    # 处理只读文件的删除
                    def handle_remove_readonly(func, path, exc):
                        """处理只读文件的删除"""
                        try:
                            os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                            func(path)
                        except Exception:
                            try:
                                func(path)
                            except:
                                pass
                    
                    # 遍历所有项目，删除公告目录
                    for item in items:
                        item_path = os.path.join(board_path, item)
                        if os.path.isdir(item_path):
                            # 检查是否有metadata.json文件（存在就认为是公告）
                            metadata_file = os.path.join(item_path, 'metadata.json')
                            if os.path.exists(metadata_file):
                                try:
                                    # 删除公告目录
                                    shutil.rmtree(item_path, onerror=handle_remove_readonly)
                                    deleted_announcements += 1
                                    logger.info(f"[BoardManager] 已删除公告: {item}")
                                except Exception as e:
                                    logger.warning(f"[BoardManager] 删除公告 {item} 失败: {e}")
                                    # 继续删除其他公告，不因单个失败而停止
                    
                    if deleted_announcements > 0:
                        logger.info(f"[BoardManager] 已自动删除 {deleted_announcements} 条公告")
                except Exception as e:
                    logger.error(f"[BoardManager] 检测或删除公告时出错: {e}", exc_info=True)
                    return False, f"处理公告时出错: {str(e)}"
            
            # 步骤3: 在事务中删除数据库记录
            # 外键约束会自动级联删除二级公告栏
            logger.info(f"[BoardManager] 开始删除数据库记录")
            with self.db.get_cursor() as cursor:
                # 确保外键约束已启用
                # MySQL自动支持外键约束，无需PRAGMA
                
                # 删除一级公告栏（会自动级联删除二级公告栏）
                cursor.execute('DELETE FROM primary_boards WHERE board_id = %s', (board_id,))
                deleted_count = cursor.rowcount
                
                if deleted_count == 0:
                    logger.warning(f"[BoardManager] 数据库记录不存在")
                    return False, "公告栏不存在"
                
                logger.info(f"[BoardManager] 数据库记录已删除，deleted_count={deleted_count}")
                
                # 验证二级公告栏是否已被级联删除
                cursor.execute('SELECT COUNT(*) as cnt FROM sub_boards WHERE parent_board_id = %s', (board_id,))
                remaining_count = cursor.fetchone()['cnt']
                
                if remaining_count > 0:
                    logger.warning(f"[BoardManager] 发现 {remaining_count} 个残留的二级公告栏，正在清理")
                    cursor.execute('DELETE FROM sub_boards WHERE parent_board_id = %s', (board_id,))
                    cleaned_count = cursor.rowcount
                    logger.info(f"[BoardManager] 已清理 {cleaned_count} 个孤儿二级公告栏")
                else:
                    logger.info(f"[BoardManager] 二级公告栏已自动级联删除")
            
            # 步骤4: 删除文件目录（在数据库提交后进行）
            # 如果文件删除失败，不影响数据库操作（数据库已提交）
            if os.path.exists(board_path):
                try:
                    logger.info(f"[BoardManager] 开始删除文件目录: {board_path}")
                    
                    # 处理只读文件的删除
                    def handle_remove_readonly(func, path, exc):
                        """处理只读文件的删除"""
                        try:
                            os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                            func(path)
                        except Exception:
                            try:
                                func(path)
                            except:
                                pass
                    
                    shutil.rmtree(board_path, onerror=handle_remove_readonly)
                    logger.info(f"[BoardManager] 文件目录已删除: {board_path}")
                except Exception as e:
                    logger.warning(f"[BoardManager] 删除文件目录失败（不影响数据库操作）: {e}")
                    # 文件删除失败不影响数据库操作，只记录警告
            
            # 构建成功消息
            message = "公告栏删除成功"
            if deleted_announcements > 0:
                message += f"，已自动删除 {deleted_announcements} 条公告"
            
            logger.info(f"[BoardManager] 删除一级公告栏完成: {board_id}")
            return True, message
            
        except Exception as e:
            logger.error(f"[BoardManager] 删除一级公告栏异常: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            return False, f"删除失败: {str(e)}"
