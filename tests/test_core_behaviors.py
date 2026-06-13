import importlib
from datetime import datetime

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
