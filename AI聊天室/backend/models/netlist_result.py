"""
网表分析结果存储模型
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import uuid


class NetlistResultStore:
    """网表分析结果存储"""
    
    def __init__(self, storage_dir: str = "./netlist_results"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def save_comparison_result(
        self,
        result_id: str,
        comparison_result: Dict,
        netlist1_name: str = "网表1",
        netlist2_name: str = "网表2"
    ) -> str:
        """保存对比结果"""
        data = {
            "id": result_id,
            "type": "comparison",
            "netlist1_name": netlist1_name,
            "netlist2_name": netlist2_name,
            "result": comparison_result,
            "created_at": datetime.now().isoformat()
        }
        
        file_path = self.storage_dir / f"{result_id}_comparison.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return str(file_path)
    
    def save_analysis_result(
        self,
        result_id: str,
        analysis_result: Dict,
        netlist_name: str = "网表"
    ) -> str:
        """保存分析结果"""
        data = {
            "id": result_id,
            "type": "analysis",
            "netlist_name": netlist_name,
            "result": analysis_result,
            "created_at": datetime.now().isoformat()
        }
        
        file_path = self.storage_dir / f"{result_id}_analysis.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return str(file_path)
    
    def load_result(self, result_id: str) -> Optional[Dict]:
        """加载结果"""
        # 尝试加载对比结果
        comparison_file = self.storage_dir / f"{result_id}_comparison.json"
        if comparison_file.exists():
            with open(comparison_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 尝试加载分析结果
        analysis_file = self.storage_dir / f"{result_id}_analysis.json"
        if analysis_file.exists():
            with open(analysis_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        return None
    
    def list_results(self, result_type: Optional[str] = None) -> List[Dict]:
        """列出所有结果"""
        results = []
        
        for file_path in self.storage_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if result_type is None or data.get('type') == result_type:
                        results.append(data)
            except:
                continue
        
        # 按创建时间排序
        results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return results
    
    def delete_result(self, result_id: str) -> bool:
        """删除结果"""
        comparison_file = self.storage_dir / f"{result_id}_comparison.json"
        analysis_file = self.storage_dir / f"{result_id}_analysis.json"
        
        deleted = False
        if comparison_file.exists():
            comparison_file.unlink()
            deleted = True
        if analysis_file.exists():
            analysis_file.unlink()
            deleted = True
        
        return deleted
