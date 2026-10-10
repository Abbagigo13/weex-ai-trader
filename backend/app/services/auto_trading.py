import time

from .market import MarketService
from .paper_trading import PaperTradingService
from ..strategies.engine import StrategyEngine
from ..strategies.risk import RiskEngine
from ..core.logging_setup import get_logger, kv

log = get_logger("auto")


class AutoPaperTradingService:
    """
    Autonomous paper-trading coordinator.

    When enabled:
        No position -> analyze -> risk checks -> possibly open
        Existing position -> monitor SL/TP

    When disabled:
        No automatic trading actions are performed.
    """

    def __init__(
        self,
        market_service: MarketService,
        paper_trading: PaperTradingService,
        strategy_engine: StrategyEngine,
        risk_engine: RiskEngine,
    ):
        self.market_service = market_service
        self.paper_trading = paper_trading
        self.strategy_engine = strategy_engine
        self.risk_engine = risk_engine

        self.enabled = True
        self.confidence_threshold = 0.75
        self.default_stop_distance_pct = 0.01

    def set_enabled(self, enabled: bool) -> dict:
        self.enabled = enabled
        log.info(
            "auto trading %s",
            "ENABLED" if enabled else "DISABLED",
        )
        return {
            "success": True,
            "auto_trading_enabled": self.enabled,
            "message": (
                "Autonomous paper trading enabled."
                if self.enabled
                else "Autonomous paper trading disabled."
            ),
        }

    def get_status(self) -> dict:
        return {
            "auto_trading_enabled": self.enabled,
            "confidence_threshold": self.confidence_threshold,
            "risk_state": self.risk_engine.get_state(),
        }

    async def run_cycle(self, symbol: str) -> dict:

        if not self.enabled:
            return {
                "symbol": symbol,
                "mode": "AUTO_DISABLED",
                "signal": None,
                "confidence": None,
                "confidence_threshold": self.confidence_threshold,
                "position_update": None,
                "position_opened": None,
                "paper_state": self.paper_trading.get_state(),
            }

        # 1. Live market snapshot
        snapshot = await self.market_service.get_market_snapshot(symbol)
        ticker = snapshot["ticker"]
        current_price = float(ticker["last"])

        log.info(
            "cycle tick %s",
            kv(symbol=symbol, price=current_price),
        )

        self.risk_engine.observe_market_timestamp(time.time())

        # 2. Existing position -> monitor only
        existing_position = self.paper_trading.position

        if existing_position:
            if existing_position["symbol"] == symbol:
                position_update = self.paper_trading.update_price(current_price)

                if (
                    isinstance(position_update, dict)
                    and position_update.get("trade")
                ):
                    self.risk_engine.observe_trade_result(
                        position_update["trade"]["pnl"]
                    )
                    log.info(
                        "position closed by monitor %s",
                        kv(
                            symbol=symbol,
                            reason=position_update.get("reason"),
                            pnl=position_update["trade"]["pnl"],
                        ),
                    )

                return {
                    "symbol": symbol,
                    "price": current_price,
                    "mode": "POSITION_MONITOR",
                    "signal": None,
                    "confidence": None,
                    "confidence_threshold": self.confidence_threshold,
                    "position_update": position_update,
                    "position_opened": None,
                    "paper_state": self.paper_trading.get_state(),
                }

            return {
                "symbol": symbol,
                "price": current_price,
                "mode": "POSITION_EXISTS",
                "signal": None,
                "confidence": None,
                "confidence_threshold": self.confidence_threshold,
                "position_update": None,
                "position_opened": None,
                "paper_state": self.paper_trading.get_state(),
            }

        # 3. No position -> analyze
        market_data = await self.market_service.get_candles(
            symbol=symbol,
            granularity="5m",
            limit=100,
        )

        analysis = self.strategy_engine.analyze(market_data)
        signal = analysis["signal"]
        confidence = analysis["confidence"]
        features = analysis.get("features", {})
        atr14 = features.get("atr14")

        log.info(
            "strategy signal %s",
            kv(signal=signal, confidence=confidence),
        )

        position_opened = None
        risk_result = None

        # 4. Entry conditions
        if (
            signal in {"BUY", "SELL"}
            and confidence >= self.confidence_threshold
        ):
            state = self.paper_trading.get_state()
            equity = state["equity"]
            daily_realized = self.paper_trading.get_daily_realized_pnl()
            daily_starting = self.paper_trading.get_daily_starting_balance()

            daily_loss = max(0.0, -daily_realized)

            size = self.risk_engine.calculate_position_size(
                equity=equity,
                price=current_price,
                atr14=atr14,
                stop_distance_pct=self.default_stop_distance_pct,
            )

            open_positions = 1 if self.paper_trading.position else 0

            risk_result = self.risk_engine.validate_position(
                size=size,
                daily_loss=daily_loss,
                equity=equity,
                daily_starting_balance=daily_starting,
                open_positions=open_positions,
                price=current_price,
            )

            log.info(
                "risk check %s",
                kv(
                    allowed=risk_result["allowed"],
                    reason=risk_result["reason"],
                    size=round(size, 8),
                ),
            )

            if risk_result["allowed"] and size > 0:
                position_opened = self.paper_trading.open_position(
                    symbol=symbol,
                    side=signal,
                    size=size,
                    price=current_price,
                    stop_loss_percent=self.default_stop_distance_pct * 100,
                    take_profit_percent=self.default_stop_distance_pct * 200,
                )
                log.info(
                    "position opened %s",
                    kv(
                        symbol=symbol,
                        side=signal,
                        size=round(size, 8),
                        price=current_price,
                    ),
                )

        return {
            "symbol": symbol,
            "price": current_price,
            "mode": "ENTRY_SCAN",
            "signal": signal,
            "confidence": confidence,
            "confidence_threshold": self.confidence_threshold,
            "risk": risk_result,
            "position_update": None,
            "position_opened": position_opened,
            "paper_state": self.paper_trading.get_state(),
        }