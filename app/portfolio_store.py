# app/portfolio_store.py
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "data" / "stock_analysis.db"
DB_FILE = os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))
LEGACY_DB_FILE = ROOT_DIR / "portfolio.db"

if load_dotenv is not None:
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _conn():
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            symbol TEXT PRIMARY KEY,
            shares REAL NOT NULL,
            avg_cost REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            name TEXT,
            side TEXT,
            shares REAL,
            price REAL,
            fee REAL,
            trade_time TEXT,
            note TEXT
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,          -- PLAN/RISK/OTHER
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        # ✅ 关注列表
        con.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            created_at TEXT NOT NULL
        )
        """)
        con.commit()
    _migrate_from_legacy_db()
    _seed_watchlist_from_env()
    _ensure_holdings_from_trades()


def _table_has_rows(con: sqlite3.Connection, table: str) -> bool:
    try:
        row = con.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str, columns: List[str]):
    cols = ", ".join(columns)
    rows = src.execute(f"SELECT {cols} FROM {table}").fetchall()
    if not rows:
        return
    placeholders = ", ".join(["?"] * len(columns))
    dst.executemany(
        f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})",
        [tuple(r[c] for c in columns) for r in rows],
    )


def _migrate_from_legacy_db():
    """
    One-time migration from legacy portfolio.db to the unified database.
    Skips if the target already has data.
    """
    if not LEGACY_DB_FILE.exists():
        return
    if Path(DB_FILE).resolve() == LEGACY_DB_FILE.resolve():
        return

    with sqlite3.connect(LEGACY_DB_FILE) as src, _conn() as dst:
        src.row_factory = sqlite3.Row
        dst.row_factory = sqlite3.Row

        if _table_has_rows(dst, "holdings") or _table_has_rows(dst, "trades"):
            return

        _copy_table(src, dst, "holdings", ["symbol", "shares", "avg_cost", "updated_at"])
        _copy_table(src, dst, "trades", ["symbol", "name", "side", "shares", "price", "fee", "trade_time", "note"])
        _copy_table(src, dst, "notes", ["category", "content", "created_at"])
        _copy_table(src, dst, "watchlist", ["symbol", "name", "created_at"])
        dst.commit()


def _parse_stock_list_env() -> List[str]:
    raw = os.getenv("STOCK_LIST", "") or ""
    if not raw.strip():
        return []
    parts = []
    normalized = (
        raw.replace(";", ",")
        .replace("，", ",")
        .replace("、", ",")
    )
    for chunk in normalized.split(","):
        sym = chunk.strip()
        if sym:
            parts.append(sym)
    # de-dup while preserving order
    seen = set()
    ordered: List[str] = []
    for sym in parts:
        if sym in seen:
            continue
        seen.add(sym)
        ordered.append(sym)
    return ordered


def _watchlist_from_env() -> List[Dict[str, Any]]:
    symbols = _parse_stock_list_env()
    if not symbols:
        return []
    now = datetime.now().isoformat()
    return [
        {"symbol": sym, "name": "", "created_at": now}
        for sym in symbols
    ]


def _seed_watchlist_from_env() -> None:
    """
    Seed watchlist from STOCK_LIST when the table is empty.
    This lets the UI read watchlist codes directly from STOCK_LIST on first run.
    """
    symbols = _parse_stock_list_env()
    if not symbols:
        return
    now = datetime.now().isoformat()
    with _conn() as con:
        if _table_has_rows(con, "watchlist"):
            return
        con.executemany(
            "INSERT OR IGNORE INTO watchlist(symbol, name, created_at) VALUES(?,?,?)",
            [(s, "", now) for s in symbols],
        )
        con.commit()


def _ensure_holdings_from_trades() -> None:
    """Rebuild holdings from trades when holdings table is empty."""
    with _conn() as con:
        if _table_has_rows(con, "holdings"):
            return
        row = con.execute("SELECT COUNT(*) FROM trades").fetchone()
        if not row or row[0] == 0:
            return
    rebuild_holdings_from_trades()


def rebuild_holdings_from_trades() -> None:
    """
    Recompute holdings using average-cost method from trades table.
    BUY increases shares/cost; SELL reduces shares/cost at avg cost.
    """
    with _conn() as con:
        trades = con.execute(
            "SELECT symbol, side, shares, price, trade_time, id FROM trades ORDER BY trade_time ASC, id ASC"
        ).fetchall()

        position_cost: Dict[str, float] = {}
        position_shares: Dict[str, float] = {}

        for t in trades:
            symbol = str(t["symbol"] or "").strip()
            side = str(t["side"] or "").upper()
            shares = float(t["shares"] or 0)
            price = float(t["price"] or 0)
            if not symbol or shares <= 0 or price <= 0:
                continue

            if side == "BUY":
                position_cost[symbol] = position_cost.get(symbol, 0.0) + shares * price
                position_shares[symbol] = position_shares.get(symbol, 0.0) + shares
            elif side == "SELL":
                cur_shares = position_shares.get(symbol, 0.0)
                cur_cost = position_cost.get(symbol, 0.0)
                if cur_shares <= 0:
                    continue
                sell_shares = min(shares, cur_shares)
                avg_cost = cur_cost / cur_shares if cur_shares > 0 else 0.0
                position_shares[symbol] = cur_shares - sell_shares
                position_cost[symbol] = cur_cost - avg_cost * sell_shares

        now = datetime.now().isoformat()
        con.execute("DELETE FROM holdings")
        rows = []
        for sym, sh in position_shares.items():
            if sh <= 0:
                continue
            cost = position_cost.get(sym, 0.0)
            avg = cost / sh if sh > 0 else 0.0
            rows.append((sym, sh, avg, now))
        if rows:
            con.executemany(
                "INSERT INTO holdings(symbol, shares, avg_cost, updated_at) VALUES(?,?,?,?)",
                rows,
            )
        con.commit()

# =========================
# 持仓操作
# =========================
def upsert_holding(symbol: str, shares: float, avg_cost: float):
    now = datetime.now().isoformat()
    with _conn() as con:
        con.execute("""
        INSERT INTO holdings(symbol, shares, avg_cost, updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(symbol) DO UPDATE SET
            shares=excluded.shares,
            avg_cost=excluded.avg_cost,
            updated_at=excluded.updated_at
        """, (symbol, shares, avg_cost, now))
        con.commit()


def delete_holding(symbol: str):
    with _conn() as con:
        con.execute("DELETE FROM holdings WHERE symbol=?", (symbol,))
        con.commit()


def get_holdings() -> List[Dict[str, Any]]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM holdings ORDER BY symbol").fetchall()
    return [dict(r) for r in rows]


def get_holding(symbol: str) -> Optional[Dict[str, Any]]:
    with _conn() as con:
        row = con.execute("SELECT * FROM holdings WHERE symbol=?", (symbol,)).fetchone()
    return dict(row) if row else None


# =========================
# 交易逻辑（核心）
# =========================
def apply_trade(
    symbol: str,
    name: str,
    side: str,
    shares: float,
    price: float,
    fee: float = 0.0,
    note: str = ""
):
    """
    记录交易 + 更新持仓
    """

    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")

    shares = float(shares)
    price = float(price)
    fee = float(fee)

    now = datetime.now().isoformat()

    with _conn() as con:

        # 1️⃣ 记录交易（永久保存）
        con.execute("""
        INSERT INTO trades(symbol, name, side, shares, price, fee, trade_time, note)
        VALUES(?,?,?,?,?,?,?,?)
        """, (symbol, name, side, shares, price, fee, now, note))

        # 2️⃣ 更新持仓
        cur = con.execute(
            "SELECT shares, avg_cost FROM holdings WHERE symbol=?",
            (symbol,)
        )
        row = cur.fetchone()

        if side == "BUY":

            if row:
                old_shares = row["shares"]
                old_cost = row["avg_cost"]

                new_shares = old_shares + shares
                new_avg = (
                    old_shares * old_cost + shares * price
                ) / new_shares

            else:
                new_shares = shares
                new_avg = price

            con.execute("""
            INSERT INTO holdings(symbol, shares, avg_cost, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                shares=?,
                avg_cost=?,
                updated_at=?
            """, (
                symbol, new_shares, new_avg, now,
                new_shares, new_avg, now
            ))

        elif side == "SELL":

            if not row:
                raise ValueError("当前无持仓")

            old_shares = row["shares"]
            old_cost = row["avg_cost"]

            if shares > old_shares:
                raise ValueError("卖出数量超过持仓")

            new_shares = old_shares - shares

            if new_shares == 0:
                con.execute("DELETE FROM holdings WHERE symbol=?", (symbol,))
            else:
                con.execute("""
                UPDATE holdings
                SET shares=?, avg_cost=?, updated_at=?
                WHERE symbol=?
                """, (new_shares, old_cost, now, symbol))

        con.commit()


# =========================
# 交易查询
# =========================
def list_trades(symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with _conn() as con:
        if symbol:
            rows = con.execute(
                "SELECT * FROM trades WHERE symbol=? ORDER BY id DESC LIMIT ?",
                (symbol, limit)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
    return [dict(r) for r in rows]
# =========================
# 投资计划 / 备注
# =========================

def add_note(category: str, content: str):
    now = datetime.now().isoformat()
    with _conn() as con:
        con.execute("""
        INSERT INTO notes(category, content, created_at)
        VALUES(?,?,?)
        """, (category.upper(), content, now))
        con.commit()


def list_notes(category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with _conn() as con:
        if category:
            rows = con.execute(
                "SELECT * FROM notes WHERE category=? ORDER BY id DESC LIMIT ?",
                (category.upper(), limit)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM notes ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
    return [dict(r) for r in rows]
def add_watch(symbol: str, name: str = ""):
    now = datetime.now().isoformat()
    with _conn() as con:
        con.execute("""
        INSERT INTO watchlist(symbol, name, created_at)
        VALUES(?,?,?)
        ON CONFLICT(symbol) DO UPDATE SET
            name=excluded.name
        """, (symbol, name or "", now))
        con.commit()


def remove_watch(symbol: str):
    with _conn() as con:
        con.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
        con.commit()


def list_watchlist() -> List[Dict[str, Any]]:
    # Prefer STOCK_LIST when provided
    env_watchlist = _watchlist_from_env()
    if env_watchlist:
        return env_watchlist
    with _conn() as con:
        rows = con.execute("SELECT * FROM watchlist ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
