# app/main.py
import time

from app.data_sources import get_a_stock_list
from app.chatbot import StockChatBot


def main():
    print("=" * 80)
    print("🤖 A股分析AI助手（工程版：落盘缓存 + 多源行情 + 重试降频 + 批量建议）")
    print("=" * 80)

    print("\n正在初始化A股数据（优先读磁盘缓存，过期才拉实时）...")
    try:
        df = get_a_stock_list()
        if df is None or df.empty:
            print("⚠️ 初始化失败：未获取到列表（但程序可继续）。\n")
        else:
            print(f"✅ 初始化成功：{len(df)} 条\n")
    except Exception as e:
        print(f"⚠️ 初始化遇到问题：{e}\n")

    bot = StockChatBot()

    print("输入 'quit' 退出；示例：")
    print("  - 给出603210，600184，002902，600416和600081的投资建议")
    print("  - 分析 600519.SS")
    print("  - 比较 600519.SS 和 000858.SZ")
    print("  - 画K线 300750.SZ")

    while True:
        try:
            q = input("\n👤 你: ").strip()
            if not q:
                continue
            if q.lower() in ["quit", "exit", "bye", "退出"]:
                print("👋 再见！股市有风险，入市需谨慎。")
                break

            ans, cost = bot.chat_with_timing(q)
            print(f"\n🤖 AI助手 (响应 {cost:.1f}s):\n" + "-" * 60)
            print(ans)
            print("-" * 60)

        except KeyboardInterrupt:
            print("\n\n已退出。")
            break
        except Exception as e:
            print(f"\n❌ 发生错误: {e}")


if __name__ == "__main__":
    main()
