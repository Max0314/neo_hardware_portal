"""
快速测试对话分类器
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from backend.models.dialogue_classifier import DialogueClassifier, SimpleDialogueClassifier

def test_classifier():
    """测试分类器"""
    print("=" * 50)
    print("对话分类器测试")
    print("=" * 50)
    
    # 测试文本
    test_texts = [
        "你好",
        "早上好",
        "这是什么",
        "怎么用",
        "帮我保存文件",
        "请执行这个命令",
        "可以帮我吗",
        "能否处理一下",
        "谢谢",
        "非常感谢",
        "出错了",
        "有问题",
        "哈哈",
        "好的",
        "ok"
    ]
    
    # 尝试加载训练好的模型
    print("\n1. 尝试加载训练好的模型...")
    classifier = DialogueClassifier(model_path="./models/dialogue_classifier")
    
    if classifier.model is None:
        print("   模型未找到，使用简单规则分类器")
        classifier = SimpleDialogueClassifier()
    else:
        print("   模型加载成功！")
    
    # 测试预测
    print("\n2. 测试预测结果：")
    print("-" * 50)
    
    for text in test_texts:
        result = classifier.predict(text)
        label = result["label"]
        confidence = result["confidence"]
        
        # 格式化输出
        label_name = {
            "greeting": "问候",
            "question": "问题",
            "command": "命令",
            "request": "请求",
            "thanks": "感谢",
            "complaint": "抱怨",
            "chat": "闲聊",
            "unknown": "未知"
        }.get(label, label)
        
        print(f"  '{text:15s}' -> {label_name:6s} (置信度: {confidence:.2f})")
    
    # 批量测试
    print("\n3. 批量预测测试：")
    print("-" * 50)
    if hasattr(classifier, 'predict_batch'):
        results = classifier.predict_batch(test_texts[:5])
        for text, result in zip(test_texts[:5], results):
            print(f"  '{text}' -> {result['label']}")
    
    print("\n" + "=" * 50)
    print("测试完成！")
    print("\n提示：")
    print("  - 如果模型未训练，系统会使用简单规则分类器")
    print("  - 要训练模型，请运行：python backend/utils/train_dialogue_classifier.py")
    print("=" * 50)

if __name__ == "__main__":
    test_classifier()
