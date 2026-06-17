#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BI 中心使用数据导出 API（/api/export/usage/*，只读）。

为「研发 BI 中心」(bi_center) 提供硬件 NEO 助手的使用数据，复刻已跑通的
「专利系统 BI 对接」模式：X-API-Key 鉴权 + {ok,data,pagination} 信封 +
以钉钉 userId 对齐。数据取自本库（与 NEO 助手后端同库）的 neo_* 指标表。

口径要点（务必与 BI 侧对账口径保持一致）：
- neo_* 表 created_at 为 ISO 字符串 'YYYY-MM-DDTHH:MM:SS'（容器北京时间、无时区
  后缀；由 NEO 后端 datetime.now().isoformat(timespec="seconds") 写入）。因带 'T'
  分隔符，MySQL 的 DATE_FORMAT / 隐式 datetime 转换不可靠，故月份/自然日一律用
  字符串前缀匹配：LEFT(created_at,7)=YYYY-MM、LEFT(created_at,10)=YYYY-MM-DD。
  ISO 定长字符串的字典序即时间序，可安全用于比较与 MAX()。
- userId = neo_*.user_key = 钉钉 userId，始终按字符串输出（库中即 VARCHAR，不丢精度）。
- pointsEarned = 该月 neo_point_events 的 SUM(points)，是按月权威值（任意历史月可对账）。
- monthPoints 取自 neo_user_point_balances（实时余额表，仅保存"当前月"的 month_id），
  故仅当前月有值、历史月返回 0；历史月对账请以 pointsEarned 为准。
