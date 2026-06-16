from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

from app.portfolio_store import add_note, list_notes, list_trades


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _parse_time(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return datetime.min


def _days_between(start: Any, end: Any) -> int:
    s = _parse_time(start)
    e = _parse_time(end)
    if s == datetime.min or e == datetime.min:
        return 0
    return max(0, (e - s).days)


def _build_round_trips() -> List[Dict[str, Any]]:
    trades = list_trades(limit=100000)
    trades = sorted(trades, key=lambda x: (_parse_time(x.get("trade_time")), int(x.get("id", 0) or 0)))
    lots: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    closed: List[Dict[str, Any]] = []

    for trade in trades:
        symbol = str(trade.get("symbol") or "").strip()
        side = str(trade.get("side") or "").upper()
        shares = _safe_float(trade.get("shares"))
        price = _safe_float(trade.get("price"))
        fee = _safe_float(trade.get("fee"))
        if not symbol or shares <= 0 or price <= 0:
            continue

        if side == "BUY":
            lots[symbol].append(
                {
                    "shares": shares,
                    "price": price,
                    "fee": fee,
                    "time": trade.get("trade_time"),
                    "note": trade.get("note") or "",
                }
            )
            continue

        if side != "SELL":
            continue

        remaining = shares
        sell_fee_left = fee
        while remaining > 1e-9 and lots[symbol]:
            lot = lots[symbol][0]
            matched = min(remaining, lot["shares"])
            buy_fee_alloc = lot["fee"] * (matched / lot["shares"]) if lot["shares"] > 0 else 0.0
            sell_fee_alloc = sell_fee_left * (matched / remaining) if remaining > 0 else 0.0
            pnl = (price - lot["price"]) * matched - buy_fee_alloc - sell_fee_alloc
            pnl_pct = (price - lot["price"]) / lot["price"] if lot["price"] > 0 else 0.0

            closed.append(
                {
                    "symbol": symbol,
                    "shares": round(matched, 4),
                    "buy_price": round(lot["price"], 4),
                    "sell_price": round(price, 4),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "holding_days": _days_between(lot["time"], trade.get("trade_time")),
                    "buy_time": lot["time"],
                    "sell_time": trade.get("trade_time"),
                    "buy_note": lot["note"],
                    "sell_note": trade.get("note") or "",
                }
            )

            lot["shares"] -= matched
            remaining -= matched
            sell_fee_left = max(0.0, sell_fee_left - sell_fee_alloc)
            if lot["shares"] <= 1e-9:
                lots[symbol].pop(0)

    return closed


def _avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _symbol_stats(round_trips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in round_trips:
        grouped[item["symbol"]].append(item)

    stats = []
    for symbol, rows in grouped.items():
        pnl_values = [_safe_float(x.get("pnl")) for x in rows]
        wins = [x for x in rows if _safe_float(x.get("pnl")) > 0]
        losses = [x for x in rows if _safe_float(x.get("pnl")) <= 0]
        stats.append(
            {
                "symbol": symbol,
                "closed_trades": len(rows),
                "win_rate": round(len(wins) / len(rows) * 100, 2) if rows else 0,
                "total_pnl": round(sum(pnl_values), 2),
                "avg_pnl": round(_avg(pnl_values), 2),
                "avg_holding_days": round(_avg([_safe_float(x.get("holding_days")) for x in rows]), 2),
                "loss_count": len(losses),
            }
        )
    stats.sort(key=lambda x: (x["total_pnl"], x["win_rate"]), reverse=True)
    return stats


def _generate_lessons(round_trips: List[Dict[str, Any]], symbol_stats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    lessons: List[Dict[str, Any]] = []
    closed_count = len(round_trips)
    wins = [x for x in round_trips if _safe_float(x.get("pnl")) > 0]
    losses = [x for x in round_trips if _safe_float(x.get("pnl")) <= 0]
    win_rate = len(wins) / closed_count if closed_count else 0.0
    avg_win = _avg([_safe_float(x.get("pnl_pct")) for x in wins])
    avg_loss = _avg([_safe_float(x.get("pnl_pct")) for x in losses])

    if closed_count < 5:
        lessons.append(
            {
                "type": "data_quality",
                "severity": "info",
                "lesson": "已完成交易样本较少，策略建议应先作为观察假设，不宜过度拟合。",
            }
        )
    if closed_count and win_rate < 0.45:
        lessons.append(
            {
                "type": "entry_quality",
                "severity": "warning",
                "lesson": "历史完成交易胜率偏低，下一阶段应提高入场条件，例如只在趋势和风险收益比同时满足时交易。",
            }
        )
    if losses and abs(avg_loss) > max(avg_win, 0.01):
        lessons.append(
            {
                "type": "risk_reward",
                "severity": "warning",
                "lesson": "平均亏损幅度大于平均盈利幅度，建议预先设置止损线，并减少亏损单补仓。",
            }
        )

    slow_losses = [x for x in losses if _safe_float(x.get("holding_days")) >= 20]
    if slow_losses:
        lessons.append(
            {
                "type": "holding_period",
                "severity": "warning",
                "lesson": "存在持有较久后仍亏损的交易，建议建立时间止损：若持仓超过20个自然日仍未验证买入逻辑，应复盘或降仓。",
            }
        )

    weak_symbols = [x for x in symbol_stats if x["closed_trades"] >= 2 and x["total_pnl"] < 0]
    if weak_symbols:
        symbols = ", ".join([x["symbol"] for x in weak_symbols[:5]])
        lessons.append(
            {
                "type": "symbol_filter",
                "severity": "warning",
                "lesson": f"这些标的历史交易贡献为负：{symbols}。再次交易前需要更严格的触发条件。",
            }
        )

    if not lessons:
        lessons.append(
            {
                "type": "baseline",
                "severity": "info",
                "lesson": "当前交易记录没有暴露明显单一问题，建议继续记录买入理由和卖出理由，提高后续复盘质量。",
            }
        )
    return lessons


def build_trade_review(limit: int = 30) -> Dict[str, Any]:
    round_trips = _build_round_trips()
    symbol_stats = _symbol_stats(round_trips)
    lessons = _generate_lessons(round_trips, symbol_stats)

    wins = [x for x in round_trips if _safe_float(x.get("pnl")) > 0]
    losses = [x for x in round_trips if _safe_float(x.get("pnl")) <= 0]
    gross_profit = sum(_safe_float(x.get("pnl")) for x in wins)
    gross_loss = abs(sum(_safe_float(x.get("pnl")) for x in losses))

    summary = {
        "closed_trades": len(round_trips),
        "win_rate": round(len(wins) / len(round_trips) * 100, 2) if round_trips else 0,
        "total_pnl": round(gross_profit - gross_loss, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "avg_win_pct": round(_avg([_safe_float(x.get("pnl_pct")) for x in wins]), 2),
        "avg_loss_pct": round(_avg([_safe_float(x.get("pnl_pct")) for x in losses]), 2),
        "avg_holding_days": round(_avg([_safe_float(x.get("holding_days")) for x in round_trips]), 2),
    }

    return {
        "ok": True,
        "asof": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "lessons": lessons,
        "symbol_stats": symbol_stats,
        "recent_round_trips": round_trips[-limit:],
        "stored_lessons": list_notes("LESSON", limit=20),
    }


def build_strategy_advice() -> Dict[str, Any]:
    review = build_trade_review(limit=10)
    summary = review["summary"]
    rules = [
        "每次交易必须写入买入理由、失效条件和计划持有周期。",
        "交易前运行 portfolio_pretrade_check，阻断超额卖出和过大单笔交易。",
        "若单一标的历史贡献为负，再次买入必须降低仓位或等待更强确认信号。",
    ]
    if summary["closed_trades"] >= 5 and summary["profit_factor"] is not None and summary["profit_factor"] < 1:
        rules.append("在 profit factor 重新高于 1 之前，降低单笔风险预算并优先做小仓验证。")
    if summary["avg_loss_pct"] < 0 and abs(summary["avg_loss_pct"]) > max(summary["avg_win_pct"], 0.01):
        rules.append("将止损线前置到下单计划中，避免亏损单拖长为大亏。")
    if summary["avg_holding_days"] > 20:
        rules.append("增加时间止损：超过20天未兑现买入逻辑时，需要复盘或减仓。")

    return {
        "ok": True,
        "asof": datetime.now().isoformat(timespec="seconds"),
        "basis": summary,
        "rules": rules,
        "lessons": review["lessons"],
    }


def _note_exists_for_today(category: str, marker: str, today: date) -> bool:
    today_prefix = today.isoformat()
    for note in list_notes(category, limit=200):
        created_at = str(note.get("created_at") or "")
        content = str(note.get("content") or "")
        if created_at.startswith(today_prefix) and marker in content:
            return True
    return False


def build_daily_review(persist: bool = True, today: date | None = None) -> Dict[str, Any]:
    """
    Build a daily review and optionally persist durable lessons.
    The write path is idempotent per day to avoid duplicate memory entries.
    """
    today = today or date.today()
    review = build_trade_review(limit=10)
    advice = build_strategy_advice()
    summary = review["summary"]
    marker = f"[daily-review:{today.isoformat()}]"
    saved_notes: List[Dict[str, Any]] = []

    headline = (
        f"{marker} 闭合交易 {summary['closed_trades']} 笔，胜率 {summary['win_rate']}%，"
        f"总收益 {summary['total_pnl']}，平均持仓 {summary['avg_holding_days']} 天。"
    )
    generated_lessons = review.get("lessons", [])
    action_items = [
        "继续为每笔交易记录买入理由、失效条件和卖出理由。",
        "交易前运行 portfolio_pretrade_check，避免超额卖出和仓位过度集中。",
    ]
    for lesson in generated_lessons[:3]:
        text = str(lesson.get("lesson") or "").strip()
        if text and text not in action_items:
            action_items.append(text)

    if persist:
        if not _note_exists_for_today("DAILY_REVIEW", marker, today):
            add_note("DAILY_REVIEW", headline)
            saved_notes.append({"category": "DAILY_REVIEW", "content": headline})

        for item in action_items[:4]:
            lesson_text = f"{marker} {item}"
            if not _note_exists_for_today("LESSON", lesson_text, today):
                add_note("LESSON", lesson_text)
                saved_notes.append({"category": "LESSON", "content": lesson_text})

    return {
        "ok": True,
        "asof": datetime.now().isoformat(timespec="seconds"),
        "date": today.isoformat(),
        "persisted": bool(persist),
        "summary": summary,
        "headline": headline,
        "action_items": action_items,
        "strategy_rules": advice.get("rules", []),
        "saved_notes": saved_notes,
        "stored_lessons": list_notes("LESSON", limit=20),
    }


def save_lesson(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {"ok": False, "error": "lesson content is empty"}
    add_note("LESSON", text)
    return {"ok": True, "lesson": text}
