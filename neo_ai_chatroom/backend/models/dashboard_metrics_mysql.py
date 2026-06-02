"""
看板指标 + 用户积分（MySQL，与 htmlsystm 同库备份）。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, Generator, List, Optional, Tuple

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:
    pymysql = None  # type: ignore
    DictCursor = None  # type: ignore

from backend.models.dashboard_metrics import month_range  # noqa: F401 — re-export helper


class DashboardMetricsMysqlStore:
    """看板统计 + 用户积分（MySQL）。"""

    POINTS_BY_EVENT: Dict[str, float] = {
        "ai_check_export": 1.0,
        "schematic_review_export": 1.0,
        "material_db_edit": 1.0,
        "compare_tool": 0.1,
        "sop_complete": 0.5,
    }

    PIE_EXCLUDED_FEATURES = frozenset({"dashboard", "leaderboard"})

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        if pymysql is None:
            raise ImportError("未安装 pymysql，请 pip install pymysql")
        self._host = (host or os.getenv("MYSQL_HOST", "")).strip()
        self._port = int(port or os.getenv("MYSQL_PORT", "3306"))
        self._user = (user or os.getenv("MYSQL_USER", "")).strip()
        self._password = password if password is not None else os.getenv("MYSQL_PASSWORD", "")
        self._database = (database or os.getenv("MYSQL_DATABASE", "")).strip()
        if not self._host or not self._user or not self._database:
            raise ValueError("MySQL 配置不完整：需 MYSQL_HOST、MYSQL_USER、MYSQL_DATABASE")
        self._ping()
        self._ensure_neo_metrics_tables()
        self._rebuild_user_scores_from_events()

    def _ensure_neo_metrics_tables(self) -> None:
        """补建 NEO 积分/看板表（老库可能仅有 users 而无 neo_point_events）。"""
        ddl = [
            '''
            CREATE TABLE IF NOT EXISTS neo_point_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                event_type VARCHAR(64) NOT NULL,
                user_key VARCHAR(128) NOT NULL,
                points DOUBLE NOT NULL,
                created_at VARCHAR(32) NOT NULL,
                INDEX idx_neo_point_events_user (user_key),
                INDEX idx_neo_point_events_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            ''',
            '''
            CREATE TABLE IF NOT EXISTS neo_user_point_balances (
                user_key VARCHAR(128) PRIMARY KEY,
                total_points DOUBLE NOT NULL DEFAULT 0,
                month_points DOUBLE NOT NULL DEFAULT 0,
                month_id VARCHAR(16) NOT NULL DEFAULT '',
                updated_at VARCHAR(32) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            ''',
            '''
            CREATE TABLE IF NOT EXISTS neo_feature_uses (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                feature VARCHAR(128) NOT NULL,
                user_key VARCHAR(128) NULL,
                created_at VARCHAR(32) NOT NULL,
                INDEX idx_neo_feature_uses_created (created_at),
                INDEX idx_neo_feature_uses_user (user_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            ''',
            '''
            CREATE TABLE IF NOT EXISTS neo_bom_info_snapshots (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                info_count INT NOT NULL,
                user_key VARCHAR(128) NULL,
                created_at VARCHAR(32) NOT NULL,
                INDEX idx_neo_bom_info_created (created_at),
                INDEX idx_neo_bom_info_user (user_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            ''',
        ]
        with self._connect() as conn:
            with conn.cursor() as cur:
                for stmt in ddl:
                    cur.execute(stmt)
            conn.commit()

    def _connect_kwargs(self) -> Dict[str, Any]:
        return {
            "host": self._host,
            "port": self._port,
            "user": self._user,
            "password": self._password,
            "database": self._database,
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "autocommit": False,
        }

    @contextmanager
    def _connect(self) -> Generator[Any, None, None]:
        conn = pymysql.connect(**self._connect_kwargs())
        try:
            yield conn
        finally:
            conn.close()

    def _ping(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.commit()

    @staticmethod
    def _round_points(value: float) -> float:
        return round(float(value) + 1e-9, 1)

    def _current_month_id(self) -> str:
        now = datetime.now()
        return f"{now.year:04d}-{now.month:02d}"

    def _parse_ts(self, s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00")[:19])
        except Exception:
            return None

    def _is_in_current_month(self, created_at: Optional[str]) -> bool:
        dt = self._parse_ts(created_at)
        if not dt:
            return False
        now = datetime.now()
        return dt.year == now.year and dt.month == now.month

    def _apply_points_in_tx(
        self,
        cur: Any,
        user_key: str,
        points: float,
        created_at: Optional[str] = None,
    ) -> None:
        if points <= 0:
            return
        uk = (user_key or "").strip()[:128]
        if not uk:
            return
        pts = self._round_points(points)
        in_month = self._is_in_current_month(created_at) if created_at else True
        month_id = self._current_month_id()
        now = datetime.now().isoformat(timespec="seconds")
        month_delta = pts if in_month else 0.0
        cur.execute(
            """
            INSERT INTO neo_user_point_balances (user_key, total_points, month_points, month_id, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                total_points = ROUND(total_points + %s, 1),
                month_points = CASE
                    WHEN month_id = %s THEN ROUND(month_points + %s, 1)
                    ELSE %s
                END,
                month_id = %s,
                updated_at = %s
            """,
            (uk, pts, month_delta, month_id, now, pts, month_id, month_delta, month_delta, month_id, now),
        )

    def record_point_event(
        self,
        event_type: str,
        user_key: Optional[str],
        points: Optional[float] = None,
    ) -> None:
        et = (event_type or "").strip()[:64]
        if not et:
            return
        uk = (user_key or "").strip()[:128]
        if not uk:
            return
        pts = self._round_points(
            float(points) if points is not None else self.POINTS_BY_EVENT.get(et, 0.0)
        )
        if pts <= 0:
            return
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO neo_point_events (event_type, user_key, points, created_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (et, uk, pts, now),
                    )
                    self._apply_points_in_tx(cur, uk, pts, now)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def consolidate_user_key_aliases(self, aliases: Dict[str, str]) -> int:
        """将历史 neo_point_events 中的别名字段合并为规范 user_key。"""
        updated = 0
        with self._connect() as conn:
            try:
                conn.begin()
                with conn.cursor() as cur:
                    for alias, canonical in (aliases or {}).items():
                        a = (alias or "").strip()[:128]
                        c = (canonical or "").strip()[:128]
                        if not a or not c or a == c:
                            continue
                        cur.execute(
                            "UPDATE neo_point_events SET user_key = %s WHERE user_key = %s",
                            (c, a),
                        )
                        updated += int(cur.rowcount or 0)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if updated:
            self._rebuild_user_scores_from_events()
        return updated

    def _rebuild_user_scores_from_events(self) -> None:
        month_id = self._current_month_id()
        totals: Dict[str, Dict[str, float]] = {}

        def bump(key: str, points: float, in_month: bool) -> None:
            if key not in totals:
                totals[key] = {"total": 0.0, "month": 0.0}
            totals[key]["total"] = self._round_points(totals[key]["total"] + points)
            if in_month:
                totals[key]["month"] = self._round_points(totals[key]["month"] + points)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_key, points, created_at FROM neo_point_events WHERE user_key != ''"
                )
                for row in cur.fetchall():
                    uk = str(row["user_key"]).strip()
                    pts = self._round_points(float(row["points"]))
                    bump(uk, pts, self._is_in_current_month(row["created_at"]))
                now = datetime.now().isoformat(timespec="seconds")
                cur.execute("DELETE FROM neo_user_point_balances")
                for uk, pts in totals.items():
                    cur.execute(
                        """
                        INSERT INTO neo_user_point_balances
                            (user_key, total_points, month_points, month_id, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (uk, pts["total"], pts["month"], month_id, now),
                    )
            conn.commit()

    def record_feature_use(self, feature: str, user_key: Optional[str] = None) -> None:
        feat = (feature or "").strip()[:128]
        if not feat:
            return
        uk = (user_key or "").strip()[:128] or None
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO neo_feature_uses (feature, user_key, created_at) VALUES (%s, %s, %s)",
                    (feat, uk, now),
                )
            conn.commit()

    def record_bom_info_count(self, info_count: int, user_key: Optional[str] = None) -> None:
        n = max(0, int(info_count))
        uk = (user_key or "").strip()[:128] or None
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO neo_bom_info_snapshots (info_count, user_key, created_at) VALUES (%s, %s, %s)",
                    (n, uk, now),
                )
            conn.commit()

    def user_points_totals(self) -> Dict[str, Dict[str, float]]:
        month_id = self._current_month_id()
        out: Dict[str, Dict[str, float]] = {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_key, total_points, month_points, month_id FROM neo_user_point_balances"
                )
                for row in cur.fetchall():
                    uk = str(row["user_key"]).strip()
                    if not uk:
                        continue
                    total = self._round_points(float(row["total_points"]))
                    month_pts = self._round_points(float(row["month_points"]))
                    if str(row["month_id"] or "") != month_id:
                        month_pts = 0.0
                    out[uk] = {"total": total, "month": month_pts}
        return out

    def get_user_points(self, user_key: Optional[str]) -> Dict[str, float]:
        uk = (user_key or "").strip()
        if not uk:
            return {"total": 0.0, "month": 0.0}
        return self.user_points_totals().get(uk, {"total": 0.0, "month": 0.0})

    def count_point_events(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM neo_point_events")
                row = cur.fetchone()
                return int(row["c"]) if row else 0

    def total_feature_uses(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM neo_feature_uses")
                row = cur.fetchone()
                return int(row["c"]) if row else 0

    def feature_uses_since(self, since: datetime) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM neo_feature_uses WHERE created_at >= %s",
                    (since.isoformat(timespec="seconds"),),
                )
                row = cur.fetchone()
                return int(row["c"]) if row else 0

    def feature_breakdown(self) -> Dict[str, int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT feature, COUNT(*) AS c FROM neo_feature_uses GROUP BY feature ORDER BY c DESC"
                )
                return {str(r["feature"]): int(r["c"]) for r in cur.fetchall()}

    def _week_slots(self, num_weeks: int) -> List[Tuple[datetime, datetime]]:
        now = datetime.now()
        week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        slots: List[Tuple[datetime, datetime]] = []
        for i in range(num_weeks):
            ws = week_start - timedelta(weeks=(num_weeks - 1 - i))
            we = ws + timedelta(days=7)
            slots.append((ws, we))
        return slots

    def weekly_feature_counts(self, num_weeks: int = 4) -> List[int]:
        counts: List[int] = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                for ws, we in self._week_slots(num_weeks):
                    cur.execute(
                        """
                        SELECT COUNT(*) AS c FROM neo_feature_uses
                        WHERE created_at >= %s AND created_at < %s
                        """,
                        (ws.isoformat(timespec="seconds"), we.isoformat(timespec="seconds")),
                    )
                    row = cur.fetchone()
                    counts.append(int(row["c"]) if row else 0)
        return counts

    def weekly_bom_info_sums(self, num_weeks: int = 4) -> List[int]:
        sums: List[int] = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                for ws, we in self._week_slots(num_weeks):
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(info_count), 0) AS s FROM neo_bom_info_snapshots
                        WHERE created_at >= %s AND created_at < %s
                        """,
                        (ws.isoformat(timespec="seconds"), we.isoformat(timespec="seconds")),
                    )
                    row = cur.fetchone()
                    sums.append(int(row["s"]) if row else 0)
        return sums

    def sum_bom_info_all(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(SUM(info_count), 0) AS s FROM neo_bom_info_snapshots")
                row = cur.fetchone()
                return int(row["s"]) if row else 0

    def sum_bom_info_in_range(self, start: datetime, end: datetime) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(info_count), 0) AS s FROM neo_bom_info_snapshots
                    WHERE created_at >= %s AND created_at < %s
                    """,
                    (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
                )
                row = cur.fetchone()
                return int(row["s"]) if row else 0

    def uses_in_range(self, start: datetime, end: datetime) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS c FROM neo_feature_uses
                    WHERE created_at >= %s AND created_at < %s
                    """,
                    (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
                )
                row = cur.fetchone()
                return int(row["c"]) if row else 0

    def list_recent_activity(self, limit: int = 40) -> List[Dict[str, Any]]:
        per_source = max(limit, 20)
        items: List[Dict[str, Any]] = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT feature, user_key, created_at FROM neo_feature_uses
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (per_source,),
                )
                for row in cur.fetchall():
                    items.append({
                        "kind": "feature",
                        "detail": str(row["feature"] or ""),
                        "user_key": (row["user_key"] or "").strip() or None,
                        "created_at": str(row["created_at"] or ""),
                    })
                cur.execute(
                    """
                    SELECT info_count, user_key, created_at FROM neo_bom_info_snapshots
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (per_source,),
                )
                for row in cur.fetchall():
                    items.append({
                        "kind": "bom",
                        "detail": str(int(row["info_count"] or 0)),
                        "user_key": (row["user_key"] or "").strip() or None,
                        "created_at": str(row["created_at"] or ""),
                    })
                cur.execute(
                    """
                    SELECT event_type, user_key, created_at FROM neo_point_events
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (per_source,),
                )
                for row in cur.fetchall():
                    items.append({
                        "kind": "points",
                        "detail": str(row["event_type"] or ""),
                        "user_key": (row["user_key"] or "").strip() or None,
                        "created_at": str(row["created_at"] or ""),
                    })
        items.sort(key=lambda it: str(it.get("created_at") or ""), reverse=True)
        return items[:limit]

    def list_feature_uses(
        self, limit: int = 80, exclude_features: Optional[frozenset] = None
    ) -> List[Dict[str, Any]]:
        excluded = exclude_features if exclude_features is not None else self.PIE_EXCLUDED_FEATURES
        fetch_n = limit + len(excluded) * 20
        rows: List[Dict[str, Any]] = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT feature, user_key, created_at FROM neo_feature_uses
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (fetch_n,),
                )
                for row in cur.fetchall():
                    feat = str(row["feature"] or "").strip()
                    if feat in excluded:
                        continue
                    rows.append({
                        "feature": feat,
                        "user_key": (row["user_key"] or "").strip() or None,
                        "created_at": str(row["created_at"] or ""),
                    })
                    if len(rows) >= limit:
                        break
        return rows

    def list_bom_snapshots(self, limit: int = 80) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT info_count, user_key, created_at FROM neo_bom_info_snapshots
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (limit,),
                )
                return [
                    {
                        "info_count": int(row["info_count"] or 0),
                        "user_key": (row["user_key"] or "").strip() or None,
                        "created_at": str(row["created_at"] or ""),
                    }
                    for row in cur.fetchall()
                ]

    def is_empty(self) -> bool:
        """是否尚无积分事件（用于判断是否需要从 SQLite 迁移）。"""
        return self.count_point_events() == 0
