from __future__ import annotations

# ===============================
# 标准库
# ===============================
import time
import os
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib import request, parse
from typing import Dict, Any

# ===============================
# FastAPI
# ===============================
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ===============================
# 应用核心
# ===============================
from app.chatbot import StockChatBot
from app.cache import cache, logger, is_cn_trading_time

# ===============================
# 数据层
# ===============================
from app.market_data import get_market_snapshot_cached
from app.data_sources import get_a_stock_list
from app.portfolio_store import (
    init_db,
    get_holdings as db_get_holdings,
    list_watchlist,
    add_watch,
    remove_watch,
    rebuild_holdings_from_trades,
)
from app.account_analytics import build_account_dashboard
from app.agent_profile import (
    agent_health,
    build_agent_profile,
    render_agent_profile_markdown,
)
from app.trade_review import build_daily_review, build_strategy_advice, build_trade_review, save_lesson
from app.investment_committee import build_investment_committee_decision
from app.dsa_bridge import get_dsa_app


# ===============================
# App Init (DSA as main frontend)
# ===============================
app = get_dsa_app()
bot: StockChatBot | None = None
router = APIRouter(prefix="/api")
templates = Jinja2Templates(directory="web/templates")
_alert_thread_started = False
_alert_stop_event = threading.Event()
_watchlist_fallback_lock = threading.Lock()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    try:
        existing_static = any(getattr(route, "path", None) == "/static" for route in app.router.routes)
        if not existing_static:
            app.mount("/static", StaticFiles(directory=STATIC_DIR), name="stock-agent-static")
    except Exception:
        logger.warning("[web] failed to mount static files", exc_info=True)

# 初始化数据库
init_db()

# .env 加载（用于 STOCK_LIST 等）
try:
    from dotenv import load_dotenv
    root_env = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(root_env):
        load_dotenv(root_env, override=False)
except Exception:
    pass


def get_bot() -> StockChatBot:
    global bot
    if bot is None:
        bot = StockChatBot()
    return bot


def _llm_configured() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY", "").strip())


# ===============================
# 资产计算
# ===============================
def calculate_metrics(force_refresh: bool = False) -> Dict[str, Any]:

    soft_key = "dashboard_metrics_soft"

    if not force_refresh:
        soft = cache.get(soft_key)
        if isinstance(soft, dict) and soft.get("_soft_ts"):
            if time.time() - float(soft["_soft_ts"]) <= 10:
                return soft

    holdings = db_get_holdings() or []
    snap = get_market_snapshot_cached()

    total_value = 0.0
    total_cost = 0.0
    details = []
    allocation_labels = []
    allocation_values = []

    price_map = {}
    name_map = {}

    if snap is not None and not snap.empty:
        for _, r in snap.iterrows():
            code = str(r["code"]).zfill(6)
            name_map[code] = str(r["name"])
            price_map[code] = r["price"]

    for h in holdings:
        raw_symbol = str(h.get("symbol", "")).strip()
        code = raw_symbol.split(".")[0].zfill(6)

        shares = float(h.get("shares", 0))
        avg_cost = float(h.get("avg_cost", 0))

        latest_price = price_map.get(code, avg_cost)
        name = name_map.get(code, "")

        market_value = shares * latest_price
        cost_value = shares * avg_cost

        pnl = market_value - cost_value
        pnl_pct = (pnl / cost_value * 100) if cost_value > 0 else 0

        total_value += market_value
        total_cost += cost_value

        allocation_labels.append(f"{code} {name}")
        allocation_values.append(round(market_value, 2))

        details.append({
            "symbol": raw_symbol,
            "code": code,
            "name": name,
            "shares": shares,
            "avg_cost": round(avg_cost, 2),
            "latest_price": round(latest_price, 2),
            "market_value": round(market_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    result = {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "details": details,
        "allocation_labels": allocation_labels,
        "allocation_values": allocation_values,
        "_soft_ts": time.time(),
    }

    cache.set(soft_key, result)
    return result


def _watchlist_offhours_marker_path() -> str:
    cache_dir = getattr(__import__("app.cache", fromlist=["config"]), "config").DISK_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "offhours_watchlist_fallback_date.txt")


def _read_watchlist_offhours_marker() -> str:
    path = _watchlist_offhours_marker_path()
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _write_watchlist_offhours_marker(date_str: str) -> None:
    path = _watchlist_offhours_marker_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(date_str)
    except Exception:
        return


def _fetch_realtime_quote_fallback(code: str):
    AkshareFetcher = None
    try:
        from data_provider.akshare_fetcher import AkshareFetcher  # type: ignore
    except Exception:
        try:
            import sys
            dsa_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "third_party", "daily_stock_analysis")
            if dsa_root not in sys.path:
                sys.path.insert(0, dsa_root)
            from data_provider.akshare_fetcher import AkshareFetcher  # type: ignore
        except Exception as e:
            logger.warning(f"[watchlist] fallback import failed: {e}")
            return None
    try:
        fetcher = AkshareFetcher()
        for source in ("tencent", "sina"):
            try:
                quote = fetcher.get_realtime_quote(code, source=source)
                if quote and quote.price is not None:
                    return quote
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"[watchlist] fallback quote failed: {e}")
    return None


