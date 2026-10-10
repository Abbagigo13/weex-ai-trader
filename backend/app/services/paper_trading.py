import datetime
from typing import Optional

from .storage import Storage


class PaperTradingService:
    def __init__(
        self,
        starting_balance: float = 1000.0,
        storage: Optional[Storage] = None,
    ):
        self.starting_balance = starting_balance
        self.storage = storage

        self.position: Optional[dict] = None
        self.trade_history: list[dict] = []

        # Restore from storage if available, otherwise start fresh.
        if self.storage is not None:
            self.balance = (
                self.starting_balance
                + self.storage.get_total_realized_pnl()
            )
            self.realized_pnl = self.storage.get_total_realized_pnl()
            stats = self.storage.get_trade_stats()
            self.total_trades = stats["total_trades"]
            self.winning_trades = stats["winning_trades"]
            self.losing_trades = stats["losing_trades"]
            self.trade_history = self.storage.get_recent_trades(limit=50)

            today = datetime.date.today().isoformat()
            row = self.storage.get_daily_pnl(today)
            if row:
                self._daily_date = today
                self._daily_realized_pnl = float(row["realized_pnl"])
                self._daily_starting_balance = float(
                    row["starting_balance"]
                )
            else:
                self._daily_date = today
                self._daily_realized_pnl = 0.0
                self._daily_starting_balance = self.balance
        else:
            self.balance = starting_balance
            self.realized_pnl = 0.0
            self.total_trades = 0
            self.winning_trades = 0
            self.losing_trades = 0

            self._daily_date = datetime.date.today().isoformat()
            self._daily_realized_pnl = 0.0
            self._daily_starting_balance = starting_balance

        # Counters for the current day (independent of persisted totals).
        self._daily_trade_count = 0
        self._daily_win_count = 0
        self._daily_loss_count = 0

    # ------------------------------------------------------------------
    # Daily helpers
    # ------------------------------------------------------------------
    def _roll_daily_if_needed(self) -> None:
        today = datetime.date.today().isoformat()
        if today != self._daily_date:
            self._daily_date = today
            self._daily_realized_pnl = 0.0
            self._daily_starting_balance = self.balance
            self._daily_trade_count = 0
            self._daily_win_count = 0
            self._daily_loss_count = 0

    def get_daily_realized_pnl(self) -> float:
        self._roll_daily_if_needed()
        return self._daily_realized_pnl

    def get_daily_starting_balance(self) -> float:
        self._roll_daily_if_needed()
        return self._daily_starting_balance

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def get_state(self) -> dict:
        self._roll_daily_if_needed()

        unrealized_pnl = 0.0
        if self.position:
            unrealized_pnl = self._calculate_pnl(
                self.position["current_price"]
            )

        equity = self.balance + unrealized_pnl

        drawdown = max(
            0.0,
            (
                (self.starting_balance - equity)
                / self.starting_balance
            )
            * 100,
        )

        return {
            "mode": "paper",
            "starting_balance": round(self.starting_balance, 4),
            "balance": round(self.balance, 4),
            "equity": round(equity, 4),
            "position": self.position,
            "unrealized_pnl": round(unrealized_pnl, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "daily_realized_pnl": round(self._daily_realized_pnl, 4),
            "daily_starting_balance": round(
                self._daily_starting_balance, 4
            ),
            "drawdown_percent": round(drawdown, 4),
            "statistics": {
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
            },
            "trade_history": self.trade_history[-20:],
        }

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------
    def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        stop_loss_percent: float = 1.0,
        take_profit_percent: float = 2.0,
    ) -> dict:

        side = side.upper()

        if side not in {"BUY", "SELL"}:
            return {
                "success": False,
                "message": "Side must be BUY or SELL.",
            }

        if size <= 0:
            return {
                "success": False,
                "message": "Position size must be greater than zero.",
            }

        if price <= 0:
            return {
                "success": False,
                "message": "Price must be greater than zero.",
            }

        if self.position:
            return {
                "success": False,
                "message": "A paper position is already open.",
            }

        if stop_loss_percent <= 0 or take_profit_percent <= 0:
            return {
                "success": False,
                "message": "Stop-loss and take-profit must be positive.",
            }

        notional = size * price

        if notional > self.balance:
            return {
                "success": False,
                "message": (
                    f"Position requires ${notional:.2f}, "
                    f"but available balance is ${self.balance:.2f}."
                ),
            }

        if side == "BUY":
            stop_loss = price * (1 - stop_loss_percent / 100)
            take_profit = price * (1 + take_profit_percent / 100)
        else:
            stop_loss = price * (1 + stop_loss_percent / 100)
            take_profit = price * (1 - take_profit_percent / 100)

        self.position = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "entry_price": price,
            "current_price": price,
            "stop_loss": round(stop_loss, 6),
            "take_profit": round(take_profit, 6),
            "stop_loss_percent": stop_loss_percent,
            "take_profit_percent": take_profit_percent,
        }

        if self.storage is not None:
            self.storage.record_snapshot(
                balance=self.balance,
                equity=self.balance,
                realized_pnl=self.realized_pnl,
                unrealized_pnl=0.0,
                position=self.position,
            )

        return {
            "success": True,
            "message": "Paper position opened.",
            "position": self.position,
        }

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update_price(self, price: float) -> dict:
        if price <= 0:
            return {
                "success": False,
                "message": "Price must be greater than zero.",
            }

        if not self.position:
            return self.get_state()

        self.position["current_price"] = price

        side = self.position["side"]
        stop_loss = self.position["stop_loss"]
        take_profit = self.position["take_profit"]

        if side == "BUY":
            if price <= stop_loss:
                return self.close_position(
                    price=price,
                    reason="STOP_LOSS",
                )
            if price >= take_profit:
                return self.close_position(
                    price=price,
                    reason="TAKE_PROFIT",
                )

        if side == "SELL":
            if price >= stop_loss:
                return self.close_position(
                    price=price,
                    reason="STOP_LOSS",
                )
            if price <= take_profit:
                return self.close_position(
                    price=price,
                    reason="TAKE_PROFIT",
                )

        return self.get_state()

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------
    def close_position(
        self,
        price: float,
        reason: str = "MANUAL",
    ) -> dict:

        if not self.position:
            return {
                "success": False,
                "message": "No open paper position.",
            }

        self.position["current_price"] = price

        pnl = self._calculate_pnl(price)

        self.realized_pnl += pnl
        self.balance += pnl

        self._roll_daily_if_needed()
        self._daily_realized_pnl += pnl
        self._daily_trade_count += 1

        self.total_trades += 1

        if pnl > 0:
            self.winning_trades += 1
            self._daily_win_count += 1
        elif pnl < 0:
            self.losing_trades += 1
            self._daily_loss_count += 1

        closed_position = dict(self.position)

        trade = {
            "symbol": closed_position["symbol"],
            "side": closed_position["side"],
            "size": closed_position["size"],
            "entry_price": closed_position["entry_price"],
            "exit_price": price,
            "pnl": round(pnl, 4),
            "reason": reason,
        }

        self.trade_history.append(trade)

        if self.storage is not None:
            self.storage.record_trade(
                symbol=trade["symbol"],
                side=trade["side"],
                size=trade["size"],
                entry_price=trade["entry_price"],
                exit_price=trade["exit_price"],
                pnl=trade["pnl"],
                reason=trade["reason"],
            )
            self.storage.upsert_daily_pnl(
                date=self._daily_date,
                realized_pnl=self._daily_realized_pnl,
                starting_balance=self._daily_starting_balance,
                ending_balance=self.balance,
                trade_count=self._daily_trade_count,
                win_count=self._daily_win_count,
                loss_count=self._daily_loss_count,
            )
            self.storage.record_snapshot(
                balance=self.balance,
                equity=self.balance,
                realized_pnl=self.realized_pnl,
                unrealized_pnl=0.0,
                position=None,
            )

        self.position = None

        return {
            "success": True,
            "message": "Paper position closed.",
            "reason": reason,
            "pnl": round(pnl, 4),
            "balance": round(self.balance, 4),
            "daily_realized_pnl": round(self._daily_realized_pnl, 4),
            "trade": trade,
        }

    # ------------------------------------------------------------------
    # PnL
    # ------------------------------------------------------------------
    def _calculate_pnl(self, price: float) -> float:
        if not self.position:
            return 0.0

        entry = self.position["entry_price"]
        size = self.position["size"]
        side = self.position["side"]

        if side == "BUY":
            return (price - entry) * size

        return (entry - price) * size