"""
Historical backtest engine.

Reuses the same StrategyEngine, RiskEngine and PaperTradingService
that drive live paper trading, so the simulation matches what the
system would have done in real time.

Storage is disabled during backtests so the live DB is untouched.
"""

import time
from typing import Any, Dict, List, Optional

from .paper_trading import PaperTradingService
from ..strategies.engine import StrategyEngine
from ..strategies.risk import RiskEngine


class BacktestEngine:
    def __init__(
        self,
        starting_balance: float = 1000.0,
        confidence_threshold: float = 0.75,
        stop_distance_pct: float = 0.01,
        take_profit_multiplier: float = 2.0,
        warmup_candles: int = 30,
    ):
        self.starting_balance = starting_balance
        self.confidence_threshold = confidence_threshold
        self.stop_distance_pct = stop_distance_pct
        self.take_profit_multiplier = take_profit_multiplier
        self.warmup_candles = warmup_candles

    # ------------------------------------------------------------------
    def run(
        self,
        candles: List[Dict[str, Any]],
        symbol: str = "cmt_btcusdt",
    ) -> Dict[str, Any]:

        if len(candles) <= self.warmup_candles + 5:
            raise ValueError(
                f"Not enough candles for backtest "
                f"({len(candles)} < {self.warmup_candles + 5})."
            )

        # Fresh engines per run. Storage is None so we don't touch
        # the live paper_trading.db.
        strategy = StrategyEngine()
        risk = RiskEngine()
        paper = PaperTradingService(
            starting_balance=self.starting_balance,
            storage=None,
        )

        equity_curve: List[Dict[str, Any]] = []
        signals_seen = 0
        signals_buy = 0
        signals_sell = 0
        signals_wait = 0
        trades_opened = 0
        risk_rejections = 0
        max_consecutive_losses = 0
        current_loss_streak = 0

        for i in range(self.warmup_candles, len(candles)):
            window = candles[: i + 1]
            bar = candles[i]
            price = float(bar["close"])

            # 1. If a position is open, update it against this bar.
            if paper.position is not None:
                # Check intrabar for SL/TP using high/low.
                high = float(bar["high"])
                low = float(bar["low"])

                # Feed high then low (and current close) to update_price
                # so stop-loss and take-profit can trigger realistically.
                side = paper.position["side"]
                if side == "BUY":
                    update_prices = (low, high, price)
                else:
                    update_prices = (high, low, price)

                for p in update_prices:
                    paper.update_price(p)
                    if paper.position is None:
                        break

                if paper.position is None:
                    # Position closed; record the loss streak.
                    last_trade = paper.trade_history[-1]
                    if last_trade["pnl"] < 0:
                        current_loss_streak += 1
                        max_consecutive_losses = max(
                            max_consecutive_losses, current_loss_streak
                        )
                    elif last_trade["pnl"] > 0:
                        current_loss_streak = 0

                    risk.observe_trade_result(last_trade["pnl"])

            # 2. If no position, look for an entry.
            if paper.position is None:
                market_data = {"candles": window}
                analysis = strategy.analyze(market_data)

                signal = analysis["signal"]
                confidence = analysis["confidence"]
                features = analysis.get("features", {})
                atr14 = features.get("atr14")

                signals_seen += 1
                if signal == "BUY":
                    signals_buy += 1
                elif signal == "SELL":
                    signals_sell += 1
                else:
                    signals_wait += 1

                if (
                    signal in {"BUY", "SELL"}
                    and confidence >= self.confidence_threshold
                ):
                    risk.observe_market_timestamp(time.time())

                    equity = paper.balance
                    size = risk.calculate_position_size(
                        equity=equity,
                        price=price,
                        atr14=atr14,
                        stop_distance_pct=self.stop_distance_pct,
                    )

                    check = risk.validate_position(
                        size=size,
                        daily_loss=0.0,
                        equity=equity,
                        daily_starting_balance=self.starting_balance,
                        open_positions=0,
                        price=price,
                    )

                    if check["allowed"] and size > 0:
                        result = paper.open_position(
                            symbol=symbol,
                            side=signal,
                            size=size,
                            price=price,
                            stop_loss_percent=(
                                self.stop_distance_pct * 100
                            ),
                            take_profit_percent=(
                                self.stop_distance_pct
                                * 100
                                * self.take_profit_multiplier
                            ),
                        )
                        if result.get("success"):
                            trades_opened += 1
                    else:
                        risk_rejections += 1

            equity_curve.append(
                {
                    "timestamp": bar["timestamp"],
                    "equity": round(paper.balance, 4),
                }
            )

        # ------------------------------------------------------------------
        # Final metrics
        # ------------------------------------------------------------------
        total_return_pct = (
            (paper.balance - self.starting_balance)
            / self.starting_balance
            * 100
        )

        wins = [t for t in paper.trade_history if t["pnl"] > 0]
        losses = [t for t in paper.trade_history if t["pnl"] < 0]

        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))

        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = float("inf") if gross_profit > 0 else 0.0

        win_rate = (
            (len(wins) / len(paper.trade_history)) * 100
            if paper.trade_history
            else 0.0
        )

        avg_trade = (
            sum(t["pnl"] for t in paper.trade_history)
            / len(paper.trade_history)
            if paper.trade_history
            else 0.0
        )

        avg_win = (
            gross_profit / len(wins) if wins else 0.0
        )
        avg_loss = (
            -gross_loss / len(losses) if losses else 0.0
        )

        peak = self.starting_balance
        max_drawdown_pct = 0.0
        for point in equity_curve:
            eq = point["equity"]
            peak = max(peak, eq)
            if peak > 0:
                dd = (peak - eq) / peak * 100
                max_drawdown_pct = max(max_drawdown_pct, dd)

        return {
            "starting_balance": self.starting_balance,
            "ending_balance": round(paper.balance, 4),
            "ending_equity": round(paper.balance, 4),
            "total_return_pct": round(total_return_pct, 4),
            "total_trades": len(paper.trade_history),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 2),
            "profit_factor": (
                round(profit_factor, 4)
                if profit_factor != float("inf")
                else None
            ),
            "average_trade": round(avg_trade, 4),
            "average_win": round(avg_win, 4),
            "average_loss": round(avg_loss, 4),
            "max_drawdown_pct": round(max_drawdown_pct, 4),
            "max_consecutive_losses": max_consecutive_losses,
            "signals_seen": signals_seen,
            "signals_buy": signals_buy,
            "signals_sell": signals_sell,
            "signals_wait": signals_wait,
            "trades_opened": trades_opened,
            "risk_rejections": risk_rejections,
            "candles_processed": len(candles),
            "warmup_candles": self.warmup_candles,
            "confidence_threshold": self.confidence_threshold,
            "stop_distance_pct": self.stop_distance_pct,
            "take_profit_multiplier": self.take_profit_multiplier,
            "equity_curve": equity_curve,
            "trade_history": paper.trade_history,
        }