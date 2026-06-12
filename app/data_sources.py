# app/data_sources.py
from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List
from app.history_store import load_history
import pandas as pd
import numpy as np
import akshare as ak
import yfinance as yf

from app.cache import (
    cache,
    config,
    logger,
    get_dynamic_ttl_hours,
    load_disk_cache,
    save_disk_cache,
    load_expired_disk_cache_if_any,
)

# =============================================================================
# 0) 路径：历史强缓存（稳定模式）
# =============================================================================
HIST_DIR = Path(config.DISK_CACHE_DIR) / "history"
HIST_DIR.mkdir(parents=True, exist_ok=True)

HIST_TTL_HOURS_DEFAULT = 24          # ✅ 稳定模式：历史缓存 24h（一天最多拉一次）
HIST_FAIL_COOLDOWN_MINUTES = 10      # ✅ 拉失败后冷却 10 分钟，避免雪崩重试

# =============================================================================
# 1) 基础：降频 / 重试（现货列表用）
# =============================================================================
def _rate_limit():
    time.sleep(config.RATE_LIMIT_SEC + random.random() * 0.2)


def _sleep_backoff(i: int):
    t = config.RETRY_BASE_SLEEP * (2 ** i) + random.random() * 0.35
    time.sleep(t)


def _is_remote_disconnected(err: Exception) -> bool:
    s = str(err)
    return ("RemoteDisconnected" in s) or ("Remote end closed connection" in s)


def retry(func, name="source", tries: Optional[int] = None):
    tries = tries or config.RETRY_TRIES
    last = None
    for i in range(tries):
        try:
            return func()
        except Exception as e:
            last = e
            # 快速降级（遇到 RemoteDisconnected 不再重试）
            if _is_remote_disconnected(e):
                logger.warning(f"[{name}] 触发快速降级（RemoteDisconnected），不再重试: {e}")
                break
            logger.warning(f"[{name}] 失败({i+1}/{tries}): {e}")
            _sleep_backoff(i)
    raise last


def _call_akshare(func_name: str, **kwargs) -> pd.DataFrame:
    if not hasattr(ak, func_name):
        raise AttributeError(f"akshare 没有接口: {func_name}")
    fn = getattr(ak, func_name)
    _rate_limit()
    return fn(**kwargs)

# =============================================================================
# 2) yfinance 全局节流（避免429）
# =============================================================================
_yf_lock = threading.Lock()
_yf_last_call = 0.0


def yf_throttle(min_interval: Optional[float] = None):
    """全局节流：避免 yfinance 429。"""
    global _yf_last_call
    min_interval = min_interval or config.YF_MIN_INTERVAL_SEC
    with _yf_lock:
        now = time.time()
        wait = _yf_last_call + min_interval - now
        if wait > 0:
            time.sleep(wait + random.random() * 0.4)
        _yf_last_call = time.time()

# =============================================================================
# 3) A股列表（多源 + 落盘缓存）
# =============================================================================
def _normalize_a_list(df: pd.DataFrame) -> pd.DataFrame:
    """统一股票列表列：代码, 名称, 最新价, 涨跌幅, 成交量, 成交额"""
    if df is None or df.empty:
        return df
    needed = ["代码", "名称", "最新价", "涨跌幅", "成交量", "成交额"]
    for c in needed:
        if c not in df.columns:
            df[c] = pd.NA
    return df[needed].copy()


def _has_price_data(df: Optional[pd.DataFrame]) -> bool:
    if df is None or df.empty:
        return False
    price_col = None
    if "最新价" in df.columns:
        price_col = "最新价"
    elif "price" in df.columns:
        price_col = "price"
    if not price_col:
        return False
    series = df[price_col]
    if series is None:
        return False
    return series.notna().any()


def _source_em_spot() -> pd.DataFrame:
    """主源：东方财富全市场实时行情（可能被风控）"""
    df = retry(lambda: _call_akshare("stock_zh_a_spot_em"), name="em_spot", tries=3)
    return _normalize_a_list(df)


def _source_alt_spot() -> pd.DataFrame:
    """备用：其他 spot（不同版本可能存在不同函数名）"""
    candidates = [
        "stock_zh_a_spot",
        "stock_zh_a_spot_hs",
        "stock_zh_a_spot_em",
    ]
    last_err = None
    for fn_name in candidates:
        if not hasattr(ak, fn_name):
            continue
        try:
            df = retry(lambda: _call_akshare(fn_name), name=f"alt_{fn_name}", tries=2)
            df = _normalize_a_list(df)
            if df is not None and not df.empty:
                logger.info(f"[alt-spot] 使用接口: {fn_name} rows={len(df)}")
                return df
        except Exception as e:
            last_err = e
            logger.warning(f"[alt-spot] {fn_name} 不可用: {e}")
    raise RuntimeError(f"备用实时源均不可用: {last_err}")


