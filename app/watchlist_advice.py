# app/watchlist_advice.py

import os
import requests
from datetime import datetime
from typing import List, Dict, Any

from dotenv import load_dotenv

from app.history_store import load_local_history
from app.market_data import get_market_snapshot_cached, norm_code
from app.portfolio_store import get_holdings

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


# -----------------------------
# DeepSeek 调用
# -----------------------------
def _call_deepseek(prompt: str) -> str:

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": "你是一名专业A股交易员，请给出结构化的每日投资建议。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.4
    }

    response = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=60)

    if response.status_code != 200:
        return f"DeepSeek API 调用失败: {response.text}"

    data = response.json()
    return data["choices"][0]["message"]["content"]


# -----------------------------
# 稳定版分析（实时+本地）
# -----------------------------
def build_daily_watchlist_advice(symbols: List[str]) -> Dict[str, Any]:

    if not symbols:
        return {
            "ok": True,
            "asof": datetime.now().isoformat(),
            "analysis": "关注列表为空"
        }

    holdings = {h["symbol"]: h for h in get_holdings()}

    # 🔥 实时行情一次性拉
    snapshot = get_market_snapshot_cached()

    price_map = {}
    change_map = {}

    if snapshot is not None and not snapshot.empty:
        for _, r in snapshot.iterrows():
            code = norm_code(r["code"])
            price_map[code] = r.get("price")
            change_map[code] = r.get("change_pct")

    analysis_blocks = []

    for raw in symbols:

        sym = raw.strip().upper()
        code = norm_code(sym)

        # -------- 实时行情 --------
        latest_price = price_map.get(code)
        change_pct = change_map.get(code)

        # -------- 本地历史 --------
        hist = load_local_history(sym)

        if hist is None or hist.empty:
            analysis_blocks.append(
                f"""
股票: {sym}
最新价: {latest_price}
涨跌幅: {change_pct}
历史数据缺失（未 warmup）
"""
            )
            continue

        ma20 = float(hist["Close"].rolling(20).mean().iloc[-1])
        ma60 = float(hist["Close"].rolling(60).mean().iloc[-1])
        high_3m = float(hist["High"].tail(60).max())
        low_3m = float(hist["Low"].tail(60).min())

        holding_info = holdings.get(sym)

        holding_text = ""
        if holding_info:
            holding_text = f"""
你当前持仓:
股数: {holding_info['shares']}
成本价: {holding_info['avg_cost']}
"""

        analysis_blocks.append(
            f"""
股票: {sym}
最新价: {latest_price}
涨跌幅: {change_pct}
3个月最高: {high_3m}
3个月最低: {low_3m}
MA20: {ma20}
MA60: {ma60}
{holding_text}
"""
        )

    # -----------------------------
    # 拼接 Prompt
    # -----------------------------
    full_prompt = f"""
请对以下股票分别分析，并按股票分段输出：

每只股票请给出：
1. 趋势判断
2. 技术面强弱
3. 是否适合加仓/减仓/观望
4. 若已持仓，给止盈止损建议
5. 风险提示

数据如下：
{''.join(analysis_blocks)}
"""

    llm_result = _call_deepseek(full_prompt)

    return {
        "ok": True,
        "asof": datetime.now().isoformat(),
        "analysis": llm_result
    }
