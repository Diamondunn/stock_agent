# app/config.py
from dataclasses import dataclass

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
