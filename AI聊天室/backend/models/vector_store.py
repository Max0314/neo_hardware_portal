import chromadb
from chromadb.config import Settings
import os
from typing import List, Dict, Optional
import uuid
from datetime import datetime


class VectorStore:
    """基于ChromaDB的向量存储系统"""
    
    def __init__(self, db_path: str = "./chroma_db"):
        # 初始化ChromaDB客户端（使用本地持久化存储）
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = None
        self._init_collection()
    
    def _init_collection(self):
        """初始化集合"""
        try:
            # 尝试获取现有集合
            self.collection = self.client.get_collection("conversation_memories")
        except:
            # 如果不存在，创建新集合
            self.collection = self.client.create_collection(
                name="conversation_memories",
                metadata={"hnsw:space": "cosine"}  # 使用余弦相似度
            )
    
    async def add_message(
        self,
        conversation_id: str,
        message_id: str,
        role: str,
        content: str,
        ai_model: Optional[str] = None,
        embedding: Optional[List[float]] = None
    ):
        """添加消息到向量数据库"""
        if not embedding:
            # 如果没有提供嵌入向量，需要先生成
            embedding = await self._generate_embedding(content)
        
        # 构建文档ID
        doc_id = f"{conversation_id}_{message_id}"
        
        # 构建元数据
        metadata = {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "role": role,
            "ai_model": ai_model or "",
            "content": content,  # 保存原始内容
            "timestamp": datetime.now().isoformat()
        }
        
        # 添加到集合
        self.collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[content],  # 文档内容
            metadatas=[metadata]
        )
    
    async def search_relevant_messages(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        ai_model: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict]:
        """搜索相关的对话历史"""
        # 生成查询向量
        query_embedding = await self._generate_embedding(query)
        
        # 构建查询条件（ChromaDB的where格式）
        where = None
        if conversation_id and ai_model:
            # 多个条件需要使用$and
            where = {
                "$and": [
                    {"conversation_id": {"$eq": conversation_id}},
                    {"ai_model": {"$eq": ai_model}}
                ]
            }
        elif conversation_id:
            where = {"conversation_id": {"$eq": conversation_id}}
        elif ai_model:
            where = {"ai_model": {"$eq": ai_model}}
        
        # 执行向量搜索
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where
        )
        
        # 格式化结果
        relevant_messages = []
        if results['ids'] and len(results['ids'][0]) > 0:
            for i in range(len(results['ids'][0])):
                metadata = results['metadatas'][0][i]
                relevant_messages.append({
                    "role": metadata.get("role"),
                    "content": metadata.get("content"),
                    "ai_model": metadata.get("ai_model"),
                    "message_id": metadata.get("message_id"),
                    "conversation_id": metadata.get("conversation_id"),
                    "similarity": 1 - results['distances'][0][i] if results.get('distances') else 0
                })
        
        return relevant_messages
    
    async def _generate_embedding(self, text: str) -> List[float]:
        """生成文本的嵌入向量"""
        # 优先使用OpenAI（DeepSeek不支持embedding API，不尝试）
        openai_key = os.getenv("OPENAI_API_KEY")
        
        # 尝试使用OpenAI
        if openai_key:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=openai_key)
                response = await client.embeddings.create(
                    model="text-embedding-3-small",
                    input=text
                )
                return response.data[0].embedding
            except Exception as e:
                # 只在第一次失败时打印警告
                if not hasattr(self, '_embedding_warning_printed'):
                    print(f"OpenAI嵌入向量生成失败: {e}，将使用简单哈希作为备选")
                    self._embedding_warning_printed = True
        
        # 如果OpenAI不可用，使用简单的文本哈希作为备选
        # 注意：简单哈希的语义搜索效果较差，但可以工作
        import hashlib
        hash_obj = hashlib.sha256(text.encode())
        hash_bytes = hash_obj.digest()
        # 将哈希转换为1536维向量（简单方法：重复哈希值）
        embedding = []
        for i in range(1536):
            embedding.append((hash_bytes[i % len(hash_bytes)] / 255.0) * 2 - 1)
        return embedding
    
    async def delete_conversation(self, conversation_id: str):
        """删除某个对话的所有向量记录"""
        try:
            # ChromaDB不支持直接按metadata删除，需要查询后删除
            results = self.collection.get(
                where={"conversation_id": conversation_id}
            )
            if results['ids']:
                self.collection.delete(ids=results['ids'])
        except Exception as e:
            print(f"删除对话向量记录失败: {e}")
    
    async def get_conversation_summary(self, conversation_id: str) -> Optional[str]:
        """获取对话摘要（可选功能）"""
        # 获取对话中的所有消息
        results = self.collection.get(
            where={"conversation_id": conversation_id}
        )
        
        if not results['ids']:
            return None
        
        # 简单摘要：返回前几条消息的摘要
        messages = []
        for i, content in enumerate(results['documents'][:5]):
            metadata = results['metadatas'][i]
            messages.append(f"{metadata.get('role', 'unknown')}: {content[:100]}")
        
        return "\n".join(messages)

