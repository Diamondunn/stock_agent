# app/cache.py

import os
import logging
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from typing import Any, Dict, Optional, List

import pandas as pd
from pathlib import Path

# ===============================
# 数据目录
# ===============================
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

HOLDINGS_FILE = DATA_DIR / "holdings.json"


# ===============================
# 配置
# ===============================
@dataclass
class Config:
    MODEL_NAME: str = "deepseek-chat"
    MODEL_PROVIDER: str = "deepseek"
    MODEL_TEMPERATURE: float = 0.1

    CACHE_ENABLED: bool = True
    CACHE_EXPIRY_MINUTES: int = 30

    DISK_CACHE_DIR: str = "./cache"
    DISK_A_LIST_FILE: str = "a_stock_list.parquet"

    DISK_TTL_TRADING_HOURS: int = 1
    DISK_TTL_OFF_HOURS: int = 24

    RATE_LIMIT_SEC: float = 1.1
    RETRY_TRIES: int = 3
    RETRY_BASE_SLEEP: float = 0.9

    YF_MIN_INTERVAL_SEC: float = 2.8

    RISK_FREE_RATE: float = 0.015


config = Config()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - stock_assistant - %(levelname)s - %(message)s",
)
logger = logging.getLogger("stock_assistant")


# ===============================
# 内存缓存
# ===============================
class DataCache:
    def __init__(self):
        self.cache: Dict[str, Any] = {}
        self.timestamps: Dict[str, datetime] = {}

    def get(self, key: str) -> Optional[Any]:
        if not config.CACHE_ENABLED:
            return None
        if key in self.cache:
            ts = self.timestamps.get(key, datetime.min)
            if datetime.now() - ts < timedelta(minutes=config.CACHE_EXPIRY_MINUTES):
                return self.cache[key]
            self.cache.pop(key, None)
            self.timestamps.pop(key, None)
        return None

    def set(self, key: str, value: Any):
        if config.CACHE_ENABLED:
            self.cache[key] = value
            self.timestamps[key] = datetime.now()


cache = DataCache()


# ===============================
# 交易时段判断
# ===============================
def is_cn_trading_time(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    morning = dtime(9, 30) <= t <= dtime(11, 30)
    afternoon = dtime(13, 0) <= t <= dtime(15, 0)
    return morning or afternoon


def get_dynamic_ttl_hours() -> int:
    return config.DISK_TTL_TRADING_HOURS if is_cn_trading_time() else config.DISK_TTL_OFF_HOURS


# ===============================
# 磁盘缓存
# ===============================
def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def disk_cache_path() -> str:
    _ensure_dir(config.DISK_CACHE_DIR)
    return os.path.join(config.DISK_CACHE_DIR, config.DISK_A_LIST_FILE)


def load_disk_cache(ttl_hours: int) -> Optional[pd.DataFrame]:
    path = disk_cache_path()
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        if df is None or df.empty:
            return None
        # If cached file has no price data, treat as invalid to force refresh.
        price_col = "最新价" if "最新价" in df.columns else ("price" if "price" in df.columns else None)
        if price_col:
            series = df[price_col]
            if series is None or series.notna().sum() == 0:
                logger.warning("[disk-cache] 价格列全为空，视为无效缓存")
                return None
        if "asof" in df.columns:
            asof = pd.to_datetime(df["asof"].iloc[0])
            if datetime.now() - asof.to_pydatetime() <= timedelta(hours=ttl_hours):
                logger.info(f"[disk-cache] 命中缓存")
                return df.drop(columns=["asof"], errors="ignore")
        return None
    except Exception as e:
        logger.warning(f"[disk-cache] 读取失败: {e}")
        return None


def save_disk_cache(df: pd.DataFrame):
    path = disk_cache_path()
    try:
        out = df.copy()
        out["asof"] = datetime.now()
        out.to_parquet(path, index=False)
        logger.info("[disk-cache] 已写入")
    except Exception as e:
        logger.warning(f"[disk-cache] 写入失败: {e}")


def load_expired_disk_cache_if_any() -> Optional[pd.DataFrame]:
    path = disk_cache_path()
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path).drop(columns=["asof"], errors="ignore")
        logger.warning("[disk-cache] 返回过期缓存")
        return df
    except Exception:
        return None
