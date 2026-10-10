from ..core.security import trading_is_allowed


class TradingService:

    async def execute_order(
        self,
        symbol: str,
        side: str,
        size: float,
    ):

        if not trading_is_allowed():
            return {
                "success": False,
                "mode": "paper",
                "message": "Real trading is disabled.",
                "order": {
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                },
            }

        # Real WEEX execution will be implemented here later.
        return {
            "success": False,
            "mode": "live",
            "message": "Live execution is not implemented yet.",
        }