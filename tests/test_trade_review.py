import importlib

from app.trade_review import build_daily_review, build_strategy_advice, build_trade_review, save_lesson


def _prepare_store(monkeypatch, tmp_path):
    portfolio_store = importlib.import_module("app.portfolio_store")
    monkeypatch.setattr(portfolio_store, "DB_FILE", str(tmp_path / "portfolio.db"))
    monkeypatch.setattr(portfolio_store, "LEGACY_DB_FILE", tmp_path / "legacy.db")
    monkeypatch.delenv("STOCK_LIST", raising=False)
    portfolio_store.init_db()
    return portfolio_store


def test_trade_review_reconstructs_closed_round_trips(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    store.apply_trade("600519.SS", "贵州茅台", "BUY", 100, 10, note="breakout")
    store.apply_trade("600519.SS", "贵州茅台", "SELL", 100, 12, note="take profit")
    store.apply_trade("000001.SZ", "平安银行", "BUY", 100, 10, note="bottom fishing")
    store.apply_trade("000001.SZ", "平安银行", "SELL", 100, 9, note="stop loss")

    review = build_trade_review()

    assert review["ok"] is True
    assert review["summary"]["closed_trades"] == 2
    assert review["summary"]["win_rate"] == 50
    assert review["summary"]["total_pnl"] == 100
    assert len(review["symbol_stats"]) == 2
    assert review["lessons"]


def test_strategy_advice_uses_review_basis(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    store.apply_trade("000001.SZ", "平安银行", "BUY", 100, 10)
    store.apply_trade("000001.SZ", "平安银行", "SELL", 100, 8)
    store.apply_trade("600519.SS", "贵州茅台", "BUY", 100, 10)
    store.apply_trade("600519.SS", "贵州茅台", "SELL", 100, 8)
    store.apply_trade("300750.SZ", "宁德时代", "BUY", 100, 10)
    store.apply_trade("300750.SZ", "宁德时代", "SELL", 100, 8)

    advice = build_strategy_advice()

    assert advice["ok"] is True
    assert advice["basis"]["closed_trades"] == 3
    assert len(advice["rules"]) >= 3
    assert any("止损" in rule or "风险" in rule for rule in advice["rules"])


def test_save_lesson_persists_as_long_term_memory(monkeypatch, tmp_path):
    _prepare_store(monkeypatch, tmp_path)

    result = save_lesson("追高失败后不补仓，等下一次确认信号。")
    review = build_trade_review()

    assert result["ok"] is True
    assert review["stored_lessons"][0]["category"] == "LESSON"
    assert "不补仓" in review["stored_lessons"][0]["content"]


def test_daily_review_persists_idempotent_memory(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    store.apply_trade("000001.SZ", "平安银行", "BUY", 100, 10)
    store.apply_trade("000001.SZ", "平安银行", "SELL", 100, 8)

    first = build_daily_review(persist=True)
    second = build_daily_review(persist=True)
    notes = store.list_notes(limit=20)

    assert first["ok"] is True
    assert any(item["category"] == "DAILY_REVIEW" for item in first["saved_notes"])
    assert any(item["category"] == "LESSON" for item in first["saved_notes"])
    assert second["saved_notes"] == []
    assert sum(1 for note in notes if note["category"] == "DAILY_REVIEW") == 1
