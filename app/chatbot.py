import re

from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage

from .portfolio_store import get_holdings

from .graph import build_graph


class StockChatBot:
    def __init__(self):
        memory = MemorySaver()
        self.graph = build_graph(checkpointer=memory)

        self.config = {
            "configurable": {"thread_id": "default_user"}
        }

    def ask(self, message: str) -> str:
        result = self.graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=self.config,
        )
        reply = result["messages"][-1].content
        return _append_holding_hint(message, reply)


def _extract_codes(text: str) -> set[str]:
    codes = set()
    for m in re.findall(r"\b\d{6}\b", text):
        codes.add(m)
    for m in re.findall(r"\b(\d{6})\.(?:SS|SZ|ss|sz)\b", text):
        codes.add(m)
    return codes


def _append_holding_hint(message: str, reply: str) -> str:
    codes = _extract_codes(message)
    if not codes:
        return reply

    holdings = get_holdings() or []
    if not holdings:
        return reply

    matched = []
    for h in holdings:
        raw_symbol = str(h.get("symbol", "")).strip()
        code = raw_symbol.split(".")[0]
        if code in codes:
            matched.append(h)

    if not matched:
        return reply

    lines = ["", "与你当前持仓相关的建议："]
    for h in matched:
        raw_symbol = str(h.get("symbol", "")).strip()
        code = raw_symbol.split(".")[0]
        shares = h.get("shares", 0)
        avg_cost = float(h.get("avg_cost", 0))
        lines.append(f"- {code}：持仓 {shares} 股，均价 {avg_cost:.4f}。可关注成本线与风控。")

    return reply + "\n" + "\n".join(lines)
