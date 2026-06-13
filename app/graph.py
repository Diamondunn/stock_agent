# app/graph.py

import os
from pathlib import Path
from dotenv import load_dotenv

from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from .config import config
from .tools import toolbox
from .prompts import ASSISTANT_SYSTEM_PROMPT
from .portfolio_store import get_holdings, list_notes


# ===============================
# 加载 .env
# ===============================
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH, override=True)


# ===============================
# 动态长期记忆
# ===============================
def _portfolio_context_text() -> str:
    parts = []

    holdings = get_holdings()
    if holdings:
        parts.append("【用户当前持仓】")
        for h in holdings:
            parts.append(
                f"- {h['symbol']}: {h['shares']} 股, 均价 {float(h['avg_cost']):.4f}"
            )

    plans = list_notes("PLAN", limit=20)
    if plans:
        parts.append("【用户投资计划】")
        for p in plans:
            parts.append(f"- {p['content']}")

    return "\n".join(parts).strip()


# ===============================
# 构建 真·ReAct Agent
# ===============================
def build_graph(checkpointer=None):

    if not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError(
            "未检测到 DEEPSEEK_API_KEY。\n"
            "请在 .env 中设置 DEEPSEEK_API_KEY。"
        )

    model = init_chat_model(
        config.MODEL_NAME,
        model_provider=config.MODEL_PROVIDER,
        temperature=config.MODEL_TEMPERATURE,
    )

    # 动态长期记忆拼进系统提示
    memory_context = _portfolio_context_text()
    if memory_context:
        full_prompt = (
            ASSISTANT_SYSTEM_PROMPT
            + "\n\n"
            + memory_context
            + "\n\n请结合上述持仓与计划进行分析。"
        )
    else:
        full_prompt = ASSISTANT_SYSTEM_PROMPT

    # 使用官方 ReAct Agent（自动工具闭环）
    graph = create_react_agent(
        model=model,
        tools=toolbox,
        prompt=full_prompt,
        checkpointer=checkpointer or MemorySaver(),
    )

    return graph
