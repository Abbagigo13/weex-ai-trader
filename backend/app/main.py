from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core.logging_setup import setup_logging, get_logger
from .api.routes import router

# Configure logging before anything else.
setup_logging()

log = get_logger("system")

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://weex-ai-trader.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    router,
    prefix=settings.API_PREFIX,
)


@app.on_event("startup")
async def on_startup():
    log.info(
        "Backend starting app=%s env=%s trading_enabled=%s paper=%s",
        settings.APP_NAME,
        settings.ENVIRONMENT,
        settings.TRADING_ENABLED,
        settings.PAPER_TRADING,
    )


@app.on_event("shutdown")
async def on_shutdown():
    log.info("Backend shutting down")


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "status": "running",
        "environment": settings.ENVIRONMENT,
        "trading_enabled": settings.TRADING_ENABLED,
        "paper_trading": settings.PAPER_TRADING,
    }