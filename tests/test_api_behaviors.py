import importlib

import pandas as pd
from fastapi.testclient import TestClient


def _prepare_web_app(monkeypatch, tmp_path):
    portfolio_store = importlib.import_module("app.portfolio_store")
    monkeypatch.setattr(portfolio_store, "DB_FILE", str(tmp_path / "portfolio.db"))
    monkeypatch.setattr(portfolio_store, "LEGACY_DB_FILE", tmp_path / "legacy.db")
    monkeypatch.setenv("STOCK_LIST", "600519,000001")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    portfolio_store.init_db()

    web_main = importlib.import_module("web.main")
    monkeypatch.setattr(web_main, "get_market_snapshot_cached", lambda force_refresh=False: pd.DataFrame())
    monkeypatch.setattr(web_main, "_get_name_map_from_a_list", lambda: {})
    monkeypatch.setattr(web_main, "_fetch_realtime_quote_fallback", lambda code: None)
    monkeypatch.setattr(web_main, "is_cn_trading_time", lambda now=None: False)
    return web_main, TestClient(web_main.app)


def test_watchlist_api_add_remove_roundtrip(monkeypatch, tmp_path):
    web_main, client = _prepare_web_app(monkeypatch, tmp_path)

    response = client.get("/api/watchlist")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["source"] == "db"

    response = client.post("/api/watchlist/add", json={"symbol": "300750", "name": "CATL"})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert any(item["symbol"] == "300750" for item in web_main.list_watchlist())

    response = client.post("/api/watchlist/remove", json={"symbol": "300750"})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert all(item["symbol"] != "300750" for item in web_main.list_watchlist())


def test_watchlist_quotes_survive_without_market_data(monkeypatch, tmp_path):
    _, client = _prepare_web_app(monkeypatch, tmp_path)

    response = client.get("/api/watchlist/quotes")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert [item["symbol"] for item in payload["items"]] == ["600519", "000001"]
    assert all(item["price"] is None for item in payload["items"])


def test_chat_without_llm_key_returns_actionable_message(monkeypatch, tmp_path):
    _, client = _prepare_web_app(monkeypatch, tmp_path)

    response = client.post("/api/chat", json={"message": "hello"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "DEEPSEEK_API_KEY" in payload["reply"]


def test_holdings_rebuild_endpoint(monkeypatch, tmp_path):
    _, client = _prepare_web_app(monkeypatch, tmp_path)

    response = client.post("/api/holdings/rebuild")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "metrics" in payload


def test_agent_showcase_endpoints_are_available(monkeypatch, tmp_path):
    _, client = _prepare_web_app(monkeypatch, tmp_path)

    profile_response = client.get("/api/agent/profile")
    assert profile_response.status_code == 200
    profile_payload = profile_response.json()
    assert profile_payload["ok"] is True
    assert profile_payload["profile"]["name"] == "stock_agent"
    assert profile_payload["profile"]["data_status"]["watchlist_count"] == 2
    assert profile_payload["profile"]["data_status"]["has_llm_key"] is False
    assert profile_payload["profile"]["demo_questions"]

    health_response = client.get("/api/agent/health")
    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["ok"] is True
    assert any(check["name"] == "database" for check in health_payload["checks"])

    prompts_response = client.get("/api/agent/demo-prompts")
    assert prompts_response.status_code == 200
    prompts_payload = prompts_response.json()
    assert prompts_payload["ok"] is True
    assert len(prompts_payload["demo_questions"]) >= 3


def test_static_dashboard_css_is_served(monkeypatch, tmp_path):
    _, client = _prepare_web_app(monkeypatch, tmp_path)

    response = client.get("/static/style.css")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert b"--surface" in response.content


def test_dashboard_exposes_investment_committee_panel(monkeypatch, tmp_path):
    _, client = _prepare_web_app(monkeypatch, tmp_path)

    response = client.get("/portfolio/embed")

    assert response.status_code == 200
    assert "投研委员会" in response.text
    assert "关注闭环" in response.text
    assert "buildWatchlistDecision" in response.text
    assert "专家 Agent" in response.text
    assert "治理 Agent" in response.text
    assert "协同流程" in response.text
    assert "loadCommitteeDecision" in response.text


def test_daily_review_endpoint_persists_memory(monkeypatch, tmp_path):
    web_main, client = _prepare_web_app(monkeypatch, tmp_path)
    portfolio_store = importlib.import_module("app.portfolio_store")
    portfolio_store.apply_trade("000001.SZ", "平安银行", "BUY", 100, 10)
    portfolio_store.apply_trade("000001.SZ", "平安银行", "SELL", 100, 8)

    response = client.post("/api/agent/daily-review", json={"persist": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["persisted"] is True
    assert payload["saved_notes"]
    assert any(note["category"] == "LESSON" for note in portfolio_store.list_notes(limit=10))


def test_watchlist_decision_endpoint(monkeypatch, tmp_path):
    _, client = _prepare_web_app(monkeypatch, tmp_path)

    response = client.post("/api/agent/watchlist-decisions", json={"persist": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert "items" in payload
