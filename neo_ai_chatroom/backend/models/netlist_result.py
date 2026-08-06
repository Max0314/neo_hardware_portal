"""
网表分析结果存储模型

持久化模型：本地目录是读缓存（列表/加载都走它，保持原有速度），对象存储是
持久层——每次保存/删除写通到 OSS，启动时本地为空则整目录恢复。
STORAGE_BACKEND=local 时 store 为 None，行为与历史版本完全一致。
"""
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from backend.object_store import build_store_from_env

logger = logging.getLogger(__name__)


class NetlistResultStore:
    """网表分析结果存储（本地缓存 + 对象存储写通）"""

    def __init__(self, storage_dir: str = "./netlist_results"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.store = build_store_from_env('netlist-results')
        if self.store is not None:
            self._restore_if_empty()

    # ---------- 对象存储写通 ----------

    def _restore_if_empty(self) -> None:
        """卷丢失后的自恢复：本地没有任何结果文件时，从对象存储整目录拉回。"""
        if any(self.storage_dir.glob('*.json')):
            return
        restored = 0
        try:
            for key in self.store.iter_keys(''):
                if not key.endswith('.json'):
                    continue
                data = self.store.get_bytes(key)
                if data is None:
                    continue
                target = self.storage_dir / os.path.basename(key)
                tmp = target.with_suffix(target.suffix + '.tmp')
                tmp.write_bytes(data)
                os.replace(tmp, target)
                restored += 1
        except Exception as e:  # noqa: BLE001 — 恢复失败不阻止启动，结果可重新生成
            logger.error("网表结果恢复中断（已恢复 %d 个）: %s", restored, e)
        if restored:
            logger.info("已从对象存储恢复 %d 个网表结果", restored)

    def _put_through(self, file_path: Path) -> None:
        if self.store is None:
            return
        try:
            self.store.put_bytes(file_path.name, file_path.read_bytes(),
                                 content_type='application/json')
        except Exception as e:  # noqa: BLE001 — 本地已落盘，可用性优先
            logger.warning("网表结果上传对象存储失败 %s: %s", file_path.name, e)

    def _delete_through(self, file_name: str) -> None:
        if self.store is None:
            return
        try:
            self.store.delete(file_name)
        except Exception as e:  # noqa: BLE001
            logger.warning("网表结果远端删除失败 %s: %s", file_name, e)

    # ---------- 业务 API（签名与历史版本一致）----------

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
        self._put_through(file_path)

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
        self._put_through(file_path)

        return str(file_path)

    def load_result(self, result_id: str) -> Optional[Dict]:
        """加载结果（本地缓存优先；miss 时回源对象存储并回填缓存）"""
        for suffix in ('comparison', 'analysis'):
            file_path = self.storage_dir / f"{result_id}_{suffix}.json"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)

        if self.store is not None:
            for suffix in ('comparison', 'analysis'):
                name = f"{result_id}_{suffix}.json"
                try:
                    raw = self.store.get_bytes(name)
                except Exception as e:  # noqa: BLE001
                    logger.warning("网表结果回源失败 %s: %s", name, e)
                    raw = None
                if raw is not None:
                    target = self.storage_dir / name
                    tmp = target.with_suffix(target.suffix + '.tmp')
                    tmp.write_bytes(raw)
                    os.replace(tmp, target)
                    return json.loads(raw.decode('utf-8'))

        return None

    def list_results(self, result_type: Optional[str] = None) -> List[Dict]:
        """列出所有结果（走本地缓存，避免逐对象远端读取）"""
        results = []

        for file_path in self.storage_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if result_type is None or data.get('type') == result_type:
                        results.append(data)
            except Exception:
                continue

        # 按创建时间排序
        results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return results

    def delete_result(self, result_id: str) -> bool:
        """删除结果（本地与对象存储同时删）"""
        deleted = False
        for suffix in ('comparison', 'analysis'):
            name = f"{result_id}_{suffix}.json"
            file_path = self.storage_dir / name
            if file_path.exists():
                file_path.unlink()
                deleted = True
            self._delete_through(name)

        return deleted
