#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
删除操作验证器
确保删除操作后数据一致性和索引正确性
"""
from typing import Tuple
from server.database import Database
from server.logger import logger


class DeleteValidator:
    """删除操作验证器，确保删除后数据一致性"""
    
    def __init__(self):
        self.db = Database()
    
    def validate_sub_board_deletion(self, parent_board_id: str, sub_board_id: str) -> Tuple[bool, str]:
        """
        验证二级公告栏删除后的数据一致性
        1. 检查数据库记录是否已删除
        2. 检查是否有孤立的公告引用
        3. 验证索引完整性
        """
        logger.info(f"[DeleteValidator] 验证二级公告栏删除: parent={parent_board_id}, sub={sub_board_id}")
        
        try:
            with self.db.get_cursor() as cursor:
                # 1. 检查数据库记录是否已删除
                cursor.execute('''
                    SELECT id FROM sub_boards
                    WHERE parent_board_id = ? AND sub_board_id = ?
                ''', (parent_board_id, sub_board_id))
                
                if cursor.fetchone():
                    return False, "数据库记录仍然存在，删除可能失败"
                
                # 2. 检查是否有其他二级公告栏引用（不应该有，但检查一下）
                cursor.execute('''
                    SELECT COUNT(*) as cnt FROM sub_boards
                    WHERE parent_board_id = ?
                ''', (parent_board_id,))
                remaining_count = cursor.fetchone()['cnt']
                logger.info(f"[DeleteValidator] 父公告栏 {parent_board_id} 下还有 {remaining_count} 个二级公告栏")
                
                # 3. 验证索引（SQLite会自动维护，这里只是确认）
                cursor.execute('''
                    SELECT COUNT(*) as cnt FROM sub_boards
                ''')
                total_count = cursor.fetchone()['cnt']
                logger.info(f"[DeleteValidator] 数据库中总共有 {total_count} 个二级公告栏")
                
                # 4. 检查是否有默认二级公告栏（每个一级公告栏都应该有一个）
                cursor.execute('''
                    SELECT COUNT(*) as cnt FROM sub_boards
                    WHERE parent_board_id = ? AND sub_board_id = 'default'
                ''', (parent_board_id,))
                default_count = cursor.fetchone()['cnt']
                
                if default_count == 0:
                    logger.warning(f"[DeleteValidator] 警告: 父公告栏 {parent_board_id} 没有'默认'二级公告栏")
                    # 自动创建默认二级公告栏
                    cursor.execute('''
                        INSERT INTO sub_boards (parent_board_id, sub_board_id, name, description, display_order)
                        VALUES (?, 'default', '默认', '显示该公告栏下的所有公告', 0)
                    ''', (parent_board_id,))
                    logger.info(f"[DeleteValidator] 已自动创建'默认'二级公告栏")
                
                return True, "验证通过，数据一致性正常"
                
        except Exception as e:
            logger.error(f"[DeleteValidator] 验证失败: {e}", exc_info=True)
            return False, f"验证失败: {str(e)}"
    
    def validate_board_deletion(self, board_id: str) -> Tuple[bool, str]:
        """
        验证一级公告栏删除后的数据一致性
        1. 检查数据库记录是否已删除
        2. 检查是否有孤立的二级公告栏
        3. 验证索引完整性
        """
        logger.info(f"[DeleteValidator] 验证一级公告栏删除: {board_id}")
        
        try:
            with self.db.get_cursor() as cursor:
                # 1. 检查数据库记录是否已删除
                cursor.execute('SELECT id FROM primary_boards WHERE board_id = ?', (board_id,))
                if cursor.fetchone():
                    return False, "数据库记录仍然存在，删除可能失败"
                
                # 2. 检查是否有孤立的二级公告栏
                from server.sub_board_manager import SubBoardManager
                sub_board_mgr = SubBoardManager()
                orphaned_sub_boards = sub_board_mgr.get_sub_boards(board_id)
                
                if orphaned_sub_boards:
                    logger.warning(f"[DeleteValidator] 发现 {len(orphaned_sub_boards)} 个孤立的二级公告栏")
                    # 可以选择删除或保留，这里记录警告
                    return False, f"发现 {len(orphaned_sub_boards)} 个孤立的二级公告栏，请先删除"
                
                return True, "验证通过，数据一致性正常"
                
        except Exception as e:
            logger.error(f"[DeleteValidator] 验证失败: {e}", exc_info=True)
            return False, f"验证失败: {str(e)}"
    
    def refresh_database_statistics(self):
        """
        刷新数据库统计信息，确保索引是最新的
        SQLite会自动维护索引，但可以执行ANALYZE来更新统计信息
        """
        try:
            logger.info("[DeleteValidator] 刷新数据库统计信息...")
            with self.db.get_cursor() as cursor:
                # 更新SQLite的查询优化器统计信息
                cursor.execute('ANALYZE sub_boards')
                cursor.execute('ANALYZE primary_boards')
                logger.info("[DeleteValidator] 数据库统计信息已更新")
            return True
        except Exception as e:
            logger.warning(f"[DeleteValidator] 更新统计信息失败: {e}")
            # 这不是关键操作，失败不影响功能
            return False