def _parse_stock_list_env() -> list[str]:
    raw = os.getenv("STOCK_LIST", "") or ""
    if not raw.strip():
        return []
    normalized = (
        raw.replace(";", ",")
        .replace("，", ",")
        .replace("、", ",")
    )
    parts = []
    for chunk in normalized.split(","):
        sym = chunk.strip()
        if sym:
            parts.append(sym)
    # de-dup while preserving order
    seen = set()
    ordered: list[str] = []
    for sym in parts:
        if sym in seen:
            continue
        seen.add(sym)
        ordered.append(sym)
    return ordered


def _get_watchlist_symbols() -> list[str]:
    wl = list_watchlist() or []
    if wl:
        return [str(w.get("symbol", "")).strip() for w in wl if str(w.get("symbol", "")).strip()]
    return _parse_stock_list_env()


def _get_watchlist_source() -> str:
    env_list = _parse_stock_list_env()
    wl = list_watchlist() or []
    if env_list and not wl:
        return "env"
    return "db"


def _get_name_map_from_a_list() -> dict[str, str]:
    try:
        df = get_a_stock_list()
        if df is None or df.empty:
            return {}
        # columns are Chinese: 代码/名称
        if "代码" in df.columns and "名称" in df.columns:
            return {
                str(r["代码"]).zfill(6): str(r["名称"])
                for _, r in df.iterrows()
            }
    except Exception:
        return {}
    return {}


def _cleanup_old_logs() -> None:
    log_dir = os.getenv("LOG_DIR", "./logs")
    try:
        retention_days = int(os.getenv("LOG_RETENTION_DAYS", "14"))
    except Exception:
        retention_days = 14
    cutoff = datetime.now() - timedelta(days=retention_days)
    if not os.path.isdir(log_dir):
        return
    for name in os.listdir(log_dir):
        path = os.path.join(log_dir, name)
        try:
            if not os.path.isfile(path):
                continue
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            if mtime < cutoff:
                os.remove(path)
        except Exception:
            continue


_cleanup_old_logs()


def _is_cn_trading_time(now: datetime) -> bool:
    day = now.weekday()  # 0 Mon - 6 Sun
    if day >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (570 <= minutes <= 690) or (780 <= minutes <= 900)


def _pushplus_send(title: str, content: str) -> None:
    token = os.getenv("PUSHPLUS_TOKEN", "").strip()
    if not token:
        return
    topic = os.getenv("PUSHPLUS_TOPIC", "").strip()
    payload = {
        "token": token,
        "title": title,
        "content": content,
    }
    if topic:
        payload["topic"] = topic
    data = parse.urlencode(payload).encode("utf-8")
    req = request.Request("https://www.pushplus.plus/send", data=data, method="POST")
    try:
        request.urlopen(req, timeout=10).read()
    except Exception:
        return


def _collect_alerts(threshold_pct: float) -> list[dict]:
    symbols = _get_watchlist_symbols()
    if not symbols:
        return []
    snap = get_market_snapshot_cached()
    if snap is None or snap.empty:
        return []
    alerts = []
    for sym in symbols:
        code = str(sym).zfill(6)
        row = snap[snap["code"] == code]
        if row.empty:
            continue
        r = row.iloc[0]
        try:
            change_pct = float(r.get("change_pct"))
        except Exception:
            continue
        if abs(change_pct) >= threshold_pct:
            alerts.append({
                "code": code,
                "name": str(r.get("name", "")),
                "price": r.get("price"),
                "change_pct": change_pct,
            })
    return alerts


