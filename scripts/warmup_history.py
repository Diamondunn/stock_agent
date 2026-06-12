# scripts/warmup_history.py

from __future__ import annotations
import sys
from pathlib import Path

# 把项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))
import time
from datetime import datetime, time as dtime
from typing import Optional

import akshare as ak
import pandas as pd

from app.portfolio_store import init_db, list_watchlist, get_holdings
from app.data_sources import ensure_suffix
from app.history_store import merge_and_save
from app.cache import logger



# ----------------------------------------
# 只建议盘后更新（避免风控）
# ----------------------------------------
def is_off_hours() -> bool:
    now = datetime.now().time()
    # 16:00 之后或 8:30 之前
    return (now >= dtime(16, 0)) or (now <= dtime(8, 30))


# ----------------------------------------
# 使用 akshare 拉历史
# ----------------------------------------
def fetch_history(symbol: str) -> Optional[pd.DataFrame]:

    try:
        code = symbol.split(".")[0]

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            adjust="qfq"
        )

        if df is None or df.empty:
            return None

        return df

    except Exception as e:
        logger.warning(f"[warmup] 拉取失败 {symbol}: {e}")
        return None


# ----------------------------------------
# 主函数
# ----------------------------------------
def main():

    init_db()

    if not is_off_hours():
        logger.warning("[warmup] 当前接近交易时间，建议盘后运行")

    symbols = set()

    # 关注列表
    for w in (list_watchlist() or []):
        symbols.add(ensure_suffix(w["symbol"]))

    # 持仓
    for h in (get_holdings() or []):
        symbols.add(ensure_suffix(h["symbol"]))

    symbols = list(symbols)

    if not symbols:
        logger.info("[warmup] 没有股票需要更新")
        return

    logger.info(f"[warmup] 更新股票数量: {len(symbols)}")

    success = 0

    for i, sym in enumerate(symbols, 1):

        logger.info(f"[warmup] {i}/{len(symbols)} {sym}")

        df = fetch_history(sym)

        if df is not None and not df.empty:
            merge_and_save(sym, df)
            success += 1

        # 🔥 慢一点，避免风控
        time.sleep(5)
        if i % 3 == 0:
            time.sleep(15)
    logger.info(f"[warmup] 完成: {success}/{len(symbols)}")


if __name__ == "__main__":
    main()
