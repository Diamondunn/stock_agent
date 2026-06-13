from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from app.data_sources import ensure_suffix, get_stock_history
from app.indicators import calculate_technical_indicators
from app.portfolio_store import get_holding, get_holdings, list_notes
from app.trade_review import build_trade_review


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _technical_snapshot(symbol: str, history_provider: Optional[Callable[[str, str], Any]] = None) -> Dict[str, Any]:
    provider = history_provider or get_stock_history
    try:
        hist = provider(symbol, "6mo")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "history_ok": False}

    if hist is None or getattr(hist, "empty", True) or "Close" not in hist.columns:
        return {"ok": False, "history_ok": False, "error": "history data unavailable"}

    try:
        close = hist["Close"].astype(float)
        tech = calculate_technical_indicators(hist) or {}
        ma20 = _safe_float(tech.get("ma_20"))
        ma50 = _safe_float(tech.get("ma_50"))
        rsi = _safe_float(tech.get("rsi"), 50.0)
        macd = tech.get("macd")
        macd_signal = tech.get("macd_signal")
        if macd is None or macd_signal is None:
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            dif = ema12 - ema26
            dea = dif.ewm(span=9, adjust=False).mean()
            macd = float(dif.iloc[-1])
            macd_signal = float(dea.iloc[-1])
        returns = close.pct_change().dropna()
        max_drawdown = 0.0
        if not returns.empty:
            nav = (1.0 + returns).cumprod()
            max_drawdown = float(((nav - nav.cummax()) / nav.cummax()).min())
        return {
            "ok": True,
            "history_ok": True,
            "price": round(float(close.iloc[-1]), 4),
            "ma20": round(ma20, 4) if ma20 else None,
            "ma50": round(ma50, 4) if ma50 else None,
            "rsi": round(rsi, 2),
            "macd": round(_safe_float(macd), 4),
            "macd_signal": round(_safe_float(macd_signal), 4),
            "max_drawdown": round(max_drawdown, 4),
            "bars": int(len(hist)),
        }
    except Exception as exc:
        return {"ok": False, "history_ok": False, "error": str(exc)}


def _score_technical(technical: Dict[str, Any]) -> Dict[str, Any]:
    if not technical.get("history_ok"):
        return {
            "role": "technical_analyst",
            "score": 0,
            "stance": "neutral",
            "evidence": ["历史行情不足，技术面保持中性。"],
        }

    score = 0
    evidence: List[str] = []
    price = _safe_float(technical.get("price"))
    ma20 = technical.get("ma20")
    ma50 = technical.get("ma50")
    rsi = _safe_float(technical.get("rsi"), 50.0)
    macd = _safe_float(technical.get("macd"))
    macd_signal = _safe_float(technical.get("macd_signal"))

    if ma20 and ma50:
        if price > ma20 > ma50:
            score += 2
            evidence.append("价格站上 MA20 且 MA20 高于 MA50，趋势结构偏强。")
        elif price < ma20 < ma50:
            score -= 2
            evidence.append("价格低于 MA20 且 MA20 低于 MA50，趋势结构偏弱。")
    if rsi >= 72:
        score -= 1
        evidence.append("RSI 偏热，追高风险上升。")
    elif rsi <= 30:
        score += 1
        evidence.append("RSI 偏冷，存在反弹观察价值。")
    if macd > macd_signal:
        score += 1
        evidence.append("MACD 位于信号线上方，动量偏正。")
    elif macd < macd_signal:
        score -= 1
        evidence.append("MACD 位于信号线下方，动量偏弱。")

    return {
        "role": "technical_analyst",
        "score": max(-3, min(3, score)),
        "stance": "bullish" if score > 0 else "bearish" if score < 0 else "neutral",
        "evidence": evidence or ["技术指标没有给出明确方向。"],
    }


