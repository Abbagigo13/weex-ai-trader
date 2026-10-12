from typing import Optional

from fastapi import APIRouter, HTTPException

from ..services.market import MarketService
from ..services.trading import TradingService
from ..services.paper_trading import PaperTradingService
from ..services.storage import Storage
from ..services.kill_switch import KillSwitch
from ..services.auto_trading import AutoPaperTradingService
from ..services.weex import WEEXClientError
from ..services.backtest import BacktestEngine
from ..services.backtest_data import load_csv, generate_synthetic
from ..services.ai_explainer import AIExplainer
from ..strategies.engine import StrategyEngine
from ..strategies.risk import RiskEngine
from ..services.walk_forward import WalkForwardEngine

router = APIRouter()

# Services
market_service = MarketService()
trading_service = TradingService()
storage = Storage()
kill_switch = KillSwitch(storage)
paper_trading = PaperTradingService(
    starting_balance=1000.0,
    storage=storage,
)
strategy_engine = StrategyEngine()
risk_engine = RiskEngine()
ai_explainer = AIExplainer()

auto_paper_trading = AutoPaperTradingService(
    market_service=market_service,
    paper_trading=paper_trading,
    strategy_engine=strategy_engine,
    risk_engine=risk_engine,
)


# Health
@router.get("/health")
async def health():
    return {"status": "ok"}


# Market data
@router.get("/market/{symbol}")
async def get_market(symbol: str):
    try:
        return await market_service.get_market_snapshot(symbol)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/candles/{symbol}")
