"""
初始化看板/积分存储：优先 MySQL，回退 SQLite；支持从 SQLite 一次性迁移。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Optional, Tuple

from backend.models.dashboard_metrics import DashboardMetricsStore


def _mysql_configured() -> bool:
    host = (os.getenv("MYSQL_HOST") or "").strip()
    user = (os.getenv("MYSQL_USER") or "").strip()
    database = (os.getenv("MYSQL_DATABASE") or "").strip()
    return bool(host and user and database)


def migrate_sqlite_to_mysql(mysql_store: Any, sqlite_path: Path) -> bool:
    """
    若 MySQL 尚无积分事件且 SQLite 有数据，则导入并归档 SQLite 文件。
    返回是否执行了迁移。
    """
    if not sqlite_path.is_file():
        return False
    if not getattr(mysql_store, "is_empty", lambda: False)():
        return False

    conn = sqlite3.connect(str(sqlite_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM point_events").fetchone()
        if not row or int(row["c"]) <= 0:
            return False

        for row in conn.execute(
            "SELECT event_type, user_key, points, created_at FROM point_events ORDER BY id"
        ):
            mysql_store.record_point_event(
                str(row["event_type"]),
                str(row["user_key"]),
                float(row["points"]),
            )

        for row in conn.execute(
            "SELECT feature, user_key, created_at FROM feature_uses ORDER BY id"
        ):
            mysql_store.record_feature_use(
                str(row["feature"]),
                (row["user_key"] or None),
            )

        for row in conn.execute(
            "SELECT info_count, user_key, created_at FROM bom_info_snapshots ORDER BY id"
        ):
            mysql_store.record_bom_info_count(
                int(row["info_count"]),
                (row["user_key"] or None),
            )
    finally:
        conn.close()

    archived = sqlite_path.with_suffix(sqlite_path.suffix + ".migrated")
    try:
        shutil.move(str(sqlite_path), str(archived))
        print(f"[dashboard_metrics] SQLite 已迁移至 MySQL，归档: {archived}")
    except OSError as e:
        print(f"[dashboard_metrics] 迁移完成但归档 SQLite 失败: {e}")
    return True


def create_dashboard_metrics_store(
    sqlite_db_path: str,
) -> Tuple[Any, str]:
    """
    创建存储实例。
    返回 (store, storage_kind)，storage_kind 为 mysql | sqlite。
    """
    sqlite_path = Path(sqlite_db_path)
    errors: list[str] = []

    if _mysql_configured():
        try:
            from backend.models.dashboard_metrics_mysql import DashboardMetricsMysqlStore

            store = DashboardMetricsMysqlStore()
            if migrate_sqlite_to_mysql(store, sqlite_path):
                print("[dashboard_metrics] 已从 dashboard_metrics.db 导入历史积分/看板数据到 MySQL")
            kind = "mysql"
            host = (os.getenv("MYSQL_HOST") or "").strip()
            n = store.count_point_events()
            print(
                f"[dashboard_metrics] storage=mysql mysql_host={host} "
                f"point_events={n} data_dir={os.getenv('CHATROOM_DATA_DIR', '.')}"
            )
            return store, kind
        except Exception as e:
            errors.append(f"MySQL: {e}")
            print(f"[dashboard_metrics] MySQL 初始化失败，尝试 SQLite: {e}")

    try:
        store = DashboardMetricsStore(db_path=sqlite_db_path)
        n = 0
        try:
            with store._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS c FROM point_events").fetchone()
                n = int(row["c"]) if row else 0
        except Exception:
            pass
        print(
            f"[dashboard_metrics] storage=sqlite path={sqlite_path} "
            f"point_events={n} data_dir={os.getenv('CHATROOM_DATA_DIR', '.')}"
        )
        if errors:
            print(f"[dashboard_metrics] 注意: MySQL 不可用 ({'; '.join(errors)})")
        return store, "sqlite"
    except Exception as e:
        errors.append(f"SQLite: {e}")
        raise RuntimeError(
            "看板/积分存储初始化失败（MySQL 与 SQLite 均不可用）。"
            f" 详情: {'; '.join(errors)}"
        ) from e
