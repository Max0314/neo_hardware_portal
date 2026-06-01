"""
测试自定义AI角色创建功能
"""
import requests
import json
import sys

# 配置
API_URL = "http://localhost:8000"


def test_get_ais():
    """测试获取AI列表"""
    print("=" * 60)
    print("测试1: 获取AI列表")
    print("=" * 60)
    
    try:
        response = requests.get(f"{API_URL}/api/ais")
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            ais = data.get("ais", [])
            print(f"✓ 成功获取 {len(ais)} 个AI")
            
            # 显示自定义角色
            custom_ais = [ai for ai in ais if ai.get("isCustom")]
            print(f"  其中自定义角色: {len(custom_ais)} 个")
            
            for ai in custom_ais:
                print(f"    - {ai.get('name')} (ID: {ai.get('id')})")
            
            return True
        else:
            print(f"✗ 失败: {response.text}")
            return False
    
    except Exception as e:
        print(f"✗ 错误: {e}")
        return False


def test_create_custom_ai():
    """测试创建自定义AI角色"""
    print("\n" + "=" * 60)
    print("测试2: 创建自定义AI角色")
    print("=" * 60)
    
    test_role = {
        "name": "测试秘书",
        "avatar": "📋",
        "baseAI": "deepseek",
        "rolePrompt": "你是一位专业、高效的秘书助手。你擅长整理信息、安排日程、处理文档。",
        "description": "测试用的秘书角色"
    }
    
    print(f"创建角色: {test_role['name']}")
    print(f"请求数据: {json.dumps(test_role, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(
            f"{API_URL}/api/custom-ai",
            json=test_role,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"\n状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 创建成功!")
            print(f"响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            role_id = data.get("id")
            if role_id:
                print(f"\n角色ID: {role_id}")
                return role_id
            else:
                print("✗ 警告: 响应中没有角色ID")
                return None
        else:
            print(f"✗ 创建失败!")
            print(f"响应内容: {response.text}")
            try:
                error_data = response.json()
                print(f"错误详情: {json.dumps(error_data, ensure_ascii=False, indent=2)}")
            except:
                pass
            return None
    
    except requests.exceptions.ConnectionError:
        print("✗ 错误: 无法连接到服务器")
        print("  请确保后端服务正在运行: http://localhost:8000")
        return None
    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_get_created_ai(role_id):
    """测试获取刚创建的角色"""
    print("\n" + "=" * 60)
    print("测试3: 验证创建的角色")
    print("=" * 60)
    
    if not role_id:
        print("跳过: 没有角色ID")
        return False
    
    try:
        response = requests.get(f"{API_URL}/api/ais")
        
        if response.status_code == 200:
            data = response.json()
            ais = data.get("ais", [])
            
            # 查找刚创建的角色
            # 注意：角色ID格式是 custom-{base_ai}-{role_id}
            found = False
            for ai in ais:
                if ai.get("id") and role_id in ai.get("id"):
                    found = True
                    print(f"✓ 找到创建的角色:")
                    print(f"  名称: {ai.get('name')}")
                    print(f"  ID: {ai.get('id')}")
                    print(f"  基础AI: {ai.get('baseAI')}")
                    print(f"  描述: {ai.get('description')}")
                    print(f"  角色设定: {ai.get('rolePrompt', '')[:50]}...")
                    return True
            
            if not found:
                print(f"✗ 未找到创建的角色 (ID包含: {role_id})")
                print(f"当前所有AI:")
                for ai in ais:
                    print(f"  - {ai.get('name')} (ID: {ai.get('id')})")
                return False
        else:
            print(f"✗ 获取AI列表失败: {response.status_code}")
            return False
    
    except Exception as e:
        print(f"✗ 错误: {e}")
        return False


def test_add_knowledge(role_id):
    """测试添加知识到角色"""
    print("\n" + "=" * 60)
    print("测试4: 添加知识到角色")
    print("=" * 60)
    
    if not role_id:
        print("跳过: 没有角色ID")
        return False
    
    knowledge = {
        "text": "重要会议需提前24小时通知参会人",
        "metadata": {"category": "日程管理"}
    }
    
    print(f"添加知识: {knowledge['text']}")
    
    try:
        response = requests.post(
            f"{API_URL}/api/custom-ai/{role_id}/knowledge",
            json=knowledge,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 添加成功!")
            print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
            return True
        else:
            print(f"✗ 添加失败: {response.text}")
            return False
    
    except Exception as e:
        print(f"✗ 错误: {e}")
        return False


def test_search_knowledge(role_id):
    """测试搜索知识库"""
    print("\n" + "=" * 60)
    print("测试5: 搜索知识库")
    print("=" * 60)
    
    if not role_id:
        print("跳过: 没有角色ID")
        return False
    
    try:
        response = requests.get(
            f"{API_URL}/api/custom-ai/{role_id}/knowledge",
            params={"query": "会议", "top_k": 5}
        )
        
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ 搜索成功!")
            print(f"查询: {data.get('query')}")
            print(f"结果数量: {len(data.get('results', []))}")
            for i, result in enumerate(data.get('results', []), 1):
                print(f"  {i}. {result}")
            return True
        else:
            print(f"✗ 搜索失败: {response.text}")
            return False
    
    except Exception as e:
        print(f"✗ 错误: {e}")
        return False


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("自定义AI角色创建功能测试")
    print("=" * 60)
    print(f"API地址: {API_URL}")
    print()
    
    # 测试1: 获取AI列表
    if not test_get_ais():
        print("\n✗ 基础测试失败，请检查后端服务")
        return
    
    # 测试2: 创建角色
    role_id = test_create_custom_ai()
    
    # 测试3: 验证创建
    if role_id:
        test_get_created_ai(role_id)
        
        # 测试4: 添加知识
        test_add_knowledge(role_id)
        
        # 测试5: 搜索知识
        test_search_knowledge(role_id)
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()

