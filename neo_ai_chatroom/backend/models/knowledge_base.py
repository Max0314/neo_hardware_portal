"""
轻量级知识库实现
支持角色专属知识库和智能检索
支持图片存储（Base64或文件路径）
"""
import os
from typing import List, Dict, Optional, Tuple
import json
from backend.models import db_compat
import uuid
from datetime import datetime


class KnowledgeBase:
    """角色知识库基类"""
    
    def __init__(self, role_id: str, persist_directory: str = "./knowledge_bases"):
        self.role_id = role_id
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)
    
    def add_knowledge(self, text: str, metadata: Dict = None):
        """添加知识片段（子类实现）"""
        raise NotImplementedError
    
    def retrieve(self, query: str, top_k: int = 3, similarity_threshold: float = 0.7) -> List[str]:
        """检索相关知识（子类实现）"""
        raise NotImplementedError


class ChromaKnowledgeBase(KnowledgeBase):
    """基于ChromaDB的知识库实现"""
    
    def __init__(self, role_id: str, persist_directory: str = "./knowledge_bases"):
        super().__init__(role_id, persist_directory)
        self._init_chromadb()
        self._init_encoder()
    
    def _init_chromadb(self):
        """初始化ChromaDB"""
        try:
            import chromadb
            from chromadb.config import Settings
            
            self.client = chromadb.PersistentClient(
                path=os.path.join(self.persist_directory, self.role_id),
                settings=Settings(
                    chroma_db_impl="duckdb+parquet",
                    anonymized_telemetry=False
                )
            )
            
            # 获取或创建集合
            try:
                self.collection = self.client.get_collection(f"{self.role_id}_knowledge")
            except:
                self.collection = self.client.create_collection(
                    name=f"{self.role_id}_knowledge",
                    metadata={"hnsw:space": "cosine"}
                )
                # 初始化默认知识
                self._initialize_default_knowledge()
        except ImportError:
            print("警告: chromadb未安装，知识库功能将不可用")
            self.collection = None
    
    def _init_encoder(self):
        """初始化嵌入模型"""
        try:
            from sentence_transformers import SentenceTransformer
            # 使用轻量级模型（80MB）
            self.encoder = SentenceTransformer('paraphrase-MiniLM-L3-v2')
        except ImportError:
            print("警告: sentence-transformers未安装，使用OpenAI API生成嵌入")
            self.encoder = None
    
    def _initialize_default_knowledge(self):
        """初始化默认知识（根据角色类型）"""
        if not self.collection:
            return
        
        # 通用知识
        default_knowledge = [
            "重要会议需提前24小时通知参会人，会前30分钟发送提醒",
            "会议冲突时，优先安排更高优先级或更早预定的会议",
            "正式邮件使用标准格式：称呼、正文、结束语、签名",
            "紧急邮件需在主题前加【紧急】标识",
            "会议纪要需在会议结束24小时内完成并分发",
        ]
        
        # 分批添加
        batch_size = 50
        for i in range(0, len(default_knowledge), batch_size):
            batch = default_knowledge[i:i+batch_size]
            self.collection.add(
                documents=batch,
                ids=[f"default_{i+j}" for j in range(len(batch))]
            )
    
    def add_knowledge(self, text: str, metadata: Dict = None):
        """添加知识片段"""
        if not self.collection:
            return False
        
        try:
            import uuid
            doc_id = str(uuid.uuid4())
            self.collection.add(
                documents=[text],
                ids=[doc_id],
                metadatas=[metadata or {}]
            )
            return True
        except Exception as e:
            print(f"添加知识失败: {e}")
            return False
    
    def retrieve(self, query: str, top_k: int = 3, similarity_threshold: float = 0.7, max_tokens: int = 1500) -> Optional[str]:
        """检索相关知识，控制token数量"""
        if not self.collection:
            return None
        
        try:
            # 生成查询向量
            if self.encoder:
                query_embedding = self.encoder.encode(query).tolist()
            else:
                # 使用OpenAI API生成嵌入（同步调用）
                query_embedding = self._generate_embedding_with_openai(query)
            
            # 检索（多取一些用于筛选）
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k * 2,
                include=["documents", "distances"]
            )
            
            # 根据相似度阈值筛选并控制token数量
            relevant_docs = []
            total_tokens = 0
            
            for doc, distance in zip(results['documents'][0], results['distances'][0]):
                similarity = 1 - distance  # ChromaDB使用余弦距离
                
                if similarity >= similarity_threshold:
                    # 估算token数（中文约2字符=1token）
                    token_estimate = len(doc) // 2
                    
                    if total_tokens + token_estimate <= max_tokens:
                        relevant_docs.append(doc)
                        total_tokens += token_estimate
                
                if len(relevant_docs) >= top_k or total_tokens >= max_tokens:
                    break
            
            return "\n".join(relevant_docs) if relevant_docs else None
        
        except Exception as e:
            print(f"知识检索失败: {e}")
            return None
    
    def _generate_embedding_with_openai(self, text: str) -> List[float]:
        """使用OpenAI API生成嵌入向量（同步版本）"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            # 只在第一次失败时打印警告
            if not hasattr(self, '_embedding_warning_printed'):
                print(f"OpenAI嵌入生成失败: {e}，知识库将使用关键词匹配")
                self._embedding_warning_printed = True
            return [0.0] * 384  # 返回零向量


class SimpleKnowledgeBase(KnowledgeBase):
    """简单内存知识库（无向量数据库依赖）- 支持问答对格式和图片"""
    
    def __init__(self, role_id: str, persist_directory: str = "./knowledge_bases", db_path: str = "chatroom.db"):
        super().__init__(role_id, persist_directory)
        self.db_path = db_path
        self.knowledge_chunks: List[Dict] = []
        self.qa_pairs: List[Dict] = []  # 问答对列表（兼容旧格式）
        self.use_database = True  # 默认使用数据库
        self._init_database()
        self._load_knowledge()
    
    def _init_database(self):
        """初始化数据库表（如果不存在）。

        与 message.py 的 _MYSQL_DDL 中 knowledge_base 定义保持一致（含 event_config），
        CREATE TABLE IF NOT EXISTS 幂等，重复执行无副作用；不再需要旧的
        “探测缺列再 ALTER” 逻辑。
        """
        try:
            conn = db_compat.connect_sync()
            cursor = conn.cursor()
            cursor.execute("""
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
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[知识库] 数据库初始化失败: {e}")
            self.use_database = False
    
    def _load_knowledge(self):
        """加载知识库（优先从数据库加载，兼容旧JSON文件）"""
        # 优先从数据库加载
        if self.use_database:
            try:
                conn = db_compat.connect_sync()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, keywords, answer, image_data, image_path, image_type, metadata, event_config
                    FROM knowledge_base
                    WHERE role_id = ?
                    ORDER BY created_at DESC
                """, (self.role_id,))
                
                rows = cursor.fetchall()
                self.qa_pairs = []
                for row in rows:
                    knowledge_id, keywords, answer, image_data, image_path, image_type, metadata_json, event_config_json = row
                    metadata = {}
                    if metadata_json:
                        try:
                            metadata = json.loads(metadata_json)
                        except:
                            pass
                    
                    event_config = None
                    if event_config_json:
                        try:
                            event_config = json.loads(event_config_json)
                        except:
                            pass
                    
                    self.qa_pairs.append({
                        "id": knowledge_id,
                        "keywords": keywords,
                        "answer": answer,
                        "image_data": image_data,
                        "image_path": image_path,
                        "image_type": image_type,
                        "metadata": metadata,
                        "event_config": event_config
                    })
                
                conn.close()
                print(f"[知识库] 从数据库加载成功: {len(self.qa_pairs)} 条问答对")
                # 如果数据库有数据，就不加载JSON文件了
                if len(self.qa_pairs) > 0:
                    self.knowledge_chunks = []
                    return
            except Exception as e:
                print(f"[知识库] 数据库加载失败: {e}")
                import traceback
                traceback.print_exc()
                self.use_database = False
        
        # 降级到文件加载（兼容旧格式）
        possible_files = [
            os.path.join(self.persist_directory, f"custom-{self.role_id}_knowledge.json"),
            os.path.join(self.persist_directory, f"{self.role_id}_knowledge.json"),
        ]
        
        knowledge_file = None
        for fpath in possible_files:
            if os.path.exists(fpath):
                knowledge_file = fpath
                break
        
        if knowledge_file:
            try:
                with open(knowledge_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 兼容旧格式和新格式
                    if isinstance(data, list):
                        # 旧格式：只有text字段
                        self.knowledge_chunks = data
                        # 转换为问答对格式
                        self.qa_pairs = []
                        for chunk in data:
                            if isinstance(chunk, dict) and "text" in chunk:
                                # 尝试从text中提取问答对（如果有明确的分隔符）
                                text = chunk.get("text", "")
                                if "|" in text or "\n" in text:
                                    # 可能是问答对格式
                                    parts = text.split("|", 1) if "|" in text else text.split("\n", 1)
                                    if len(parts) == 2:
                                        self.qa_pairs.append({
                                            "keywords": parts[0].strip(),
                                            "answer": parts[1].strip()
                                        })
                    elif isinstance(data, dict):
                        # 新格式：包含qa_pairs
                        self.qa_pairs = data.get("qa_pairs", [])
                        self.knowledge_chunks = data.get("knowledge_chunks", [])
                    else:
                        self.knowledge_chunks = []
                        self.qa_pairs = []
                    print(f"[知识库] 从文件加载成功: {knowledge_file}, QA对: {len(self.qa_pairs)}, 知识片段: {len(self.knowledge_chunks)}")
            except Exception as e:
                print(f"加载知识库失败: {e}")
                import traceback
                traceback.print_exc()
                self.knowledge_chunks = []
                self.qa_pairs = []
        else:
            # 如果既没有数据库数据，也没有文件，初始化为空
            if not self.qa_pairs:
                print(f"[知识库] 文件不存在，尝试的文件: {possible_files}")
                self.knowledge_chunks = []
                self.qa_pairs = []
    
    def _save_knowledge(self):
        """保存知识库"""
        # 使用与加载相同的文件名逻辑
        knowledge_file = os.path.join(self.persist_directory, f"custom-{self.role_id}_knowledge.json")
        # 如果文件不存在，尝试另一个格式
        if not os.path.exists(knowledge_file):
            alt_file = os.path.join(self.persist_directory, f"{self.role_id}_knowledge.json")
            if os.path.exists(alt_file):
                knowledge_file = alt_file
        
        try:
            data = {
                "qa_pairs": self.qa_pairs,
                "knowledge_chunks": self.knowledge_chunks  # 保留旧格式兼容性
            }
            with open(knowledge_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[知识库] 保存成功: {knowledge_file}")
        except Exception as e:
            print(f"保存知识库失败: {e}")
    
    def add_knowledge(self, text: str, metadata: Dict = None, image_data: str = None, image_path: str = None, image_type: str = None, event_config: Dict = None):
        """添加知识片段（支持问答对格式、图片和事件配置）"""
        # 检查是否是问答对格式：关键词|答案 或 关键词\n答案
        keywords = None
        answer = None
        
        if "|" in text:
            parts = text.split("|", 1)
            if len(parts) == 2:
                keywords = parts[0].strip()
                answer = parts[1].strip()
        elif "\n" in text and len(text.split("\n")) == 2:
            parts = text.split("\n", 1)
            if len(parts) == 2:
                keywords = parts[0].strip()
                answer = parts[1].strip()
        
        # 如果只有事件配置，没有问答对，使用事件配置中的关键词
        if not keywords and event_config and event_config.get("params", {}).get("keywords"):
            keywords_list = event_config["params"]["keywords"]
            if isinstance(keywords_list, list) and len(keywords_list) > 0:
                keywords = keywords_list[0]  # 使用第一个关键词作为主关键词
            elif isinstance(keywords_list, str):
                keywords = keywords_list.split(",")[0].strip()
        
        # 如果没有关键词，使用默认值
        if not keywords:
            keywords = event_config.get("params", {}).get("keywords", ["事件触发"])[0] if event_config else "事件触发"
        
        # 如果没有答案，使用默认值或空字符串
        if not answer:
            answer = "[事件触发]" if event_config else ""
        
        # 如果使用数据库存储（只要有keywords就可以存储）
        if self.use_database and keywords:
            try:
                conn = db_compat.connect_sync()
                cursor = conn.cursor()
                
                # 将metadata和event_config转换为JSON字符串
                metadata_json = json.dumps(metadata or {}) if metadata else None
                event_config_json = json.dumps(event_config) if event_config else None
                
                knowledge_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO knowledge_base 
                    (id, role_id, keywords, answer, image_data, image_path, image_type, metadata, event_config)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (knowledge_id, self.role_id, keywords, answer, image_data, image_path, image_type, metadata_json, event_config_json))
                
                conn.commit()
                conn.close()
                print(f"[知识库] 已添加到数据库: {keywords}")
                return True
            except Exception as e:
                print(f"[知识库] 数据库添加失败: {e}")
                # 降级到文件存储
                self.use_database = False
        
        # 降级到文件存储（兼容旧格式）
        if keywords and answer:
            self.qa_pairs.append({
                "keywords": keywords,
                "answer": answer,
                "metadata": metadata or {},
                "image_data": image_data,
                "image_path": image_path,
                "image_type": image_type,
                "event_config": event_config
            })
        else:
            # 旧格式：只有文本
            self.knowledge_chunks.append({
                "text": text,
                "metadata": metadata or {}
            })
        
        self._save_knowledge()
        return True
    
    def delete_qa_pair(self, keywords: str, answer: str = None) -> bool:
        """删除问答对（根据关键词和答案匹配）"""
        # 优先从数据库删除
        if self.use_database:
            try:
                conn = db_compat.connect_sync()
                cursor = conn.cursor()
                
                if answer:
                    # 精确匹配
                    cursor.execute("""
                        DELETE FROM knowledge_base
                        WHERE role_id = ? AND keywords = ? AND answer = ?
                    """, (self.role_id, keywords.strip(), answer.strip()))
                else:
                    # 只根据关键词匹配
                    cursor.execute("""
                        DELETE FROM knowledge_base
                        WHERE role_id = ? AND keywords = ?
                    """, (self.role_id, keywords.strip()))
                
                deleted_count = cursor.rowcount
                conn.commit()
                conn.close()
                
                if deleted_count > 0:
                    print(f"[知识库] 从数据库删除成功，删除了 {deleted_count} 条问答对")
                    # 重新加载
                    self._load_knowledge()
                    return True
                else:
                    print(f"[知识库] 未找到匹配的问答对")
                    return False
            except Exception as e:
                print(f"[知识库] 数据库删除失败: {e}")
                self.use_database = False
        
        # 降级到文件删除
        self._load_knowledge()  # 确保加载最新数据
        
        initial_count = len(self.qa_pairs)
        
        if answer:
            # 如果提供了答案，精确匹配
            self.qa_pairs = [
                qa for qa in self.qa_pairs 
                if not (qa.get("keywords", "").strip() == keywords.strip() and 
                       qa.get("answer", "").strip() == answer.strip())
            ]
        else:
            # 只根据关键词匹配
            self.qa_pairs = [
                qa for qa in self.qa_pairs 
                if qa.get("keywords", "").strip() != keywords.strip()
            ]
        
        if len(self.qa_pairs) < initial_count:
            self._save_knowledge()
            print(f"[知识库] 删除成功，删除了 {initial_count - len(self.qa_pairs)} 条问答对")
            return True
        else:
            print(f"[知识库] 未找到匹配的问答对")
            return False
    
    def delete_knowledge_chunk(self, text: str) -> bool:
        """删除知识片段"""
        self._load_knowledge()  # 确保加载最新数据
        
        initial_count = len(self.knowledge_chunks)
        self.knowledge_chunks = [
            chunk for chunk in self.knowledge_chunks 
            if chunk.get("text", "").strip() != text.strip()
        ]
        
        if len(self.knowledge_chunks) < initial_count:
            self._save_knowledge()
            print(f"[知识库] 删除成功，删除了 {initial_count - len(self.knowledge_chunks)} 条知识片段")
            return True
        else:
            print(f"[知识库] 未找到匹配的知识片段")
            return False
    
    def get_all_qa_pairs(self) -> List[Dict]:
        """获取所有问答对"""
        self._load_knowledge()
        return self.qa_pairs.copy()
    
    def get_all_knowledge_chunks(self) -> List[Dict]:
        """获取所有知识片段"""
        self._load_knowledge()
        return self.knowledge_chunks.copy()
    
    def retrieve(self, query: str, top_k: int = 3, similarity_threshold: float = 0.7, max_tokens: int = 1500, return_all_matches: bool = False) -> Optional[str]:
        """关键字匹配检索 - 返回匹配的答案（支持返回所有匹配项）"""
        query_lower = query.lower().strip()
        
        # 优先使用问答对格式
        if self.qa_pairs:
            # 提取查询关键词（更宽泛的匹配：两个字以上就匹配）
            stop_words = {'的', '是', '多少', '什么', '？', '?', '，', ',', '。', '.', '了', '吗', '呢', '啊', '呀', ' ', '\t', '\n'}
            # 提取所有2个字符以上的词（包括英文单词）
            query_keywords = []
            # 先按空格分割
            for word in query_lower.split():
                word_clean = word.strip()
                if word_clean and word_clean not in stop_words and len(word_clean) >= 2:
                    query_keywords.append(word_clean)
            
            # 如果没有提取到关键词，尝试从整个查询字符串中提取2个字符以上的子串
            if not query_keywords:
                # 提取所有连续的2个字符以上的子串（包括英文单词）
                for i in range(len(query_lower) - 1):
                    substr = query_lower[i:i+2]
                    if substr not in stop_words and len(substr) >= 2:
                        query_keywords.append(substr)
            
            # 如果查询本身就是关键词（如"pcie"、"带宽"），直接添加
            if query_lower and len(query_lower) >= 2 and query_lower not in stop_words:
                if query_lower not in query_keywords:
                    query_keywords.insert(0, query_lower)  # 优先使用完整查询
            
            matches = []  # 存储所有匹配项
            
            for qa in self.qa_pairs:
                keywords_str = qa.get("keywords", "").lower().strip()
                answer = qa.get("answer", "")
                
                if not keywords_str:
                    continue
                
                # 计算匹配分数
                score = 0
                matched_chars = 0
                
                # 完全匹配（最高分）
                if keywords_str == query_lower or query_lower in keywords_str or keywords_str in query_lower:
                    score += 20
                    matched_chars = len(keywords_str)
                else:
                    # 关键词匹配（更宽泛）
                    keywords_list = keywords_str.split()
                    
                    for kw in query_keywords:
                        if len(kw) >= 2:  # 两个字以上的关键词
                            # 检查是否在关键词字符串中
                            if kw in keywords_str:
                                score += 5
                                matched_chars += len(kw)
                            # 检查是否在关键词列表中
                            for keyword in keywords_list:
                                if kw in keyword or keyword in kw:
                                    score += 6
                                    matched_chars += len(kw)
                                    break
                    
                    # 也检查关键词是否在查询中
                    for keyword in keywords_list:
                        if len(keyword) >= 2 and keyword in query_lower:
                            score += 4
                            matched_chars += len(keyword)
                
                # 如果匹配到至少2个字符，就认为匹配成功
                if matched_chars >= 2 or score > 0:
                    matches.append({
                        "score": score,
                        "question": qa.get("keywords", ""),
                        "answer": answer,
                        "image_data": qa.get("image_data"),  # 包含图片数据
                        "image_path": qa.get("image_path"),
                        "image_type": qa.get("image_type"),
                        "event_config": qa.get("event_config")  # 包含事件配置
                    })
            
            # 按分数排序
            matches.sort(reverse=True, key=lambda x: x["score"])
            
            if matches:
                print(f"[知识库匹配] 查询: {query}")
                print(f"[知识库匹配] 找到 {len(matches)} 个匹配项")
                for i, match in enumerate(matches[:5], 1):
                    print(f"[知识库匹配] {i}. 分数:{match['score']}, 问题:{match['question']}")
                
                # 如果只需要返回最佳匹配
                if not return_all_matches:
                    best_match = matches[0]
                    print(f"[知识库匹配] 返回最佳匹配: {best_match['question']}")
                    return best_match["answer"]
                else:
                    # 返回所有匹配项（用于显示选择）
                    return matches
        
        # 如果没有问答对或没有匹配，使用旧格式的关键词匹配
        if self.knowledge_chunks:
            query_lower = query.lower()
            stop_words = {'的', '是', '多少', '什么', '？', '?', '，', ',', '。', '.', '了', '吗', '呢'}
            keywords = [kw for kw in query_lower.split() if kw not in stop_words and len(kw) > 1]
            
            relevant_docs = []
            match_scores = []
            
            for chunk in self.knowledge_chunks:
                text = chunk["text"].lower()
                matched_keywords = [kw for kw in keywords if kw in text]
                match_score = len(matched_keywords)
                
                if match_score > 0:
                    match_scores.append((match_score, chunk["text"]))
            
            match_scores.sort(reverse=True, key=lambda x: x[0])
            relevant_docs = [doc for score, doc in match_scores[:top_k] if score > 0]
            
            if relevant_docs:
                return "\n".join(relevant_docs)
        
        return None


def create_knowledge_base(
    role_id: str,
    use_vector: bool = True,
    db_path: str = "chatroom.db",
    persist_directory: str = "./knowledge_bases",
) -> KnowledgeBase:
    """创建知识库实例"""
    if use_vector:
        try:
            return ChromaKnowledgeBase(role_id, persist_directory=persist_directory)
        except:
            print("向量知识库创建失败，使用简单知识库")
            return SimpleKnowledgeBase(
                role_id, persist_directory=persist_directory, db_path=db_path
            )
    else:
        return SimpleKnowledgeBase(
            role_id, persist_directory=persist_directory, db_path=db_path
        )

