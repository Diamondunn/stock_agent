# app/history_store.py
from __future__ import annotations

import os
import time
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

import pandas as pd

from app.cache import logger
HISTORY_DIR = Path("data/history")
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def history_path(symbol: str):
    return HISTORY_DIR / f"{symbol}.parquet"


def load_local_history(symbol: str):
    path = history_path(symbol)
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception:
            return None
    return None

# 允许的周期 -> 天数
PERIOD_DAYS = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "3y": 1095,
}


def _sleep_jitter(sec: float):
    time.sleep(sec + random.random() * 0.4)


def _normalize_code(symbol: str) -> str:
    """
    输入可能是 000989 / 000989.SZ / 600184.SS
    存储统一用 6位数字 + suffix(SS/SZ)
    """
    s = (symbol or "").strip().upper()
    if "." in s:
        code, suf = s.split(".", 1)
        code = code.zfill(6) if code.isdigit() else code
        suf = "SS" if "SS" in suf else ("SZ" if "SZ" in suf else suf)
        return f"{code}.{suf}"
    # 无后缀
    if s.isdigit():
        s = s.zfill(6)
        suf = "SS" if s.startswith(("6", "9")) else "SZ"
        return f"{s}.{suf}"
    return s


def _hist_path(symbol: str) -> Path:
    sym = _normalize_code(symbol)
    return HISTORY_DIR / f"{sym}.parquet"


def _to_ohlcv(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None

    # yfinance 风格
    if all(c in df.columns for c in ["Open", "High", "Low", "Close", "Volume"]):
        out = df.copy()
        if "Date" in out.columns:
            out["Date"] = pd.to_datetime(out["Date"])
            out = out.set_index("Date")
        if not isinstance(out.index, pd.DatetimeIndex):
            out.index = pd.to_datetime(out.index)
        out = out.sort_index()
        return out[["Open", "High", "Low", "Close", "Volume"]].copy()

    # akshare stock_zh_a_hist 常见中文列
    if "日期" in df.columns and "收盘" in df.columns:
        cn_map = {
            "日期": "Date",
            "开盘": "Open",
            "收盘": "Close",
            "最高": "High",
            "最低": "Low",
            "成交量": "Volume",
        }
        out = df.rename(columns=cn_map).copy()
        out["Date"] = pd.to_datetime(out["Date"])
        out = out.set_index("Date")
        out = out.sort_index()
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            if c not in out.columns:
                out[c] = pd.NA
        return out[["Open", "High", "Low", "Close", "Volume"]].copy()

    return None


def load_history(symbol: str, period: str = "6mo") -> Optional[pd.DataFrame]:
    """
    只读本地历史库（稳定）。
    period 只是裁剪窗口，不触网。
    """
    p = _hist_path(symbol)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        if df is None or df.empty:
            return None
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        days = PERIOD_DAYS.get(period, 180)
        cutoff = datetime.now() - timedelta(days=days)
        return df[df.index >= cutoff].copy()
    except Exception as e:
        logger.warning(f"[history-store] load failed {symbol}: {e}")
        return None


def save_history(symbol: str, df: pd.DataFrame) -> None:
    p = _hist_path(symbol)
    try:
        out = df.copy()
        out = out.reset_index().rename(columns={"index": "Date"})
        out.to_parquet(p, index=False)
        logger.info(f"[history-store] saved {symbol} rows={len(df)}")
    except Exception as e:
        logger.warning(f"[history-store] save failed {symbol}: {e}")


def merge_and_save(symbol: str, new_df: pd.DataFrame) -> None:
    """
    增量合并保存：失败不影响服务。
    """
    new_df = _to_ohlcv(new_df)
    if new_df is None or new_df.empty:
        return

    old = load_history(symbol, period="3y")
    if old is None or old.empty:
        save_history(symbol, new_df)
        return

    merged = pd.concat([old, new_df], axis=0)
    merged = merged[~merged.index.duplicated(keep="last")]
    merged = merged.sort_index()
    save_history(symbol, merged)


# --------------------------
# 离线更新：仅用于“计划任务/手动运行”
# --------------------------
def update_history_from_sources(
    symbol: str,
    period: str = "2y",
    akshare_fetch=None,
    yfinance_fetch=None,
    max_retries: int = 2,
) -> bool:
    """
    外部传入 fetch 函数，避免循环导入。
    成功写入返回 True；失败返回 False（但不会抛异常）。
    """
    sym = _normalize_code(symbol)
    last_err = None

    # 1) akshare 优先（如果你现在也被风控，则会失败，但不会影响服务）
    if akshare_fetch is not None:
        for i in range(max_retries):
            try:
                df = akshare_fetch(sym, period=period)
                if df is not None and not df.empty:
                    merge_and_save(sym, df)
                    return True
            except Exception as e:
                last_err = e
                _sleep_jitter(0.8 * (2**i))

    # 2) yfinance fallback（你现在被 429，就别指望它）
    if yfinance_fetch is not None:
        for i in range(max_retries):
            try:
                df = yfinance_fetch(sym, period=period)
                if df is not None and not df.empty:
                    merge_and_save(sym, df)
                    return True
            except Exception as e:
                last_err = e
                _sleep_jitter(1.2 * (2**i))

    logger.warning(f"[history-store] update failed {sym}: {last_err}")
    return False
