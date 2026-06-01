"""
VikingDB 向量后端（Phase B，合规与账号就绪后启用）。

环境变量示例（以官方 SDK 为准，可能随版本调整）：
  MEMORY_VECTOR_BACKEND=vikingdb
  VIKINGDB_AK=...
  VIKINGDB_SK=...
  VIKINGDB_HOST=...
  VIKINGDB_REGION=...

当前仓库未强制依赖 vikingdb SDK；未安装或配置不全时 from_env() 返回 None，
create_vector_memory_backend 会回退或打印错误。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from backend.memory.vector_backend import VectorMemoryBackend


class VikingDBMemoryBackend(VectorMemoryBackend):
    """占位：数据面 Upsert/Search 需在合规开通后按官方 SDK 实现。"""

    def __init__(self, message: str = "VikingDB 未配置"):
        self._message = message

    @classmethod
    def from_env(cls) -> Optional["VikingDBMemoryBackend"]:
        """
        未实现真实 VikingDB 连接时一律返回 None，便于 create_vector_memory_backend 回退到 Chroma。
        实现完成后在此实例化并返回真实 Backend。
        """
        ak = os.getenv("VIKINGDB_AK") or os.getenv("VOLC_ACCESSKEY")
        sk = os.getenv("VIKINGDB_SK") or os.getenv("VOLC_SECRETKEY")
        if not ak or not sk:
            print("[memory] VikingDB：未设置 VIKINGDB_AK/SK，跳过")
            return None
        try:
            import vikingdb  # noqa: F401
        except ImportError:
            print("[memory] VikingDB：未安装 vikingdb-python-sdk，跳过")
            return None
        print(
            "[memory] VikingDB：SDK 已安装但数据面未对接，请在 vikingdb_backend.py 实现后返回实例；当前跳过"
        )
        return None

    async def upsert(
        self,
        point_id: str,
        vector: List[float],
        document: str,
        metadata: Dict[str, Any],
    ) -> None:
        raise RuntimeError(
            f"VikingDB 记忆后端尚未完成对接: {self._message}。"
            "请参考火山引擎 VikingDB 文档实现 UpsertData / SearchByVector。"
        )

    async def delete(self, point_id: str) -> None:
        raise RuntimeError("VikingDB delete 未实现")

    async def search(
        self,
        query_vector: List[float],
        where: Optional[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        raise RuntimeError("VikingDB search 未实现")


def migration_note() -> str:
    """供运维脚本或文档引用。"""
    return (
        "从 Chroma/Qdrant 迁移到 VikingDB：导出 memory_items 与向量 id 映射，"
        "批量调用 VikingDB Upsert；切换 MEMORY_VECTOR_BACKEND=vikingdb 并配置 IAM。"
    )
