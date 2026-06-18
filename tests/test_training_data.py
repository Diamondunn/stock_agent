import importlib
import json
from datetime import date

import pandas as pd

from app.training_data import build_watchlist_finetune_records, write_jsonl


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


def test_watchlist_finetune_records_include_review_outcome(monkeypatch, tmp_path):
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
            "coordinator": {"rationale": "趋势偏强且风控没有否决。"},
            "technical": {"price": 100.0},
            "next_steps": ["先小仓验证。"],
        },
    )

    cycle.build_watchlist_decisions(persist=True, today=date(2026, 6, 15))
    monkeypatch.setattr(cycle, "get_market_snapshot_cached", lambda: _quote_df(104.0))
    cycle.review_previous_watchlist_decisions(persist=True, today=date(2026, 6, 16))

    records = build_watchlist_finetune_records()

    assert len(records) == 1
    assert records[0]["messages"][0]["role"] == "system"
    assert records[0]["messages"][1]["role"] == "user"
    assert records[0]["messages"][2]["role"] == "assistant"
    assert "复盘状态：HIT" in records[0]["messages"][2]["content"]
    assert records[0]["metadata"]["review_status"] == "HIT"


def test_write_jsonl_outputs_one_record_per_line(tmp_path):
    path = tmp_path / "dataset.jsonl"
    result = write_jsonl([{"messages": [{"role": "user", "content": "x"}]}], path)

    assert result["ok"] is True
    assert result["records"] == 1
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["messages"][0]["content"] == "x"


def test_watchlist_finetune_records_clean_legacy_watch_wording(monkeypatch, tmp_path):
    store = _prepare_store(monkeypatch, tmp_path)
    payload = {
        "date": "2026-06-16",
        "items": [
            {
                "symbol": "000989.SZ",
                "name": "九芝堂",
                "action": "WATCH",
                "action_label": "观察",
                "score": 0,
                "confidence": "low",
                "has_position": False,
                "price": 7.93,
                "change_pct": -1.7,
                "reason": "关键行情证据缺失，协调员将决策降级为观察。",
                "next_steps": ["保持观察，等待技术面、风险面或交易记忆给出更一致信号。"],
            }
        ],
    }
    store.add_note("WATCHLIST_DECISION", json.dumps(payload, ensure_ascii=False))

    records = build_watchlist_finetune_records()
    target = records[0]["messages"][2]["content"]

    assert "更一致信号" not in target
    assert "历史K线或关键行情证据缺失" in target
    assert "至少两项证据同向" in target
