from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app import portfolio_store
from app.account_analytics import build_account_dashboard
from app.portfolio_store import (
    get_holdings,
    init_db,
    list_notes,
    list_trades,
    list_watchlist,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DSA_DIR = ROOT_DIR / "third_party" / "daily_stock_analysis"

DEMO_QUESTIONS = [
    "我的组合现在风险主要集中在哪里？",
    "分析我的关注列表，给出今天最值得观察的三件事。",
    "帮我记录：10.5买入100股600519，理由是回踩支撑。",
    "复盘我的历史交易胜率和最大回撤。",
    "基于持仓和关注列表，生成下一周观察计划。",
]


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _count_table(table: str) -> int:
    try:
        with sqlite3.connect(portfolio_store.DB_FILE) as con:
            row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def _portfolio_summary(holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    total_cost = 0.0
    total_shares = 0.0
    for item in holdings:
        shares = _safe_float(item.get("shares"))
        avg_cost = _safe_float(item.get("avg_cost"))
        cost_value = shares * avg_cost
        total_cost += cost_value
        total_shares += shares
        rows.append(
            {
                "symbol": str(item.get("symbol", "")),
                "shares": shares,
                "avg_cost": avg_cost,
                "cost_value": round(cost_value, 2),
                "updated_at": item.get("updated_at"),
            }
        )
    return {
        "holding_count": len(rows),
        "total_cost_value": round(total_cost, 2),
        "total_shares": round(total_shares, 4),
        "holdings": rows,
    }


def _safe_account_summary() -> Dict[str, Any]:
    try:
        data = build_account_dashboard()
        return {
            "realized_pnl": data.get("realized_pnl", 0),
            "win_rate": data.get("win_rate", 0),
            "trade_count": data.get("trade_count", 0),
            "profit_factor": data.get("profit_factor", 0),
            "max_drawdown": data.get("max_drawdown", 0),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _capabilities() -> List[Dict[str, str]]:
    return [
        {
            "name": "Portfolio memory",
            "description": "SQLite stores holdings, trades, watchlist items, and investment plans.",
        },
        {
            "name": "Tool-calling agent",
            "description": "LangChain tools expose portfolio accounting, watchlist analysis, trade logging, and DSA reports.",
        },
        {
            "name": "Risk analytics",
            "description": "Account dashboard computes realized PnL, win rate, profit factor, equity curve, and drawdown.",
        },
        {
            "name": "Multi-agent committee",
            "description": "Specialist agents debate technical, risk, and trade-memory evidence; a coordinator arbitrates and a critic flags missing evidence.",
        },
        {
            "name": "Watchlist research",
            "description": "Watchlist tools combine cached quotes, local history, technical indicators, and trend signals.",
        },
        {
            "name": "Privacy-first publishing",
            "description": "Runtime secrets, databases, caches, logs, and deploy keys are excluded from GitHub sync.",
        },
    ]


def build_agent_profile() -> Dict[str, Any]:
    """Return an offline, JSON-safe project profile for demos and health pages."""
    init_db()
    holdings = get_holdings() or []
    watchlist = list_watchlist() or []
    recent_trades = list_trades(limit=5) or []
    recent_plans = list_notes("PLAN", limit=5) or []

    return {
        "name": "stock_agent",
        "asof": datetime.now().isoformat(timespec="seconds"),
        "summary": (
            "A local A-share stock assistant with persistent portfolio memory, "
            "watchlist research tools, account risk analytics, and a FastAPI dashboard."
        ),
        "capabilities": _capabilities(),
        "data_status": {
            "holdings_count": len(holdings),
            "watchlist_count": len(watchlist),
            "trades_count": _count_table("trades"),
            "plans_count": _count_table("notes"),
            "has_llm_key": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
            "database_path": portfolio_store.DB_FILE,
            "dsa_available": DSA_DIR.exists(),
        },
        "portfolio_summary": _portfolio_summary(holdings),
        "account_summary": _safe_account_summary(),
        "watchlist": [
            {
                "symbol": str(item.get("symbol", "")),
                "name": str(item.get("name", "")),
                "created_at": item.get("created_at"),
            }
            for item in watchlist
        ],
        "recent_trades": recent_trades,
        "recent_plans": recent_plans,
        "demo_questions": DEMO_QUESTIONS,
    }


def agent_health() -> Dict[str, Any]:
    """Return operational checks without exposing secret values."""
    checks = []

    try:
        init_db()
        with sqlite3.connect(portfolio_store.DB_FILE) as con:
            con.execute("SELECT 1").fetchone()
        checks.append({"name": "database", "ok": True, "detail": "SQLite database is reachable."})
    except Exception as exc:
        checks.append({"name": "database", "ok": False, "detail": str(exc)})

    env_example = ROOT_DIR / ".env.example"
    checks.append(
        {
            "name": "env_example",
            "ok": env_example.exists(),
            "detail": ".env.example is present." if env_example.exists() else ".env.example is missing.",
        }
    )

    has_llm_key = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
    checks.append(
        {
            "name": "llm_key",
            "ok": True,
            "detail": "DEEPSEEK_API_KEY is configured." if has_llm_key else "Chat is disabled until DEEPSEEK_API_KEY is set.",
            "severity": "info" if has_llm_key else "warning",
        }
    )

    checks.append(
        {
            "name": "dsa_bridge",
            "ok": DSA_DIR.exists(),
            "detail": "daily_stock_analysis integration is available." if DSA_DIR.exists() else "daily_stock_analysis directory is missing.",
        }
    )

    profile = build_agent_profile()
    checks.append(
        {
            "name": "stored_memory",
            "ok": True,
            "detail": (
                f"{profile['data_status']['holdings_count']} holdings, "
                f"{profile['data_status']['watchlist_count']} watchlist items, "
                f"{profile['data_status']['trades_count']} trades."
            ),
        }
    )

    hard_failures = [c for c in checks if not c.get("ok") and c.get("severity") != "warning"]
    return {"ok": not hard_failures, "asof": datetime.now().isoformat(timespec="seconds"), "checks": checks}


def render_agent_profile_markdown() -> str:
    profile = build_agent_profile()
    status = profile["data_status"]
    lines = [
        "# stock_agent Agent Profile",
        "",
        profile["summary"],
        "",
        "## Data Status",
        f"- Holdings: {status['holdings_count']}",
        f"- Watchlist: {status['watchlist_count']}",
        f"- Trades: {status['trades_count']}",
        f"- Plans: {status['plans_count']}",
        f"- LLM configured: {'yes' if status['has_llm_key'] else 'no'}",
        f"- DSA available: {'yes' if status['dsa_available'] else 'no'}",
        "",
        "## Capabilities",
    ]
    for capability in profile["capabilities"]:
        lines.append(f"- {capability['name']}: {capability['description']}")
    lines.extend(["", "## Demo Questions"])
    for question in profile["demo_questions"]:
        lines.append(f"- {question}")
    return "\n".join(lines)
