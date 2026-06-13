# app/tools.py

import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from math import sqrt
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from langchain_core.tools import tool

# ===============================
# 内部模块（统一使用 app. 前缀，避免相对导入混乱）
# ===============================

from app.cache import cache, logger, config
from app.market_data import get_market_snapshot_cached, norm_code
from app.portfolio_store import (
    init_db,
    get_holdings,
    list_trades,
    add_note,
    list_notes,
    apply_trade,
    list_watchlist,
)
from app.account_analytics import build_account_dashboard
from app.portfolio_analytics import (
    build_portfolio_snapshot,
    compute_portfolio_performance,
)
from app.agent_profile import build_agent_profile, agent_health
from app.trade_intelligence import (
    classify_intent,
    parse_trade_instruction,
    pretrade_risk_check,
)
from app.data_sources import (
    ensure_suffix,
    get_a_stock_list,
    get_stock_history,
    yf_throttle,
)
from app.indicators import calculate_technical_indicators


init_db()


# ===============================
# 组合类工具
# ===============================

@tool
def portfolio_snapshot() -> Dict[str, Any]:
    """组合快照：市值/成本/浮盈亏/仓位占比"""
    return build_portfolio_snapshot(price_period="6mo")


@tool
def portfolio_performance(lookback: str = "1y") -> Dict[str, Any]:
    """组合表现：收益/回撤/波动/夏普"""
    return compute_portfolio_performance(lookback=lookback)


@tool
def portfolio_view() -> str:
    """查看当前持仓"""
    hs = get_holdings()
    if not hs:
        return "当前没有记录到任何持仓。"

    lines = ["当前持仓："]
    for h in hs:
        lines.append(
            f"- {h['symbol']}：{h['shares']} 股，均价 {h['avg_cost']:.4f}"
        )
    return "\n".join(lines)


@tool
def portfolio_record_trade(
    symbol: str,
    side: str,
    shares: float,
    price: float,
    fee: float = 0.0,
    note: str = ""
) -> str:
    """
    记录交易（自动获取股票名称）
    """

    sym = ensure_suffix(symbol)
    risk = pretrade_risk_check(sym, side, shares, price, fee)
    if not risk["ok"]:
        return "交易未记录，风控校验未通过：" + "；".join(risk["blockers"])

    code = sym.split(".")[0]

    # 🔎 自动查股票名称
    name = ""
    df = get_a_stock_list()
    if df is not None and not df.empty:
        match = df[df["代码"].astype(str) == code]
        if not match.empty:
            name = str(match.iloc[0]["名称"])

    # 🔥 正确调用 apply_trade（顺序必须一致）
    apply_trade(
        symbol=sym,
        name=name,
        side=side,
        shares=shares,
        price=price,
        fee=fee,
        note=note,
    )

    return f"✅ 已记录交易：{sym}（{name}） {side} {shares} 股 @ {price}"


@tool
def classify_user_intent_tool(message: str) -> Dict[str, Any]:
    """对用户问题做确定性意图分类，用于选择组合、关注股、交易或复盘工具。"""
    return classify_intent(message)


@tool
def parse_trade_instruction_tool(text: str) -> Dict[str, Any]:
    """从自然语言交易指令中解析方向、股票代码、数量、价格和备注。"""
    return parse_trade_instruction(text)


@tool
def portfolio_pretrade_check(
    symbol: str,
    side: str,
    shares: float,
    price: float,
    fee: float = 0.0,
) -> Dict[str, Any]:
    """交易前风控校验：检查方向、数量、价格、持仓、单笔金额和仓位集中度。"""
    return pretrade_risk_check(symbol, side, shares, price, fee)


@tool
def portfolio_trades(symbol: Optional[str] = None, limit: int = 20) -> str:
    """查看交易记录"""

    sym = ensure_suffix(symbol) if symbol else None
    ts = list_trades(sym, limit=limit)

    if not ts:
        return "暂无交易记录。"

    lines = ["最近交易："]
    for t in ts:
        lines.append(
            f"- [{t['trade_time']}] "
            f"{t['symbol']} {t['side']} {t['shares']} @ {t['price']} "
            f"fee={t['fee']} note={t['note'] or ''}"
        )

    return "\n".join(lines)


@tool
def portfolio_add_plan(content: str) -> str:
    """记录投资计划"""
    add_note("PLAN", content)
    return "✅ 已记录计划。"


@tool
def portfolio_view_plans(limit: int = 20) -> str:
    """查看投资计划"""
    ns = list_notes("PLAN", limit=limit)
    if not ns:
        return "暂无计划记录。"

    lines = ["你的计划："]
    for n in ns:
        lines.append(f"- [{n['created_at']}] {n['content']}")

    return "\n".join(lines)


