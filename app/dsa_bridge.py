from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_DSA_ROOT = _ROOT / "third_party" / "daily_stock_analysis"
_DSA_APP = None


def _ensure_dsa_importable() -> None:
    if not _DSA_ROOT.exists():
        raise RuntimeError(f"daily_stock_analysis not found at {_DSA_ROOT}")
    if str(_DSA_ROOT) not in sys.path:
        sys.path.insert(0, str(_DSA_ROOT))
    # Always point DSA to the unified root .env when present.
    root_env = _ROOT / ".env"
    if "ENV_FILE" not in os.environ and root_env.exists():
        os.environ["ENV_FILE"] = str(root_env)


def get_dsa_config():
    _ensure_dsa_importable()
    from src.config import setup_env, get_config

    setup_env()
    return get_config()


def get_dsa_app():
    global _DSA_APP
    if _DSA_APP is not None:
        return _DSA_APP
    _ensure_dsa_importable()
    from api.app import create_app

    _DSA_APP = create_app()
    return _DSA_APP


def _merge_stock_codes(codes: Iterable[str]) -> List[str]:
    _ensure_dsa_importable()
    from data_provider.base import canonical_stock_code

    seen = set()
    merged: List[str] = []
    for raw in codes:
        code = canonical_stock_code(raw or "")
        if not code:
            continue
        if code in seen:
            continue
        seen.add(code)
        merged.append(code)
    return merged


def sync_dsa_stock_list(extra_codes: Optional[List[str]] = None) -> List[str]:
    _ensure_dsa_importable()
    from app.portfolio_store import get_holdings, list_watchlist

    codes: List[str] = []
    for h in get_holdings() or []:
        codes.append(str(h.get("symbol", "")).strip())
    for w in list_watchlist() or []:
        codes.append(str(w.get("symbol", "")).strip())
    if extra_codes:
        codes.extend(extra_codes)

    codes = _merge_stock_codes(codes)
    config = get_dsa_config()
    config.stock_list = codes
    return codes


def dsa_analyze_stock(
    stock_code: str,
    report_type: str = "detailed",
    force_refresh: bool = False,
    send_notification: bool = False,
) -> Optional[Dict[str, Any]]:
    _ensure_dsa_importable()
    from src.services.analysis_service import AnalysisService

    return AnalysisService().analyze_stock(
        stock_code=stock_code,
        report_type=report_type,
        force_refresh=force_refresh,
        send_notification=send_notification,
    )


def dsa_analyze_watchlist(
    report_type: str = "detailed",
    force_refresh: bool = False,
    limit: Optional[int] = None,
    send_notification: bool = False,
) -> List[Dict[str, Any]]:
    codes = sync_dsa_stock_list()
    if limit is not None:
        codes = codes[: max(0, int(limit))]

    results: List[Dict[str, Any]] = []
    for code in codes:
        result = dsa_analyze_stock(
            stock_code=code,
            report_type=report_type,
            force_refresh=force_refresh,
            send_notification=send_notification,
        )
        if result:
            results.append(result)
    return results


def dsa_market_review(
    region: Optional[str] = None,
    send_notification: bool = False,
) -> Optional[str]:
    _ensure_dsa_importable()
    from src.notification import NotificationService
    from src.core.market_review import run_market_review

    config = get_dsa_config()
    if region:
        config.market_review_region = region

    notifier = NotificationService()
    return run_market_review(
        notifier=notifier,
        send_notification=send_notification,
        override_region=region,
    )