def _start_alert_thread() -> None:
    global _alert_thread_started
    if _alert_thread_started:
        return
    if os.getenv("ALERT_ENABLED", "false").lower() != "true":
        return
    _alert_thread_started = True

    threshold_pct = float(os.getenv("ALERT_PCT", "5"))
    interval = int(os.getenv("ALERT_CHECK_SEC", "60"))
    push_enabled = os.getenv("ALERT_PUSHPLUS", "true").lower() == "true"
    tz = ZoneInfo("Asia/Shanghai")
    last_sent: dict[str, str] = {}

    def _loop():
        while not _alert_stop_event.is_set():
            now = datetime.now(tz)
            if _is_cn_trading_time(now):
                alerts = _collect_alerts(threshold_pct)
                if alerts and push_enabled:
                    date_key = now.strftime("%Y-%m-%d")
                    lines = []
                    for a in alerts:
                        key = f"{date_key}:{a['code']}"
                        if last_sent.get(key) == "sent":
                            continue
                        last_sent[key] = "sent"
                        lines.append(f"{a['code']} {a['name']} {a['change_pct']:.2f}%")
                    if lines:
                        _pushplus_send("关注股异常波动提醒", "\n".join(lines))
            time.sleep(interval)

    t = threading.Thread(target=_loop, name="watchlist-alert", daemon=True)
    t.start()


# ===============================
# API - 资产刷新
# ===============================
@router.get("/metrics")
async def api_metrics():
    try:
        metrics = calculate_metrics(force_refresh=True)
        return JSONResponse({"ok": True, "metrics": metrics})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ===============================
# API - Agent showcase and health
# ===============================
@router.get("/agent/profile")
async def api_agent_profile():
    try:
        return JSONResponse({"ok": True, "profile": build_agent_profile()})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/agent/health")
async def api_agent_health():
    try:
        return JSONResponse(agent_health())
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "checks": []})


@router.get("/agent/demo-prompts")
async def api_agent_demo_prompts():
    try:
        profile = build_agent_profile()
        return JSONResponse({"ok": True, "demo_questions": profile["demo_questions"]})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "demo_questions": []})


@router.get("/agent/trade-review")
async def api_agent_trade_review(limit: int = Query(30, ge=1, le=200)):
    try:
        return JSONResponse(build_trade_review(limit=limit))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/agent/strategy-advice")
async def api_agent_strategy_advice():
    try:
        return JSONResponse(build_strategy_advice())
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/agent/daily-review")
async def api_agent_daily_review(data: dict | None = None):
    try:
        persist = True
        if isinstance(data, dict) and "persist" in data:
            persist = bool(data.get("persist"))
        return JSONResponse(build_daily_review(persist=persist))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/agent/committee/{symbol}")
async def api_agent_committee(symbol: str):
    try:
        return JSONResponse(build_investment_committee_decision(symbol))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/agent/lessons")
async def api_agent_save_lesson(data: dict):
    try:
        content = (data or {}).get("content", "")
        return JSONResponse(save_lesson(content))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ===============================
# API - 关注股实时行情
# ===============================
@router.get("/watchlist/quotes")
async def api_watchlist_quotes(force: bool = Query(False, description="强制刷新行情")):
    try:
        symbols = _get_watchlist_symbols()
        snap = get_market_snapshot_cached(force_refresh=force)
        name_map = {}

        items = []
        allow_fallback = True
        if not is_cn_trading_time():
            today = datetime.now().strftime("%Y-%m-%d")
            if _read_watchlist_offhours_marker() == today:
                allow_fallback = False
            else:
                _write_watchlist_offhours_marker(today)

        for sym in symbols:
            code = str(sym).zfill(6)
            item = {
                "symbol": code,
                "name": "",
                "price": None,
                "change_pct": None,
            }

            if snap is not None and not snap.empty:
                row = snap[snap["code"] == code]
                if not row.empty:
                    r = row.iloc[0]
                    item["name"] = r["name"]
                    item["price"] = r["price"]
                    item["change_pct"] = r.get("change_pct")
            if not item["name"]:
                if not name_map:
                    name_map = _get_name_map_from_a_list()
                item["name"] = name_map.get(code, "")
            if allow_fallback and (item["price"] is None or item["change_pct"] is None):
                with _watchlist_fallback_lock:
                    quote = _fetch_realtime_quote_fallback(code)
                if quote:
                    if not item["name"]:
                        item["name"] = quote.name or item["name"]
                    item["price"] = quote.price if item["price"] is None else item["price"]
                    item["change_pct"] = quote.change_pct if item["change_pct"] is None else item["change_pct"]

            items.append(item)
        return JSONResponse({"ok": True, "items": items})

    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "items": []})