@tool
def portfolio_record_batch(text: str) -> str:
    """
    解析自然语言中的多笔买卖记录。
    例如：
    我8.84买入100股000989，并9.43卖出；
    """

    import re

    pattern = r'(\d+\.?\d*)买入(\d+)股(\d{6})|(\d+\.?\d*)卖出'

    trades = []
    current_symbol = None
    current_shares = None

    for part in text.split("；"):
        buy_match = re.search(r'(\d+\.?\d*)买入(\d+)股(\d{6})', part)
        sell_match = re.search(r'(\d+\.?\d*)卖出', part)

        if buy_match:
            price = float(buy_match.group(1))
            shares = float(buy_match.group(2))
            symbol = buy_match.group(3)

            current_symbol = symbol
            current_shares = shares

            apply_trade(
                symbol=ensure_suffix(symbol),
                name="",
                side="BUY",
                shares=shares,
                price=price,
            )

        if sell_match and current_symbol:
            sell_price = float(sell_match.group(1))

            apply_trade(
                symbol=ensure_suffix(current_symbol),
                name="",
                side="SELL",
                shares=current_shares,
                price=sell_price,
            )

            current_symbol = None
            current_shares = None

    return "✅ 已解析并记录所有交易"


@tool
def lookup_stock_symbol(company_name: str) -> str:
    """模糊匹配公司名称"""
    stock_list = get_a_stock_list()
    if stock_list is None or stock_list.empty:
        return "暂时无法获取股票列表。"

    matches = stock_list[
        stock_list["名称"].astype(str).str.contains(company_name, na=False)
    ]

    if matches.empty:
        return "未找到匹配公司。"

    lines = []
    for _, row in matches.head(5).iterrows():
        code = ensure_suffix(str(row["代码"]))
        lines.append(f"{code}（{row['名称']}）")

    return "\n".join(lines)
@tool
def get_watchlist() -> str:
    """获取当前关注股票列表（长期存储）"""
    from app.portfolio_store import list_watchlist
    wl = list_watchlist()
    if not wl:
        return "当前没有关注股票。"
    return "当前关注股票：" + ", ".join([x["symbol"] for x in wl])




def _snapshot_df_cached(ttl_seconds: int = 15):
    """
    进程内“秒级软TTL”快照：避免每次 tool 都打数据源。
    你 cache.py 的 DataCache 是分钟 TTL，我们这里自己做秒级。
    """
    key = "market_snapshot_df_soft"
    now = time.time()
    hit = cache.get(key)
    if isinstance(hit, dict) and "ts" in hit and "df" in hit:
        if now - float(hit["ts"]) <= ttl_seconds:
            return hit["df"]

    df = None
    try:
        df = get_a_stock_list()
        if df is None or df.empty:
            cache.set(key, {"ts": now, "df": None})
            return None

        cols = list(df.columns)
        # 兼容：你日志里现在是 ['code','name','price','change_pct']
        if set(["code", "name", "price"]).issubset(cols):
            slim = df.copy()
            cache.set(key, {"ts": now, "df": slim})
            return slim

        # 兼容老列名：['代码','名称','最新价','涨跌幅']
        code_col = "代码" if "代码" in cols else None
        name_col = "名称" if "名称" in cols else None
        price_col = "最新价" if "最新价" in cols else None
        pct_col = "涨跌幅" if "涨跌幅" in cols else None

        if not (code_col and name_col and price_col):
            logger.warning(f"[snapshot] columns not supported: {cols}")
            cache.set(key, {"ts": now, "df": None})
            return None

        use_cols = [code_col, name_col, price_col] + ([pct_col] if pct_col else [])
        slim = df[use_cols].copy()
        slim.columns = ["code", "name", "price"] + (["change_pct"] if pct_col else [])
        cache.set(key, {"ts": now, "df": slim})
        return slim

    except Exception as e:
        logger.warning(f"[snapshot] failed: {e}")
        cache.set(key, {"ts": now, "df": None})
        return None


@tool
def get_watchlist_tool() -> Dict[str, Any]:
    """读取关注列表（长期存储DB）。"""
    wl = list_watchlist() or []
    # 统一成 6 位 code，便于匹配快照
    items = []
    for x in wl:
        sym = norm_code(x.get("symbol", ""))
        items.append({"symbol": sym, "name": (x.get("name") or "").strip()})
    return {"ok": True, "items": items, "count": len(items)}


