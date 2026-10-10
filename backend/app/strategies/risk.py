"""
Risk engine.

Deterministic risk controls, kept OUTSIDE any LLM / strategy logic.

Implements the controls listed in the project handoff (section 19):

    1. Actual daily realized PnL
    2. Maximum daily loss
    3. Maximum position size
    4. Maximum consecutive losses
    5. Maximum open positions
    6. Cooldown after losses
    7. Volatility-based position sizing
    8. Absolute maximum size cap
    9. Stale-data protection

The engine is stateless with respect to trades — it observes the state
that the paper-trading service reports. This keeps it safe to reason
about and easy to test.
"""

import time
from typing import Optional


class RiskEngine:
    # ------------------------------------------------------------------
    # Defaults — all overridable via the constructor
    # ------------------------------------------------------------------
    DEFAULT_MAX_POSITION_NOTIONAL = 1000.0   # absolute cap in quote currency
    DEFAULT_MAX_OPEN_POSITIONS = 1          # handoff: one active position
    DEFAULT_MAX_DAILY_LOSS_PCT = 0.05       # 5% of daily starting balance
    DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
    DEFAULT_COOLDOWN_SECONDS = 300          # 5 minutes after loss streak
    DEFAULT_RISK_PER_TRADE_PCT = 0.01       # 1% of equity risked per trade
    DEFAULT_MAX_STALE_SECONDS = 30          # reject if market data older
    DEFAULT_MIN_STOP_DISTANCE_PCT = 0.001   # 0.1% of price

    def __init__(
        self,
        max_position_notional: float = DEFAULT_MAX_POSITION_NOTIONAL,
        max_open_positions: int = DEFAULT_MAX_OPEN_POSITIONS,
        max_daily_loss_pct: float = DEFAULT_MAX_DAILY_LOSS_PCT,
        max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        risk_per_trade_pct: float = DEFAULT_RISK_PER_TRADE_PCT,
        max_stale_seconds: float = DEFAULT_MAX_STALE_SECONDS,
        min_stop_distance_pct: float = DEFAULT_MIN_STOP_DISTANCE_PCT,
    ):
        self.max_position_notional = max_position_notional
        self.max_open_positions = max_open_positions
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_seconds = cooldown_seconds
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_stale_seconds = max_stale_seconds
        self.min_stop_distance_pct = min_stop_distance_pct

        # Internal state
        self._consecutive_losses = 0
        self._last_loss_ts: Optional[float] = None
        self._last_market_ts: Optional[float] = None

    # ------------------------------------------------------------------
    # State ingestion — called by the auto trader
    # ------------------------------------------------------------------
    def observe_trade_result(self, pnl: float, timestamp: Optional[float] = None) -> None:
        """
        Feed a closed-trade PnL into the engine so consecutive-loss and
        cooldown logic can work.
        """
        if pnl < 0:
            self._consecutive_losses += 1
            self._last_loss_ts = timestamp if timestamp is not None else time.time()
        elif pnl > 0:
            self._consecutive_losses = 0

    def observe_market_timestamp(self, ts: Optional[float] = None) -> None:
        """Record the timestamp of the most recent successful market read."""
        self._last_market_ts = ts if ts is not None else time.time()

    # ------------------------------------------------------------------
    # Position sizing — volatility-based
    # ------------------------------------------------------------------
    def calculate_position_size(
        self,
        equity: float,
        price: float,
        atr14: Optional[float],
        stop_distance_pct: Optional[float] = None,
    ) -> float:
        """
        position_size = risk_amount / stop_distance

        Where:
            risk_amount    = equity * risk_per_trade_pct
            stop_distance  = price * stop_distance_pct
                             (falls back to ATR14 if no pct is given)

        The result is in base-asset units (same unit the paper engine uses).
        """
        if equity <= 0 or price <= 0:
            return 0.0

        risk_amount = equity * self.risk_per_trade_pct

        # Prefer explicit stop distance if given.
        if stop_distance_pct and stop_distance_pct > 0:
            stop_distance = price * stop_distance_pct
        elif atr14 and atr14 > 0:
            stop_distance = atr14
        else:
            # Fall back to a minimal fraction of price to avoid zero.
            stop_distance = price * self.min_stop_distance_pct

        if stop_distance <= 0:
            return 0.0

        raw_size = risk_amount / stop_distance

        # Enforce absolute maximum notional.
        max_size_by_notional = self.max_position_notional / price

        return min(raw_size, max_size_by_notional)

    # ------------------------------------------------------------------
    # Validation — main gate
    # ------------------------------------------------------------------
    def validate_position(
        self,
        size: float,
        daily_loss: float,
        equity: Optional[float] = None,
        daily_starting_balance: Optional[float] = None,
        open_positions: int = 0,
        price: Optional[float] = None,
    ) -> dict:
        """
        Return {"allowed": bool, "reason": str}.

        daily_loss is expected to be a POSITIVE number representing the
        magnitude of today's realized loss, or 0 if the day is flat/up.
        """

        # 1. Basic sanity
        if size <= 0:
            return {"allowed": False, "reason": "Position size must be > 0."}

        # 2. Max open positions
        if open_positions >= self.max_open_positions:
            return {
                "allowed": False,
                "reason": f"Max open positions reached ({self.max_open_positions}).",
            }

        # 3. Stale-data protection
        if self._last_market_ts is not None:
            age = time.time() - self._last_market_ts
            if age > self.max_stale_seconds:
                return {
                    "allowed": False,
                    "reason": f"Market data is stale ({age:.1f}s old).",
                }

        # 4. Consecutive-loss cooldown
        if (
            self._consecutive_losses >= self.max_consecutive_losses
            and self._last_loss_ts is not None
        ):
            elapsed = time.time() - self._last_loss_ts
            if elapsed < self.cooldown_seconds:
                remaining = self.cooldown_seconds - elapsed
                return {
                    "allowed": False,
                    "reason": f"Cooldown active after losses ({remaining:.0f}s left).",
                }

        # 5. Max daily loss
        if daily_starting_balance is None and equity is not None:
            # fall back: treat current equity as reference
            daily_starting_balance = equity

        if daily_starting_balance and daily_starting_balance > 0:
            loss_limit = daily_starting_balance * self.max_daily_loss_pct
            if daily_loss >= loss_limit:
                return {
                    "allowed": False,
                    "reason": f"Daily loss limit reached (${loss_limit:.2f}).",
                }

        # 6. Absolute maximum position size (notional cap)
        if price is not None and price > 0:
            notional = size * price
            if notional > self.max_position_notional:
                return {
                    "allowed": False,
                    "reason": (
                        f"Position notional ${notional:.2f} exceeds cap "
                        f"${self.max_position_notional:.2f}."
                    ),
                }

        return {"allowed": True, "reason": "Risk checks passed."}

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def get_state(self) -> dict:
        return {
            "consecutive_losses": self._consecutive_losses,
            "last_loss_ts": self._last_loss_ts,
            "cooldown_seconds": self.cooldown_seconds,
            "max_position_notional": self.max_position_notional,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_consecutive_losses": self.max_consecutive_losses,
            "risk_per_trade_pct": self.risk_per_trade_pct,
        }