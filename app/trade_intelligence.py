from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.data_sources import ensure_suffix
from app.portfolio_store import get_holding, get_holdings


DEFAULT_MAX_TRADE_VALUE = 100000.0
DEFAULT_MAX_POSITION_WEIGHT = 0.35


@dataclass
class ParsedTrade:
    symbol: str
    side: str
    shares: float
    price: float
    fee: float = 0.0
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "shares": self.shares,
            "price": self.price,
            "fee": self.fee,
            "note": self.note,
        }


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _max_trade_value() -> float:
    return _safe_float(os.getenv("MAX_TRADE_VALUE"), DEFAULT_MAX_TRADE_VALUE)


def _max_position_weight() -> float:
    return _safe_float(os.getenv("MAX_POSITION_WEIGHT"), DEFAULT_MAX_POSITION_WEIGHT)


def _normalize_side(side_text: str) -> str:
    text = (side_text or "").strip().upper()
    if text in {"BUY", "B", "买", "买入", "加仓"}:
        return "BUY"
    if text in {"SELL", "S", "卖", "卖出", "减仓", "止盈", "止损"}:
        return "SELL"
    return text


def classify_intent(message: str) -> Dict[str, Any]:
    """Classify common portfolio-agent intents with deterministic rules."""
    text = (message or "").strip()
    lowered = text.lower()
    rules = [
        ("record_trade", ["买入", "卖出", "加仓", "减仓", "止盈", "止损", "record trade", "buy ", "sell "]),
        ("portfolio_status", ["持仓", "组合", "仓位", "浮盈", "浮亏", "盈亏"]),
        ("account_review", ["胜率", "回撤", "收益曲线", "账户收益", "交易复盘", "profit factor"]),
        ("watchlist_analysis", ["关注列表", "关注股", "今日建议", "观察重点", "watchlist"]),
        ("investment_plan", ["计划", "提醒", "观察计划", "复盘计划"]),
        ("market_review", ["大盘", "市场复盘", "指数", "market review"]),
    ]
    for intent, keywords in rules:
        if any(keyword in text or keyword in lowered for keyword in keywords):
            return {"intent": intent, "confidence": 0.86, "matched": True}
    if re.search(r"\b\d{6}(?:\.(?:SS|SZ))?\b", text, flags=re.IGNORECASE):
        return {"intent": "stock_analysis", "confidence": 0.72, "matched": True}
    return {"intent": "general_chat", "confidence": 0.45, "matched": False}


def parse_trade_instruction(text: str) -> Dict[str, Any]:
    """
    Parse a single Chinese/English trade instruction into structured fields.

    Supported examples:
    - 10.5买入100股600519
    - 买入 600519 100股 @ 10.5
    - sell 000001 200 @ 9.8
    """
    raw = (text or "").strip()
    patterns = [
        r"(?P<price>\d+(?:\.\d+)?)\s*(?P<side>买入|卖出|加仓|减仓|止盈|止损)\s*(?P<shares>\d+(?:\.\d+)?)\s*股?\s*(?P<symbol>\d{6}(?:\.(?:SS|SZ|ss|sz))?)",
        r"(?P<side>买入|卖出|加仓|减仓|止盈|止损)\s*(?P<symbol>\d{6}(?:\.(?:SS|SZ|ss|sz))?)\s*(?P<shares>\d+(?:\.\d+)?)\s*股?\s*(?:@|于|价格|价)?\s*(?P<price>\d+(?:\.\d+)?)",
        r"(?P<side>buy|sell|BUY|SELL)\s+(?P<symbol>\d{6}(?:\.(?:SS|SZ|ss|sz))?)\s+(?P<shares>\d+(?:\.\d+)?)\s*(?:shares?)?\s*(?:@|at)?\s*(?P<price>\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if not match:
            continue
        try:
            trade = ParsedTrade(
                symbol=ensure_suffix(match.group("symbol")),
                side=_normalize_side(match.group("side")),
                shares=float(match.group("shares")),
                price=float(match.group("price")),
                note=raw,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc), "raw": raw}
        return {"ok": True, "trade": trade.as_dict(), "raw": raw}
    return {
        "ok": False,
        "error": "无法从文本中解析出完整交易指令，需要包含方向、代码、数量和价格。",
        "raw": raw,
    }


def pretrade_risk_check(
    symbol: str,
    side: str,
    shares: float,
    price: float,
    fee: float = 0.0,
) -> Dict[str, Any]:
    """Check deterministic portfolio constraints before a trade is persisted."""
    symbol = ensure_suffix(symbol)
    side = _normalize_side(side)
    shares = float(shares)
    price = float(price)
    fee = float(fee or 0)
    trade_value = shares * price + (fee if side == "BUY" else 0)

    blockers: List[str] = []
    warnings: List[str] = []

    if side not in {"BUY", "SELL"}:
        blockers.append("side must be BUY or SELL")
    if shares <= 0:
        blockers.append("shares must be positive")
    if price <= 0:
        blockers.append("price must be positive")

    max_trade_value = _max_trade_value()
    if trade_value > max_trade_value:
        blockers.append(f"single trade value {trade_value:.2f} exceeds limit {max_trade_value:.2f}")

    holding = get_holding(symbol)
    current_shares = float(holding.get("shares", 0)) if holding else 0.0
    if side == "SELL" and shares > current_shares:
        blockers.append(f"sell shares {shares:.4f} exceed current holding {current_shares:.4f}")

    holdings = get_holdings() or []
    current_cost_total = 0.0
    current_symbol_cost = 0.0
    for item in holdings:
        item_symbol = ensure_suffix(str(item.get("symbol", "")))
        item_cost = float(item.get("shares", 0) or 0) * float(item.get("avg_cost", 0) or 0)
        current_cost_total += item_cost
        if item_symbol == symbol:
            current_symbol_cost += item_cost

    projected_symbol_cost = current_symbol_cost
    projected_total_cost = current_cost_total
    if side == "BUY":
        projected_symbol_cost += trade_value
        projected_total_cost += trade_value
    elif side == "SELL" and holding:
        avg_cost = float(holding.get("avg_cost", 0) or 0)
        cost_reduction = min(shares, current_shares) * avg_cost
        projected_symbol_cost = max(0.0, current_symbol_cost - cost_reduction)
        projected_total_cost = max(0.0, current_cost_total - cost_reduction)

    projected_weight = (projected_symbol_cost / projected_total_cost) if projected_total_cost > 0 else 0.0
    max_weight = _max_position_weight()
    if side == "BUY" and projected_weight > max_weight:
        warnings.append(f"projected position weight {projected_weight:.2%} exceeds guideline {max_weight:.2%}")

    return {
        "ok": not blockers,
        "asof": datetime.now().isoformat(timespec="seconds"),
        "symbol": symbol,
        "side": side,
        "trade_value": round(trade_value, 2),
        "current_shares": current_shares,
        "projected_position_weight": round(projected_weight, 4),
        "limits": {
            "max_trade_value": max_trade_value,
            "max_position_weight": max_weight,
        },
        "blockers": blockers,
        "warnings": warnings,
    }