@tool
def watchlist_snapshot_tool() -> dict:
    """
    获取用户关注股票的实时行情数据。
    """

    watchlist = list_watchlist()
    snap = get_market_snapshot_cached()

    if snap is None or snap.empty:
        return {"ok": False, "items": []}

    # 🔥 关键：统一格式
    snap["code"] = snap["code"].astype(str).apply(norm_code)

    items = []

    for w in watchlist:
        code = norm_code(w["symbol"])

        row = snap[snap["code"] == code]

        if not row.empty:
            r = row.iloc[0]
            items.append({
                "symbol": code,
                "name": r.get("name", ""),
                "price": r.get("price"),
                "change_pct": r.get("change_pct"),
            })
        else:
            items.append({
                "symbol": code,
                "name": w.get("name", ""),
                "price": None,
                "change_pct": None,
            })

    return {"ok": True, "items": items}


def _max_drawdown(equity: pd.Series) -> float:
    """最大回撤（负数）"""
    if equity is None or equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = (equity / peak) - 1.0
    return float(dd.min())

def _annual_vol(returns: pd.Series) -> float:
    """年化波动率"""
    if returns is None or returns.empty:
        return 0.0
    return float(returns.std() * sqrt(252))

def _safe_num(x):
    try:
        if x is None:
            return None
        if pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None

@tool
def watchlist_analysis_tool(
    period: str = "6mo",
    limit: int = 20,
    use_cache_minutes: int = 15,
) -> Dict[str, Any]:
    """
    关注股量化分析（自动拉历史K线 + 技术指标 + 风险指标）。
    返回：每只关注股的最新价/涨跌幅/MA20/MA60/RSI/MACD/波动率/最大回撤/趋势判断/信号。
    """
    wl = list_watchlist() or []
    if not wl:
        return {"ok": True, "items": [], "count": 0, "note": "关注列表为空"}

    wl = wl[: max(1, int(limit))]

    # 先拿实时快照（用于最新价/涨跌幅）
    snap = get_market_snapshot_cached()
    price_map, pct_map, name_map = {}, {}, {}
    if snap is not None and not snap.empty:
        # snap 约定列：code/name/price/change_pct
        for _, r in snap.iterrows():
            c = norm_code(r.get("code"))
            if not c:
                continue
            name_map[c] = str(r.get("name") or "").strip()
            price_map[c] = _safe_num(r.get("price"))
            pct_map[c] = _safe_num(r.get("change_pct"))

    items: List[Dict[str, Any]] = []
    now_ts = time.time()
    ttl_sec = max(60, int(use_cache_minutes) * 60)

    for w in wl:
        code = norm_code(w.get("symbol"))
        display_name = (w.get("name") or "").strip() or name_map.get(code, "")

        # —— per-symbol 缓存（避免频繁打历史接口）
        ck = f"watch_an_{code}_{period}"
        cached = cache.get(ck)
        if isinstance(cached, dict) and cached.get("_ts") and (now_ts - float(cached["_ts"]) <= ttl_sec):
            items.append(cached["item"])
            continue

        # 拉历史K线（这是你真正需要的“走势基础”）
        hist = None
        try:
            # 注意：你的 get_stock_history 需要带 .SS/.SZ 后缀
            sym = ensure_suffix(code)
            hist = get_stock_history(sym, period)
        except Exception:
            hist = None

        # 默认输出（即使历史失败，也能返回实时价/涨跌幅）
        out: Dict[str, Any] = {
            "symbol": code,
            "name": display_name,
            "price": price_map.get(code),
            "change_pct": pct_map.get(code),
            "trend": "N/A",
            "signal": "N/A",
            "ma20": None,
            "ma60": None,
            "rsi": None,
            "macd": None,
            "macd_signal": None,
            "volatility": None,
            "max_drawdown": None,
            "asof": datetime.now().isoformat(),
            "history_ok": False,
        }

        if hist is None or hist.empty or len(hist) < 40:
            # 历史不足：只返回实时快照（LLM 会提示“历史不足无法算指标”）
            cache.set(ck, {"_ts": now_ts, "item": out})
            items.append(out)
            continue

        # 计算技术指标（你已有 calculate_technical_indicators）
        tech = calculate_technical_indicators(hist) or {}
        rsi = _safe_num(tech.get("rsi"))
        ma20 = _safe_num(tech.get("ma_20"))
        ma50 = _safe_num(tech.get("ma_50"))
        ma60 = None

        # 你 indicators 里未必算 ma60，我们这里补一个
        try:
            ma60 = float(hist["Close"].rolling(60).mean().iloc[-1]) if len(hist) >= 60 else None
        except Exception:
            ma60 = None

        # MACD（如果你的 indicators 返回了就用，否则自己简单算）
        macd = _safe_num(tech.get("macd"))
        macd_sig = _safe_num(tech.get("macd_signal"))
        if macd is None or macd_sig is None:
            try:
                close = hist["Close"].astype(float)
                ema12 = close.ewm(span=12, adjust=False).mean()
                ema26 = close.ewm(span=26, adjust=False).mean()
                dif = ema12 - ema26
                dea = dif.ewm(span=9, adjust=False).mean()
                macd = float(dif.iloc[-1])
                macd_sig = float(dea.iloc[-1])
            except Exception:
                macd, macd_sig = None, None

        # 风险指标：波动率 / 最大回撤
        try:
            rets = hist["Close"].astype(float).pct_change().dropna()
            vol = _annual_vol(rets)
            eq = (1.0 + rets).cumprod()
            mdd = _max_drawdown(eq)
        except Exception:
            vol, mdd = None, None

        # 趋势判断（简洁、可解释）
        trend = "震荡"
        if ma20 is not None and ma60 is not None:
            if ma20 > ma60:
                trend = "上升"
            elif ma20 < ma60:
                trend = "下降"

        # 信号（简单但实用）
        signal = "观望"
        if rsi is not None:
            if rsi >= 70:
                signal = "偏热（分批止盈/谨慎追高）"
            elif rsi <= 30:
                signal = "偏冷（小仓试探/等企稳）"

        if macd is not None and macd_sig is not None:
            if macd > macd_sig and trend == "上升" and signal == "观望":
                signal = "偏强（回踩分批布局）"
            if macd < macd_sig and trend == "下降":
                signal = "偏弱（反弹减仓/设止损）"

        out.update(
            {
                "history_ok": True,
                "ma20": ma20,
                "ma60": ma60,
                "rsi": rsi,
                "macd": macd,
                "macd_signal": macd_sig,
                "volatility": vol,
                "max_drawdown": mdd,
                "trend": trend,
                "signal": signal,
            }
        )

        cache.set(ck, {"_ts": now_ts, "item": out})
        items.append(out)

    return {"ok": True, "count": len(items), "items": items, "period": period, "asof": datetime.now().isoformat()}


