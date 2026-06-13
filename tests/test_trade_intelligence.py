import importlib

from app.trade_intelligence import (
    classify_intent,
    parse_trade_instruction,
    pretrade_risk_check,
)


def _prepare_store(monkeypatch, tmp_path):
    portfolio_store = importlib.import_module("app.portfolio_store")
    monkeypatch.setattr(portfolio_store, "DB_FILE", str(tmp_path / "portfolio.db"))
    monkeypatch.setattr(portfolio_store, "LEGACY_DB_FILE", tmp_path / "legacy.db")
    monkeypatch.delenv("STOCK_LIST", raising=False)
    portfolio_store.init_db()
    return portfolio_store


def test_classify_intent_detects_trade_and_watchlist():
    trade = classify_intent("帮我记录：10.5买入100股600519")
    assert trade["intent"] == "record_trade"
    assert trade["matched"] is True

    watchlist = classify_intent("分析我的关注列表，给出观察重点")
    assert watchlist["intent"] == "watchlist_analysis"


def test_parse_trade_instruction_price_first_chinese():
    result = parse_trade_instruction("10.5买入100股600519，理由是回踩支撑")

    assert result["ok"] is True
    assert result["trade"]["symbol"] == "600519.SS"
    assert result["trade"]["side"] == "BUY"
    assert result["trade"]["shares"] == 100
    assert result["trade"]["price"] == 10.5


def test_parse_trade_instruction_english_sell():
    result = parse_trade_instruction("sell 000001 200 @ 9.8")

    assert result["ok"] is True
    assert result["trade"]["symbol"] == "000001.SZ"
    assert result["trade"]["side"] == "SELL"


def test_pretrade_blocks_sell_above_holding(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    store.apply_trade("600519.SS", "贵州茅台", "BUY", 100, 10)

    result = pretrade_risk_check("600519", "SELL", 200, 11)

    assert result["ok"] is False
    assert "exceed current holding" in result["blockers"][0]


def test_pretrade_blocks_large_single_trade(monkeypatch, tmp_path):
    _prepare_store(monkeypatch, tmp_path)
    monkeypatch.setenv("MAX_TRADE_VALUE", "1000")

    result = pretrade_risk_check("600519", "BUY", 200, 10)

    assert result["ok"] is False
    assert any("exceeds limit" in item for item in result["blockers"])


def test_pretrade_warns_position_concentration(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    monkeypatch.setenv("MAX_TRADE_VALUE", "1000000")
    monkeypatch.setenv("MAX_POSITION_WEIGHT", "0.35")
    store.apply_trade("000001.SZ", "平安银行", "BUY", 100, 10)

    result = pretrade_risk_check("600519", "BUY", 100, 20)

    assert result["ok"] is True
    assert result["warnings"]
    assert result["projected_position_weight"] > 0.35
