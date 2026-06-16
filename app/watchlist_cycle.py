from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data_sources import ensure_suffix
from app.investment_committee import build_investment_committee_decision
from app.market_data import get_market_snapshot_cached, norm_code
from app.portfolio_store import add_note, get_holding, list_notes, list_watchlist


DECISION_CATEGORY = "WATCHLIST_DECISION"
REVIEW_CATEGORY = "WATCHLIST_REVIEW"


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _marker(prefix: str, day: date) -> str:
    return f"[{prefix}:{day.isoformat()}]"


def _load_json_notes(category: str, limit: int = 100) -> List[Dict[str, Any]]:
    rows = []
    for note in list_notes(category, limit=limit):
        content = str(note.get("content") or "")
        try:
            payload = json.loads(content)
        except Exception:
            continue
        if isinstance(payload, dict):
            payload["_note_id"] = note.get("id")
            payload["_created_at"] = note.get("created_at")
            rows.append(payload)
    return rows


def _note_exists(category: str, marker: str) -> bool:
    return any(marker in str(note.get("content") or "") for note in list_notes(category, limit=200))


def _quote_map() -> Dict[str, Dict[str, Any]]:
    snap = get_market_snapshot_cached()
    if snap is None or getattr(snap, "empty", True):
        return {}
    quotes: Dict[str, Dict[str, Any]] = {}
    for _, row in snap.iterrows():
        code = norm_code(row.get("code"))
        if not code:
            continue
        quotes[code] = {
            "price": _safe_float(row.get("price")),
            "change_pct": _safe_float(row.get("change_pct")),
            "name": str(row.get("name") or "").strip(),
        }
    return quotes


def _quote_code(symbol: Any) -> str:
    raw = str(symbol or "").strip().upper()
    if "." in raw:
        raw = raw.split(".", 1)[0]
    return norm_code(raw)


def _decision_action(committee: Dict[str, Any], has_position: bool) -> str:
    action = committee.get("action")
    if action == "BUY_CANDIDATE":
        return "ADD" if has_position else "BUY_CANDIDATE"
    if action == "AVOID_OR_REDUCE":
        return "REDUCE" if has_position else "AVOID"
    return "WATCH"


def _action_label(action: str) -> str:
    return {
        "ADD": "加仓候选",
        "BUY_CANDIDATE": "建仓候选",
        "REDUCE": "减仓/降风险",
        "AVOID": "回避",
        "WATCH": "观察",
    }.get(action, "观察")


def _extract_price(symbol: str, committee: Dict[str, Any], quotes: Dict[str, Dict[str, Any]]) -> Optional[float]:
    code = _quote_code(symbol)
    quote_price = _safe_float((quotes.get(code) or {}).get("price"))
    if quote_price is not None:
        return quote_price
    technical = committee.get("technical") or {}
    return _safe_float(technical.get("price"))


def build_watchlist_decisions(persist: bool = True, today: date | None = None) -> Dict[str, Any]:
    today = today or date.today()
    marker = _marker("watchlist-decision", today)
    watchlist = list_watchlist() or []
    quotes = _quote_map()
    decisions: List[Dict[str, Any]] = []

    for item in watchlist:
        raw_symbol = str(item.get("symbol") or "").strip()
        if not raw_symbol:
            continue
        symbol = ensure_suffix(raw_symbol)
        committee = build_investment_committee_decision(symbol)
        has_position = get_holding(symbol) is not None
        action = _decision_action(committee, has_position)
        price = _extract_price(raw_symbol, committee, quotes)
        quote = quotes.get(_quote_code(raw_symbol)) or {}
        decisions.append(
            {
                "symbol": symbol,
                "name": quote.get("name") or item.get("name") or "",
                "action": action,
                "action_label": _action_label(action),
                "score": committee.get("score"),
                "confidence": committee.get("confidence"),
                "has_position": has_position,
                "price": price,
                "change_pct": quote.get("change_pct"),
                "reason": (committee.get("coordinator") or {}).get("rationale")
                or "基于投研委员会综合判断。",
                "next_steps": committee.get("next_steps", []),
            }
        )

    payload = {
        "ok": True,
        "date": today.isoformat(),
        "asof": datetime.now().isoformat(timespec="seconds"),
        "marker": marker,
        "count": len(decisions),
        "items": decisions,
    }
    if persist and decisions and not _note_exists(DECISION_CATEGORY, marker):
        add_note(DECISION_CATEGORY, json.dumps(payload, ensure_ascii=False, sort_keys=True))
        payload["persisted"] = True
    else:
        payload["persisted"] = False
    return payload


