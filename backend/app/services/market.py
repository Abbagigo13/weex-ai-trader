from .weex import WEEXClient, WEEXClientError
from ..core.logging_setup import get_logger, kv

log = get_logger("market")


class MarketService:
    def __init__(self):
        self.client = WEEXClient()

    async def get_market_snapshot(self, symbol: str):
        log.info("requesting ticker %s", kv(symbol=symbol))
        try:
            ticker = await self.client.get_ticker(symbol)
        except WEEXClientError as error:
            log.error(
                "ticker failed %s",
                kv(symbol=symbol, error=str(error)),
            )
            raise

        log.info(
            "ticker received %s",
            kv(
                symbol=symbol,
                last=ticker.get("last"),
                bid=ticker.get("best_bid"),
                ask=ticker.get("best_ask"),
            ),
        )

        return {
            "symbol": symbol,
            "ticker": ticker,
        }

    async def get_candles(
        self,
        symbol: str,
        granularity: str = "5m",
        limit: int = 100,
    ):
        log.info(
            "requesting candles %s",
            kv(symbol=symbol, granularity=granularity, limit=limit),
        )

        try:
            raw_candles = await self.client.get_candles(
                symbol=symbol,
                granularity=granularity,
                limit=limit,
            )
        except WEEXClientError as error:
            log.error(
                "candles failed %s",
                kv(
                    symbol=symbol,
                    granularity=granularity,
                    error=str(error),
                ),
            )
            raise

        normalized = []

        for item in raw_candles:
            # V3 candles are returned as arrays, but we handle both
            # shapes (dicts with a "value" wrapper, or plain arrays)
            # to be safe.
            if isinstance(item, dict):
                candle = item.get("value", [])
            elif isinstance(item, list):
                candle = item
            else:
                continue

            if len(candle) < 8:
                continue

            normalized.append(
                {
                    "timestamp": int(candle[0]),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                    "quote_volume": float(candle[7]),
                }
            )

        # Ensure oldest -> newest, regardless of API response order.
        normalized.sort(key=lambda item: item["timestamp"])

        log.info(
            "candles normalised %s",
            kv(
                symbol=symbol,
                granularity=granularity,
                count=len(normalized),
            ),
        )

        return {
            "symbol": symbol,
            "granularity": granularity,
            "candles": normalized,
        }