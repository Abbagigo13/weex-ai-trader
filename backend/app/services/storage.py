"""
SQLite persistence for paper trading.

Pure stdlib. No external dependencies.

Tables:
    trades              one row per closed trade
    daily_pnl           aggregated daily realized PnL
    account_snapshots   equity snapshots
    signals             strategy signal log
"""

import datetime
import json
import os
import sqlite3
import threading
from typing import Any, Optional


_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DEFAULT_DB_PATH = os.path.join(_BACKEND_DIR, "data", "paper_trading.db")


class Storage:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    size REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    pnl REAL NOT NULL,
                    reason TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);

                CREATE TABLE IF NOT EXISTS daily_pnl (
                    date TEXT PRIMARY KEY,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    starting_balance REAL NOT NULL DEFAULT 0,
                    ending_balance REAL NOT NULL DEFAULT 0,
                    trade_count INTEGER NOT NULL DEFAULT 0,
                    win_count INTEGER NOT NULL DEFAULT 0,
                    loss_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS account_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    balance REAL NOT NULL,
                    equity REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    position_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_ts
                    ON account_snapshots(ts);

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT,
                    features_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);
                """
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def record_trade(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        exit_price: float,
        pnl: float,
        reason: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO trades
                (ts, symbol, side, size, entry_price, exit_price, pnl, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.datetime.utcnow().isoformat(),
                    symbol,
                    side,
                    size,
                    entry_price,
                    exit_price,
                    pnl,
                    reason,
                ),
            )
            self._conn.commit()

    def upsert_daily_pnl(
        self,
        date: str,
        realized_pnl: float,
        starting_balance: float,
        ending_balance: float,
        trade_count: int,
        win_count: int,
        loss_count: int,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO daily_pnl
                (date, realized_pnl, starting_balance, ending_balance,
                 trade_count, win_count, loss_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    realized_pnl = excluded.realized_pnl,
                    starting_balance = excluded.starting_balance,
                    ending_balance = excluded.ending_balance,
                    trade_count = excluded.trade_count,
                    win_count = excluded.win_count,
                    loss_count = excluded.loss_count,
                    updated_at = excluded.updated_at
                """,
                (
                    date,
                    realized_pnl,
                    starting_balance,
                    ending_balance,
                    trade_count,
                    win_count,
                    loss_count,
                    datetime.datetime.utcnow().isoformat(),
                ),
            )
            self._conn.commit()

    def record_snapshot(
        self,
        balance: float,
        equity: float,
        realized_pnl: float,
        unrealized_pnl: float,
        position: Optional[dict],
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO account_snapshots
                (ts, balance, equity, realized_pnl, unrealized_pnl,
                 position_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.datetime.utcnow().isoformat(),
                    balance,
                    equity,
                    realized_pnl,
                    unrealized_pnl,
                    json.dumps(position) if position else None,
                ),
            )
            self._conn.commit()

    def record_signal(
        self,
        symbol: str,
        signal: str,
        confidence: float,
        reason: Optional[str],
        features: Optional[dict],
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO signals
                (ts, symbol, signal, confidence, reason, features_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.datetime.utcnow().isoformat(),
                    symbol,
                    signal,
                    confidence,
                    reason,
                    json.dumps(features) if features else None,
                ),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_recent_trades(self, limit: int = 50) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT * FROM trades
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_total_realized_pnl(self) -> float:
        with self._lock:
            cur = self._conn.execute(
                "SELECT COALESCE(SUM(pnl), 0.0) AS total FROM trades"
            )
            return float(cur.fetchone()["total"])

    def get_daily_pnl(self, date: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM daily_pnl WHERE date = ?",
                (date,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_trade_stats(self) -> dict:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses
                FROM trades
                """
            )
            row = cur.fetchone()
            return {
                "total_trades": int(row["total"] or 0),
                "winning_trades": int(row["wins"] or 0),
                "losing_trades": int(row["losses"] or 0),
            }

    def close(self) -> None:
        with self._lock:
            self._conn.close()