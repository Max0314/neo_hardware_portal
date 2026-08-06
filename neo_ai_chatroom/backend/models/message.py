import json
import os
import time
from datetime import datetime
from typing import List, Dict, Optional
import uuid

from backend.models import db_compat


# MySQL 建表语句。来自原 SQLite DDL，差异说明：
# - TEXT 主键改 VARCHAR（InnoDB 不接受无长度 TEXT 主键）；值均为 UUID/短标识
# - 正文类字段用 MEDIUMTEXT；image_data 存 base64 图片，用 LONGTEXT
# - SQLite 的 CREATE INDEX IF NOT EXISTS 在 MySQL 不存在，索引改为建表内联
# - 原 DDL 声明的外键在 SQLite 下从未生效（aiosqlite 默认不开 PRAGMA
#   foreign_keys），代码一直靠手工清理维持一致性；为保持行为不变，这里不建外键
# - system_config 更名 neo_system_config：htmlsystm 在同一库中已有同名不同构的表
_MYSQL_DDL = [
    """
    CREATE TABLE IF NOT EXISTS messages (
        id VARCHAR(64) PRIMARY KEY,
        conversation_id VARCHAR(64) NOT NULL,
        role VARCHAR(32) NOT NULL,
        content MEDIUMTEXT NOT NULL,
        ai_model VARCHAR(128),
        status VARCHAR(32),
        parent_message_id VARCHAR(64),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_visible_in_group TINYINT DEFAULT 1,
        KEY idx_messages_conv (conversation_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id VARCHAR(64) PRIMARY KEY,
        title VARCHAR(512),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS custom_ai_roles (
        id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        avatar MEDIUMTEXT NOT NULL,
        base_ai VARCHAR(128) NOT NULL,
        role_prompt MEDIUMTEXT NOT NULL,
        description MEDIUMTEXT,
        enabled TINYINT DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS custom_ai_role_config (
        role_id VARCHAR(64) PRIMARY KEY,
        config_json MEDIUMTEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_recycle_bin (
        id VARCHAR(64) PRIMARY KEY,
        original_role_id VARCHAR(64) NOT NULL,
        original_role_name VARCHAR(255) NOT NULL,
        knowledge_type VARCHAR(64) NOT NULL,
        knowledge_path VARCHAR(1024) NOT NULL,
        deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        restored_to_role_id VARCHAR(64),
        restored_at TIMESTAMP NULL DEFAULT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS role_knowledge_associations (
        id VARCHAR(64) PRIMARY KEY,
        role_id VARCHAR(64) NOT NULL,
        knowledge_id VARCHAR(64) NOT NULL,
        associated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_role_knowledge (role_id, knowledge_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_config (
        id VARCHAR(64) PRIMARY KEY,
        admin_name VARCHAR(255) NOT NULL DEFAULT '巴巴塔',
        enabled TINYINT DEFAULT 1,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_provider_secrets (
        provider_id VARCHAR(128) PRIMARY KEY,
        ciphertext MEDIUMTEXT NOT NULL,
        hint VARCHAR(255) NOT NULL DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS schematic_review_prompt_history (
        id VARCHAR(64) PRIMARY KEY,
        content MEDIUMTEXT NOT NULL,
        note VARCHAR(1024) NOT NULL DEFAULT '',
        created_by VARCHAR(255) NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_current TINYINT NOT NULL DEFAULT 0,
        KEY idx_schematic_prompt_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS neo_system_config (
        config_key VARCHAR(255) PRIMARY KEY,
        config_value MEDIUMTEXT NOT NULL,
        updated_by VARCHAR(255) NOT NULL DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS schematic_review_history (
        id VARCHAR(64) PRIMARY KEY,
        user_key VARCHAR(255) NOT NULL,
        title VARCHAR(512) NOT NULL DEFAULT '',
        netlist_result_id VARCHAR(64),
        summary_pass INT NOT NULL DEFAULT 0,
        summary_warning INT NOT NULL DEFAULT 0,
        summary_info INT NOT NULL DEFAULT 0,
        payload_json MEDIUMTEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        KEY idx_schematic_review_history_user (user_key, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_base (
        id VARCHAR(64) PRIMARY KEY,
        role_id VARCHAR(64) NOT NULL,
        keywords MEDIUMTEXT NOT NULL,
        answer MEDIUMTEXT NOT NULL,
        image_data LONGTEXT,
        image_path VARCHAR(1024),
        image_type VARCHAR(64),
        metadata MEDIUMTEXT,
        event_config MEDIUMTEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        KEY idx_knowledge_role_id (role_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]


class MessageStore:
    def __init__(self, db_path: str = "chatroom.db"):
        # db_path 仅作迁移期定位旧 SQLite 文件用；运行时读写全部走 MySQL
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库（同步，应用启动时执行）。

        数据库在本 Compose 栈之外，容器启动时它可能尚未就绪；失败重试最多 60 秒，
        超时抛错交给 Docker 重启策略，避免应用带着缺表状态运行。
        """
        deadline = time.monotonic() + 60.0
        delay = 1.0
        while True:
            try:
                conn = db_compat.connect_sync()
                break
            except Exception as e:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"MySQL 在 60 秒内不可达，MessageStore 放弃启动: {e}")
                print(f"[MessageStore] 等待 MySQL 可用…（{e}）")
                time.sleep(delay)
                delay = min(delay * 2, 8.0)

        try:
            for ddl in _MYSQL_DDL:
                conn.execute(ddl)
            conn.execute("""
                INSERT IGNORE INTO admin_config (id, admin_name, enabled)
                VALUES ('default', '巴巴塔', 1)
            """)
            conn.commit()
        finally:
            conn.close()
    
    async def create_or_update_conversation(self, conversation_id: str, title: Optional[str] = None):
        """创建或更新对话记录"""
        async with db_compat.connect() as db:
            # 检查对话是否存在
            cursor = await db.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,))
            exists = await cursor.fetchone()
            
            if exists:
                # 更新对话的更新时间
                await db.execute("""
                    UPDATE conversations 
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (conversation_id,))
            else:
                # 创建新对话
                await db.execute("""
                    INSERT INTO conversations (id, title, created_at, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (conversation_id, title))
            await db.commit()
    
    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        ai_model: Optional[str] = None
    ) -> str:
        """保存消息"""
        # 确保对话记录存在
        await self.create_or_update_conversation(conversation_id)
        
        message_id = str(uuid.uuid4())
        
        async with db_compat.connect() as db:
            await db.execute("""
                INSERT INTO messages (id, conversation_id, role, content, ai_model, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (message_id, conversation_id, role, content, ai_model, "completed"))
            await db.commit()
        
        return message_id
    
    async def create_ai_message_record(
        self,
        conversation_id: str,
        ai_model: str,
        status: str,
        parent_message_id: str
    ) -> str:
        """创建AI消息记录"""
        message_id = str(uuid.uuid4())
        
        async with db_compat.connect() as db:
            await db.execute("""
                INSERT INTO messages (id, conversation_id, role, content, ai_model, status, parent_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (message_id, conversation_id, "assistant", "", ai_model, status, parent_message_id))
            await db.commit()
        
        return message_id
    
    async def update_ai_message(
        self,
        message_id: str,
        content: str,
        status: str
    ):
        """更新AI消息"""
        async with db_compat.connect() as db:
            await db.execute("""
                UPDATE messages
                SET content = ?, status = ?
                WHERE id = ?
            """, (content, status, message_id))
            await db.commit()
    
    async def get_conversations(self) -> List[Dict]:
        """获取所有对话列表（带消息数量）"""
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute("""
                SELECT 
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                GROUP BY c.id
                ORDER BY c.updated_at DESC
            """)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_group_conversation_messages(self, conversation_id: str) -> List[Dict]:
        """获取群聊消息（按时间顺序）"""
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute("""
                SELECT *
                FROM messages
                WHERE conversation_id = ?
                  AND (role = 'user' OR is_visible_in_group = 1)
                ORDER BY created_at ASC
            """, (conversation_id,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_ai_conversation_history(
        self,
        conversation_id: str,
        ai_model: str,
        limit: int = 20
    ) -> List[Dict]:
        """获取特定AI的对话历史（用于上下文）
        
        返回格式：[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            # 获取用户消息和该AI的回复，按时间顺序排列
            cursor = await db.execute("""
                SELECT 
                    role,
                    content,
                    ai_model,
                    created_at
                FROM messages
                WHERE conversation_id = ?
                  AND (
                    role = 'user' 
                    OR (role = 'assistant' AND ai_model = ? AND status = 'completed')
                  )
                ORDER BY created_at ASC
                LIMIT ?
            """, (conversation_id, ai_model, limit))
            rows = await cursor.fetchall()
            
            # 转换为标准格式
            history = []
            for row in rows:
                history.append({
                    "role": row["role"],
                    "content": row["content"]
                })
            
            return history
    
    async def save_custom_ai_role(
        self,
        role_id: str,
        name: str,
        avatar: str,
        base_ai: str,
        role_prompt: str,
        description: str = "",
        role_config: Optional[Dict] = None
    ):
        """保存自定义AI角色"""
        import json
        async with db_compat.connect() as db:
            # REPLACE INTO 与 SQLite 的 INSERT OR REPLACE 语义一致（删除旧行重插，
            # created_at 重置为当前时间）；两表均无外键，不会引发级联删除
            await db.execute("""
                REPLACE INTO custom_ai_roles
                (id, name, avatar, base_ai, role_prompt, description, enabled)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (role_id, name, avatar, base_ai, role_prompt, description))

            # 保存详细配置（如果有）
            if role_config:
                config_json = json.dumps(role_config, ensure_ascii=False)
                await db.execute("""
                    REPLACE INTO custom_ai_role_config
                    (role_id, config_json)
                    VALUES (?, ?)
                """, (role_id, config_json))
            
            await db.commit()
    
    async def get_custom_ai_roles(self) -> List[Dict]:
        """获取所有自定义AI角色（包括详细配置）"""
        import json
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute("""
                SELECT r.*, c.config_json
                FROM custom_ai_roles r
                LEFT JOIN custom_ai_role_config c ON r.id = c.role_id
                WHERE r.enabled = 1
                ORDER BY r.created_at DESC
            """)
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                role_dict = dict(row)
                # 解析配置JSON
                if role_dict.get('config_json'):
                    try:
                        role_dict['role_config'] = json.loads(role_dict['config_json'])
                    except:
                        role_dict['role_config'] = None
                else:
                    role_dict['role_config'] = None
                # 移除config_json字段
                role_dict.pop('config_json', None)
                result.append(role_dict)
            return result
    
    async def delete_custom_ai_role(self, role_id: str):
        """删除自定义AI角色"""
        async with db_compat.connect() as db:
            await db.execute("""
                UPDATE custom_ai_roles SET enabled = 0 WHERE id = ?
            """, (role_id,))
            await db.commit()
    
    async def add_to_recycle_bin(
        self,
        knowledge_id: str,
        original_role_id: str,
        original_role_name: str,
        knowledge_type: str,
        knowledge_path: str
    ):
        """将知识库添加到回收站"""
        async with db_compat.connect() as db:
            await db.execute("""
                INSERT INTO knowledge_recycle_bin 
                (id, original_role_id, original_role_name, knowledge_type, knowledge_path)
                VALUES (?, ?, ?, ?, ?)
            """, (knowledge_id, original_role_id, original_role_name, knowledge_type, knowledge_path))
            await db.commit()
    
    async def get_recycle_bin_items(self) -> List[Dict]:
        """获取回收站中的所有项目"""
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute("""
                SELECT * FROM knowledge_recycle_bin
                WHERE restored_to_role_id IS NULL
                ORDER BY deleted_at DESC
            """)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def restore_knowledge_from_recycle_bin(self, knowledge_id: str, target_role_id: str):
        """从回收站恢复知识库到指定角色"""
        async with db_compat.connect() as db:
            await db.execute("""
                UPDATE knowledge_recycle_bin
                SET restored_to_role_id = ?, restored_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (target_role_id, knowledge_id))
            await db.commit()
    
    async def permanently_delete_from_recycle_bin(self, knowledge_id: str) -> str:
        """从回收站永久删除知识库，返回知识库路径"""
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute("""
                SELECT knowledge_path FROM knowledge_recycle_bin WHERE id = ?
            """, (knowledge_id,))
            row = await cursor.fetchone()
            knowledge_path = row["knowledge_path"] if row else None
            
            await db.execute("""
                DELETE FROM knowledge_recycle_bin WHERE id = ?
            """, (knowledge_id,))
            await db.commit()
            return knowledge_path
    
    async def associate_knowledge_to_role(self, role_id: str, knowledge_id: str):
        """关联知识库到角色"""
        import uuid
        association_id = str(uuid.uuid4())
        async with db_compat.connect() as db:
            # 幂等依据 uq_role_knowledge (role_id, knowledge_id) 唯一键；
            # SQLite 时代主键是随机 id，OR IGNORE 实际从未去重，这里一并修正
            await db.execute("""
                INSERT IGNORE INTO role_knowledge_associations
                (id, role_id, knowledge_id)
                VALUES (?, ?, ?)
            """, (association_id, role_id, knowledge_id))
            await db.commit()
    
    async def get_role_knowledge_associations(self, role_id: str) -> List[Dict]:
        """获取角色关联的所有知识库"""
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute("""
                SELECT k.* FROM knowledge_recycle_bin k
                INNER JOIN role_knowledge_associations r ON k.id = r.knowledge_id
                WHERE r.role_id = ?
            """, (role_id,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def remove_knowledge_association(self, role_id: str, knowledge_id: str):
        """移除角色与知识库的关联"""
        async with db_compat.connect() as db:
            await db.execute("""
                DELETE FROM role_knowledge_associations
                WHERE role_id = ? AND knowledge_id = ?
            """, (role_id, knowledge_id))
            await db.commit()
    
    async def get_admin_config(self) -> Dict:
        """获取管理员配置"""
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute("""
                SELECT * FROM admin_config WHERE id = 'default'
            """)
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return {"id": "default", "admin_name": "巴巴塔", "enabled": 1}
    
    async def update_admin_config(self, admin_name: str = None, enabled: bool = None):
        """更新管理员配置"""
        async with db_compat.connect() as db:
            if admin_name is not None:
                await db.execute("""
                    UPDATE admin_config 
                    SET admin_name = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 'default'
                """, (admin_name,))
            if enabled is not None:
                await db.execute("""
                    UPDATE admin_config 
                    SET enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 'default'
                """, (1 if enabled else 0,))
            await db.commit()

    async def get_ai_secret(self, provider_id: str):
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute(
                "SELECT provider_id, ciphertext, hint, updated_at FROM ai_provider_secrets WHERE provider_id = ?",
                (provider_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def upsert_ai_secret(self, provider_id: str, ciphertext: str, hint: str):
        async with db_compat.connect() as db:
            await db.execute(
                """
                INSERT INTO ai_provider_secrets (provider_id, ciphertext, hint, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    ciphertext = VALUES(ciphertext),
                    hint = VALUES(hint),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (provider_id, ciphertext, hint),
            )
            await db.commit()

    async def delete_ai_secret(self, provider_id: str):
        async with db_compat.connect() as db:
            await db.execute(
                "DELETE FROM ai_provider_secrets WHERE provider_id = ?",
                (provider_id,),
            )
            await db.commit()

    async def get_current_schematic_review_prompt(self) -> Optional[Dict]:
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute(
                """
                SELECT id, content, note, created_by, created_at
                FROM schematic_review_prompt_history
                WHERE is_current = 1
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_schematic_review_prompt_history(self, limit: int = 50) -> List[Dict]:
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute(
                """
                SELECT id, content, note, created_by, created_at, is_current
                FROM schematic_review_prompt_history
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def save_schematic_review_prompt(
        self, content: str, created_by: str = "", note: str = ""
    ) -> Dict:
        prompt = (content or "").strip()
        if not prompt:
            raise ValueError("提示词不能为空")
        row_id = str(uuid.uuid4())
        async with db_compat.connect() as db:
            await db.execute(
                "UPDATE schematic_review_prompt_history SET is_current = 0 WHERE is_current = 1"
            )
            await db.execute(
                """
                INSERT INTO schematic_review_prompt_history
                (id, content, note, created_by, created_at, is_current)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 1)
                """,
                (row_id, prompt, (note or "").strip(), (created_by or "").strip()),
            )
            await db.commit()
        return {
            "id": row_id,
            "content": prompt,
            "note": (note or "").strip(),
            "created_by": (created_by or "").strip(),
            "is_current": 1,
        }

    async def restore_schematic_review_prompt(self, history_id: str, restored_by: str = "") -> Dict:
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute(
                "SELECT id, content FROM schematic_review_prompt_history WHERE id = ?",
                (history_id,),
            )
            row = await cursor.fetchone()
            if not row:
                raise ValueError("历史版本不存在")
            content = row["content"]
        note = f"从历史版本 {history_id[:8]}… 恢复"
        return await self.save_schematic_review_prompt(
            content, created_by=restored_by, note=note
        )

    async def get_system_config(self, config_key: str) -> Optional[str]:
        async with db_compat.connect() as db:
            cursor = await db.execute(
                "SELECT config_value FROM neo_system_config WHERE config_key = ?",
                (config_key,),
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_system_config(
        self, config_key: str, config_value: str, updated_by: str = ""
    ) -> None:
        key = (config_key or "").strip()
        val = (config_value or "").strip()
        if not key:
            raise ValueError("config_key 不能为空")
        async with db_compat.connect() as db:
            await db.execute(
                """
                INSERT INTO neo_system_config (config_key, config_value, updated_by, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    config_value = VALUES(config_value),
                    updated_by = VALUES(updated_by),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, val, (updated_by or "").strip()),
            )
            await db.commit()

    async def save_schematic_review_history(
        self,
        user_key: str,
        title: str,
        netlist_result_id: Optional[str],
        summary_pass: int,
        summary_warning: int,
        summary_info: int,
        payload: Dict,
    ) -> Dict:
        uk = (user_key or "").strip()
        if not uk:
            raise ValueError("user_key 不能为空")
        row_id = str(uuid.uuid4())
        payload_json = json.dumps(payload, ensure_ascii=False)
        async with db_compat.connect() as db:
            await db.execute(
                """
                INSERT INTO schematic_review_history
                (id, user_key, title, netlist_result_id, summary_pass, summary_warning, summary_info, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    row_id,
                    uk,
                    (title or "原理图审核").strip() or "原理图审核",
                    netlist_result_id,
                    int(summary_pass),
                    int(summary_warning),
                    int(summary_info),
                    payload_json,
                ),
            )
            await db.commit()
        return {
            "id": row_id,
            "user_key": uk,
            "title": (title or "原理图审核").strip() or "原理图审核",
            "netlist_result_id": netlist_result_id,
            "summary_pass": int(summary_pass),
            "summary_warning": int(summary_warning),
            "summary_info": int(summary_info),
            "created_at": datetime.now().isoformat(),
        }

    async def list_schematic_review_history(
        self, user_key: str, limit: int = 50
    ) -> List[Dict]:
        uk = (user_key or "").strip()
        if not uk:
            return []
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute(
                """
                SELECT id, user_key, title, netlist_result_id,
                       summary_pass, summary_warning, summary_info, created_at
                FROM schematic_review_history
                WHERE user_key = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (uk, max(1, min(limit, 200))),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_schematic_review_history(
        self, history_id: str, user_key: str
    ) -> Optional[Dict]:
        uk = (user_key or "").strip()
        async with db_compat.connect() as db:
            db.row_factory = db_compat.Row
            cursor = await db.execute(
                """
                SELECT id, user_key, title, netlist_result_id,
                       summary_pass, summary_warning, summary_info, payload_json, created_at
                FROM schematic_review_history
                WHERE id = ? AND user_key = ?
                """,
                (history_id, uk),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["payload"] = json.loads(data.pop("payload_json") or "{}")
            except json.JSONDecodeError:
                data["payload"] = {}
            return data

