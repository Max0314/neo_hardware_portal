"""
批量导入知识库脚本
支持从TXT和JSON文件导入知识
"""
import requests
import json
import sys
import os

# 配置
API_URL = "http://localhost:8000"


def import_from_txt(file_path, role_id, metadata=None):
    """从TXT文件导入知识（每行一条）"""
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        return
    
    success_count = 0
    fail_count = 0
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    print(f"开始导入 {len(lines)} 条知识...")
    
    for i, line in enumerate(lines, 1):
        line = line.strip()
        
        # 跳过空行和注释
        if not line or line.startswith('#'):
            continue
        
        try:
            response = requests.post(
                f"{API_URL}/api/custom-ai/{role_id}/knowledge",
                json={
                    "text": line,
                    "metadata": metadata or {}
                }
            )
            
            if response.status_code == 200:
                success_count += 1
                print(f"[{i}/{len(lines)}] ✓ 添加成功: {line[:50]}...")
            else:
                fail_count += 1
                print(f"[{i}/{len(lines)}] ✗ 添加失败: {response.text}")
        
        except Exception as e:
            fail_count += 1
            print(f"[{i}/{len(lines)}] ✗ 错误: {e}")
    
    print(f"\n导入完成: 成功 {success_count} 条, 失败 {fail_count} 条")


def import_from_json(file_path, role_id):
    """从JSON文件导入知识"""
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        return
    
    with open(file_path, 'r', encoding='utf-8') as f:
        knowledge_items = json.load(f)
    
    if not isinstance(knowledge_items, list):
        print("错误: JSON文件格式不正确，应该是数组格式")
        return
    
    success_count = 0
    fail_count = 0
    
    print(f"开始导入 {len(knowledge_items)} 条知识...")
    
    for i, item in enumerate(knowledge_items, 1):
        if not isinstance(item, dict):
            print(f"[{i}/{len(knowledge_items)}] ✗ 跳过: 格式不正确")
            fail_count += 1
            continue
        
        text = item.get("text", "")
        metadata = item.get("metadata", {})
        
        if not text:
            print(f"[{i}/{len(knowledge_items)}] ✗ 跳过: 文本为空")
            fail_count += 1
            continue
        
        try:
            response = requests.post(
                f"{API_URL}/api/custom-ai/{role_id}/knowledge",
                json={
                    "text": text,
                    "metadata": metadata
                }
            )
            
            if response.status_code == 200:
                success_count += 1
                print(f"[{i}/{len(knowledge_items)}] ✓ 添加成功: {text[:50]}...")
            else:
                fail_count += 1
                print(f"[{i}/{len(knowledge_items)}] ✗ 添加失败: {response.text}")
        
        except Exception as e:
            fail_count += 1
            print(f"[{i}/{len(knowledge_items)}] ✗ 错误: {e}")
    
    print(f"\n导入完成: 成功 {success_count} 条, 失败 {fail_count} 条")


def main():
    """主函数"""
    if len(sys.argv) < 3:
        print("用法:")
        print("  python 批量导入知识库.py <文件路径> <角色ID> [metadata_json]")
        print("")
        print("示例:")
        print("  python 批量导入知识库.py knowledge.txt d0bbab7a-7efe-4d43-8d1e-49581264d6ff")
        print("  python 批量导入知识库.py knowledge.json d0bbab7a-7efe-4d43-8d1e-49581264d6ff")
        print("  python 批量导入知识库.py knowledge.txt d0bbab7a-7efe-4d43-8d1e-49581264d6ff '{\"category\":\"日程管理\"}'")
        return
    
    file_path = sys.argv[1]
    role_id = sys.argv[2]
    metadata = None
    
    if len(sys.argv) > 3:
        try:
            metadata = json.loads(sys.argv[3])
        except:
            print("警告: metadata格式不正确，将忽略")
    
    # 根据文件扩展名选择导入方式
    if file_path.endswith('.json'):
        import_from_json(file_path, role_id)
    else:
        import_from_txt(file_path, role_id, metadata)


if __name__ == "__main__":
    main()

