"""
主页组件使用次数、BOM INFO 上报等看板指标（SQLite）。
按 user_key 维护总积分与当月积分，与前端首页展示一致。
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class DashboardMetricsStore:
    """看板统计 + 用户积分（point_events 表为积分唯一来源）。"""

    POINTS_BY_EVENT: Dict[str, float] = {
        "ai_check_export": 1.0,
        "schematic_review_export": 1.0,
        "material_db_edit": 1.0,
        "compare_tool": 0.1,
        "sop_complete": 0.5,
    }

    def __init__(self, db_path: str = "dashboard_metrics.db"):
        self.db_path = Path(db_path)
        self._init_db()
        self._rebuild_user_scores_from_events()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_uses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feature TEXT NOT NULL,
                    user_key TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bom_info_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    info_count INTEGER NOT NULL,
                    user_key TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS point_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    user_key TEXT NOT NULL,
                    points REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_point_balances (
                    user_key TEXT PRIMARY KEY,
                    total_points REAL NOT NULL DEFAULT 0,
                    month_points REAL NOT NULL DEFAULT 0,
                    month_id TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "feature_uses", "user_key", "TEXT")
            self._ensure_column(conn, "bom_info_snapshots", "user_key", "TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feature_uses_created ON feature_uses(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bom_info_created ON bom_info_snapshots(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_point_events_user ON point_events(user_key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_point_events_created ON point_events(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feature_uses_user ON feature_uses(user_key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bom_info_user ON bom_info_snapshots(user_key)"
            )
            conn.commit()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {str(r[1]) for r in rows}
        if column not in names:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def _current_month_id(self) -> str:
        now = datetime.now()
        return f"{now.year:04d}-{now.month:02d}"

    def _month_start(self) -> datetime:
        now = datetime.now()
        return datetime(now.year, now.month, 1, 0, 0, 0)

    def _is_in_current_month(self, created_at: Optional[str]) -> bool:
        dt = self._parse_ts(created_at)
        if not dt:
            return False
        now = datetime.now()
        return dt.year == now.year and dt.month == now.month

    @staticmethod
    def _round_points(value: float) -> float:
        return round(float(value) + 1e-9, 1)

    def _apply_points_in_tx(
        self,
        conn: sqlite3.Connection,
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
        conn.execute(
            """
            INSERT INTO user_point_balances (user_key, total_points, month_points, month_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_key) DO UPDATE SET
                total_points = ROUND(user_point_balances.total_points + ?, 1),
                month_points = CASE
                    WHEN user_point_balances.month_id = ? THEN ROUND(user_point_balances.month_points + ?, 1)
                    ELSE ?
                END,
                month_id = ?,
                updated_at = excluded.updated_at
            """,
            (uk, pts, month_delta, month_id, now, pts, month_id, month_delta, month_delta, month_id),
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
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO point_events (event_type, user_key, points, created_at) VALUES (?, ?, ?, ?)",
                    (et, uk, pts, now),
                )
                self._apply_points_in_tx(conn, uk, pts, now)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def consolidate_user_key_aliases(self, aliases: Dict[str, str]) -> int:
        """
        将历史 point_events 中的别名字段（如 username）合并为规范 user_key（钉钉 userid）。
        返回更新的行数。
        """
        updated = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for alias, canonical in (aliases or {}).items():
                    a = (alias or "").strip()[:128]
                    c = (canonical or "").strip()[:128]
                    if not a or not c or a == c:
                        continue
                    cur = conn.execute(
                        "UPDATE point_events SET user_key = ? WHERE user_key = ?",
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
        """从 point_events 重建用户积分余额。"""
        month_id = self._current_month_id()
        totals: Dict[str, Dict[str, float]] = {}

        def bump(key: str, points: float, in_month: bool) -> None:
            if key not in totals:
                totals[key] = {"total": 0.0, "month": 0.0}
            totals[key]["total"] = self._round_points(totals[key]["total"] + points)
            if in_month:
                totals[key]["month"] = self._round_points(totals[key]["month"] + points)

        with self._connect() as conn:
            for row in conn.execute(
                "SELECT user_key, points, created_at FROM point_events WHERE user_key != ''"
            ):
                uk = str(row["user_key"]).strip()
                pts = self._round_points(float(row["points"]))
                bump(uk, pts, self._is_in_current_month(row["created_at"]))

            now = datetime.now().isoformat(timespec="seconds")
            conn.execute("DELETE FROM user_point_balances")
            for uk, pts in totals.items():
                conn.execute(
                    """
                    INSERT INTO user_point_balances (user_key, total_points, month_points, month_id, updated_at)
                    VALUES (?, ?, ?, ?, ?)
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
            conn.execute(
                "INSERT INTO feature_uses (feature, user_key, created_at) VALUES (?, ?, ?)",
                (feat, uk, now),
            )
            conn.commit()

    def record_bom_info_count(self, info_count: int, user_key: Optional[str] = None) -> None:
        n = int(info_count)
        if n < 0:
            n = 0
        uk = (user_key or "").strip()[:128] or None
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO bom_info_snapshots (info_count, user_key, created_at) VALUES (?, ?, ?)",
                (n, uk, now),
            )
            conn.commit()

    def user_points_totals(self) -> Dict[str, Dict[str, float]]:
        """按 user_key 返回总积分与当月积分（与首页 /api/leaderboard 一致）。"""
        month_id = self._current_month_id()
        out: Dict[str, Dict[str, float]] = {}
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT user_key, total_points, month_points, month_id FROM user_point_balances"
            ):
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
        totals = self.user_points_totals()
        return totals.get(uk, {"total": 0.0, "month": 0.0})

    def count_point_events(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM point_events").fetchone()
            return int(row["c"]) if row else 0

    def is_empty(self) -> bool:
        return self.count_point_events() == 0

    def _parse_ts(self, s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00")[:19])
        except Exception:
            return None

    def total_feature_uses(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM feature_uses").fetchone()
            return int(row["c"]) if row else 0

    def feature_uses_since(self, since: datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM feature_uses WHERE created_at >= ?",
                (since.isoformat(timespec="seconds"),),
            ).fetchone()
            return int(row["c"]) if row else 0

    def feature_breakdown(self) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT feature, COUNT(*) AS c FROM feature_uses GROUP BY feature ORDER BY c DESC"
            ).fetchall()
            return {str(r["feature"]): int(r["c"]) for r in rows}

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
            for ws, we in self._week_slots(num_weeks):
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM feature_uses
                    WHERE created_at >= ? AND created_at < ?
                    """,
                    (ws.isoformat(timespec="seconds"), we.isoformat(timespec="seconds")),
                ).fetchone()
                counts.append(int(row["c"]) if row else 0)
        return counts

    def weekly_bom_info_sums(self, num_weeks: int = 4) -> List[int]:
        sums: List[int] = []
        with self._connect() as conn:
            for ws, we in self._week_slots(num_weeks):
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(info_count), 0) AS s FROM bom_info_snapshots
                    WHERE created_at >= ? AND created_at < ?
                    """,
                    (ws.isoformat(timespec="seconds"), we.isoformat(timespec="seconds")),
                ).fetchone()
                sums.append(int(row["s"]) if row else 0)
        return sums

    def sum_bom_info_all(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(info_count), 0) AS s FROM bom_info_snapshots"
            ).fetchone()
            return int(row["s"]) if row else 0

    def sum_bom_info_in_range(self, start: datetime, end: datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(info_count), 0) AS s FROM bom_info_snapshots
                WHERE created_at >= ? AND created_at < ?
                """,
                (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
            ).fetchone()
            return int(row["s"]) if row else 0

    def uses_in_range(self, start: datetime, end: datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM feature_uses
                WHERE created_at >= ? AND created_at < ?
                """,
                (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
            ).fetchone()
            return int(row["c"]) if row else 0

    def list_recent_activity(self, limit: int = 40) -> List[Dict[str, Any]]:
        """合并功能点击、BOM 上报、积分事件，按时间倒序返回近期动态。"""
        per_source = max(limit, 20)
        items: List[Dict[str, Any]] = []
        with self._connect() as conn:
            for row in conn.execute(
                """
                SELECT feature, user_key, created_at FROM feature_uses
                ORDER BY created_at DESC LIMIT ?
                """,
                (per_source,),
            ):
                items.append({
                    "kind": "feature",
                    "detail": str(row["feature"] or ""),
                    "user_key": (row["user_key"] or "").strip() or None,
                    "created_at": str(row["created_at"] or ""),
                })
            for row in conn.execute(
                """
                SELECT info_count, user_key, created_at FROM bom_info_snapshots
                ORDER BY created_at DESC LIMIT ?
                """,
                (per_source,),
            ):
                items.append({
                    "kind": "bom",
                    "detail": str(int(row["info_count"] or 0)),
                    "user_key": (row["user_key"] or "").strip() or None,
                    "created_at": str(row["created_at"] or ""),
                })
            for row in conn.execute(
                """
                SELECT event_type, user_key, created_at FROM point_events
                ORDER BY created_at DESC LIMIT ?
                """,
                (per_source,),
            ):
                items.append({
                    "kind": "points",
                    "detail": str(row["event_type"] or ""),
                    "user_key": (row["user_key"] or "").strip() or None,
                    "created_at": str(row["created_at"] or ""),
                })

        def sort_key(it: Dict[str, Any]) -> str:
            return str(it.get("created_at") or "")

        items.sort(key=sort_key, reverse=True)
        return items[:limit]

    # 饼图与「组件使用」明细均不展示
    PIE_EXCLUDED_FEATURES = frozenset({"dashboard", "leaderboard"})

    def list_feature_uses(
        self, limit: int = 80, exclude_features: Optional[frozenset] = None
    ) -> List[Dict[str, Any]]:
        excluded = exclude_features if exclude_features is not None else self.PIE_EXCLUDED_FEATURES
        fetch_n = limit + len(excluded) * 20
        rows: List[Dict[str, Any]] = []
        with self._connect() as conn:
            for row in conn.execute(
                """
                SELECT feature, user_key, created_at FROM feature_uses
                ORDER BY created_at DESC LIMIT ?
                """,
                (fetch_n,),
            ):
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
            cur = conn.execute(
                """
                SELECT info_count, user_key, created_at FROM bom_info_snapshots
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            return [
                {
                    "info_count": int(row["info_count"] or 0),
                    "user_key": (row["user_key"] or "").strip() or None,
                    "created_at": str(row["created_at"] or ""),
                }
                for row in cur
            ]


def count_netlist_need_check_items(analysis_result: Dict[str, Any]) -> int:
    summary = analysis_result.get("summary") or {}
    analysis = analysis_result.get("analysis") or {}
    issues = analysis.get("potential_issues") or []
    n = 2
    power = summary.get("power_nets") or []
    if power:
        n += 1
    n += len(issues)
    return n


def month_range(year: int, month: int) -> Tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end
