#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
二级公告栏管理器
管理子公告栏下的二级公告栏（子分类）
"""
# 已迁移到MySQL，不再使用sqlite3
import os
import json
from typing import List, Dict, Optional, Tuple
from server.config import DB_PATH
from server.database import Database
from server.logger import logger


class SubBoardManager:
    """二级公告栏管理器"""
    
    def __init__(self):
        self.db = Database()
    
    def get_sub_boards(self, parent_board_id: str) -> List[Dict]:
        """获取指定父公告栏下的所有二级公告栏（验证父公告栏是否存在）"""
        sub_boards = []
        try:
            logger.debug(f"[SubBoardManager] 获取二级公告栏: parent={parent_board_id}")
            with self.db.get_cursor() as cursor:
                # 首先验证父公告栏是否存在
                logger.debug(f"[SubBoardManager] 验证父公告栏是否存在")
                cursor.execute('SELECT board_id FROM primary_boards WHERE board_id = %s', (parent_board_id,))
                if not cursor.fetchone():
                    logger.debug(f"[SubBoardManager] 父公告栏 {parent_board_id} 不存在，返回空列表")
                    return sub_boards
                
                # 只返回父公告栏存在的二级公告栏
                logger.debug(f"[SubBoardManager] 查询二级公告栏")
                cursor.execute('''
                    SELECT sb.id, sb.parent_board_id, sb.sub_board_id, sb.name, sb.description, sb.display_order
                    FROM sub_boards sb
                    INNER JOIN primary_boards pb ON sb.parent_board_id = pb.board_id
                    WHERE sb.parent_board_id = %s
                    ORDER BY sb.display_order ASC, sb.id ASC
                ''', (parent_board_id,))
                
                rows = cursor.fetchall()
                logger.debug(f"[SubBoardManager] 查询到 {len(rows)} 个二级公告栏")
                
                for row in rows:
                    sub_boards.append({
                        'id': row['id'],
                        'parent_board_id': row['parent_board_id'],
                        'sub_board_id': row['sub_board_id'],
                        'name': row['name'],
                        'description': row['description'],
                        'display_order': row['display_order']
                    })
            
            logger.debug(f"[SubBoardManager] 返回 {len(sub_boards)} 个二级公告栏")
            return sub_boards
        except Exception as e:
            logger.error(f"[SubBoardManager] 获取二级公告栏失败: {e}", exc_info=True)
            return sub_boards
    
    def get_all_sub_boards(self) -> Dict[str, List[Dict]]:
        """获取所有二级公告栏，按父公告栏分组（只返回父公告栏仍然存在的二级公告栏）"""
        result = {}
        try:
            with self.db.get_cursor() as cursor:
                # MySQL表结构由mysql_schema管理，表应该已经存在，无需检查
                # 直接查询数据
                
                # 检查表中有多少条记录
                cursor.execute("SELECT COUNT(*) as cnt FROM sub_boards")
                count_row = cursor.fetchone()
                total_count = count_row['cnt'] if count_row else 0
                logger.debug(f"[SubBoardManager] sub_boards 表中总共有 {total_count} 条记录")
                
                # 使用 LEFT JOIN 只返回父公告栏仍然存在的二级公告栏
                # 这样可以过滤掉"孤儿"二级公告栏（父公告栏已被删除）
                cursor.execute('''
                    SELECT sb.id, sb.parent_board_id, sb.sub_board_id, sb.name, sb.description, sb.display_order
                    FROM sub_boards sb
                    INNER JOIN primary_boards pb ON sb.parent_board_id = pb.board_id
                    ORDER BY sb.parent_board_id ASC, sb.display_order ASC, sb.id ASC
                ''')
                
                rows = cursor.fetchall()
                logger.debug(f"[SubBoardManager] 查询到 {len(rows)} 条有效的二级公告栏记录（已过滤孤儿数据）")
                
                # 如果查询结果为空但表中还有记录，说明可能有孤儿数据
                if len(rows) == 0 and total_count > 0:
                    logger.warning(f"[SubBoardManager] 警告: 查询结果为空，但表中显示有 {total_count} 条记录，可能存在孤儿数据")
                    # 尝试查找孤儿数据
                    cursor.execute('''
                        SELECT sb.parent_board_id, COUNT(*) as cnt
                        FROM sub_boards sb
                        LEFT JOIN primary_boards pb ON sb.parent_board_id = pb.board_id
                        WHERE pb.board_id IS NULL
                        GROUP BY sb.parent_board_id
                    ''')
                    orphan_rows = cursor.fetchall()
                    if orphan_rows:
                        logger.warning("[SubBoardManager] 发现孤儿二级公告栏数据:")
                        for orphan_row in orphan_rows:
                            logger.warning(f"[SubBoardManager]   父公告栏 {orphan_row['parent_board_id']}: {orphan_row['cnt']} 条孤儿二级公告栏")
                
                for row in rows:
                    parent_id = row['parent_board_id']
                    if parent_id not in result:
                        result[parent_id] = []
                    
                    result[parent_id].append({
                        'id': row['id'],
                        'parent_board_id': row['parent_board_id'],
                        'sub_board_id': row['sub_board_id'],
                        'name': row['name'],
                        'description': row['description'],
                        'display_order': row['display_order']
                    })
                
                logger.debug(f"[SubBoardManager] 返回 {len(result)} 个父公告栏的二级公告栏")
                for parent_id, sub_boards in result.items():
                    logger.debug(f"[SubBoardManager]   {parent_id}: {len(sub_boards)} 个二级公告栏")
        except Exception as e:
            logger.error(f"[SubBoardManager] 获取二级公告栏失败: {e}", exc_info=True)
        
        return result
    
    def get_sub_board(self, parent_board_id: str, sub_board_id: str) -> Optional[Dict]:
        """获取指定的二级公告栏"""
        with self.db.get_cursor() as cursor:
            cursor.execute('''
                SELECT id, parent_board_id, sub_board_id, name, description, display_order
                FROM sub_boards
                WHERE parent_board_id = %s AND sub_board_id = %s
            ''', (parent_board_id, sub_board_id))
            
            row = cursor.fetchone()
            if row:
                return {
                    'id': row['id'],
                    'parent_board_id': row['parent_board_id'],
                    'sub_board_id': row['sub_board_id'],
                    'name': row['name'],
                    'description': row['description'],
                    'display_order': row['display_order']
                }
        
        return None
    
    def create_sub_board(self, parent_board_id: str, sub_board_id: str, name: str, 
                        description: str = '', display_order: int = 0) -> Tuple[bool, str]:
        """创建二级公告栏"""
        logger.debug(f"[SubBoardManager] 创建二级公告栏: parent={parent_board_id}, sub={sub_board_id}, name={name}")
        
        if not parent_board_id or not sub_board_id or not name:
            logger.warning(f"[SubBoardManager] 验证失败: 缺少必要字段")
            return False, "缺少必要字段"
        
        try:
            with self.db.get_cursor() as cursor:
                logger.debug(f"[SubBoardManager] 执行SQL插入...")
                cursor.execute('''
                    INSERT INTO sub_boards (parent_board_id, sub_board_id, name, description, display_order)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (parent_board_id, sub_board_id, name, description, display_order))
                
                logger.debug(f"[SubBoardManager] SQL插入完成，准备提交...")
                # commit 在 context manager 中自动处理
            logger.info(f"[SubBoardManager] 二级公告栏创建成功: parent={parent_board_id}, sub={sub_board_id}, name={name}")
            return True, "二级公告栏创建成功"
        except Exception as e:
            logger.error(f"[SubBoardManager] 创建失败: {e}", exc_info=True)
            # 检查是否是重复键错误
            error_str = str(e).lower()
            if 'duplicate' in error_str or 'unique' in error_str or 'primary' in error_str:
                return False, "二级公告栏ID已存在"
            return False, f"创建失败: {e}"
    
    def update_sub_board(self, parent_board_id: str, sub_board_id: str, 
                        name: str = None, description: str = None, 
                        display_order: int = None) -> Tuple[bool, str]:
        """更新二级公告栏"""
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = %s")
            params.append(name)
        if description is not None:
            updates.append("description = %s")
            params.append(description)
        if display_order is not None:
            updates.append("display_order = %s")
            params.append(display_order)
        
        if not updates:
            return False, "没有要更新的字段"
        
        updates.append("updated_time = CURRENT_TIMESTAMP")
        params.extend([parent_board_id, sub_board_id])
        
        with self.db.get_cursor() as cursor:
            try:
                cursor.execute(f'''
                    UPDATE sub_boards
                    SET {', '.join(updates)}
                    WHERE parent_board_id = %s AND sub_board_id = %s
                ''', params)
                
                if cursor.rowcount == 0:
                    return False, "二级公告栏不存在"
                
                self.db.commit()
                return True, "更新成功"
            except Exception as e:
                self.db.rollback()
                return False, f"更新失败: {e}"
    
    def delete_sub_board(self, parent_board_id: str, sub_board_id: str) -> Tuple[bool, str]:
        """删除二级公告栏"""
        logger.debug(f"[SubBoardManager] 开始删除二级公告栏: parent={parent_board_id}, sub={sub_board_id}")
        try:
            # 不能删除 'default' 二级公告栏
            if sub_board_id == 'default':
                logger.warning(f"[SubBoardManager] 不能删除'默认'二级公告栏")
                return False, "不能删除'默认'二级公告栏"
            
            # 检查是否有公告使用此二级公告栏
            logger.debug(f"[SubBoardManager] 正在检查是否有公告使用此二级公告栏...")
            from server.announcement_manager import AnnouncementManager
            announcement_mgr = AnnouncementManager()
            
            # 获取使用此二级公告栏的公告
            announcements = announcement_mgr.get_announcements(
                board_id=parent_board_id, 
                sub_board_id=sub_board_id
            )
            logger.debug(f"[SubBoardManager] get_announcements 返回: {len(announcements)} 条公告")
            
            if announcements:
                # 如果有公告使用此二级公告栏，将它们迁移到'default'
                logger.info(f"[SubBoardManager] 发现 {len(announcements)} 条公告使用此二级公告栏，正在迁移到'默认'...")
                
                for ann in announcements:
                    announcement_id = ann.get('id')
                    if announcement_id:
                        # 更新公告的 sub_board_id 为 'default'
                        announcement_path = None
                        # 查找公告目录
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
                            metadata = announcement_mgr._read_metadata(announcement_path)
                            if metadata:
                                metadata['sub_board_id'] = 'default'
                                metadata_path = os.path.join(announcement_path, 'metadata.json')
                                with open(metadata_path, 'w', encoding='utf-8') as f:
                                    json.dump(metadata, f, ensure_ascii=False, indent=2)
                                logger.debug(f"[SubBoardManager] 已更新公告 {announcement_id} 的 sub_board_id 为 'default'")
                
                logger.info(f"[SubBoardManager] 已将所有相关公告迁移到'默认'二级公告栏")
            else:
                logger.debug(f"[SubBoardManager] 没有找到使用此二级公告栏的公告，直接删除")
            
            # 删除二级公告栏
            logger.debug(f"[SubBoardManager] 开始删除数据库记录...")
            try:
                with self.db.get_cursor() as cursor:
                    cursor.execute('''
                        DELETE FROM sub_boards
                        WHERE parent_board_id = %s AND sub_board_id = %s
                    ''', (parent_board_id, sub_board_id))
                    
                    deleted_count = cursor.rowcount
                    logger.debug(f"[SubBoardManager] 数据库删除操作完成，影响行数: {deleted_count}")
                    
                    if deleted_count == 0:
                        logger.warning(f"[SubBoardManager] 二级公告栏不存在")
                        return False, "二级公告栏不存在"
                
                # get_cursor 上下文管理器会自动提交，无需手动commit
                logger.debug(f"[SubBoardManager] 数据库提交成功（由上下文管理器自动提交）")
                
                # 验证删除后的数据一致性
                try:
                    from server.delete_validator import DeleteValidator
                    validator = DeleteValidator()
                    valid, msg = validator.validate_sub_board_deletion(parent_board_id, sub_board_id)
                    if valid:
                        logger.debug(f"[SubBoardManager] 数据一致性验证通过")
                    else:
                        logger.warning(f"[SubBoardManager] 警告: {msg}")
                except Exception as e:
                    logger.warning(f"[SubBoardManager] 验证数据一致性时出错: {e}", exc_info=True)
                    # 验证失败不影响删除操作本身
                
                message = f"删除成功"
                if announcements:
                    message += f"，已迁移 {len(announcements)} 条公告到'默认'二级公告栏"
                logger.info(f"[SubBoardManager] 删除二级公告栏成功: parent={parent_board_id}, sub={sub_board_id}, 迁移公告数={len(announcements)}")
                return True, message
            except Exception as db_error:
                logger.error(f"[SubBoardManager] 数据库操作异常: {db_error}", exc_info=True)
                # get_cursor 上下文管理器会自动回滚，但为了保险起见也调用一次
                try:
                    self.db.rollback()
                except:
                    pass
                raise
        except Exception as e:
            logger.error(f"[SubBoardManager] 删除二级公告栏异常: {e}", exc_info=True)
            if hasattr(self, 'db'):
                self.db.rollback()
            return False, f"删除失败: {e}"

