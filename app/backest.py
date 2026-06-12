# app/backtest.py
import pandas as pd
from typing import Callable, Dict, Any, Tuple, List
from .performance import summarize

def run_backtest(
    df: pd.DataFrame,
    signal_fn: Callable[[pd.DataFrame], pd.DataFrame],
    fee_rate: float = 0.0003,
    risk_free: float = 0.015
) -> Dict[str, Any]:
    """
    最小可用回测：
    - signal: 1 持有，0 空仓
    - 按每日收盘收益计算
    - 换仓时扣手续费（按fee_rate）
    """
    data = df.copy()
    data = signal_fn(data)
    if "signal" not in data.columns:
        raise ValueError("signal_fn must produce column 'signal'")

    data["ret"] = data["Close"].astype(float).pct_change().fillna(0)
    data["pos"] = data["signal"].shift(1).fillna(0)  # 次日开仓视角（简化）
    data["pos_change"] = (data["pos"] - data["pos"].shift(1).fillna(0)).abs()

    # 策略收益：持仓收益 - 手续费
    data["strategy_ret"] = data["pos"] * data["ret"] - data["pos_change"] * fee_rate
    data["equity"] = (1 + data["strategy_ret"]).cumprod()

    # 交易统计（简化：每次 pos 从0->1 记为买入，1->0 为卖出）
    trades = []
    entry_equity = None
    in_pos = False
    for i in range(len(data)):
        pc = data["pos_change"].iloc[i]
        p = data["pos"].iloc[i]
        eq = data["equity"].iloc[i]
        if not in_pos and p == 1:
            in_pos = True
            entry_equity = eq
        elif in_pos and p == 0 and entry_equity is not None:
            in_pos = False
            trades.append(eq / entry_equity - 1)

    stats = summarize(data, trades, risk_free=risk_free)
    return {"curve": data, "stats": stats}
