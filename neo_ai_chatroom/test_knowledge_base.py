"""
测试知识库是否正常工作
"""
import requests
import json

# 配置
API_URL = "http://localhost:8000"

def get_role_id():
    """获取硬件专家角色的ID"""
    response = requests.get(f"{API_URL}/api/ais")
    if response.status_code == 200:
        data = response.json()
        for ai in data.get("ais", []):
            if ai.get("name") == "硬件专家" and ai.get("isCustom"):
                # 提取角色ID
                ai_id = ai.get("id", "")
                if ai_id.startswith("custom-"):
                    # custom-deepseek-xxx -> xxx
                    parts = ai_id.split("-")
                    if len(parts) >= 3:
                        return "-".join(parts[2:])
    return None

def test_knowledge_base(role_id):
    """测试知识库"""
    print(f"\n{'='*50}")
    print(f"测试角色ID: {role_id}")
    print(f"{'='*50}\n")
    
    # 1. 查看所有知识
    print("1. 查看所有知识:")
    response = requests.get(
        f"{API_URL}/api/custom-ai/{role_id}/knowledge",
        params={"query": "", "top_k": 100}
    )
    if response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        print(f"   找到 {len(results)} 条知识")
        for i, knowledge in enumerate(results[:5], 1):  # 只显示前5条
            print(f"   {i}. {knowledge[:80]}...")
    else:
        print(f"   错误: {response.status_code} - {response.text}")
    
    # 2. 测试检索
    print("\n2. 测试检索 'PCIe 3.0 的带宽':")
    response = requests.get(
        f"{API_URL}/api/custom-ai/{role_id}/knowledge",
        params={"query": "PCIe 3.0 的带宽", "top_k": 3}
    )
    if response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        if results:
            print(f"   检索到 {len(results)} 条相关知识:")
            for i, knowledge in enumerate(results, 1):
                print(f"   {i}. {knowledge}")
        else:
            print("   未检索到相关知识")
    else:
        print(f"   错误: {response.status_code} - {response.text}")
    
    # 3. 测试检索 "带宽"
    print("\n3. 测试检索 '带宽':")
    response = requests.get(
        f"{API_URL}/api/custom-ai/{role_id}/knowledge",
        params={"query": "带宽", "top_k": 3}
    )
    if response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        if results:
            print(f"   检索到 {len(results)} 条相关知识:")
            for i, knowledge in enumerate(results, 1):
                print(f"   {i}. {knowledge}")
        else:
            print("   未检索到相关知识")
    else:
        print(f"   错误: {response.status_code} - {response.text}")

if __name__ == "__main__":
    print("知识库测试工具")
    print("="*50)
    
    role_id = get_role_id()
    if role_id:
        test_knowledge_base(role_id)
    else:
        print("错误: 未找到'硬件专家'角色")
        print("\n提示: 请确保:")
        print("1. 后端服务正在运行")
        print("2. 已创建'硬件专家'自定义角色")
        print("3. 角色名称完全匹配")
