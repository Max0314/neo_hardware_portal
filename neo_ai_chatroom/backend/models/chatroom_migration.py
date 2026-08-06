"""chatroom.db（SQLite）→ 共享 MySQL 的一次性数据迁移。

在应用启动、所有表结构就绪之后调用。防护规则：

- MySQL 的 messages 或 conversations 已有数据 → 判定已迁移过，直接跳过；
- 旧 SQLite 文件不存在 → 无可迁移，跳过；
- 全部表在**同一个 MySQL 事务**内写入，任一失败即回滚，下次启动自动重试；
- 提交后逐表核对行数，全部一致才把 SQLite 文件改名归档（.migrated-<时间戳>），
  绝不删除原文件。

时间戳原样复制：SQLite 的 CURRENT_TIMESTAMP 是 UTC 文本，历史数据展示效果与
迁移前完全一致；新写入行由 MySQL 按服务器时区生成，二者相隔数天，不影响排序。

参考先例：dashboard_metrics_factory.migrate_sqlite_to_mysql（已在生产完成迁移）。
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Tuple

from backend.models import db_compat

# (SQLite 表名, MySQL 表名)。system_config 在 MySQL 侧更名，
# 因为同库的 htmlsystm 已有一张同名但列结构不同的表。
_TABLES: List[Tuple[str, str]] = [
    ("conversations", "conversations"),
    ("messages", "messages"),
    ("custom_ai_roles", "custom_ai_roles"),
    ("custom_ai_role_config", "custom_ai_role_config"),
    ("knowledge_recycle_bin", "knowledge_recycle_bin"),
    ("role_knowledge_associations", "role_knowledge_associations"),
    ("admin_config", "admin_config"),
    ("ai_provider_secrets", "ai_provider_secrets"),
    ("schematic_review_prompt_history", "schematic_review_prompt_history"),
    ("schematic_review_history", "schematic_review_history"),
    ("system_config", "neo_system_config"),
    ("knowledge_base", "knowledge_base"),
    ("memory_recall_config", "memory_recall_config"),
    ("memory_templates", "memory_templates"),
    ("memory_items", "memory_items"),
    ("memory_extraction_dedup", "memory_extraction_dedup"),
]

# 这些表在应用启动时会写入默认种子行（admin_config 的 default、
# memory_recall_config 的 id=1、memory_templates 的 tpl_default_*）。
# 迁移用 REPLACE 让 SQLite 里的真实数据覆盖种子；其余表用普通 INSERT，
# 撞主键即报错回滚，避免悄悄吞掉数据不一致。
_SEEDED = {"admin_config", "memory_recall_config", "memory_templates"}


def _sqlite_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for src, _dst in _TABLES:
        try:
            counts[src] = conn.execute(f'SELECT COUNT(*) FROM "{src}"').fetchone()[0]
        except sqlite3.OperationalError:
            counts[src] = -1  # 表不存在（旧库可能缺个别表）
    return counts


def migrate_if_needed(sqlite_path: str) -> bool:
    """需要时执行迁移。返回是否真的执行了迁移。"""
    path = Path(sqlite_path)
    if not path.is_file():
        return False

    # 已迁移判定：MySQL 侧核心表有数据即跳过
    guard = db_compat.connect_sync()
    try:
        n_msg = guard.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        n_conv = guard.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    finally:
        guard.close()
    if n_msg > 0 or n_conv > 0:
        return False

    src = sqlite3.connect(str(path), timeout=30.0)
    src.row_factory = sqlite3.Row
    try:
        counts = _sqlite_counts(src)
        total = sum(c for c in counts.values() if c > 0)
        if total == 0:
            print("[chatroom-migration] 旧 SQLite 无数据，跳过迁移")
            return False

        print(f"[chatroom-migration] 开始迁移 {path.name} → MySQL（{total} 行）")
        dst = db_compat.connect_sync()
        try:
            for src_table, dst_table in _TABLES:
                if counts.get(src_table, -1) <= 0:
                    continue
                rows = src.execute(f'SELECT * FROM "{src_table}"').fetchall()
                columns = rows[0].keys()
                col_list = ", ".join(f"`{c}`" for c in columns)
                placeholders = ", ".join("?" for _ in columns)
                verb = "REPLACE" if src_table in _SEEDED else "INSERT"
                sql = f"{verb} INTO `{dst_table}` ({col_list}) VALUES ({placeholders})"
                dst.executemany(sql, [tuple(r) for r in rows])
                print(f"[chatroom-migration]   {src_table} → {dst_table}: {len(rows)} 行")
            dst.commit()

            # 提交后逐表核对
            mismatch = []
            for src_table, dst_table in _TABLES:
                expect = counts.get(src_table, -1)
                if expect < 0:
                    continue
                got = dst.execute(f"SELECT COUNT(*) FROM `{dst_table}`").fetchone()[0]
                if got != expect:
                    mismatch.append(f"{dst_table}: 期望 {expect} 实际 {got}")
            if mismatch:
                # 数据已提交但数量对不上——不归档源文件，人工介入
                raise RuntimeError("行数核对失败: " + "; ".join(mismatch))
        except Exception:
            try:
                dst.rollback()
            finally:
                dst.close()
            raise
        dst.close()
    finally:
        src.close()

    # 全部核对通过，归档源文件（连同 -wal/-shm），保留原数据可随时回看
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.rename(str(p) + f".migrated-{stamp}")
    print(f"[chatroom-migration] 迁移完成并已核对，源文件归档为 *.migrated-{stamp}")
    return True