def _source_code_table() -> pd.DataFrame:
    """终极兜底：代码表（最稳，保证 lookup 不挂）"""
    df = retry(lambda: _call_akshare("stock_info_a_code_name"), name="code_name", tries=3)
    if df is None or df.empty:
        raise RuntimeError("stock_info_a_code_name 返回空")
    df = df.rename(columns={"code": "代码", "name": "名称"})[["代码", "名称"]].copy()
    return _normalize_a_list(df)


SOURCES_A_LIST: List[Tuple[str, callable]] = [
    ("em_spot", _source_em_spot),
    ("alt_spot", _source_alt_spot),
    ("code_table", _source_code_table),
]


def get_a_stock_list(force_refresh: bool = False, allow_remote: bool = True) -> Optional[pd.DataFrame]:
    """
    获取A股股票列表（优先磁盘缓存；过期才拉；主源失败快速降级；最终保证可用）。
    """
    cache_key = "a_stock_list"
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    ttl = get_dynamic_ttl_hours()

    # 1) 先读磁盘缓存
    if not force_refresh:
        if allow_remote:
            disk = load_disk_cache(ttl_hours=ttl)
            if disk is not None and not disk.empty:
                cache.set(cache_key, disk)
                return disk
        else:
            disk_any = load_expired_disk_cache_if_any()
            if disk_any is not None and not disk_any.empty:
                cache.set(cache_key, disk_any)
                return disk_any
            return None

    # 2) 多源拉取
    if not allow_remote:
        expired = load_expired_disk_cache_if_any()
        if expired is not None and not expired.empty:
            cache.set(cache_key, expired)
            return expired
        return None
    last_err = None
    for name, fn in SOURCES_A_LIST:
        try:
            df = fn()
            if df is not None and not df.empty:
                if _has_price_data(df):
                    save_disk_cache(df)
                    cache.set(cache_key, df)
                    logger.info(f"[a_list] 使用源: {name} rows={len(df)}")
                    return df

                # No price data (code table fallback). Try stale snapshot first.
                stale = load_expired_disk_cache_if_any()
                if _has_price_data(stale):
                    cache.set(cache_key, stale)
                    logger.info(f"[a_list] 源 {name} 无价格，使用过期快照 rows={len(stale)}")
                    return stale

                cache.set(cache_key, df)
                logger.info(f"[a_list] 使用源: {name} (无价格) rows={len(df)}")
                return df
        except Exception as e:
            last_err = e
            logger.warning(f"[a_list] 源 {name} 失败，切换：{e}")

    # 3) 全失败：返回过期缓存兜底
    expired = load_expired_disk_cache_if_any()
    if expired is not None and not expired.empty:
        cache.set(cache_key, expired)
        return expired

    logger.warning(f"[a_list] 最终失败: {last_err}")
    return None

# =============================================================================
# 4) 历史数据（稳定模式：只用 yfinance + 强磁盘缓存 + 失败冷却）
# =============================================================================
def _hist_cache_path(symbol: str, period: str) -> Path:
    safe_sym = symbol.replace("/", "_").replace("\\", "_").replace(":", "_")
    return HIST_DIR / f"{safe_sym}_{period}.parquet"


def _hist_fail_flag_path(symbol: str, period: str) -> Path:
    safe_sym = symbol.replace("/", "_").replace("\\", "_").replace(":", "_")
    return HIST_DIR / f"fail_{safe_sym}_{period}.flag"


def _read_hist_disk(symbol: str, period: str, ttl_hours: int) -> Optional[pd.DataFrame]:
    path = _hist_cache_path(symbol, period)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if df is None or df.empty:
            return None
        # 约定：文件里带 asof 列
        if "asof" in df.columns:
            asof = pd.to_datetime(df["asof"].iloc[0]).to_pydatetime()
            if datetime.now() - asof <= timedelta(hours=ttl_hours):
                logger.info(f"[hist-disk] 命中缓存 {symbol} {period}")
                return df.drop(columns=["asof"], errors="ignore")
        return None
    except Exception as e:
        logger.warning(f"[hist-disk] 读取失败 {symbol} {period}: {e}")
        return None


def _read_hist_disk_any(symbol: str, period: str) -> Optional[pd.DataFrame]:
    """读取不管是否过期的历史（兜底用）"""
    path = _hist_cache_path(symbol, period)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path).drop(columns=["asof"], errors="ignore")
        if df is None or df.empty:
            return None
        logger.warning(f"[hist-disk] 返回过期缓存 {symbol} {period}")
        return df
    except Exception:
        return None


def _write_hist_disk(symbol: str, period: str, df: pd.DataFrame):
    path = _hist_cache_path(symbol, period)
    try:
        out = df.copy()
        out["asof"] = datetime.now()
        out.to_parquet(path, index=True)
        logger.info(f"[hist-disk] 已写入 {symbol} {period} rows={len(df)}")
    except Exception as e:
        logger.warning(f"[hist-disk] 写入失败 {symbol} {period}: {e}")


def _is_fail_cooldown(symbol: str, period: str) -> bool:
    flag = _hist_fail_flag_path(symbol, period)
    if not flag.exists():
        return False
    try:
        last = datetime.fromtimestamp(flag.stat().st_mtime)
        return (datetime.now() - last) < timedelta(minutes=HIST_FAIL_COOLDOWN_MINUTES)
    except Exception:
        return False


