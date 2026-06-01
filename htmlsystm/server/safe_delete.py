#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全的删除操作模块
提供事务性的删除操作，确保数据一致性
"""
import os
import json
import shutil
from typing import Tuple, List, Dict
from server.database import Database
from server.logger import logger


class SafeDeleteManager:
    """安全的删除管理器，确保删除操作的原子性和数据一致性"""
    
    def __init__(self):
        self.db = Database()
    
    def delete_sub_board_safe(self, parent_board_id: str, sub_board_id: str) -> Tuple[bool, str]:
        """
        安全删除二级公告栏
        1. 检查是否可以删除
        2. 迁移相关公告（如果失败则回滚）
        3. 删除数据库记录（如果失败则回滚迁移）
        4. 确保所有操作都在事务中
        """
        logger.info(f"[SafeDelete] 开始安全删除二级公告栏: parent={parent_board_id}, sub={sub_board_id}")
        
        # 1. 预检查
        if sub_board_id == 'default':
            return False, "不能删除'默认'二级公告栏"
        
        # 检查二级公告栏是否存在
        with self.db.get_cursor() as cursor:
            cursor.execute('''
                SELECT id FROM sub_boards
                WHERE parent_board_id = ? AND sub_board_id = ?
            ''', (parent_board_id, sub_board_id))
            if not cursor.fetchone():
                return False, "二级公告栏不存在"
        
        # 2. 获取需要迁移的公告列表（在删除前）
        from server.announcement_manager import AnnouncementManager
        announcement_mgr = AnnouncementManager()
        
        announcements = announcement_mgr.get_announcements(
            board_id=parent_board_id,
            sub_board_id=sub_board_id
        )
        
        logger.info(f"[SafeDelete] 找到 {len(announcements)} 条需要迁移的公告")
        
        # 3. 备份需要修改的公告元数据（用于回滚）
        announcement_backups = []
        announcement_paths = []
        
        try:
            # 4. 迁移公告（如果失败，可以回滚）
            if announcements:
                logger.info(f"[SafeDelete] 开始迁移公告到'默认'二级公告栏...")
                
                for ann in announcements:
                    announcement_id = ann.get('id')
                    if not announcement_id:
                        continue
                    
                    # 查找公告目录
                    announcement_path = None
                    for bid in announcement_mgr._get_all_board_ids():
                        board_path = os.path.join(announcement_mgr.base_dir, bid)
                        if not os.path.exists(board_path):
                            continue
                        for item in os.listdir(board_path):
                            item_path = os.path.join(board_path, item)
                            if os.path.isdir(item_path):
                                metadata = announcement_mgr._read_metadata(item_path)
                                if metadata and metadata.get('id') == announcement_id:
                                    announcement_path = item_path
                                    break
                        if announcement_path:
                            break
                    
                    if announcement_path:
                        metadata_file = os.path.join(announcement_path, 'metadata.json')
                        if os.path.exists(metadata_file):
                            # 备份原始元数据
                            with open(metadata_file, 'r', encoding='utf-8') as f:
                                original_metadata = json.load(f)
                            announcement_backups.append({
                                'path': metadata_file,
                                'metadata': original_metadata
                            })
                            announcement_paths.append(announcement_path)
                            
                            # 更新元数据
                            original_metadata['sub_board_id'] = 'default'
                            with open(metadata_file, 'w', encoding='utf-8') as f:
                                json.dump(original_metadata, f, ensure_ascii=False, indent=2)
                            logger.info(f"[SafeDelete] 已迁移公告 {announcement_id}")
            
            # 5. 删除数据库记录（在事务中）
            logger.info(f"[SafeDelete] 开始删除数据库记录...")
            with self.db.get_cursor() as cursor:
                cursor.execute('''
                    DELETE FROM sub_boards
                    WHERE parent_board_id = ? AND sub_board_id = ?
                ''', (parent_board_id, sub_board_id))
                
                deleted_count = cursor.rowcount
                if deleted_count == 0:
                    # 如果数据库记录不存在，回滚文件修改
                    logger.warning(f"[SafeDelete] 数据库记录不存在，回滚文件修改")
                    self._rollback_announcement_migrations(announcement_backups)
                    return False, "二级公告栏不存在"
            
            # 6. 所有操作成功
            logger.info(f"[SafeDelete] 删除成功")
            message = "删除成功"
            if announcements:
                message += f"，已迁移 {len(announcements)} 条公告到'默认'二级公告栏"
            return True, message
            
        except Exception as e:
            # 发生错误，回滚所有修改
            logger.error(f"[SafeDelete] 删除过程中发生错误: {e}", exc_info=True)
            self._rollback_announcement_migrations(announcement_backups)
            return False, f"删除失败: {str(e)}"
    
    def _rollback_announcement_migrations(self, backups: List[Dict]):
        """回滚公告迁移"""
        if not backups:
            return
        
        logger.warning(f"[SafeDelete] 开始回滚 {len(backups)} 条公告的修改...")
        for backup in backups:
            try:
                with open(backup['path'], 'w', encoding='utf-8') as f:
                    json.dump(backup['metadata'], f, ensure_ascii=False, indent=2)
                logger.info(f"[SafeDelete] 已回滚公告: {backup['path']}")
            except Exception as e:
                logger.error(f"[SafeDelete] 回滚公告失败 {backup['path']}: {e}")
    
    def delete_board_safe(self, board_id: str) -> Tuple[bool, str]:
        """
        安全删除一级公告栏
        1. 检查是否有公告和二级公告栏
        2. 如果都没有，删除文件目录和数据库记录
        3. 确保操作的原子性
        """
        logger.info(f"[SafeDelete] 开始安全删除一级公告栏: {board_id}")
        
        if board_id == 'all':
            return False, "不能删除 'all' 公告栏"
        
        try:
            # 1. 检查是否存在
            with self.db.get_cursor() as cursor:
                cursor.execute('SELECT id FROM primary_boards WHERE board_id = ?', (board_id,))
                if not cursor.fetchone():
                    return False, "公告栏不存在"
            
            # 2. 检查是否有公告
            from server.announcement_manager import AnnouncementManager
            announcement_mgr = AnnouncementManager()
            announcements = announcement_mgr.get_announcements(board_id=board_id)
            if announcements:
                return False, f"该公告栏下有 {len(announcements)} 条公告，请先删除所有公告"
            
            # 3. 检查是否有二级公告栏
            from server.sub_board_manager import SubBoardManager
            sub_board_mgr = SubBoardManager()
            sub_boards = sub_board_mgr.get_sub_boards(board_id)
            if sub_boards:
                return False, f"该公告栏下有 {len(sub_boards)} 个二级公告栏，请先删除所有二级公告栏"
            
            # 4. 删除文件目录（先删除文件，如果失败不会影响数据库）
            board_path = os.path.join(announcement_mgr.base_dir, board_id)
            if os.path.exists(board_path):
                try:
                    shutil.rmtree(board_path)
                    logger.info(f"[SafeDelete] 已删除公告栏目录: {board_path}")
                except Exception as e:
                    logger.error(f"[SafeDelete] 删除目录失败: {e}")
                    return False, f"删除公告栏目录失败: {str(e)}"
            
            # 5. 删除数据库记录（在事务中）
            with self.db.get_cursor() as cursor:
                cursor.execute('DELETE FROM primary_boards WHERE board_id = ?', (board_id,))
                deleted_count = cursor.rowcount
                if deleted_count == 0:
                    # 如果数据库记录不存在，但目录已删除，需要恢复目录（但这里已经删除了，无法恢复）
                    logger.warning(f"[SafeDelete] 数据库记录不存在，但目录已删除")
                    return False, "公告栏不存在"
            
            logger.info(f"[SafeDelete] 删除一级公告栏成功")
            return True, "公告栏删除成功"
            
        except Exception as e:
            logger.error(f"[SafeDelete] 删除一级公告栏失败: {e}", exc_info=True)
            return False, f"删除失败: {str(e)}"