- 仅统计 user_key 非空的行（匿名使用无法归人）。物料库审计 / 登录日志 / 公告等不在范围。
"""
import hmac
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from server.logger import logger

API_KEY_ENV = "BI_EXPORT_API_KEY"
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 200


class BiExportApi:
    """/api/export/usage/* 的请求分派与实现。"""

    def __init__(self, handler: Any):
        self.h = handler

    # ---------------------------------------------------------------- routing
    def dispatch(self, method: str, path: str, parsed_path: Any) -> None:
        try:
            if not self._authorized():
                return
            if path == "/api/export/usage/monthly":
                self._usage_monthly(parsed_path)
            elif path == "/api/export/usage/latest":
                self._usage_latest()
            else:
                self._fail(404, "invalid_params")
        except Exception as exc:  # 始终返回 JSON 信封，绝不抛裸 500
            logger.error(f"[bi-export] 处理失败 path={path}: {exc}", exc_info=True)
            self._fail(500, "internal_error")

    # ------------------------------------------------------------------- auth
    def _authorized(self) -> bool:
        configured = (os.getenv(API_KEY_ENV) or "").strip()
        if not configured:
            self._fail(503, "export_not_configured")
            return False
        provided = self._header("X-API-Key").strip()
        if not provided or not hmac.compare_digest(provided, configured):
            self._fail(401, "unauthorized")
            return False
        return True

    # -------------------------------------------------------------- responses
    def _fail(self, status: int, error: str) -> None:
        self.h.send_json_response({"ok": False, "error": error}, status=status)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _pool():
        from server.mysql_connection_pool import get_mysql_connection_pool
        return get_mysql_connection_pool()

    @staticmethod
    def _round1(value: Any) -> float:
        try:
            return round(float(value) + 1e-9, 1)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clean_key(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    def _header(self, name: str) -> str:
        """Read a request header case-insensitively across HTTP and WSGI adapters."""
        headers = getattr(self.h, "headers", None)
        if not headers:
            return ""
        getter = getattr(headers, "get", None)
        if callable(getter):
            candidates = (name, name.title(), name.lower(), name.upper())
            for candidate in candidates:
                value = getter(candidate, None)
                if value is not None:
                    return str(value)
        target = name.lower()
        items = getattr(headers, "items", None)
        if callable(items):
            for key, value in items():
                if str(key).lower() == target:
                    return str(value or "")
        return ""

    @staticmethod
    def _int_param(params: Dict[str, List[str]], name: str, default: int) -> Optional[int]:
        raw = ((params.get(name) or [""])[0] or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return None

    # ---------------------------------------------------- GET .../usage/monthly
    def _usage_monthly(self, parsed_path: Any) -> None:
        params = self.h._get_query_params(parsed_path)
        month = ((params.get("month") or [""])[0] or "").strip()
        if not MONTH_RE.match(month):
            self._fail(400, "invalid_params")
            return
        page = self._int_param(params, "page", 1)
        page_size = self._int_param(params, "pageSize", DEFAULT_PAGE_SIZE)
        if page is None or page_size is None or page < 1 or page_size < 1:
            self._fail(400, "invalid_params")
            return
        page_size = min(page_size, MAX_PAGE_SIZE)

        rows = self._aggregate_month(month)
        total = len(rows)
        total_pages = math.ceil(total / page_size) if total else 0
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        self.h.send_json_response({
            "ok": True,
            "data": page_rows,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": total_pages,
            },
        }, status=200)

    def _aggregate_month(self, month: str) -> List[Dict[str, Any]]:
        """按「员工 × 月」聚合 neo_* 指标，返回稳定排序后的整表（分页在内存切片）。"""
        pool = self._pool()
        agg: Dict[str, Dict[str, Any]] = {}

        def slot(uk: str) -> Dict[str, Any]:
            s = agg.get(uk)
            if s is None:
                s = {
                    "featureUses": {},
                    "totalFeatureUses": 0,
                    "pointsEarned": 0.0,
                    "monthPoints": 0.0,
                    "bomInfoCount": 0,
                    "activeDays": 0,
                }
                agg[uk] = s
            return s

        # 1) 功能使用：user_key × feature 计数（totalFeatureUses = 各 feature 计数之和）
        for r in pool.execute_query(
            """
            SELECT user_key, feature, COUNT(*) AS cnt
            FROM neo_feature_uses
            WHERE LEFT(created_at, 7) = %s
              AND user_key IS NOT NULL AND user_key <> ''
            GROUP BY user_key, feature
            """,
            (month,),
        ):
            uk = self._clean_key(r.get("user_key"))
            feat = str(r.get("feature") or "").strip()
            if not uk or not feat:
                continue
            cnt = int(r.get("cnt") or 0)
            s = slot(uk)
            s["featureUses"][feat] = s["featureUses"].get(feat, 0) + cnt
            s["totalFeatureUses"] += cnt

        # 2) 积分：该月 SUM(points)
        for r in pool.execute_query(
            """
            SELECT user_key, SUM(points) AS pts
            FROM neo_point_events
            WHERE LEFT(created_at, 7) = %s
              AND user_key IS NOT NULL AND user_key <> ''
            GROUP BY user_key
            """,
            (month,),
        ):
            uk = self._clean_key(r.get("user_key"))
            if not uk:
                continue
            slot(uk)["pointsEarned"] = self._round1(r.get("pts"))

        # 3) 活跃天数：feature + point 事件去重后的北京自然日数
        for r in pool.execute_query(
            """
            SELECT user_key, COUNT(DISTINCT d) AS active_days FROM (
                SELECT user_key, LEFT(created_at, 10) AS d FROM neo_feature_uses
                WHERE LEFT(created_at, 7) = %s AND user_key IS NOT NULL AND user_key <> ''
                UNION
                SELECT user_key, LEFT(created_at, 10) AS d FROM neo_point_events
                WHERE LEFT(created_at, 7) = %s AND user_key IS NOT NULL AND user_key <> ''
            ) t
            GROUP BY user_key
            """,
            (month, month),
        ):
            uk = self._clean_key(r.get("user_key"))
            if not uk:
                continue
            slot(uk)["activeDays"] = int(r.get("active_days") or 0)

        # 4) BOM 信息数：该月最新一条快照的 info_count（仅补给已有使用记录的员工）
        for r in pool.execute_query(
            """
            SELECT s.user_key AS user_key, s.info_count AS info_count
            FROM neo_bom_info_snapshots s
            JOIN (
                SELECT user_key, MAX(created_at) AS mx
                FROM neo_bom_info_snapshots
                WHERE LEFT(created_at, 7) = %s
                  AND user_key IS NOT NULL AND user_key <> ''
                GROUP BY user_key
            ) m ON m.user_key = s.user_key AND m.mx = s.created_at
            """,
            (month,),
        ):
            uk = self._clean_key(r.get("user_key"))
            if not uk or uk not in agg:
                continue
            s = agg[uk]
            # 同秒并列时 JOIN 可能返回多行，取较大值以保证确定性
            s["bomInfoCount"] = max(s["bomInfoCount"], int(r.get("info_count") or 0))

        # 5) monthPoints：实时余额表，仅当前月 month_id 命中（历史月维持 0）
        for r in pool.execute_query(
            """
            SELECT user_key, month_points
            FROM neo_user_point_balances
            WHERE month_id = %s AND user_key IS NOT NULL AND user_key <> ''
            """,
            (month,),
        ):
            uk = self._clean_key(r.get("user_key"))
            if uk in agg:
                agg[uk]["monthPoints"] = self._round1(r.get("month_points"))

        # 身份回填：users.dingtalk_userid = user_key
        identities = self._lookup_identities(list(agg.keys()))

        out: List[Dict[str, Any]] = []
        for uk, s in agg.items():
            ident = identities.get(uk) or {}
            out.append({
                "userId": uk,                          # 字符串，原样输出
                "userName": ident.get("name") or "",   # 匹配不上给空串（BI 按 userId 兜底）
                "department": ident.get("department"),  # 匹配不上给 null
                "jobNumber": ident.get("job_number"),   # 匹配不上给 null
                "featureUses": s["featureUses"],
                "totalFeatureUses": s["totalFeatureUses"],
                "pointsEarned": s["pointsEarned"],
                "monthPoints": s["monthPoints"],
                "bomInfoCount": s["bomInfoCount"],
                "activeDays": s["activeDays"],
            })
        # 稳定全序排序（使用次数→积分→userId），保证 bi_center 逐页拉取结果可重复
        out.sort(key=lambda x: (-x["totalFeatureUses"], -x["pointsEarned"], x["userId"]))
        return out

    def _lookup_identities(self, user_keys: List[str]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        if not user_keys:
            return out
        pool = self._pool()
        chunk = 500
        for i in range(0, len(user_keys), chunk):
            part = user_keys[i:i + chunk]
            placeholders = ",".join(["%s"] * len(part))
            for r in pool.execute_query(
                f"""
                SELECT dingtalk_userid, name, department, job_number
                FROM users
                WHERE dingtalk_userid IN ({placeholders})
                """,
                tuple(part),
            ):
                uk = self._clean_key(r.get("dingtalk_userid"))
                if not uk:
                    continue
                out[uk] = {
                    "name": r.get("name"),
                    "department": r.get("department"),
                    "job_number": r.get("job_number"),
                }
        return out

    # ----------------------------------------------------- GET .../usage/latest
    def _usage_latest(self) -> None:
        pool = self._pool()
        rows = pool.execute_query(
            """
            SELECT MAX(m) AS latest FROM (
                SELECT MAX(LEFT(created_at, 7)) AS m FROM neo_feature_uses
                WHERE user_key IS NOT NULL AND user_key <> ''
                UNION
                SELECT MAX(LEFT(created_at, 7)) AS m FROM neo_point_events
                WHERE user_key IS NOT NULL AND user_key <> ''
            ) t
            """
        )
        latest = rows[0].get("latest") if rows else None
        latest = (str(latest).strip() or None) if latest else None
        employee_count = 0
        if latest:
            cnt_rows = pool.execute_query(
                """
                SELECT COUNT(*) AS c FROM (
                    SELECT user_key FROM neo_feature_uses
                    WHERE LEFT(created_at, 7) = %s AND user_key IS NOT NULL AND user_key <> ''
                    UNION
                    SELECT user_key FROM neo_point_events
                    WHERE LEFT(created_at, 7) = %s AND user_key IS NOT NULL AND user_key <> ''
                ) u
                """,
                (latest, latest),
            )
            employee_count = int(cnt_rows[0].get("c") or 0) if cnt_rows else 0
        generated_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        self.h.send_json_response({
            "ok": True,
            "latestMonth": latest,
            "employeeCount": employee_count,
            "generatedAt": generated_at,
        }, status=200)
