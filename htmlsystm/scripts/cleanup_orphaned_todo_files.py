#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理孤立待办文件脚本
删除已删除公告对应的待办Excel文件
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from server.config import DATA_DIR
from server.announcement_manager import AnnouncementManager
from server.todo_manager import TodoManager
from server.logger import logger

def cleanup_orphaned_todo_files():
    """清理孤立的待办文件（已删除公告的待办文件）"""
    print("=" * 80)
    print("  清理孤立待办文件脚本")
    print("=" * 80)
    
    announcement_mgr = AnnouncementManager()
    todo_mgr = TodoManager()
    
    # 获取所有存在的公告ID
    announcements = announcement_mgr.get_announcements(status=None, include_temp=True)
    existing_announcement_ids = set()
    
    for ann in announcements:
        ann_id = ann.get('id', '')
        if ann_id:
            existing_announcement_ids.add(ann_id)
    
    print(f"📋 找到 {len(existing_announcement_ids)} 个存在的公告")
    
    # 获取所有待办文件
    todos_dir = os.path.join(DATA_DIR, 'todos')
    if not os.path.exists(todos_dir):
        print(f"❌ 待办目录不存在: {todos_dir}")
        return
    
    todo_files = [f for f in os.listdir(todos_dir) if f.endswith('_todos.xlsx')]
    print(f"📁 找到 {len(todo_files)} 个待办Excel文件")
    
    orphaned_files = []
    
    for filename in todo_files:
        # 提取公告ID：announcement_<id>_todos.xlsx
        # 去掉前缀 "announcement_" (13个字符) 和后缀 "_todos.xlsx" (11个字符)
        if filename.startswith('announcement_') and filename.endswith('_todos.xlsx'):
            announcement_id = filename[13:-11]  # 修正：_todos.xlsx是11个字符，不是10个
        else:
            continue
        
        # 检查公告是否存在
        if announcement_id not in existing_announcement_ids:
            orphaned_files.append({
                'filename': filename,
                'announcement_id': announcement_id,
                'file_path': os.path.join(todos_dir, filename)
            })
    
    if not orphaned_files:
        print("\n✅ 没有发现孤立的待办文件")
        return
    
    print(f"\n⚠️  发现 {len(orphaned_files)} 个孤立的待办文件（对应公告已不存在）:")
    for item in orphaned_files:
        print(f"  - {item['filename']} (公告ID: {item['announcement_id']})")
    
    # 询问是否删除
    print("\n是否要删除这些文件？(y/n): ", end='')
    try:
        response = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n❌ 操作已取消")
        return
    
    if response != 'y':
        print("❌ 操作已取消")
        return
    
    # 删除文件
    deleted_count = 0
    failed_count = 0
    
    for item in orphaned_files:
        try:
            os.remove(item['file_path'])
            deleted_count += 1
            print(f"  ✅ 已删除: {item['filename']}")
        except Exception as e:
            failed_count += 1
            print(f"  ❌ 删除失败: {item['filename']} - {e}")
    
    print(f"\n📊 清理完成: 成功删除 {deleted_count} 个文件, 失败 {failed_count} 个文件")

if __name__ == '__main__':
    try:
        cleanup_orphaned_todo_files()
    except Exception as e:
        import traceback
        print(f"\n❌ 清理过程发生错误: {e}")
        print(traceback.format_exc())
        sys.exit(1)

