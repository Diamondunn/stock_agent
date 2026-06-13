import importlib

from app.investment_committee import build_investment_committee_decision


def _prepare_store(monkeypatch, tmp_path):
    portfolio_store = importlib.import_module("app.portfolio_store")
    monkeypatch.setattr(portfolio_store, "DB_FILE", str(tmp_path / "portfolio.db"))
    monkeypatch.setattr(portfolio_store, "LEGACY_DB_FILE", tmp_path / "legacy.db")
    monkeypatch.delenv("STOCK_LIST", raising=False)
    portfolio_store.init_db()
    return portfolio_store


def _bullish_technical():
    return {
        "ok": True,
        "history_ok": True,
        "price": 12,
        "ma20": 11,
        "ma50": 10,
        "rsi": 55,
        "macd": 0.4,
        "macd_signal": 0.1,
        "max_drawdown": -0.08,
        "bars": 80,
    }


def test_committee_outputs_buy_candidate_for_aligned_positive_signals(monkeypatch, tmp_path):
    _prepare_store(monkeypatch, tmp_path)

    decision = build_investment_committee_decision("600519", technical_override=_bullish_technical())

    assert decision["ok"] is True
    assert decision["symbol"] == "600519.SS"
    assert decision["action"] == "BUY_CANDIDATE"
    assert decision["confidence"] in {"medium", "high"}
    assert len(decision["votes"]) == 3


def test_committee_penalizes_concentrated_existing_position(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    store.apply_trade("600519.SS", "贵州茅台", "BUY", 100, 10)

    decision = build_investment_committee_decision("600519", technical_override=_bullish_technical())
    risk_vote = next(v for v in decision["votes"] if v["role"] == "risk_manager")

    assert decision["has_position"] is True
    assert risk_vote["score"] < 0
    assert "集中度风险" in risk_vote["evidence"][0]


def test_committee_uses_negative_trade_memory(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    store.apply_trade("000001.SZ", "平安银行", "BUY", 100, 10)
    store.apply_trade("000001.SZ", "平安银行", "SELL", 100, 8)

    decision = build_investment_committee_decision("000001", technical_override=_bullish_technical())
    memory_vote = next(v for v in decision["votes"] if v["role"] == "memory_reviewer")

    assert memory_vote["score"] < 0
    assert any("贡献为负" in item for item in memory_vote["evidence"])
