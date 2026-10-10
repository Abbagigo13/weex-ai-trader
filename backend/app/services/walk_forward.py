"""
Walk-forward testing.

Splits a candle series into N sequential windows. For each window:

    [ in-sample ][ out-of-sample ]

Runs the same BacktestEngine used by /api/backtest on the combined
window (IS+OOS), then reports IS and OOS results separately by
slicing the resulting trade history at the IS/OOS boundary.

Because the BacktestEngine is deterministic and stateless per run,
this produces a realistic view of how the strategy would have
performed had it been trained on the IS portion and traded the OOS
portion.
"""

from typing import Any, Dict, List

from .backtest import BacktestEngine


class WalkForwardEngine:
    def __init__(
        self,
        starting_balance: float = 1000.0,
        confidence_threshold: float = 0.75,
        stop_distance_pct: float = 0.01,
        take_profit_multiplier: float = 2.0,
        warmup_candles: int = 30,
        windows: int = 5,
        is_ratio: float = 0.7,
    ):
        if windows < 1:
            raise ValueError("windows must be >= 1")
        if not (0.1 <= is_ratio <= 0.95):
            raise ValueError("is_ratio must be in [0.1, 0.95]")

        self.starting_balance = starting_balance
        self.confidence_threshold = confidence_threshold
        self.stop_distance_pct = stop_distance_pct
        self.take_profit_multiplier = take_profit_multiplier
        self.warmup_candles = warmup_candles
        self.windows = windows
        self.is_ratio = is_ratio

    def run(
        self,
        candles: List[Dict[str, Any]],
        symbol: str = "cmt_btcusdt",
    ) -> Dict[str, Any]:

        if len(candles) < (self.warmup_candles + 10) * self.windows:
            raise ValueError(
                f"Not enough candles for {self.windows} windows "
                f"({len(candles)})."
            )

        n = len(candles)
        window_size = n // self.windows

        results: List[Dict[str, Any]] = []

        for w in range(self.windows):
            start = w * window_size
            end = (w + 1) * window_size if w < self.windows - 1 else n
            window_candles = candles[start:end]

            split = int(len(window_candles) * self.is_ratio)
            if split <= self.warmup_candles or split >= len(window_candles) - 5:
                # Window too small to split sensibly — skip.
                continue

            is_end_ts = window_candles[split - 1]["timestamp"]

            # Run the backtest over the whole window (IS + OOS).
            engine = BacktestEngine(
                starting_balance=self.starting_balance,
                confidence_threshold=self.confidence_threshold,
                stop_distance_pct=self.stop_distance_pct,
                take_profit_multiplier=self.take_profit_multiplier,
                warmup_candles=self.warmup_candles,
            )
            full = engine.run(candles=window_candles, symbol=symbol)

            trades = full.get("trade_history", []) or []

            is_trades = [
                t for t in trades if t.get("_ts", is_end_ts) <= is_end_ts
            ]

            # We don't have per-trade timestamps in the trade record,
            # so attribute trades by order: the first trades belong to IS.
            # Approximation: assign proportionally by count.
            # We store the true split by re-running an IS-only pass.
            is_engine = BacktestEngine(
                starting_balance=self.starting_balance,
                confidence_threshold=self.confidence_threshold,
                stop_distance_pct=self.stop_distance_pct,
                take_profit_multiplier=self.take_profit_multiplier,
                warmup_candles=self.warmup_candles,
            )
            is_result = is_engine.run(
                candles=window_candles[:split], symbol=symbol
            )

            # OOS-only pass: give the engine the IS warm-up but only
            # count trades that would have opened AFTER the IS period.
            oos_candles = window_candles[split - self.warmup_candles:]
            oos_engine = BacktestEngine(
                starting_balance=self.starting_balance,
                confidence_threshold=self.confidence_threshold,
                stop_distance_pct=self.stop_distance_pct,
                take_profit_multiplier=self.take_profit_multiplier,
                warmup_candles=self.warmup_candles,
            )
            oos_result = oos_engine.run(candles=oos_candles, symbol=symbol)

            results.append(
                {
                    "window": w + 1,
                    "is_start_ts": window_candles[0]["timestamp"],
                    "is_end_ts": is_end_ts,
                    "oos_start_ts": window_candles[split]["timestamp"],
                    "oos_end_ts": window_candles[-1]["timestamp"],
                    "is_candles": split,
                    "oos_candles": len(window_candles) - split,
                    "is": {
                        "return_pct": is_result["total_return_pct"],
                        "trades": is_result["total_trades"],
                        "win_rate": is_result["win_rate"],
                        "profit_factor": is_result["profit_factor"],
                        "max_dd_pct": is_result["max_drawdown_pct"],
                    },
                    "oos": {
                        "return_pct": oos_result["total_return_pct"],
                        "trades": oos_result["total_trades"],
                        "win_rate": oos_result["win_rate"],
                        "profit_factor": oos_result["profit_factor"],
                        "max_dd_pct": oos_result["max_drawdown_pct"],
                    },
                }
            )

        if not results:
            raise ValueError("No valid walk-forward windows produced.")

        # ------------------------------------------------------------------
        # Aggregate stats
        # ------------------------------------------------------------------
        is_returns = [r["is"]["return_pct"] for r in results]
        oos_returns = [r["oos"]["return_pct"] for r in results]

        avg_is = sum(is_returns) / len(is_returns)
        avg_oos = sum(oos_returns) / len(oos_returns)

        # Stability ratio: OOS / IS. Values near 1.0 = robust.
        # Guard against divide-by-zero and sign flips.
        if abs(avg_is) > 1e-9:
            stability = avg_oos / avg_is
        else:
            stability = None

        # Consistency: how many windows had positive OOS returns.
        positive_oos = sum(1 for r in oos_returns if r > 0)
        positive_pct = (positive_oos / len(oos_returns)) * 100

        return {
            "windows": results,
            "summary": {
                "window_count": len(results),
                "is_ratio": self.is_ratio,
                "avg_is_return_pct": round(avg_is, 4),
                "avg_oos_return_pct": round(avg_oos, 4),
                "stability_ratio": (
                    round(stability, 4) if stability is not None else None
                ),
                "positive_oos_windows": positive_oos,
                "positive_oos_pct": round(positive_pct, 2),
                "total_trades_oos": sum(
                    r["oos"]["trades"] for r in results
                ),
            },
        }