# app/indicators.py
from typing import Any, Dict
import numpy as np
import pandas as pd


def calculate_technical_indicators(data: pd.DataFrame) -> Dict[str, Any]:
    """计算常用技术指标（MA/RSI/MACD/布林带）"""
    if data is None or data.empty or len(data) < 20:
        return {}

    close = data["Close"].astype(float)

    ma_20 = close.rolling(20).mean().iloc[-1]
    ma_50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else np.nan
    ma_200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else np.nan

    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs)).iloc[-1] if rs.iloc[-1] not in [0, np.nan] else 50

    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = (bb_mid + 2 * bb_std).iloc[-1]
    bb_lower = (bb_mid - 2 * bb_std).iloc[-1]

    return {
        "ma_20": float(ma_20),
        "ma_50": None if np.isnan(ma_50) else float(ma_50),
        "ma_200": None if np.isnan(ma_200) else float(ma_200),
        "rsi": float(rsi) if not np.isnan(rsi) else 50.0,
        "macd": float(macd.iloc[-1]) if not macd.empty else None,
        "signal": float(signal.iloc[-1]) if not signal.empty else None,
        "bb_upper": float(bb_upper) if not np.isnan(bb_upper) else None,
        "bb_lower": float(bb_lower) if not np.isnan(bb_lower) else None,
    }
