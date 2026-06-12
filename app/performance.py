# app/performance.py
import numpy as np
import pandas as pd
from typing import Dict, Any

def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())

def sharpe_ratio(daily_returns: pd.Series, risk_free: float = 0.015) -> float:
    # 简化：年化无风险利率 -> 日
    rf_daily = (1 + risk_free) ** (1/252) - 1
    excess = daily_returns - rf_daily
    if excess.std() == 0 or np.isnan(excess.std()):
        return 0.0
    return float((excess.mean() / excess.std()) * np.sqrt(252))

def win_rate(trade_pnls: list[float]) -> float:
    if not trade_pnls:
        return 0.0
    wins = sum(1 for x in trade_pnls if x > 0)
    return float(wins / len(trade_pnls))

def summarize(backtest_df: pd.DataFrame, trade_pnls: list[float], risk_free: float = 0.015) -> Dict[str, Any]:
    equity = backtest_df["equity"]
    rets = backtest_df["strategy_ret"].fillna(0)

    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    mdd = max_drawdown(equity)
    sr = sharpe_ratio(rets, risk_free=risk_free)

    return {
        "total_return": total_return,
        "max_drawdown": mdd,
        "sharpe": sr,
        "trades": len(trade_pnls),
        "win_rate": win_rate(trade_pnls),
    }
