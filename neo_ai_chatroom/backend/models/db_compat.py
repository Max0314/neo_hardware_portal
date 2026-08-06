"""MySQL 访问层，保持 aiosqlite 的调用面。

NEO 后端的三个存储（message / memory / knowledge_base）此前使用 chatroom.db
（SQLite）。平台要求结构化数据统一放共享 MySQL，因此改为 MySQL；为了不重写
三十多个查询方法，本模块按 aiosqlite 的接口习惯提供：

- ``connect()``            异步上下文管理器，``execute()`` 返回可 ``fetchone/fetchall`` 的游标
- ``connect_sync()``       同步版本，供 SimpleKnowledgeBase 等同步代码使用
- ``Row``                  同时支持列名和位置下标访问（对应 sqlite3.Row）
- ``IntegrityError``       唯一键冲突（对应 aiosqlite.IntegrityError）

SQL 语句仍写 ``?`` 占位符，由本层翻译为 pymysql 的 ``%s``；语句中的字面 ``%``
会被转义，避免被驱动误当作格式化符。

沿用 aiosqlite 的"每次操作建一条连接"的用法：调用方本来就是每个方法
``async with connect()``，对内网 MySQL 一次握手约 1-2ms，此应用的量级下无需连接池。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Iterable, Optional, Sequence

import pymysql

# 调用方捕获的异常类型（对应 aiosqlite.IntegrityError）
IntegrityError = pymysql.err.IntegrityError


def _mysql_config() -> dict:
    host = (os.getenv("MYSQL_HOST") or "").strip()
    user = (os.getenv("MYSQL_USER") or "").strip()
    database = (os.getenv("MYSQL_DATABASE") or "").strip()
    if not host or not user or not database:
        raise RuntimeError(
            "MySQL 配置不完整：需要 MYSQL_HOST、MYSQL_USER、MYSQL_DATABASE"
            "（NEO 聊天数据已迁移至共享 MySQL，不再使用 chatroom.db）"
        )
    return {
        "host": host,
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": user,
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": database,
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": 5,
        "read_timeout": 30,
        "write_timeout": 30,
    }


def _translate(sql: str) -> str:
    """把 ``?`` 占位符翻译成 ``%s``，并转义字面 ``%``。

    仓库内这三个存储的语句中，``?`` 只作占位符出现（无字符串字面量包含问号），
    因此直接替换是安全的；字面 ``%``（如 LIKE 模式）需翻倍以免被驱动解析。
    """
    return sql.replace("%", "%%").replace("?", "%s")


class Row:
    """结果行：``row["col"]`` 与 ``row[0]`` 均可用，``dict(row)`` 保序。"""

    __slots__ = ("_names", "_values")

    def __init__(self, names: Sequence[str], values: Sequence[Any]):
        self._names = names
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._names.index(key)]

    def __contains__(self, key) -> bool:
        return key in self._names

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self):
        """dict(row) 依赖 keys() + __getitem__。"""
        return list(self._names)

    def get(self, key, default=None):
        try:
            return self[key]
        except (ValueError, IndexError):
            return default

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"Row({dict(zip(self._names, self._values))!r})"


class _Cursor:
    """execute() 的返回值；行形态由连接上的 row_factory 决定（对齐 aiosqlite）。"""

    def __init__(self, conn: "_SyncConnection", cursor: pymysql.cursors.Cursor):
        self._conn = conn
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    def _wrap(self, row):
        if row is None:
            return None
        if self._conn.row_factory is Row:
            names = [d[0] for d in (self._cursor.description or [])]
            return Row(names, row)
        return row

    def fetchone(self):
        return self._wrap(self._cursor.fetchone())

    def fetchall(self):
        return [self._wrap(r) for r in self._cursor.fetchall()]

    def close(self) -> None:
        self._cursor.close()


class _StatefulCursor:
    """兼容 sqlite3 的 ``cursor = conn.cursor(); cursor.execute(...); cursor.fetchall()`` 写法。"""

    def __init__(self, conn: "_SyncConnection"):
        self._conn = conn
        self._cur: Optional[_Cursor] = None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> "_StatefulCursor":
        self._cur = self._conn.execute(sql, params)
        return self

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount if self._cur else -1

    @property
    def lastrowid(self):
        return self._cur.lastrowid if self._cur else None

    def fetchone(self):
        return self._cur.fetchone() if self._cur else None

    def fetchall(self):
        return self._cur.fetchall() if self._cur else []

    def close(self) -> None:
        if self._cur:
            self._cur.close()


class _SyncConnection:
    """同步连接。cursor 结果默认元组；row_factory=Row 时返回 Row。"""

    def __init__(self):
        self.row_factory: Optional[type] = None
        self._conn = pymysql.connect(**_mysql_config())

    def execute(self, sql: str, params: Iterable[Any] = ()) -> _Cursor:
        cursor = self._conn.cursor()
        cursor.execute(_translate(sql), tuple(params))
        return _Cursor(self, cursor)

    def executemany(self, sql: str, seq_of_params) -> _Cursor:
        cursor = self._conn.cursor()
        cursor.executemany(_translate(sql), [tuple(p) for p in seq_of_params])
        return _Cursor(self, cursor)

    def cursor(self) -> _StatefulCursor:
        return _StatefulCursor(self)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> "_SyncConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self.close()


class _AsyncConnection:
    """异步外观：把同步连接的每个操作丢进线程池，接口对齐 aiosqlite。"""

    def __init__(self):
        self._sync: Optional[_SyncConnection] = None

    # row_factory 透传给底层同步连接
    @property
    def row_factory(self):
        return self._sync.row_factory if self._sync else None

    @row_factory.setter
    def row_factory(self, value):
        if self._sync:
            self._sync.row_factory = value

    async def __aenter__(self) -> "_AsyncConnection":
        self._sync = await asyncio.to_thread(_SyncConnection)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        sync = self._sync
        self._sync = None
        if sync is None:
            return

        def _finish():
            try:
                if exc_type is None:
                    sync.commit()
                else:
                    sync.rollback()
            finally:
                sync.close()

        await asyncio.to_thread(_finish)

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> "_AsyncCursor":
        cursor = await asyncio.to_thread(self._sync.execute, sql, params)
        return _AsyncCursor(cursor)

    async def commit(self) -> None:
        await asyncio.to_thread(self._sync.commit)

    async def rollback(self) -> None:
        await asyncio.to_thread(self._sync.rollback)


class _AsyncCursor:
    def __init__(self, cursor: _Cursor):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    async def fetchone(self):
        return await asyncio.to_thread(self._cursor.fetchone)

    async def fetchall(self):
        return await asyncio.to_thread(self._cursor.fetchall)


def connect(*_args, **_kwargs) -> _AsyncConnection:
    """异步连接。接受并忽略位置参数，以兼容原先的 connect(db_path) 调用。"""
    return _AsyncConnection()


def connect_sync(*_args, **_kwargs) -> _SyncConnection:
    """同步连接，供非 async 代码使用。"""
    return _SyncConnection()
