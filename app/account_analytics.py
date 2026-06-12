from collections import defaultdict
from datetime import datetime
from .portfolio_store import list_trades


def build_account_dashboard():

    trades = list_trades(limit=100000)
    trades = sorted(trades, key=lambda x: x["trade_time"])

    position_cost = defaultdict(float)
    position_shares = defaultdict(float)

    realized = 0.0
    win = 0
    sell_count = 0
    buy_count = 0

    equity_curve = []
    cumulative = 0.0

    win_list = []
    loss_list = []

    for t in trades:

        symbol = t["symbol"]
        shares = float(t["shares"])
        price = float(t["price"])
        fee = float(t.get("fee", 0) or 0)
        side = t["side"]

        if side == "BUY":
            position_cost[symbol] += shares * price
            position_shares[symbol] += shares
            buy_count += 1

        elif side == "SELL":

            if position_shares[symbol] <= 0:
                continue

            sell_count += 1

            avg = position_cost[symbol] / position_shares[symbol]
            pnl = (price - avg) * shares - fee

            realized += pnl
            cumulative += pnl

            if pnl > 0:
                win += 1
                win_list.append(pnl)
            else:
                loss_list.append(pnl)

            equity_curve.append({
                "time": t["trade_time"],
                "equity": round(cumulative, 2)
            })

            position_shares[symbol] -= shares
            position_cost[symbol] -= avg * shares

    # -------------------------
    # 统计指标
    # -------------------------

    win_rate = (win / sell_count * 100) if sell_count else 0

    avg_win = sum(win_list) / len(win_list) if win_list else 0
    avg_loss = sum(loss_list) / len(loss_list) if loss_list else 0

    total_win = sum(win_list) if win_list else 0
    total_loss = abs(sum(loss_list)) if loss_list else 0

    profit_factor = (total_win / total_loss) if total_loss > 0 else None

    max_single_win = max(win_list) if win_list else 0
    max_single_loss = min(loss_list) if loss_list else 0

    # -------------------------
    # 最大回撤计算
    # -------------------------

    peak = 0
    max_drawdown = 0

    for point in equity_curve:
        equity = point["equity"]
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return {
        "realized_pnl": round(realized, 2),
        "win_rate": round(win_rate, 2),
        "buy_trades": buy_count,
        "sell_trades": sell_count,
        "equity_curve": equity_curve,

        # 新增统计
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor else None,
        "max_single_win": round(max_single_win, 2),
        "max_single_loss": round(max_single_loss, 2),
        "max_drawdown": round(max_drawdown, 2),
    }
