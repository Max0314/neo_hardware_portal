"""
轻量级对话分类模型
用于识别基础对话类型（问候、问题、命令、闲聊等）
"""
import os
import json
import pickle
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import numpy as np

try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer
    from transformers import pipeline
    import torch
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    print("警告: transformers未安装，对话分类模型功能将不可用")


class DialogueCategory:
    """对话类别枚举"""
    GREETING = "greeting"  # 问候
    QUESTION = "question"  # 问题
    COMMAND = "command"  # 命令
    CHAT = "chat"  # 闲聊
    REQUEST = "request"  # 请求
    COMPLAINT = "complaint"  # 抱怨
    THANKS = "thanks"  # 感谢
    UNKNOWN = "unknown"  # 未知


class DialogueClassifier:
    """对话分类器"""
    
    def __init__(self, model_path: str = "./models/dialogue_classifier"):
        self.model_path = Path(model_path)
        self.model_path.mkdir(parents=True, exist_ok=True)
        self.model = None
        self.tokenizer = None
        self.label2id = None
        self.id2label = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu" if TRANSFORMERS_AVAILABLE else None
        
        # 如果模型已存在，加载它
        if (self.model_path / "config.json").exists():
            self.load_model()
    
    def prepare_labels(self, training_data: List[Dict]) -> Tuple[Dict, Dict]:
        """从训练数据中准备标签映射"""
        labels = set()
        for item in training_data:
            labels.add(item["label"])
        
        label2id = {label: idx for idx, label in enumerate(sorted(labels))}
        id2label = {idx: label for label, idx in label2id.items()}
        
        return label2id, id2label
    
    def train(
        self,
        training_data: List[Dict],
        model_name: str = "bert-base-chinese",
        epochs: int = 3,
        batch_size: int = 16,
        learning_rate: float = 2e-5
    ):
        """
        训练对话分类模型
        
        Args:
            training_data: 训练数据列表，格式 [{"text": "你好", "label": "greeting"}, ...]
            model_name: 预训练模型名称（推荐：bert-base-chinese, distilbert-base-chinese）
            epochs: 训练轮数
            batch_size: 批次大小
            learning_rate: 学习率
        """
        if not TRANSFORMERS_AVAILABLE:
            raise ImportError("transformers库未安装，请先安装：pip install transformers torch")
        
        print(f"开始训练对话分类模型...")
        print(f"训练数据量: {len(training_data)}")
        
        # 准备标签
        self.label2id, self.id2label = self.prepare_labels(training_data)
        num_labels = len(self.label2id)
        
        print(f"类别数量: {num_labels}")
        print(f"类别: {list(self.label2id.keys())}")
        
        # 加载tokenizer和模型
        print(f"加载预训练模型: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_name,
            num_labels=num_labels,
            id2label=self.id2label,
            label2id=self.label2id
        )
        
        # 准备数据集
        texts = [item["text"] for item in training_data]
        labels = [self.label2id[item["label"]] for item in training_data]
        
        # Tokenize
        encodings = self.tokenizer(
            texts,
            truncation=True,
            padding=True,
            max_length=128,
            return_tensors="pt"
        )
        
        # 创建数据集类
        class DialogueDataset(torch.utils.data.Dataset):
            def __init__(self, encodings, labels):
                self.encodings = encodings
                self.labels = labels
            
            def __getitem__(self, idx):
                item = {key: val[idx] for key, val in self.encodings.items()}
                item['labels'] = torch.tensor(self.labels[idx])
                return item
            
            def __len__(self):
                return len(self.labels)
        
        # 划分训练集和验证集（80/20）
        split_idx = int(len(training_data) * 0.8)
        train_dataset = DialogueDataset(
            {k: v[:split_idx] for k, v in encodings.items()},
            labels[:split_idx]
        )
        val_dataset = DialogueDataset(
            {k: v[split_idx:] for k, v in encodings.items()},
            labels[split_idx:]
        )
        
        # 训练参数
        training_args = TrainingArguments(
            output_dir=str(self.model_path),
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            learning_rate=learning_rate,
            weight_decay=0.01,
            logging_dir=str(self.model_path / "logs"),
            logging_steps=10,
            eval_strategy="epoch",
            save_strategy="epoch",
            load_best_model_at_end=True,
        )
        
        # 创建Trainer
        trainer = Trainer(
            model=self.model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=val_dataset,
        )
        
        # 训练
        print("开始训练...")
        trainer.train()
        
        # 保存模型
        self.save_model()
        
        # 评估
        eval_results = trainer.evaluate()
        print(f"验证集准确率: {eval_results.get('eval_accuracy', 0):.4f}")
        
        print(f"模型已保存到: {self.model_path}")
    
    def save_model(self):
        """保存模型"""
        if self.model and self.tokenizer:
            self.model.save_pretrained(str(self.model_path))
            self.tokenizer.save_pretrained(str(self.model_path))
            
            # 保存标签映射
            with open(self.model_path / "label_mapping.json", "w", encoding="utf-8") as f:
                json.dump({
                    "label2id": self.label2id,
                    "id2label": {str(k): v for k, v in self.id2label.items()}
                }, f, ensure_ascii=False, indent=2)
    
    def load_model(self):
        """加载模型"""
        if not TRANSFORMERS_AVAILABLE:
            return False
        
        try:
            # 加载标签映射
            label_mapping_file = self.model_path / "label_mapping.json"
            if label_mapping_file.exists():
                with open(label_mapping_file, "r", encoding="utf-8") as f:
                    mapping = json.load(f)
                    self.label2id = mapping["label2id"]
                    self.id2label = {int(k): v for k, v in mapping["id2label"].items()}
            
            # 加载模型和tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_path))
            self.model = AutoModelForSequenceClassification.from_pretrained(str(self.model_path))
            self.model.eval()
            
            print(f"模型已从 {self.model_path} 加载")
            return True
        except Exception as e:
            print(f"加载模型失败: {e}")
            return False
    
    def predict(self, text: str, return_probs: bool = False) -> Dict:
        """
        预测对话类别
        
        Args:
            text: 输入文本
            return_probs: 是否返回所有类别的概率
        
        Returns:
            {"label": "greeting", "confidence": 0.95} 或包含所有概率的字典
        """
        if not self.model or not self.tokenizer:
            return {"label": DialogueCategory.UNKNOWN, "confidence": 0.0}
        
        # Tokenize
        inputs = self.tokenizer(
            text,
            truncation=True,
            padding=True,
            max_length=128,
            return_tensors="pt"
        )
        
        # 预测
        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = outputs.logits
            probs = torch.softmax(logits, dim=-1)
        
        # 获取预测结果
        predicted_id = torch.argmax(probs, dim=-1).item()
        predicted_label = self.id2label[predicted_id]
        confidence = probs[0][predicted_id].item()
        
        if return_probs:
            # 返回所有类别的概率
            result = {
                "label": predicted_label,
                "confidence": confidence,
                "probabilities": {
                    self.id2label[i]: probs[0][i].item()
                    for i in range(len(self.id2label))
                }
            }
        else:
            result = {
                "label": predicted_label,
                "confidence": confidence
            }
        
        return result
    
    def predict_batch(self, texts: List[str]) -> List[Dict]:
        """批量预测"""
        results = []
        for text in texts:
            results.append(self.predict(text))
        return results