def _touch_fail_flag(symbol: str, period: str):
    flag = _hist_fail_flag_path(symbol, period)
    try:
        flag.touch()
    except Exception:
        pass


def _to_ohlcv(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    将不同来源的DataFrame尽量转换为 OHLCV（Open/High/Low/Close/Volume），索引为DatetimeIndex。
    这里主要服务 yfinance，但也做一些健壮性处理。
    """
    if df is None or df.empty:
        return None

    # yfinance 标准
    cols = set(df.columns)
    need = {"Open", "High", "Low", "Close", "Volume"}
    if need.issubset(cols):
        out = df.copy()
        # yfinance index 通常就是 DatetimeIndex
        if not isinstance(out.index, pd.DatetimeIndex):
            if "Date" in out.columns:
                out["Date"] = pd.to_datetime(out["Date"])
                out = out.set_index("Date")
            else:
                out.index = pd.to_datetime(out.index)
        out = out.sort_index()
        return out[["Open", "High", "Low", "Close", "Volume"]].copy()

    # 兼容：有些源列名小写
    lower = {c.lower(): c for c in df.columns}
    if {"open", "high", "low", "close", "volume"}.issubset(set(lower.keys())):
        out = df.rename(columns={
            lower["open"]: "Open",
            lower["high"]: "High",
            lower["low"]: "Low",
            lower["close"]: "Close",
            lower["volume"]: "Volume",
        }).copy()
        if not isinstance(out.index, pd.DatetimeIndex):
            out.index = pd.to_datetime(out.index)
        out = out.sort_index()
        return out[["Open", "High", "Low", "Close", "Volume"]].copy()

    return None


def _yf_history_with_backoff(symbol: str, period: str, max_tries: int = 3) -> Optional[pd.DataFrame]:
    """
    yfinance 历史拉取：遇到 429 时指数退避重试（稳定模式下重试次数有限）
    """
    last_err = None
    for i in range(max_tries):
        try:
            yf_throttle()
            hist = yf.Ticker(symbol).history(period=period, auto_adjust=False)
            df = _to_ohlcv(hist)
            if df is not None and not df.empty:
                return df
            last_err = RuntimeError("yfinance 返回空")
        except Exception as e:
            last_err = e
            msg = str(e)
            # 429 / rate limit：指数退避
            if ("Too Many Requests" in msg) or ("Rate limited" in msg) or ("429" in msg):
                sleep_s = min(5 * (2 ** i) + random.random() * 1.2, 30)
                logger.warning(f"[hist] yfinance 429，退避 {sleep_s:.1f}s: {e}")
                time.sleep(sleep_s)
                continue
            else:
                logger.warning(f"[hist] yfinance 获取失败 {symbol}: {e}")
                break

    logger.warning(f"[hist] yfinance 最终失败 {symbol}: {last_err}")
    return None

def get_stock_history(symbol: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    """
    ✅ 稳定模式历史数据读取函数（永不触网）

    特点：
    - 只读取本地离线历史库（parquet）
    - 不调用 akshare
    - 不调用 yfinance
    - 不会触发 429
    - 不会触发 RemoteDisconnected
    - 即使网络断开也能正常运行

    参数：
        symbol: 000989 / 000989.SZ / 600184.SS
        period: 1mo / 3mo / 6mo / 1y / 2y / 3y

    返回：
        DataFrame(Open/High/Low/Close/Volume)
        或 None（如果本地没有历史）
    """

    try:
        df = load_history(symbol, period=period)

        if df is None or df.empty:
            logger.warning(f"[history] 本地历史不存在: {symbol} ({period})")
            return None

        return df

    except Exception as e:
        logger.warning(f"[history] 读取失败 {symbol}: {e}")
        return None


# =============================================================================
# 5) 工具函数：补后缀 / 最新价（稳定：优先用 a_stock_list 缓存）
# =============================================================================
def ensure_suffix(code_or_symbol: str) -> str:
    """自动补全 .SS/.SZ 后缀（A股常用：6/9开头 -> .SS，其它 -> .SZ）。"""
    s = (code_or_symbol or "").strip()
    if not s:
        return s
    if "." in s:
        return s
    return f"{s}.SS" if s.startswith(("6", "9")) else f"{s}.SZ"


def get_latest_price(code_6: str) -> Optional[float]:
    """
    稳定获取 A 股最新价：优先走 get_a_stock_list()（带磁盘缓存）。
    code_6: "000989"
    """
    code_6 = str(code_6).strip()
    if not code_6:
        return None

    df = get_a_stock_list()
    if df is None or df.empty:
        return None

    # df 标准列：代码/最新价
    try:
        m = df[df["代码"].astype(str).str.replace(".0", "", regex=False) == code_6]
        if not m.empty:
            x = m.iloc[0].get("最新价", None)
            if pd.isna(x):
                return None
            return float(x)
    except Exception:
        return None

    return None