# ===============================
# API - 关注列表管理
# ===============================
@router.get("/watchlist")
async def api_watchlist():
    symbols = _get_watchlist_symbols()
    return JSONResponse({
        "ok": True,
        "source": _get_watchlist_source(),
        "watchlist": [{"symbol": s, "name": ""} for s in symbols],
    })


@router.post("/holdings/rebuild")
async def api_holdings_rebuild():
    try:
        rebuild_holdings_from_trades()
        metrics = calculate_metrics(force_refresh=True)
        return JSONResponse({"ok": True, "metrics": metrics})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/watchlist/alerts")
async def api_watchlist_alerts_preview():
    try:
        threshold = float(os.getenv("ALERT_PCT", "5"))
        alerts = _collect_alerts(threshold)
        return JSONResponse({"ok": True, "threshold_pct": threshold, "alerts": alerts})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "alerts": []})


@router.post("/watchlist/add")
async def api_watchlist_add(data: dict):
    try:
        symbol = (data or {}).get("symbol", "").strip()
        name = (data or {}).get("name", "").strip()

        if not symbol:
            return JSONResponse({"ok": False, "error": "symbol 不能为空"})

        add_watch(symbol, name=name)
        return JSONResponse({"ok": True, "watchlist": list_watchlist()})

    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/watchlist/remove")
async def api_watchlist_remove(data: dict):
    try:
        symbol = (data or {}).get("symbol", "").strip()
        if not symbol:
            return JSONResponse({"ok": False, "error": "symbol 不能为空"})

        remove_watch(symbol)
        return JSONResponse({"ok": True, "watchlist": list_watchlist()})

    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ===============================
# API - AI 聊天
# ===============================
@router.post("/chat")
async def chat(data: dict):
    try:
        message = (data or {}).get("message", "") or ""
        if not _llm_configured():
            return JSONResponse({
                "ok": False,
                "reply": (
                    "AI assistant is not configured yet. "
                    "Set DEEPSEEK_API_KEY in .env to enable chat. "
                    "The portfolio dashboard and watchlist APIs still work without it."
                ),
            })
        reply = get_bot().ask(message)
        return JSONResponse({"ok": True, "reply": reply})

    except Exception as e:
        return JSONResponse({"ok": False, "reply": str(e)})


app.include_router(router)
_start_alert_thread()


# ===============================
# Web - 组合看板（持仓 + 历史收益）
# ===============================
@app.get("/portfolio/embed")
async def portfolio_page(request: Request):
    metrics = calculate_metrics(force_refresh=True)
    account = build_account_dashboard()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "metrics": metrics,
            "account": account,
        },
    )


@app.get("/agent/profile", response_class=PlainTextResponse)
async def agent_profile_page():
    return render_agent_profile_markdown()


@app.get("/portfolio/")
async def portfolio_slash_redirect():
    return RedirectResponse(url="/portfolio", status_code=307)


def _move_spa_fallback_to_end() -> None:
    """Ensure SPA catch-all route doesn't shadow custom HTML routes."""
    try:
        routes = list(app.router.routes)
        fallback = [r for r in routes if getattr(r, "path", None) == "/{full_path:path}"]
        if not fallback:
            return
        others = [r for r in routes if r not in fallback]
        app.router.routes = others + fallback
    except Exception:
        # If routing internals change, fail open rather than crash startup.
        return


_move_spa_fallback_to_end()
