#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清空 MySQL 用户相关数据，仅保留超级管理员 zzw，便于重新手动钉钉同步。

不删除：公告栏、物料库、system_config、zzw 账号本身。
删除：其他 users、sessions、待办、NEO 积分/看板、登录封禁记录等。
"""
from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db_adapter import get_connection_pool
from server.security import SUPER_ADMIN_USERNAME


def _table_exists(cursor, name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1",
        (name,),
    )
    return cursor.fetchone() is not None


def _count(cursor, sql: str, params=()) -> int:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    if not row:
        return 0
    if isinstance(row, dict):
        return int(next(iter(row.values())))
    return int(row[0])


def _truncate_or_delete(cursor, table: str) -> int:
    if not _table_exists(cursor, table):
        return 0
    before = _count(cursor, f"SELECT COUNT(*) FROM `{table}`")
    try:
        cursor.execute(f"TRUNCATE TABLE `{table}`")
    except Exception:
        cursor.execute(f"DELETE FROM `{table}`")
    return before


def reset_users_keep_admin(*, admin_username: str, dry_run: bool = False) -> dict:
    admin_username = (admin_username or SUPER_ADMIN_USERNAME or "zzw").strip()
    pool = get_connection_pool()
    stats = {}

    with pool.get_cursor() as cursor:
        if not _table_exists(cursor, "users"):
            raise RuntimeError("users 表不存在，请先初始化 MySQL 模式")

        cursor.execute(
            "SELECT id, username, status FROM users WHERE username = %s LIMIT 1",
            (admin_username,),
        )
        admin_row = cursor.fetchone()
        if not admin_row:
            raise RuntimeError(
                f"未找到管理员 {admin_username!r}，请先创建或执行 --reset 设置密码后再清空用户"
            )
        if isinstance(admin_row, dict):
            admin_id = int(admin_row["id"])
        else:
            admin_id = int(admin_row[0])

        stats["admin_id"] = admin_id
        stats["users_before"] = _count(cursor, "SELECT COUNT(*) FROM users")
        stats["users_to_delete"] = _count(
            cursor, "SELECT COUNT(*) FROM users WHERE id != %s", (admin_id,)
        )

        if dry_run:
            stats["dry_run"] = True
            return stats

        # 1) 会话（避免外键/登录残留）
        if _table_exists(cursor, "sessions"):
            stats["sessions_removed"] = _truncate_or_delete(cursor, "sessions")

        # 2) 登录封禁
        for tbl in ("login_attempts", "ip_blacklist"):
            stats[f"{tbl}_removed"] = _truncate_or_delete(cursor, tbl)

        # 3) NEO 积分/看板（MySQL）
        for tbl in (
            "neo_point_events",
            "neo_user_point_balances",
            "neo_feature_uses",
            "neo_bom_info_snapshots",
        ):
            stats[f"{tbl}_removed"] = _truncate_or_delete(cursor, tbl)

        # 4) 用户相关待办
        stats["todos_removed"] = _truncate_or_delete(cursor, "todos")

        # 5) 审计（可选保留物料审计，这里清空与用户登录/操作相关的表）
        for tbl in ("audit_logs", "material_db_audit"):
            stats[f"{tbl}_removed"] = _truncate_or_delete(cursor, tbl)

        # 6) 删除除 zzw 外所有用户
        cursor.execute("DELETE FROM users WHERE id != %s", (admin_id,))
        stats["users_deleted"] = cursor.rowcount

        # 7) 规范化 zzw：确保 active + 超级管理员角色
        cursor.execute(
            """
            UPDATE users SET
                status = 'active',
                roles = 'admin,management,super_admin',
                dingtalk_data = NULL,
                dingtalk_userid = NULL,
                dingtalk_unionid = NULL,
                job_number = NULL,
                user_source = 'local',
                updated_time = NOW()
            WHERE id = %s
            """,
            (admin_id,),
        )

        stats["users_after"] = _count(cursor, "SELECT COUNT(*) FROM users")

    return stats


def main():
    parser = argparse.ArgumentParser(description="清空用户数据，仅保留 zzw")
    parser.add_argument("--admin", default=SUPER_ADMIN_USERNAME, help="保留的管理员用户名")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不执行删除")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认执行（危险：删除除管理员外全部用户）",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.confirm:
        print("❌ 必须加 --confirm 才会执行删除；可先 --dry-run 查看影响范围")
        sys.exit(1)

    print("=" * 72)
    print("MySQL 用户数据重置（仅保留管理员）")
    print("=" * 72)
    print(f"保留账号: {args.admin!r}")
    print(f"模式: {'dry-run' if args.dry_run else 'EXECUTE'}")
    print("=" * 72)

    try:
        stats = reset_users_keep_admin(
            admin_username=args.admin,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"❌ 失败: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")

    if args.dry_run:
        print("\n以上为预览。确认后执行:")
        print(f"  python scripts/reset_users_keep_admin.py --admin {args.admin} --confirm")
    else:
        print("\n✅ 完成。建议:")
        print("  docker exec stack-htmlsystm python scripts/view_and_reset_admin_password.py --clear-blocks")
        print("  docker compose restart htmlsystm backend")
        print("  然后在管理界面手动触发钉钉用户同步")
    print("=" * 72)


if __name__ == "__main__":
    main()
