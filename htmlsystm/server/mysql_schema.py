#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL数据库模式定义
将SQLite表结构转换为MySQL语法
"""
import os
import json
from typing import Optional

try:
    from server.config import DEPARTMENT_OPTIONS, JOB_POSITION_OPTIONS
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DEPARTMENT_OPTIONS = {
        'hardware_rd': '硬件研发部',
        'purchase': '采购',
        'cost': '成本',
        'management': '管理组'
    }
    JOB_POSITION_OPTIONS = {
        'management': '管理组',
        'circuit': '电路设计组',
        'structure': '结构设计组',
        'packaging': '包装设计组',
        'testing': '测试组'
    }

# 数据库版本
DB_VERSION = 6  # v6: auth_session_index + users.session_rev


def create_users_table(cursor):
    """创建用户表（MySQL语法）"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            department VARCHAR(255) NOT NULL,
            job_position VARCHAR(255),
            roles TEXT,
            library_roles TEXT,
            status VARCHAR(50) DEFAULT 'active',
            created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            last_login_time TIMESTAMP NULL,
            dingtalk_userid VARCHAR(64) NULL COMMENT '钉钉 userid',
            dingtalk_unionid VARCHAR(128) NULL COMMENT '钉钉 unionid',
            job_number VARCHAR(64) NULL COMMENT '工号',
            user_source VARCHAR(32) DEFAULT 'local' COMMENT 'local|dingtalk',
            dingtalk_data JSON NULL COMMENT '钉钉扩展字段 JSON',
            INDEX idx_username (username),
            INDEX idx_status (status),
            INDEX idx_department (department),
            INDEX idx_dingtalk_userid (dingtalk_userid),
            CHECK (status IN ('active', 'disabled', 'pending', 'rejected', 'inactive'))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table, column),
    )
    return cursor.fetchone() is not None


def migrate_users_table(cursor):
    """升级 users 表：钉钉字段与索引（幂等，Docker 启动时自动执行）。"""
    alters = [
        ("dingtalk_data", "JSON NULL COMMENT '钉钉扩展字段 JSON'"),
        ("dingtalk_userid", "VARCHAR(64) NULL COMMENT '钉钉 userid'"),
        ("dingtalk_unionid", "VARCHAR(128) NULL COMMENT '钉钉 unionid'"),
        ("job_number", "VARCHAR(64) NULL COMMENT '工号'"),
        ("user_source", "VARCHAR(32) DEFAULT 'local' COMMENT 'local|dingtalk'"),
    ]
    for col, definition in alters:
        if not _column_exists(cursor, "users", col):
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")

    if not _column_exists(cursor, "users", "dingtalk_userid"):
        return

    try:
        cursor.execute(
            "SELECT COUNT(*) AS c FROM INFORMATION_SCHEMA.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' "
            "AND INDEX_NAME = 'idx_dingtalk_userid'"
        )
        row = cursor.fetchone()
        has_idx = (row.get("c", 0) if isinstance(row, dict) else row[0]) > 0
        if not has_idx:
            cursor.execute("CREATE INDEX idx_dingtalk_userid ON users (dingtalk_userid)")
    except Exception:
        pass

    # 从 dingtalk_data JSON 回填独立列（历史数据）
    if _column_exists(cursor, "users", "dingtalk_data"):
        cursor.execute(
            """
            UPDATE users
            SET dingtalk_userid = JSON_UNQUOTE(JSON_EXTRACT(dingtalk_data, '$.userid')),
                dingtalk_unionid = COALESCE(
                    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(dingtalk_data, '$.unionid')), ''),
                    dingtalk_unionid
                ),
                job_number = COALESCE(
                    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(dingtalk_data, '$.job_number')), ''),
                    job_number
                ),
                user_source = 'dingtalk'
            WHERE dingtalk_data IS NOT NULL
              AND JSON_EXTRACT(dingtalk_data, '$.userid') IS NOT NULL
              AND (dingtalk_userid IS NULL OR dingtalk_userid = '')
            """
        )


