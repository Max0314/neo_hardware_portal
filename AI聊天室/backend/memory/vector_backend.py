"""可插拔向量后端：Chroma（默认）、Qdrant（可选）、VikingDB（见 vikingdb_backend）。"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class VectorMemoryBackend(ABC):
    """记忆条目向量存储抽象。"""

    @abstractmethod
    async def upsert(
        self,
        point_id: str,
        vector: List[float],
        document: str,
        metadata: Dict[str, Any],
    ) -> None:
        pass

    @abstractmethod
    async def delete(self, point_id: str) -> None:
        pass

    @abstractmethod
    async def search(
        self,
        query_vector: List[float],
        where: Optional[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """
        返回 dict 列表：memory_item_id, document, metadata, distance
        """
        pass


def _chroma_where_from_dict(flat: Dict[str, str]) -> Optional[Dict[str, Any]]:
    if not flat:
        return None
    parts = [{k: {"$eq": v}} for k, v in flat.items()]
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


class ChromaMemoryVectorBackend(VectorMemoryBackend):
    """使用独立 collection，与 conversation_memories 隔离。"""

    COLLECTION = "layered_memory_items"

    def __init__(self, db_path: str = "./chroma_db"):
        import chromadb

        self._client = chromadb.PersistentClient(path=db_path)
        try:
            self._col = self._client.get_collection(self.COLLECTION)
        except Exception:
            self._col = self._client.create_collection(
                name=self.COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )

    async def upsert(
        self,
        point_id: str,
        vector: List[float],
        document: str,
        metadata: Dict[str, Any],
    ) -> None:
        meta = {k: (str(v) if v is not None else "") for k, v in metadata.items()}
        try:
            self._col.delete(ids=[point_id])
        except Exception:
            pass
        self._col.add(
            ids=[point_id],
            embeddings=[vector],
            documents=[document],
            metadatas=[meta],
        )

    async def delete(self, point_id: str) -> None:
        try:
            self._col.delete(ids=[point_id])
        except Exception:
            pass

    async def search(
        self,
        query_vector: List[float],
        where: Optional[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {
            "query_embeddings": [query_vector],
            "n_results": top_k,
        }
        if where:
            kwargs["where"] = where
        results = self._col.query(**kwargs)
        out: List[Dict[str, Any]] = []
        if not results.get("ids") or not results["ids"][0]:
            return out
        for i, pid in enumerate(results["ids"][0]):
            meta = (results.get("metadatas") or [[{}]])[0][i] or {}
            doc = (results.get("documents") or [[""]])[0][i] or ""
            dist = (results.get("distances") or [[1.0]])[0][i]
            out.append(
                {
                    "memory_item_id": pid,
                    "document": doc,
                    "metadata": meta,
                    "distance": dist,
                }
            )
        return out


class QdrantMemoryVectorBackend(VectorMemoryBackend):
    """可选：需安装 qdrant-client，且 Qdrant 服务可访问。"""

    def __init__(self, url: str, collection: str = "layered_memory_items"):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self._collection = collection
        self._client = QdrantClient(url=url)
        if not self._client.collection_exists(collection):
            self._client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
            )

    async def upsert(
        self,
        point_id: str,
        vector: List[float],
        document: str,
        metadata: Dict[str, Any],
    ) -> None:
        from qdrant_client.models import PointStruct

        payload = {**metadata, "document": document}
        self._client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(id=point_id, vector=vector, payload=payload),
            ],
        )

    async def delete(self, point_id: str) -> None:
        from qdrant_client.http import models as qm

        self._client.delete(
            collection_name=self._collection,
            points_selector=qm.PointIdsList(points=[point_id]),
        )

    async def search(
        self,
        query_vector: List[float],
        where: Optional[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        flt = None
        if where:

            def walk(node, must):
                if isinstance(node, dict) and "$and" in node:
                    for sub in node["$and"]:
                        walk(sub, must)
                    return
                if isinstance(node, dict) and len(node) == 1:
                    k, v = next(iter(node.items()))
                    if isinstance(v, dict) and "$eq" in v:
                        must.append(
                            FieldCondition(key=k, match=MatchValue(value=v["$eq"]))
                        )

            must_list = []
            walk(where, must_list)
            if must_list:
                flt = Filter(must=must_list)

        hits = self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=flt,
        )
        out = []
        for h in hits:
            pl = h.payload or {}
            doc = pl.pop("document", "") or ""
            out.append(
                {
                    "memory_item_id": str(h.id),
                    "document": doc,
                    "metadata": pl,
                    "distance": h.score if hasattr(h, "score") else 0,
                }
            )
        return out


def create_vector_memory_backend() -> Optional[VectorMemoryBackend]:
    kind = (os.getenv("MEMORY_VECTOR_BACKEND") or "chroma").strip().lower()
    if kind in ("none", "off", "disabled", ""):
        return None
    if kind == "vikingdb":
        try:
            from backend.memory.vikingdb_backend import VikingDBMemoryBackend

            vb = VikingDBMemoryBackend.from_env()
            if vb is not None:
                return vb
            print("[memory] VikingDB 未就绪，回退 Chroma")
        except Exception as e:
            print(f"[memory] VikingDB 后端不可用: {e}")
    if kind == "qdrant":
        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        try:
            return QdrantMemoryVectorBackend(url=url)
        except Exception as e:
            print(f"[memory] Qdrant 后端初始化失败: {e}")
            return None
    # chroma
    try:
        path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
        return ChromaMemoryVectorBackend(db_path=path)
    except Exception as e:
        print(f"[memory] Chroma 记忆向量后端初始化失败: {e}")
        return None
