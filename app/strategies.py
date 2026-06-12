# app/strategies.py
import pandas as pd
import numpy as np
from typing import Dict, Any

def ma_cross_signals(df: pd.DataFrame, fast: int = 20, slow: int = 60) -> pd.DataFrame:
    """
    均线交叉信号：
    - fast 上穿 slow => signal=1 (做多)
    - fast 下穿 slow => signal=0 (空仓)
    """
    out = df.copy()
    close = out["Close"].astype(float)
    out["ma_fast"] = close.rolling(fast).mean()
    out["ma_slow"] = close.rolling(slow).mean()
    out["signal"] = (out["ma_fast"] > out["ma_slow"]).astype(int)
    out["signal"] = out["signal"].fillna(0)
    return out

def rsi_signals(df: pd.DataFrame, period: int = 14, low: float = 30, high: float = 70) -> pd.DataFrame:
    out = df.copy()
    close = out["Close"].astype(float)
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    out["rsi"] = rsi.fillna(50)

    # 简单规则：rsi<low 做多；rsi>high 空仓
    out["signal"] = 0
    out.loc[out["rsi"] < low, "signal"] = 1
    out.loc[out["rsi"] > high, "signal"] = 0
    out["signal"] = out["signal"].ffill().fillna(0).astype(int)
    return out