def _score_risk(symbol: str) -> Dict[str, Any]:
    holdings = get_holdings() or []
    total_cost = 0.0
    symbol_cost = 0.0
    symbol = ensure_suffix(symbol)
    for item in holdings:
        shares = _safe_float(item.get("shares"))
        avg_cost = _safe_float(item.get("avg_cost"))
        cost = shares * avg_cost
        total_cost += cost
        if ensure_suffix(str(item.get("symbol", ""))) == symbol:
            symbol_cost += cost
    weight = symbol_cost / total_cost if total_cost > 0 else 0.0

    score = 0
    evidence: List[str] = []
    if weight >= 0.35:
        score -= 2
        evidence.append(f"当前成本仓位占比 {weight:.1%}，存在集中度风险。")
    elif weight >= 0.2:
        score -= 1
        evidence.append(f"当前成本仓位占比 {weight:.1%}，加仓需谨慎。")
    elif symbol_cost > 0:
        evidence.append(f"已有持仓，成本仓位占比 {weight:.1%}。")
    else:
        evidence.append("当前未持有该标的，仓位集中度压力较低。")

    return {
        "role": "risk_manager",
        "score": score,
        "stance": "risk_off" if score < 0 else "neutral",
        "evidence": evidence,
        "position_weight": round(weight, 4),
    }


def _score_memory(symbol: str, review: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    review = review or build_trade_review(limit=10)
    symbol = ensure_suffix(symbol)
    stats = next((x for x in review.get("symbol_stats", []) if x.get("symbol") == symbol), None)
    stored_lessons = list_notes("LESSON", limit=5)
    score = 0
    evidence: List[str] = []

    if stats:
        if _safe_float(stats.get("total_pnl")) > 0 and _safe_float(stats.get("win_rate")) >= 50:
            score += 1
            evidence.append("该标的历史闭合交易贡献为正，交易记忆略偏支持。")
        elif _safe_float(stats.get("total_pnl")) < 0:
            score -= 2
            evidence.append("该标的历史闭合交易贡献为负，需要更严格触发条件。")
        evidence.append(
            f"历史闭合 {stats.get('closed_trades')} 笔，胜率 {stats.get('win_rate')}%，累计盈亏 {stats.get('total_pnl')}。"
        )
    else:
        evidence.append("该标的没有可用闭合交易记忆。")

    if stored_lessons:
        evidence.append(f"长期经验记忆 {len(stored_lessons)} 条，可用于约束交易纪律。")

    return {
        "role": "memory_reviewer",
        "score": max(-3, min(3, score)),
        "stance": "supportive" if score > 0 else "cautious" if score < 0 else "neutral",
        "evidence": evidence,
    }


def build_investment_committee_decision(
    symbol: str,
    history_provider: Optional[Callable[[str, str], Any]] = None,
    technical_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Lightweight multi-role decision layer inspired by popular trading-agent repos.
    It is deterministic and explainable: no model call, no trade execution.
    """
    symbol = ensure_suffix(symbol)
    technical = technical_override or _technical_snapshot(symbol, history_provider=history_provider)
    technical_vote = _score_technical(technical)
    risk_vote = _score_risk(symbol)
    memory_vote = _score_memory(symbol)

    votes = [technical_vote, risk_vote, memory_vote]
    total_score = sum(int(v.get("score", 0)) for v in votes)
    evidence_count = sum(len(v.get("evidence", [])) for v in votes)
    history_ok = bool(technical.get("history_ok"))
    confidence = "low"
    if history_ok and (evidence_count >= 4 or abs(total_score) >= 2):
        confidence = "medium"
    if history_ok and abs(total_score) >= 4 and evidence_count >= 4:
        confidence = "high"

    if total_score >= 3:
        action = "BUY_CANDIDATE"
    elif total_score <= -3:
        action = "AVOID_OR_REDUCE"
    else:
        action = "WATCH"

    holding = get_holding(symbol)
    return {
        "ok": True,
        "asof": datetime.now().isoformat(timespec="seconds"),
        "symbol": symbol,
        "action": action,
        "score": total_score,
        "confidence": confidence,
        "has_position": holding is not None,
        "technical": technical,
        "votes": votes,
        "next_steps": _next_steps(action, holding is not None),
    }


def _next_steps(action: str, has_position: bool) -> List[str]:
    if action == "BUY_CANDIDATE":
        return [
            "先运行 portfolio_pretrade_check 校验单笔金额和仓位集中度。",
            "只考虑分批建仓，不把建议直接转成自动下单。",
            "写入买入理由和失效条件，便于后续复盘。",
        ]
    if action == "AVOID_OR_REDUCE":
        if has_position:
            return ["复核持仓理由是否仍成立。", "若趋势和交易记忆同时偏弱，考虑降仓或设置更紧的止损。"]
        return ["暂不加入买入候选，等待趋势、风险或交易记忆改善。"]
    return ["保持观察，等待技术面、风险面或交易记忆给出更一致信号。"]
