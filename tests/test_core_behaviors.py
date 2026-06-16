import importlib
from datetime import datetime

import pandas as pd

from app.cache import is_cn_trading_time


def test_cn_trading_time_rejects_weekends():
    saturday_morning = datetime(2026, 6, 13, 10, 0)
    assert is_cn_trading_time(saturday_morning) is False


def test_cn_trading_time_accepts_weekday_session():
    friday_morning = datetime(2026, 6, 12, 10, 0)
    assert is_cn_trading_time(friday_morning) is True


def test_watchlist_uses_db_before_env(monkeypatch, tmp_path):
    portfolio_store = importlib.import_module("app.portfolio_store")
    monkeypatch.setattr(portfolio_store, "DB_FILE", str(tmp_path / "portfolio.db"))
    monkeypatch.setattr(portfolio_store, "LEGACY_DB_FILE", tmp_path / "legacy.db")
    monkeypatch.setenv("STOCK_LIST", "600519,000001")

    portfolio_store.init_db()
    portfolio_store.add_watch("300750", "宁德时代")
    portfolio_store.remove_watch("600519")
    portfolio_store.remove_watch("000001")

    symbols = [item["symbol"] for item in portfolio_store.list_watchlist()]
    assert symbols == ["300750"]


def test_stock_history_reads_legacy_cache(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / "cache" / "history"
    cache_dir.mkdir(parents=True)
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "Open": [10, 11],
            "High": [11, 12],
            "Low": [9, 10],
            "Close": [10.5, 11.5],
            "Volume": [1000, 1200],
        }
    )
    df.to_parquet(cache_dir / "600519.SS.parquet", index=False)
    data_sources = importlib.import_module("app.data_sources")

    hist = data_sources.get_stock_history("600519.SS", "6mo")

    assert hist is not None
    assert list(hist.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(hist) == 2
