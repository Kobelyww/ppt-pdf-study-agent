import asyncio
from pathlib import Path
from src.config import load_config
from src.services.rag_service import RAGService


async def main():
    """主函数"""
    print("PPT/PDF转复习提纲和考试例题智能系统")
    print("=" * 50)

    # 加载配置
    config = load_config()
    print(f"LLM模型: {config.llm.primary_model}")

    # 初始化当前CLI可直接使用的轻量组件
    rag_service = RAGService()
    parsed_document = None

    help_text = "\n".join(
        [
            "可用命令:",
            "  /parse <file_path> - 解析文档",
            "  /ask <question> - 提问",
            "  /outline - 生成复习提纲",
            "  /questions - 生成考试例题",
            "  /help - 查看可用命令",
            "  /quit - 退出",
        ]
    )

    print("系统初始化完成")
    print(help_text)

    # 简单的命令行循环
    while True:
        try:
            user_input = input("\n> ").strip()

            if not user_input:
                continue

            if user_input == "/quit":
                print("再见！")
                break

            elif user_input == "/help":
                print(help_text)

            elif user_input == "/parse" or user_input.startswith("/parse "):
                file_path = user_input[6:].strip()
                if not file_path:
                    print("错误: 请提供文件路径，例如 /parse ./lecture.pdf")
                    continue

                path = Path(file_path).expanduser()
                if not path.exists():
                    print(f"错误: 文件不存在: {file_path}")
                    continue

                parsed_document = {"path": str(path), "name": path.name}
                print(f"已找到文件: {path}")
                print("文档解析已准备就绪；当前环境将跳过外部模型调用。")

            elif user_input.startswith("/ask "):
                question = user_input[5:].strip()
                if not question:
                    print("错误: 请提供问题")
                    continue

                response = await rag_service.query(question)
                if response.sources:
                    print(response.answer)
                    print(f"来源: {', '.join(response.sources)}")
                else:
                    print("当前没有可用知识点，请先解析文档")

            elif user_input == "/outline":
                if parsed_document is None:
                    print("错误: 请先解析文档")
                    continue

                print(f"复习提纲需要已抽取知识点后生成，当前文档: {parsed_document['name']}")

            elif user_input == "/questions":
                if parsed_document is None:
                    print("错误: 请先解析文档")
                    continue

                print(f"当前没有可用知识点，无法生成考试例题，当前文档: {parsed_document['name']}")

            else:
                print(f"未知命令: {user_input}")
                print("输入 /help 查看可用命令")

        except KeyboardInterrupt:
            print("\n再见！")
            break
        except EOFError:
            print("\n输入结束，退出。")
            break
        except Exception as e:
            print(f"错误: {str(e)}")


if __name__ == "__main__":
    asyncio.run(main())
