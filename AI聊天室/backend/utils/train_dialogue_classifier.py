"""
对话分类模型训练脚本
"""
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.models.dialogue_classifier import DialogueClassifier, DialogueCategory


def create_sample_training_data():
    """创建示例训练数据"""
    training_data = [
        # 问候类
        {"text": "你好", "label": DialogueCategory.GREETING},
        {"text": "您好", "label": DialogueCategory.GREETING},
        {"text": "早上好", "label": DialogueCategory.GREETING},
        {"text": "下午好", "label": DialogueCategory.GREETING},
        {"text": "晚上好", "label": DialogueCategory.GREETING},
        {"text": "hi", "label": DialogueCategory.GREETING},
        {"text": "hello", "label": DialogueCategory.GREETING},
        {"text": "哈喽", "label": DialogueCategory.GREETING},
        {"text": "你好啊", "label": DialogueCategory.GREETING},
        {"text": "在吗", "label": DialogueCategory.GREETING},
        
        # 问题类
        {"text": "这是什么", "label": DialogueCategory.QUESTION},
        {"text": "怎么用", "label": DialogueCategory.QUESTION},
        {"text": "为什么", "label": DialogueCategory.QUESTION},
        {"text": "如何操作", "label": DialogueCategory.QUESTION},
        {"text": "在哪里", "label": DialogueCategory.QUESTION},
        {"text": "哪个更好", "label": DialogueCategory.QUESTION},
        {"text": "可以吗", "label": DialogueCategory.QUESTION},
        {"text": "行不行", "label": DialogueCategory.QUESTION},
        {"text": "什么时候", "label": DialogueCategory.QUESTION},
        {"text": "多少钱", "label": DialogueCategory.QUESTION},
        {"text": "什么是人工智能", "label": DialogueCategory.QUESTION},
        {"text": "怎么安装", "label": DialogueCategory.QUESTION},
        
        # 命令类
        {"text": "帮我保存", "label": DialogueCategory.COMMAND},
        {"text": "请执行", "label": DialogueCategory.COMMAND},
        {"text": "开始运行", "label": DialogueCategory.COMMAND},
        {"text": "停止程序", "label": DialogueCategory.COMMAND},
        {"text": "删除文件", "label": DialogueCategory.COMMAND},
        {"text": "创建文件夹", "label": DialogueCategory.COMMAND},
        {"text": "打开文件", "label": DialogueCategory.COMMAND},
        {"text": "关闭窗口", "label": DialogueCategory.COMMAND},
        {"text": "重启服务", "label": DialogueCategory.COMMAND},
        {"text": "导出数据", "label": DialogueCategory.COMMAND},
        
        # 请求类
        {"text": "可以帮我吗", "label": DialogueCategory.REQUEST},
        {"text": "能否处理", "label": DialogueCategory.REQUEST},
        {"text": "麻烦你", "label": DialogueCategory.REQUEST},
        {"text": "请求帮助", "label": DialogueCategory.REQUEST},
        {"text": "能帮我一下吗", "label": DialogueCategory.REQUEST},
        {"text": "可以吗", "label": DialogueCategory.REQUEST},
        {"text": "能不能", "label": DialogueCategory.REQUEST},
        
        # 感谢类
        {"text": "谢谢", "label": DialogueCategory.THANKS},
        {"text": "感谢", "label": DialogueCategory.THANKS},
        {"text": "多谢", "label": DialogueCategory.THANKS},
        {"text": "非常感谢", "label": DialogueCategory.THANKS},
        {"text": "谢谢你的帮助", "label": DialogueCategory.THANKS},
        {"text": "thx", "label": DialogueCategory.THANKS},
        {"text": "thanks", "label": DialogueCategory.THANKS},
        
        # 抱怨类
        {"text": "不好用", "label": DialogueCategory.COMPLAINT},
        {"text": "出错了", "label": DialogueCategory.COMPLAINT},
        {"text": "失败了", "label": DialogueCategory.COMPLAINT},
        {"text": "有问题", "label": DialogueCategory.COMPLAINT},
        {"text": "有bug", "label": DialogueCategory.COMPLAINT},
        {"text": "不行", "label": DialogueCategory.COMPLAINT},
        {"text": "错误", "label": DialogueCategory.COMPLAINT},
        
        # 闲聊类
        {"text": "哈哈", "label": DialogueCategory.CHAT},
        {"text": "呵呵", "label": DialogueCategory.CHAT},
        {"text": "嗯", "label": DialogueCategory.CHAT},
        {"text": "哦", "label": DialogueCategory.CHAT},
        {"text": "好的", "label": DialogueCategory.CHAT},
        {"text": "ok", "label": DialogueCategory.CHAT},
        {"text": "okay", "label": DialogueCategory.CHAT},
        {"text": "知道了", "label": DialogueCategory.CHAT},
        {"text": "明白了", "label": DialogueCategory.CHAT},
    ]
    
    return training_data


def load_training_data(data_file: str = None):
    """加载训练数据"""
    if data_file and Path(data_file).exists():
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    else:
        print("使用示例训练数据...")
        return create_sample_training_data()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="训练对话分类模型")
    parser.add_argument("--data", type=str, help="训练数据文件路径（JSON格式）")
    parser.add_argument("--model", type=str, default="bert-base-chinese", 
                       help="预训练模型名称（默认: bert-base-chinese）")
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数（默认: 3）")
    parser.add_argument("--batch-size", type=int, default=16, help="批次大小（默认: 16）")
    parser.add_argument("--lr", type=float, default=2e-5, help="学习率（默认: 2e-5）")
    parser.add_argument("--output", type=str, default="./models/dialogue_classifier",
                       help="模型保存路径（默认: ./models/dialogue_classifier）")
    
    args = parser.parse_args()
    
    # 加载训练数据
    training_data = load_training_data(args.data)
    print(f"加载了 {len(training_data)} 条训练数据")
    
    # 创建分类器
    classifier = DialogueClassifier(model_path=args.output)
    
    # 训练模型
    try:
        classifier.train(
            training_data=training_data,
            model_name=args.model,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.lr
        )
        print("\n训练完成！")
        print(f"模型已保存到: {args.output}")
        
        # 测试预测
        print("\n测试预测:")
        test_texts = ["你好", "这是什么", "帮我保存", "谢谢", "哈哈"]
        for text in test_texts:
            result = classifier.predict(text)
            print(f"  '{text}' -> {result['label']} (置信度: {result['confidence']:.2f})")
            
    except ImportError as e:
        print(f"\n错误: {e}")
        print("\n请先安装依赖:")
        print("  pip install transformers torch")
    except Exception as e:
        print(f"\n训练失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
