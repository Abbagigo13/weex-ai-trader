from typing import Any


class StrategyEngine:
    """
    Deterministic market-analysis engine.

    This is our first strategy layer.
    It does NOT place trades.

    Signals are based on:
    - EMA 9 vs EMA 21
    - RSI 14
    - short-term momentum
    - ATR-based volatility
    """

    def analyze(self, market_data: Any) -> dict:
        candles = market_data.get("candles", [])

        if len(candles) < 30:
            return {
                "signal": "WAIT",
                "confidence": 0.0,
                "reason": "Not enough candle data for analysis.",
                "features": {},
            }

        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]

        ema9 = self._ema(closes, 9)
        ema21 = self._ema(closes, 21)
        rsi14 = self._rsi(closes, 14)
        atr14 = self._atr(highs, lows, closes, 14)

        current_price = closes[-1]

        momentum_period = 10

        if len(closes) > momentum_period:
            momentum = (
                (current_price - closes[-1 - momentum_period])
                / closes[-1 - momentum_period]
            ) * 100
        else:
            momentum = 0.0

        score = 0
        reasons = []

        # Trend
        if ema9 > ema21:
            score += 2
            reasons.append("EMA9 is above EMA21")
        elif ema9 < ema21:
            score -= 2
            reasons.append("EMA9 is below EMA21")

        # RSI
        if 50 <= rsi14 < 70:
            score += 1
            reasons.append("RSI supports bullish momentum")
        elif 30 < rsi14 < 50:
            score -= 1
            reasons.append("RSI supports bearish momentum")
        elif rsi14 >= 70:
            reasons.append("RSI is overbought")
        elif rsi14 <= 30:
            reasons.append("RSI is oversold")

        # Momentum
        if momentum > 0.15:
            score += 1
            reasons.append("Short-term momentum is positive")
        elif momentum < -0.15:
            score -= 1
            reasons.append("Short-term momentum is negative")

        # Convert score to signal
        if score >= 3:
            signal = "BUY"
        elif score <= -3:
            signal = "SELL"
        else:
            signal = "WAIT"

        confidence = min(abs(score) / 4, 1.0)

        # Don't give high confidence to extreme RSI conditions.
        if signal == "BUY" and rsi14 >= 75:
            confidence *= 0.65

        if signal == "SELL" and rsi14 <= 25:
            confidence *= 0.65

        reason = "; ".join(reasons)

        return {
            "signal": signal,
            "confidence": round(confidence, 3),
            "reason": reason,
            "features": {
                "price": round(current_price, 4),
                "ema9": round(ema9, 4),
                "ema21": round(ema21, 4),
                "rsi14": round(rsi14, 2),
                "momentum_percent": round(momentum, 3),
                "atr14": round(atr14, 4),
                "score": score,
                "candles_used": len(candles),
            },
        }

    def _ema(self, values: list[float], period: int) -> float:
        if len(values) < period:
            return values[-1]

        multiplier = 2 / (period + 1)

        ema = sum(values[:period]) / period

        for price in values[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    def _rsi(self, values: list[float], period: int = 14) -> float:
        if len(values) <= period:
            return 50.0

        gains = []
        losses = []

        for i in range(1, len(values)):
            change = values[i] - values[i - 1]

            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss

        return 100 - (100 / (1 + rs))

    def _atr(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> float:

        if len(closes) <= period:
            return 0.0

        true_ranges = []

        for i in range(1, len(closes)):
            high = highs[i]
            low = lows[i]
            previous_close = closes[i - 1]

            true_range = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )

            true_ranges.append(true_range)

        if len(true_ranges) < period:
            return 0.0

        atr = sum(true_ranges[:period]) / period

        for value in true_ranges[period:]:
            atr = ((atr * (period - 1)) + value) / period

        return atr