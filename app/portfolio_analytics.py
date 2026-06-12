# app/portfolio_analytics.py
"""
组合分析引擎（Portfolio Analytics）

能力：
- 基于长期记忆持仓（SQLite）计算：市值、成本、浮盈亏、收益率、仓位占比
- 基于历史行情构建组合净值曲线：日收益率、年化收益、年化波动、最大回撤、夏普
- 对缺失数据做尽力对齐与前向填充（避免部分票缺几天导致全体断裂）

注意：
- 本模块不依赖 @tool，可被 tools.py 调用。
- 行情依赖你现有的 get_stock_history(symbol, period)（OHLCV，Close列必须有）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

from .portfolio_store import get_holdings
from .data_sources import ensure_suffix, get_stock_history
from .cache import config, logger


@dataclass
class HoldingSnapshot:
    symbol: str
    shares: float
    avg_cost: float
    price: float
    market_value: float
    cost_value: float
    pnl: float
    pnl_pct: float


def _safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _get_latest_close(symbol: str, period: str = "6mo") -> Optional[float]:
    """取最近收盘价（用历史最后一根Close近似当前价）。"""
    df = get_stock_history(symbol, period)
    if df is None or df.empty:
        return None
    if "Close" not in df.columns:
        return None
    try:
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def build_portfolio_snapshot(price_period: str = "6mo") -> Dict[str, Any]:
    """
    返回：持仓快照 + 汇总
    """
    hs = get_holdings()
    if not hs:
        return {
            "ok": True,
            "asof": datetime.now().isoformat(),
            "summary": {
                "total_market_value": 0.0,
                "total_cost_value": 0.0,
                "total_pnl": 0.0,
                "total_pnl_pct": 0.0,
                "holding_count": 0,
            },
            "holdings": [],
            "note": "当前没有记录到任何持仓。",
        }

    snapshots: List[HoldingSnapshot] = []
    total_mv = 0.0
    total_cv = 0.0

    for h in hs:
        sym = ensure_suffix(h["symbol"])
        shares = _safe_float(h.get("shares"), 0.0)
        avg_cost = _safe_float(h.get("avg_cost"), 0.0)

        price = _get_latest_close(sym, period=price_period)
        if price is None:
            # 缺行情：用成本价兜底，至少不崩
            price = avg_cost
            logger.warning(f"[portfolio] {sym} 无法取到行情，使用 avg_cost 兜底")

        mv = shares * price
        cv = shares * avg_cost
        pnl = mv - cv
        pnl_pct = (pnl / cv * 100.0) if cv > 0 else 0.0

        snapshots.append(
            HoldingSnapshot(
                symbol=sym,
                shares=shares,
                avg_cost=avg_cost,
                price=price,
                market_value=mv,
                cost_value=cv,
                pnl=pnl,
                pnl_pct=pnl_pct,
            )
        )
        total_mv += mv
        total_cv += cv

    total_pnl = total_mv - total_cv
    total_pnl_pct = (total_pnl / total_cv * 100.0) if total_cv > 0 else 0.0

    # 仓位占比
    holdings_out: List[Dict[str, Any]] = []
    for s in snapshots:
        weight = (s.market_value / total_mv * 100.0) if total_mv > 0 else 0.0
        holdings_out.append(
            {
                "symbol": s.symbol,
                "shares": s.shares,
                "avg_cost": round(s.avg_cost, 6),
                "price": round(s.price, 6),
                "market_value": round(s.market_value, 2),
                "cost_value": round(s.cost_value, 2),
                "pnl": round(s.pnl, 2),
                "pnl_pct": round(s.pnl_pct, 2),
                "weight_pct": round(weight, 2),
            }
        )

    # 按市值降序
    holdings_out.sort(key=lambda x: x["market_value"], reverse=True)

    return {
        "ok": True,
        "asof": datetime.now().isoformat(),
        "summary": {
            "total_market_value": round(total_mv, 2),
            "total_cost_value": round(total_cv, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "holding_count": len(holdings_out),
        },
        "holdings": holdings_out,
    }


def _align_close_series(series_list: List[Tuple[str, float, pd.Series]]) -> pd.DataFrame:
    """
    series_list: [(symbol, shares, close_series_indexed_by_date), ...]
    输出：DataFrame columns=symbol，每列为Close，按日期对齐，ffill，dropna尽力保留
    """
    if not series_list:
        return pd.DataFrame()

    df = pd.DataFrame()
    for sym, shares, s in series_list:
        # 确保DatetimeIndex
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.to_datetime(s.index)
        s = s.sort_index()
        df[sym] = s.astype(float)

    # 对齐后前向填充（避免单票缺几天导致组合断裂）
    df = df.sort_index().ffill()

    # 仍可能有开头缺失：丢掉全空行
    df = df.dropna(how="all")
    return df


def compute_portfolio_performance(lookback: str = "1y") -> Dict[str, Any]:
    """
    组合表现（基于持仓 shares * Close 构建组合日净值）
    返回：
    - nav_series: 净值曲线（dict，日期->净值）
    - stats: 年化收益、年化波动、最大回撤、夏普、胜率、日均收益等
    """
    hs = get_holdings()
    if not hs:
        return {
            "ok": True,
            "asof": datetime.now().isoformat(),
            "note": "当前没有持仓，无法计算组合表现。",
            "stats": {},
            "nav_series": {},
        }

    series_list: List[Tuple[str, float, pd.Series]] = []
    missing: List[str] = []

    for h in hs:
        sym = ensure_suffix(h["symbol"])
        shares = _safe_float(h.get("shares"), 0.0)
        if shares <= 0:
            continue

        df = get_stock_history(sym, lookback)
        if df is None or df.empty or "Close" not in df.columns:
            missing.append(sym)
            continue

        close = df["Close"].copy()
        series_list.append((sym, shares, close))

    if not series_list:
        return {
            "ok": False,
            "asof": datetime.now().isoformat(),
            "error": f"无法获取任何持仓的历史行情：{missing}",
        }

    close_df = _align_close_series(series_list)
    if close_df.empty or len(close_df) < 20:
        return {
            "ok": False,
            "asof": datetime.now().isoformat(),
            "error": "历史序列过短，无法计算组合指标。",
        }

    # 组合市值序列：sum(shares * close)
    shares_map = {sym: shares for sym, shares, _ in series_list}
    value_df = close_df.copy()
    for sym in value_df.columns:
        value_df[sym] = value_df[sym] * shares_map.get(sym, 0.0)

    portfolio_value = value_df.sum(axis=1)
    # 组合净值（起点=1）
    nav = portfolio_value / float(portfolio_value.iloc[0])
    rets = nav.pct_change().dropna()

    # 统计
    ann_return = float((nav.iloc[-1] ** (252 / max(len(rets), 1)) - 1.0)) if len(rets) > 5 else float(nav.iloc[-1] - 1.0)
    ann_vol = float(rets.std() * np.sqrt(252)) if len(rets) > 5 else 0.0
    sharpe = float((rets.mean() * 252 - config.RISK_FREE_RATE) / (rets.std() * np.sqrt(252))) if (len(rets) > 5 and rets.std() > 1e-12) else 0.0

    cummax = nav.cummax()
    drawdown = (nav - cummax) / cummax
    max_dd = float(drawdown.min())

    win_rate = float((rets > 0).mean()) if len(rets) > 0 else 0.0
    avg_daily = float(rets.mean()) if len(rets) > 0 else 0.0

    stats = {
        "lookback": lookback,
        "trading_days": int(len(rets)),
        "nav_start": float(nav.iloc[0]),
        "nav_end": float(nav.iloc[-1]),
        "total_return_pct": round((float(nav.iloc[-1]) - 1.0) * 100.0, 2),
        "annual_return_pct": round(ann_return * 100.0, 2),
        "annual_volatility_pct": round(ann_vol * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe_ratio": round(sharpe, 3),
        "win_rate_pct": round(win_rate * 100.0, 2),
        "avg_daily_return_pct": round(avg_daily * 100.0, 4),
        "missing_symbols": missing,
    }

    # 压缩净值输出（避免太大）：最多输出最近 300 个点
    nav_tail = nav.tail(300)
    nav_series = {d.strftime("%Y-%m-%d"): float(v) for d, v in nav_tail.items()}

    return {
        "ok": True,
        "asof": datetime.now().isoformat(),
        "stats": stats,
        "nav_series": nav_series,
    }
def calculate_portfolio_metrics():
    holdings = get_holdings()

    total_value = 0
    total_cost = 0
    symbols = []

    for h in holdings:
        hist = get_stock_history(h["symbol"], "1mo")
        if hist is None or hist.empty:
            continue

        current_price = float(hist["Close"].iloc[-1])
        market_value = current_price * h["shares"]

        total_value += market_value
        total_cost += h["avg_cost"] * h["shares"]

        symbols.append(
            {
                "symbol": h["symbol"],
                "value": market_value,
            }
        )

    profit = total_value - total_cost
    profit_pct = (profit / total_cost * 100) if total_cost else 0

    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "profit": round(profit, 2),
        "profit_pct": round(profit_pct, 2),
        "allocation": symbols,
    }