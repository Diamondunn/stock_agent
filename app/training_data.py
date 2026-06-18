from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.portfolio_store import list_notes


SYSTEM_MESSAGE = (
    "你是 stock_agent 的投研决策助手。你必须基于已给出的结构化证据回答，"
    "不能编造行情、价格或指标；当证据不足时要明确降级为观察，并给出下一步补证条件。"
)


def _safe_json(value: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(value)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _json_notes(category: str, limit: int = 500) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for note in list_notes(category, limit=limit):
        payload = _safe_json(str(note.get("content") or ""))
        if not payload:
            continue
        payload["_note_id"] = note.get("id")
        payload["_created_at"] = note.get("created_at")
        rows.append(payload)
    return rows


def _action_quality(review_item: Optional[Dict[str, Any]]) -> str:
    if not review_item:
        return "PENDING_REVIEW"
    return str(review_item.get("status") or "PENDING_REVIEW")


def _clean_training_text(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = cleaned.replace("关键行情证据缺失", "历史K线或关键行情证据缺失")
    cleaned = cleaned.replace("关键行情证据不足", "历史K线或关键行情证据不足")
    cleaned = cleaned.replace(
        "保持观察，等待技术面、风险面或交易记忆给出更一致信号。",
        "补齐最近 6 个月 K 线、实时价格和交易记忆；至少两项证据同向后再升级为加仓/减仓候选。",
    )
    return cleaned


def _decision_target(item: Dict[str, Any], review_item: Optional[Dict[str, Any]]) -> str:
    action = str(item.get("action_label") or item.get("action") or "观察")
    reason = _clean_training_text(str(item.get("reason") or "暂无理由。"))
    quality = _action_quality(review_item)

    if quality == "HIT":
        review_text = "次日复盘验证方向有效，可以保留该类触发条件。"
    elif quality in {"MISS", "MISSED_MOVE"}:
        review_text = "次日复盘没有验证该判断，需要降低置信度并补充触发条件。"
    elif quality == "STABLE":
        review_text = "次日波动有限，观察判断基本匹配震荡场景。"
    elif quality == "PENDING_DATA":
        review_text = "复盘价格缺失，不能评价判断质量。"
    else:
        review_text = "尚未完成次日复盘，不能把该样本当作强监督信号。"

    next_steps = item.get("next_steps") or []
    if isinstance(next_steps, list):
        next_text = "；".join(_clean_training_text(str(x)) for x in next_steps if str(x).strip())
    else:
        next_text = _clean_training_text(str(next_steps))

    return (
        f"建议动作：{action}。\n"
        f"判断依据：{reason}\n"
        f"复盘状态：{quality}。{review_text}\n"
        f"下一步：{next_text or '补齐行情、仓位和交易记忆后再复核。'}"
    )


def _decision_prompt(item: Dict[str, Any], decision_date: str) -> str:
    fields = {
        "date": decision_date,
        "symbol": item.get("symbol"),
        "name": item.get("name"),
        "score": item.get("score"),
        "confidence": item.get("confidence"),
        "has_position": item.get("has_position"),
        "price": item.get("price"),
        "change_pct": item.get("change_pct"),
    }
    return (
        "请根据以下关注股结构化证据，给出加仓/减仓/观察判断。"
        "要求说明证据缺口、动作边界和下一步触发条件。\n"
        + json.dumps(fields, ensure_ascii=False, sort_keys=True)
    )


def _review_lookup(reviews: Iterable[Dict[str, Any]]) -> Dict[tuple[str, str], Dict[str, Any]]:
    lookup: Dict[tuple[str, str], Dict[str, Any]] = {}
    for review in reviews:
        reviewed_date = str(review.get("reviewed_date") or "")
        for item in review.get("items") or []:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "")
            if reviewed_date and symbol:
                lookup[(reviewed_date, symbol)] = item
    return lookup


def build_watchlist_finetune_records(limit: int = 500) -> List[Dict[str, Any]]:
    """
    Build provider-neutral chat fine-tuning records from daily watchlist decisions.

    These records train decision discipline and explanation format, not price
    prediction. Strong labels come only from persisted decisions plus optional
    next-day review outcomes.
    """
    decisions = _json_notes("WATCHLIST_DECISION", limit=limit)
    reviews = _json_notes("WATCHLIST_REVIEW", limit=limit)
    review_items = _review_lookup(reviews)
    records: List[Dict[str, Any]] = []

    for decision in sorted(decisions, key=lambda x: str(x.get("date") or "")):
        decision_date = str(decision.get("date") or "")
        for item in decision.get("items") or []:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "")
            review_item = review_items.get((decision_date, symbol))
            records.append(
                {
                    "messages": [
                        {"role": "system", "content": SYSTEM_MESSAGE},
                        {"role": "user", "content": _decision_prompt(item, decision_date)},
                        {"role": "assistant", "content": _decision_target(item, review_item)},
                    ],
                    "metadata": {
                        "source": "watchlist_cycle",
                        "date": decision_date,
                        "symbol": symbol,
                        "action": item.get("action"),
                        "review_status": _action_quality(review_item),
                    },
                }
            )
    return records


def write_jsonl(records: Iterable[Dict[str, Any]], path: str | Path) -> Dict[str, Any]:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return {"ok": True, "path": str(out_path), "records": count}