def _latest_decision_before(today: date) -> Optional[Dict[str, Any]]:
    candidates = []
    for payload in _load_json_notes(DECISION_CATEGORY, limit=200):
        try:
            payload_date = date.fromisoformat(str(payload.get("date")))
        except Exception:
            continue
        if payload_date < today:
            candidates.append((payload_date, payload))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _review_item(previous: Dict[str, Any], current: Optional[float]) -> Dict[str, Any]:
    start = _safe_float(previous.get("price"))
    action = str(previous.get("action") or "WATCH")
    if start is None or current is None or start <= 0:
        status = "PENDING_DATA"
        change_pct = None
        comment = "缺少决策日或复盘日价格，暂不评价。"
    else:
        change_pct = round((current - start) / start * 100, 2)
        if action in {"ADD", "BUY_CANDIDATE"}:
            status = "HIT" if change_pct > 0 else "MISS"
            comment = "上涨验证了偏积极判断。" if status == "HIT" else "价格走弱，需复核加仓/建仓条件。"
        elif action in {"REDUCE", "AVOID"}:
            status = "HIT" if change_pct < 0 else "MISS"
            comment = "走弱验证了防守判断。" if status == "HIT" else "价格走强，需复核过度保守的可能。"
        else:
            status = "STABLE" if abs(change_pct) <= 1 else "MISSED_MOVE"
            comment = "观察判断基本匹配震荡。" if status == "STABLE" else "观察后出现较大波动，需补充触发条件。"

    return {
        "symbol": previous.get("symbol"),
        "name": previous.get("name", ""),
        "previous_action": action,
        "previous_action_label": previous.get("action_label") or _action_label(action),
        "previous_price": start,
        "current_price": current,
        "change_pct": change_pct,
        "status": status,
        "comment": comment,
    }


def review_previous_watchlist_decisions(persist: bool = True, today: date | None = None) -> Dict[str, Any]:
    today = today or date.today()
    marker = _marker("watchlist-review", today)
    previous = _latest_decision_before(today)
    if not previous:
        return {
            "ok": True,
            "date": today.isoformat(),
            "asof": datetime.now().isoformat(timespec="seconds"),
            "reviewed_date": None,
            "items": [],
            "summary": {"hit": 0, "miss": 0, "pending": 0},
            "persisted": False,
            "note": "没有找到今天以前的关注列表决策记录。",
        }

    quotes = _quote_map()
    items = []
    for item in previous.get("items", []):
        code = _quote_code(item.get("symbol"))
        current = _safe_float((quotes.get(code) or {}).get("price"))
        items.append(_review_item(item, current))

    summary = {
        "hit": sum(1 for item in items if item["status"] == "HIT"),
        "miss": sum(1 for item in items if item["status"] in {"MISS", "MISSED_MOVE"}),
        "pending": sum(1 for item in items if item["status"] == "PENDING_DATA"),
        "stable": sum(1 for item in items if item["status"] == "STABLE"),
    }
    payload = {
        "ok": True,
        "date": today.isoformat(),
        "asof": datetime.now().isoformat(timespec="seconds"),
        "marker": marker,
        "reviewed_date": previous.get("date"),
        "items": items,
        "summary": summary,
    }
    if persist and items and not _note_exists(REVIEW_CATEGORY, marker):
        add_note(REVIEW_CATEGORY, json.dumps(payload, ensure_ascii=False, sort_keys=True))
        payload["persisted"] = True
    else:
        payload["persisted"] = False
    return payload