class SimpleDialogueClassifier:
    """简单规则分类器（无需训练，作为备用方案）"""
    
    def __init__(self):
        # 关键词规则
        self.rules = {
            DialogueCategory.GREETING: ["你好", "您好", "早上好", "下午好", "晚上好", "hi", "hello", "哈喽"],
            DialogueCategory.QUESTION: ["什么", "怎么", "为什么", "如何", "哪里", "哪个", "?", "？", "吗"],
            DialogueCategory.COMMAND: ["帮我", "请", "做", "执行", "运行", "开始", "停止", "保存", "删除"],
            DialogueCategory.REQUEST: ["可以", "能否", "能不能", "麻烦", "请求"],
            DialogueCategory.THANKS: ["谢谢", "感谢", "多谢", "thx", "thanks"],
            DialogueCategory.COMPLAINT: ["不好", "不行", "错误", "失败", "问题", "bug"],
            DialogueCategory.CHAT: ["哈哈", "呵呵", "嗯", "哦", "好的", "ok", "okay"],
        }
    
    def predict(self, text: str, return_probs: bool = False) -> Dict:
        """基于规则的预测"""
        if not text:
            return {"label": DialogueCategory.UNKNOWN, "confidence": 0.0}
        
        text_lower = text.lower()
        scores = {}
        
        for category, keywords in self.rules.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[category] = score
        
        if scores:
            predicted = max(scores, key=scores.get)
            confidence = min(0.9, scores[predicted] / 3.0)
        else:
            predicted = DialogueCategory.UNKNOWN
            confidence = 0.5
        
        result = {
            "label": predicted,
            "confidence": confidence
        }
        
        if return_probs:
            # 计算所有类别的概率（归一化）
            total_score = sum(scores.values()) if scores else 1
            probabilities = {
                cat: (scores.get(cat, 0) / total_score) if total_score > 0 else 0.0
                for cat in [DialogueCategory.GREETING, DialogueCategory.QUESTION, 
                           DialogueCategory.COMMAND, DialogueCategory.REQUEST,
                           DialogueCategory.THANKS, DialogueCategory.COMPLAINT,
                           DialogueCategory.CHAT, DialogueCategory.UNKNOWN]
            }
            result["probabilities"] = probabilities
        
        return result
    
    def predict_batch(self, texts: List[str]) -> List[Dict]:
        """批量预测"""
        results = []
        for text in texts:
            results.append(self.predict(text))
        return results