async def get_candles(
    symbol: str,
    granularity: str = "5m",
    limit: int = 100,
):
    try:
        return await market_service.get_candles(
            symbol=symbol,
            granularity=granularity,
            limit=limit,
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# Strategy analysis
@router.get("/analyze/{symbol}")
async def analyze_market(symbol: str):
    try:
        market_data = await market_service.get_candles(
            symbol=symbol,
            granularity="5m",
            limit=100,
        )
        return strategy_engine.analyze(market_data)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# AI explanation layer (explains the rule engine's decision)
@router.get("/ai/status")
async def ai_status():
    return ai_explainer.status()


@router.get("/analyze/{symbol}/explain")
async def analyze_market_with_ai(symbol: str):
    try:
        market_data = await market_service.get_candles(
            symbol=symbol,
            granularity="5m",
            limit=100,
        )
        analysis = strategy_engine.analyze(market_data)
        ai = await ai_explainer.explain(symbol, analysis)
        return {**analysis, "ai": ai}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# Trading endpoint (live execution remains disabled)
@router.post("/trade")
async def execute_trade(
    symbol: str,
    side: str,
    size: float,
):
    try:
        return await trading_service.execute_order(
            symbol=symbol,
            side=side,
            size=size,
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# Paper trading
@router.get("/paper/state")
async def paper_state():
    return paper_trading.get_state()


@router.post("/paper/open")
async def paper_open(
    symbol: str,
    side: str,
    size: float,
    price: float,
):
    if kill_switch.is_active():
        raise HTTPException(
            status_code=403,
            detail=(
                "Kill switch active. New positions are blocked. "
                f"Reason: {kill_switch.get_state()['reason']}"
            ),
        )
    try:
        return paper_trading.open_position(
            symbol=symbol,
            side=side,
            size=size,
            price=price,
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.post("/paper/update")
async def paper_update(price: float):
    try:
        return paper_trading.update_price(price)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.post("/paper/close")
async def paper_close(
    price: Optional[float] = None,
    reason: str = "MANUAL",
):
    try:
        if price is None:
            if paper_trading.position is None:
                raise HTTPException(
                    status_code=400,
                    detail="No open position and no price supplied.",
                )
            price = paper_trading.position["current_price"]

        return paper_trading.close_position(
            price=price, reason=reason
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/paper/history")
async def paper_history():
    return {
        "history": paper_trading.trade_history,
    }


# Autonomous paper trading
@router.get("/paper/auto/status")
async def paper_auto_status():
    return auto_paper_trading.get_status()


@router.post("/paper/auto/toggle")
async def paper_auto_toggle(enabled: bool):
    if enabled and kill_switch.is_active():
        raise HTTPException(
            status_code=403,
            detail="Kill switch active. Cannot enable auto trading.",
        )
    return auto_paper_trading.set_enabled(enabled)


@router.post("/paper/auto")
async def paper_auto(symbol: str = "cmt_btcusdt"):
    try:
        return await auto_paper_trading.run_cycle(symbol=symbol)
    except WEEXClientError as error:
        return {
            "symbol": symbol,
            "mode": "MARKET_UNAVAILABLE",
            "signal": None,
            "confidence": None,
            "position_update": None,
            "position_opened": None,
            "message": str(error),
            "paper_state": paper_trading.get_state(),
        }
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# Persistent history
@router.get("/paper/trades")
async def paper_trades(limit: int = 50):
    return {"trades": storage.get_recent_trades(limit=limit)}


@router.get("/paper/daily/{date}")
async def paper_daily(date: str):
    row = storage.get_daily_pnl(date)
    if row is None:
        raise HTTPException(
            status_code=404, detail="No data for that date."
        )
    return row


@router.get("/paper/stats")
async def paper_stats():
    return storage.get_trade_stats()


# Backtesting
@router.post("/backtest")
async def run_backtest(
    symbol: str = "cmt_btcusdt",
    source: str = "synthetic",
    csv_path: str = "",
    count: int = 2000,
    starting_balance: float = 1000.0,
    confidence_threshold: float = 0.75,
):
    try:
        if source == "synthetic":
            candles = generate_synthetic(count=count)
        elif source == "csv":
            if not csv_path:
                raise HTTPException(
                    status_code=400,
                    detail="csv_path is required when source=csv",
                )
            candles = load_csv(csv_path)
        else:
            raise HTTPException(
                status_code=400,
                detail="source must be 'synthetic' or 'csv'",
            )

        engine = BacktestEngine(
            starting_balance=starting_balance,
            confidence_threshold=confidence_threshold,
        )
        return engine.run(candles=candles, symbol=symbol)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/backtest/available")
async def backtest_available():
    import os

    from ..services.backtest_data import DEFAULT_HISTORY_DIR

    if not os.path.isdir(DEFAULT_HISTORY_DIR):
        return {"files": []}

    files = [
        f
        for f in os.listdir(DEFAULT_HISTORY_DIR)
        if f.lower().endswith(".csv")
    ]
    return {"files": sorted(files)}


# Kill switch
@router.get("/kill/status")
async def kill_status():
    return kill_switch.get_state()


@router.post("/kill/trigger")
async def kill_trigger(reason: str = "MANUAL_EMERGENCY_STOP"):
    state = kill_switch.trigger(reason=reason)
    auto_paper_trading.set_enabled(False)
    return state


@router.post("/kill/release")
async def kill_release():
    return kill_switch.release()


@router.post("/backtest/walk-forward")
async def walk_forward_backtest(
    symbol: str = "cmt_btcusdt",
    source: str = "synthetic",
    csv_path: str = "",
    count: int = 5000,
    windows: int = 5,
    is_ratio: float = 0.7,
    starting_balance: float = 1000.0,
    confidence_threshold: float = 0.75,
):
    try:
        if source == "synthetic":
            candles = generate_synthetic(count=count)
        elif source == "csv":
            if not csv_path:
                raise HTTPException(
                    status_code=400,
                    detail="csv_path is required when source=csv",
                )
            candles = load_csv(csv_path)
        else:
            raise HTTPException(
                status_code=400,
                detail="source must be 'synthetic' or 'csv'",
            )

        engine = WalkForwardEngine(
            starting_balance=starting_balance,
            confidence_threshold=confidence_threshold,
            windows=windows,
            is_ratio=is_ratio,
        )
        return engine.run(candles=candles, symbol=symbol)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/rate-limiter/status")
async def rate_limiter_status():
    return market_service.client.rate_limiter_state()