def create_sessions_table(cursor):
    """创建会话表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id VARCHAR(255) PRIMARY KEY,
            user_id INT NOT NULL,
            user_data TEXT NOT NULL,
            created_at DOUBLE NOT NULL,
            expires_at DOUBLE NOT NULL,
            last_access DOUBLE NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            INDEX idx_user_id (user_id),
            INDEX idx_expires_at (expires_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')


def create_material_db_tables(cursor):
    """物料数据库（多库 Excel）与操作审计表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS material_db_libraries (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            prefix VARCHAR(255) DEFAULT '',
            password_hash VARCHAR(255) NOT NULL,
            current_table_json LONGTEXT,
            history_tables_json LONGTEXT,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            INDEX idx_material_db_name (name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS material_db_audit (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
            user_display VARCHAR(255) NOT NULL DEFAULT '',
            action VARCHAR(64) NOT NULL,
            library_id VARCHAR(36) NULL,
            library_name VARCHAR(255) NULL,
            detail TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_mdb_audit_lib (library_id),
            INDEX idx_mdb_audit_time (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')


def create_audit_log_table(cursor):
    """创建审计日志表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            action VARCHAR(255) NOT NULL,
            resource_type VARCHAR(255),
            resource_id VARCHAR(255),
            details TEXT,
            ip_address VARCHAR(255),
            user_agent TEXT,
            created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            INDEX idx_user_id (user_id),
            INDEX idx_action (action),
            INDEX idx_created_time (created_time)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')


def create_primary_boards_table(cursor):
    """创建一级公告栏表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS primary_boards (
            id INT AUTO_INCREMENT PRIMARY KEY,
            board_id VARCHAR(255) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            display_order INT DEFAULT 0,
            created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_board_id (board_id),
            INDEX idx_display_order (display_order)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')


def create_sub_boards_table(cursor):
    """创建二级公告栏表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sub_boards (
            id INT AUTO_INCREMENT PRIMARY KEY,
            parent_board_id VARCHAR(255) NOT NULL,
            sub_board_id VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            display_order INT DEFAULT 0,
            created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY unique_parent_sub (parent_board_id, sub_board_id),
            FOREIGN KEY (parent_board_id) REFERENCES primary_boards(board_id) ON DELETE CASCADE,
            INDEX idx_parent_board (parent_board_id),
            INDEX idx_display_order (display_order)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')


def create_todos_table(cursor):
    """创建待办任务表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS todos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            announcement_id VARCHAR(255) NOT NULL,
            title VARCHAR(500) NOT NULL,
            source_id VARCHAR(255),
            userid VARCHAR(255) NOT NULL,
            unionid VARCHAR(255),
            task_id VARCHAR(255),
            username VARCHAR(255),
            name VARCHAR(255),
            status VARCHAR(50) DEFAULT '未完成',
            complete_time TIMESTAMP NULL,
            create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_announcement_id (announcement_id),
            INDEX idx_userid (userid),
            INDEX idx_status (status),
            INDEX idx_announcement_user (announcement_id, userid),
            CHECK (status IN ('未完成', '已完成', 'done', 'pending'))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')


def create_system_config_table(cursor):
    """创建系统配置表"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_config (
            config_key VARCHAR(255) PRIMARY KEY,
            config_value TEXT NOT NULL,
            description TEXT,
            updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')
    
    # 插入数据库版本
    cursor.execute('''
        INSERT INTO system_config (config_key, config_value, description)
        VALUES ('db_version', %s, '数据库版本号')
        ON DUPLICATE KEY UPDATE config_value = %s
    ''', (str(DB_VERSION), str(DB_VERSION)))


def init_default_users(cursor):
    """初始化默认用户（zzw 密码见 admin_credentials.json，由 UserManager 创建时打印）"""
    try:
        from server.user_manager import UserManager
        UserManager()._ensure_super_admin()
        return
    except Exception as exc:
        print(f'init_default_users 委托 UserManager 失败，尝试直接插入: {exc}')

    from server.security import SUPER_ADMIN_USERNAME, PasswordHasher
    from server.admin_credentials import bootstrap_admin_password, print_admin_credentials_banner

    cursor.execute('SELECT id FROM users WHERE username = %s', (SUPER_ADMIN_USERNAME,))
    if cursor.fetchone():
        return

    admin_user, plain_password, is_new = bootstrap_admin_password(create_if_missing=True)
    default_users = [
        {
            'username': admin_user,
            'password': PasswordHasher.hash_password(plain_password),
            'name': '系统最高管理员',
            'department': 'management',
            'job_position': 'management',
            'library_roles': '',
            'status': 'active'
        },
    ]
    if is_new:
        print_admin_credentials_banner(plain_password, username=admin_user)
    
    for user in default_users:
        try:
            cursor.execute('''
                INSERT IGNORE INTO users 
                (username, password, name, department, job_position, library_roles, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (
                user['username'],
                user['password'],
                user['name'],
                user['department'],
                user['job_position'],
                user['library_roles'],
                user['status']
            ))
        except Exception as e:
            print(f"插入用户 {user['username']} 失败: {e}")


def init_default_primary_boards(cursor):
    """初始化默认一级公告栏"""
    try:
        from server.announcement_config import ANNOUNCEMENT_BOARDS
        
        for board_id, board_name in ANNOUNCEMENT_BOARDS.items():
            cursor.execute('''
                INSERT IGNORE INTO primary_boards (board_id, name, description, display_order)
                VALUES (%s, %s, %s, %s)
            ''', (board_id, board_name, f'{board_name}公告栏', 0))
        
        print("默认一级公告栏初始化完成")
    except Exception as e:
        print(f"初始化默认一级公告栏失败: {e}")


def init_default_sub_boards(cursor):
    """初始化默认二级公告栏"""
    try:
        cursor.execute('SELECT board_id, name FROM primary_boards WHERE board_id != "all"')
        primary_boards = cursor.fetchall()
        
        if not primary_boards:
            try:
                from server.announcement_config import ANNOUNCEMENT_BOARDS
            except ImportError:
                ANNOUNCEMENT_BOARDS = {
                    'hardware': '硬件研发部',
                    'circuit': '电路设计组',
                    'structure': '结构组',
                    'packaging': '包装标签组',
                    'testing': '测试组'
                }
            
            for board_id, board_name in ANNOUNCEMENT_BOARDS.items():
                cursor.execute('SELECT id FROM primary_boards WHERE board_id = %s', (board_id,))
                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO primary_boards (board_id, name, description, display_order)
                        VALUES (%s, %s, %s, %s)
                    ''', (board_id, board_name, f'{board_name}公告栏', 0))
                
                cursor.execute('''
                    INSERT IGNORE INTO sub_boards (parent_board_id, sub_board_id, name, description, display_order)
                    VALUES (%s, 'default', '默认', '显示该公告栏下的所有公告', 0)
                ''', (board_id,))
        else:
            for row in primary_boards:
                board_id = row['board_id']
                board_name = row['name']
                
                cursor.execute('''
                    SELECT id FROM sub_boards 
                    WHERE parent_board_id = %s AND sub_board_id = 'default'
                ''', (board_id,))
                
                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO sub_boards (parent_board_id, sub_board_id, name, description, display_order)
                        VALUES (%s, 'default', '默认', '显示该公告栏下的所有公告', 0)
                    ''', (board_id,))
    except Exception as e:
        print(f"初始化默认二级公告栏失败: {e}")


def create_neo_metrics_tables(cursor):
    """NEO 积分与看板指标（与 dashboard_metrics.db 同构，便于 mysqldump 统一备份）。"""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS neo_point_events (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            event_type VARCHAR(64) NOT NULL,
            user_key VARCHAR(128) NOT NULL,
            points DOUBLE NOT NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_neo_point_events_user (user_key),
            INDEX idx_neo_point_events_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS neo_user_point_balances (
            user_key VARCHAR(128) PRIMARY KEY,
            total_points DOUBLE NOT NULL DEFAULT 0,
            month_points DOUBLE NOT NULL DEFAULT 0,
            month_id VARCHAR(16) NOT NULL DEFAULT '',
            updated_at VARCHAR(32) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS neo_feature_uses (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            feature VARCHAR(128) NOT NULL,
            user_key VARCHAR(128) NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_neo_feature_uses_created (created_at),
            INDEX idx_neo_feature_uses_user (user_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS neo_bom_info_snapshots (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            info_count INT NOT NULL,
            user_key VARCHAR(128) NULL,
            created_at VARCHAR(32) NOT NULL,
            INDEX idx_neo_bom_info_created (created_at),
            INDEX idx_neo_bom_info_user (user_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    ''')


def ensure_incremental_schema(mysql_pool):
    """已有数据库补建后续版本新增的表（CREATE IF NOT EXISTS，不破坏业务数据）。"""
    with mysql_pool.get_cursor() as cursor:
        create_neo_metrics_tables(cursor)
        from server.auth.session_index import ensure_auth_session_table, migrate_users_session_rev

        ensure_auth_session_table(cursor)
        migrate_users_session_rev(cursor)


def initialize_mysql_schema(mysql_pool):
    """
    初始化MySQL数据库模式
    
    Args:
        mysql_pool: MySQL连接池实例
    """
    with mysql_pool.get_cursor() as cursor:
        # 创建表
        create_users_table(cursor)
        migrate_users_table(cursor)
        create_sessions_table(cursor)
        create_audit_log_table(cursor)
        create_material_db_tables(cursor)
        create_todos_table(cursor)
        create_system_config_table(cursor)
        create_primary_boards_table(cursor)
        create_sub_boards_table(cursor)
        create_neo_metrics_tables(cursor)
        from server.auth.session_index import ensure_auth_session_table, migrate_users_session_rev

        ensure_auth_session_table(cursor)
        migrate_users_session_rev(cursor)
        
        # 初始化默认数据
        init_default_users(cursor)
        init_default_primary_boards(cursor)
        init_default_sub_boards(cursor)
        
        print("MySQL数据库模式初始化完成")

