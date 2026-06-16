import importlib
from datetime import date

import pandas as pd

from app.watchlist_cycle import build_watchlist_decisions, review_previous_watchlist_decisions


def _prepare_store(monkeypatch, tmp_path):
    portfolio_store = importlib.import_module("app.portfolio_store")
    monkeypatch.setattr(portfolio_store, "DB_FILE", str(tmp_path / "portfolio.db"))
    monkeypatch.setattr(portfolio_store, "LEGACY_DB_FILE", tmp_path / "legacy.db")
    monkeypatch.delenv("STOCK_LIST", raising=False)
    portfolio_store.init_db()
    return portfolio_store


def _quote_df(price: float):
    return pd.DataFrame(
        [{"code": "600519", "name": "贵州茅台", "price": price, "change_pct": 1.2}]
    )


def test_watchlist_decision_persists_daily_actions(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    store.add_watch("600519", "贵州茅台")
    cycle = importlib.import_module("app.watchlist_cycle")
    monkeypatch.setattr(cycle, "get_market_snapshot_cached", lambda: _quote_df(100.0))
    monkeypatch.setattr(
        cycle,
        "build_investment_committee_decision",
        lambda symbol: {
            "action": "BUY_CANDIDATE",
            "score": 3,
            "confidence": "medium",
            "coordinator": {"rationale": "趋势、风险、记忆没有形成重大冲突。"},
            "technical": {"price": 100.0},
            "next_steps": ["先小仓验证。"],
        },
    )

    result = build_watchlist_decisions(persist=True, today=date(2026, 6, 16))
    again = build_watchlist_decisions(persist=True, today=date(2026, 6, 16))

    assert result["ok"] is True
    assert result["items"][0]["action"] == "BUY_CANDIDATE"
    assert result["persisted"] is True
    assert again["persisted"] is False
    assert any(note["category"] == "WATCHLIST_DECISION" for note in store.list_notes(limit=10))


def test_watchlist_next_day_review_scores_previous_decision(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    store.add_watch("600519", "贵州茅台")
    cycle = importlib.import_module("app.watchlist_cycle")
    monkeypatch.setattr(cycle, "get_market_snapshot_cached", lambda: _quote_df(100.0))
    monkeypatch.setattr(
        cycle,
        "build_investment_committee_decision",
        lambda symbol: {
            "action": "BUY_CANDIDATE",
            "score": 3,
            "confidence": "medium",
            "coordinator": {"rationale": "趋势偏强。"},
            "technical": {"price": 100.0},
            "next_steps": [],
        },
    )
    build_watchlist_decisions(persist=True, today=date(2026, 6, 15))

    monkeypatch.setattr(cycle, "get_market_snapshot_cached", lambda: _quote_df(104.0))
    review = review_previous_watchlist_decisions(persist=True, today=date(2026, 6, 16))

    assert review["reviewed_date"] == "2026-06-15"
    assert review["items"][0]["status"] == "HIT"
    assert review["items"][0]["change_pct"] == 4.0
    assert review["summary"]["hit"] == 1
    assert any(note["category"] == "WATCHLIST_REVIEW" for note in store.list_notes(limit=10))
