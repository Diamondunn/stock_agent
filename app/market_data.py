import os
import time
from datetime import datetime
from app.cache import cache, logger, config, is_cn_trading_time
from app.data_sources import get_a_stock_list


def _safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def norm_code(x: str) -> str:
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if s.isdigit():
        s = s.zfill(6)
    return s


def _offhours_marker_path() -> str:
    os.makedirs(config.DISK_CACHE_DIR, exist_ok=True)
    return os.path.join(config.DISK_CACHE_DIR, "offhours_snapshot_date.txt")


def _read_offhours_marker() -> str:
    path = _offhours_marker_path()
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _write_offhours_marker(date_str: str) -> None:
    path = _offhours_marker_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(date_str)
    except Exception:
        return


def get_market_snapshot_cached(ttl_seconds: int = 30, force_refresh: bool = False):
    """
    获取A股全市场实时快照（带缓存）
    """
    key = "market_snapshot_df"

    if not force_refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached

    try:
        allow_remote = True
        if not is_cn_trading_time():
            today = datetime.now().strftime("%Y-%m-%d")
            marker = _read_offhours_marker()
            if marker == today:
                allow_remote = False
                force_refresh = False
            else:
                _write_offhours_marker(today)

        df = get_a_stock_list(force_refresh=force_refresh, allow_remote=allow_remote)
        if (df is None or df.empty) and force_refresh:
            # fallback to cached/expired data when force refresh fails
            df = get_a_stock_list(force_refresh=False, allow_remote=False)
        if df is None or df.empty:
            return None

        cols = list(df.columns)

        code_col = "code" if "code" in cols else "代码"
        name_col = "name" if "name" in cols else "名称"
        price_col = "price" if "price" in cols else "最新价"
        pct_col = "change_pct" if "change_pct" in cols else "涨跌幅"

        slim = df[[code_col, name_col, price_col, pct_col]].copy()
        slim.columns = ["code", "name", "price", "change_pct"]

        slim["code"] = (
            slim["code"]
            .astype(str)
            .str.replace(".0", "", regex=False)
            .str.extract(r"(\d{6})")[0]
        )
        slim["price"] = slim["price"].apply(_safe_float)
        slim["change_pct"] = slim["change_pct"].apply(_safe_float)

        cache.set(key, slim)
        logger.info(f"[snapshot] columns: {slim.columns}")
        return slim

    except Exception as e:
        logger.warning(f"[market_snapshot] 获取失败: {e}")
        return None