@tool
def account_dashboard_tool() -> Dict[str, Any]:
    """账户收益统计（完全不拉历史，仅按 trades 计算：已实现收益/胜率/净值曲线等）。"""
    data = build_account_dashboard()
    # 确保返回 JSON-safe
    return {"ok": True, "data": data}


@tool
def agent_profile_tool() -> Dict[str, Any]:
    """返回智能体能力画像、记忆状态、可展示示例问题和项目状态。"""
    return {"ok": True, "profile": build_agent_profile()}


@tool
def agent_health_tool() -> Dict[str, Any]:
    """检查智能体运行健康状态，不泄露任何 API key 或私密配置值。"""
    return agent_health()


@tool
def dsa_analyze_stock_tool(
    symbol: str,
    report_type: str = "detailed",
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """深度分析单只股票（支持 A/H/US）。"""
    try:
        from app.dsa_bridge import dsa_analyze_stock

        result = dsa_analyze_stock(
            stock_code=symbol,
            report_type=report_type,
            force_refresh=force_refresh,
            send_notification=False,
        )
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool
def dsa_analyze_watchlist_tool(
    report_type: str = "detailed",
    force_refresh: bool = False,
    limit: int = 20,
) -> Dict[str, Any]:
    """深度分析关注列表 + 持仓（支持 A/H/US）。"""
    try:
        from app.dsa_bridge import dsa_analyze_watchlist

        results = dsa_analyze_watchlist(
            report_type=report_type,
            force_refresh=force_refresh,
            limit=limit,
            send_notification=False,
        )
        return {"ok": True, "items": results, "count": len(results)}
    except Exception as e:
        return {"ok": False, "error": str(e), "items": []}


@tool
def dsa_market_review_tool(region: str = "cn") -> Dict[str, Any]:
    """大盘复盘（cn/us/both）。"""
    try:
        from app.dsa_bridge import dsa_market_review

        report = dsa_market_review(region=region, send_notification=False)
        return {"ok": True, "region": region, "report": report}
    except Exception as e:
        return {"ok": False, "error": str(e), "region": region}
# ===============================
# 工具注册列表
# ===============================

toolbox = [
    portfolio_snapshot,
    portfolio_performance,
    portfolio_view,
    classify_user_intent_tool,
    parse_trade_instruction_tool,
    portfolio_pretrade_check,
    portfolio_record_trade,
    portfolio_trades,
    portfolio_add_plan,
    portfolio_view_plans,
    lookup_stock_symbol,
    portfolio_record_batch,
    get_watchlist,
    get_watchlist_tool,
    watchlist_snapshot_tool,
    watchlist_analysis_tool,
    account_dashboard_tool,
    agent_profile_tool,
    agent_health_tool,
    dsa_analyze_stock_tool,
    dsa_analyze_watchlist_tool,
    dsa_market_review_tool,
]
