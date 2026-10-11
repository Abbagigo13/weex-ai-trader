# WEEX AI Wars II — AI Futures Trading Agent

An automated, AI/quant-style futures trading agent built for **WEEX AI Wars II**.

**Paper trading only.** Live execution is intentionally disabled. All trades
are simulated against live WEEX V3 market data.

## Live Deployment

| Component | URL |
|---|---|
| Frontend (Vercel) | https://weex-ai-trader.vercel.app |
| Backend (Railway) | https://weex-ai-trader-production.up.railway.app |
| Backend API docs | https://weex-ai-trader-production.up.railway.app/docs |
| GitHub | https://github.com/Abbagigo13/weex-ai-trader |

## What This Project Does

- Obtains live WEEX V3 futures market data
- Computes technical indicators (EMA 9/21, RSI 14, Momentum, ATR 14)
- Generates BUY / SELL / WAIT signals with confidence scores
- Applies a full deterministic risk engine (9 controls)
- Simulates trades with a persistent paper-trading engine
- Automatically opens and monitors paper positions
- Tracks realized / unrealized PnL and full trade history
- Persists all state in SQLite (survives restarts)
- Supports historical backtesting and walk-forward validation
- Provides an emergency kill switch
- Exposes a FastAPI backend + React dashboard
- Includes a client-side rate limiter that respects WEEX's
  500 weight / 10s per-IP budget

## Architecture

```

WEEX V3 API
│
▼
WEEXClient  ──►  MarketService
│
▼
StrategyEngine  ──►  RiskEngine  ──►  PaperTradingService
│
▼
AutoPaperTradingService
│
▼
FastAPI  ──►  React Dashboard (Vercel)
│
▼
SQLite (trades, daily_pnl,
snapshots, signals)

```

## Folder Structure

```

weex-ai-trader/
├── README.md
├── DEPLOY.md
├── COMPETITION.md
├── .gitignore
├── backend/
│   ├── .env.example
│   ├── Procfile
│   ├── runtime.txt
│   ├── requirements.txt
│   ├── data/
│   │   ├── paper_trading.db
│   │   └── historical/         # optional CSV fixtures
│   ├── logs/
│   │   └── trader.log
│   └── app/
│       ├── main.py
│       ├── api/
│       │   └── routes.py
│       ├── core/
│       │   ├── config.py
│       │   ├── logging_setup.py
│       │   └── security.py
│       ├── services/
│       │   ├── market.py
│       │   ├── paper_trading.py
│       │   ├── trading.py
│       │   ├── auto_trading.py
│       │   ├── weex.py
│       │   ├── storage.py
│       │   ├── kill_switch.py
│       │   ├── rate_limiter.py
│       │   ├── backtest.py
│       │   ├── backtest_data.py
│       │   └── walk_forward.py
│       └── strategies/
│           ├── engine.py
│           └── risk.py
└── frontend/
├── package.json
├── vite.config.js
├── index.html
└── src/
├── App.jsx
├── main.jsx
├── index.css
└── assets/

```

## Running Locally

### Backend

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

· Backend:  http://127.0.0.1:8000
· Swagger:  http://127.0.0.1:8000/docs

Frontend

```powershell
cd frontend
npm install
npm run dev
```

· Dashboard: http://localhost:5173

Note: frontend/src/App.jsx currently points at the Railway backend.
To use a local backend instead, change line 4:

```javascript
const API = "http://127.0.0.1:8000/api";
```

Environment Variables

Create backend/.env locally (never commit it):

```
ENVIRONMENT=development
TRADING_ENABLED=false
PAPER_TRADING=true
API_PREFIX=/api
APP_NAME=Abbagigo AI Trader

# Optional — only needed for live execution
WEEX_API_KEY=
WEEX_API_SECRET=
WEEX_API_PASSPHRASE=
```

backend/.env.example contains the same keys with empty values, safe to commit.

For deployment, these are set as Railway environment variables.
The frontend URL is added to the CORS allow-list in backend/app/main.py.

API Endpoints

Health and diagnostics

Method Path Purpose
GET /api/health Liveness
GET /api/rate-limiter/status Rate limiter snapshot
GET / Root info

Market data

Method Path Purpose
GET /api/market/{symbol} Live ticker
GET /api/candles/{symbol} Candles
GET /api/analyze/{symbol} Strategy analysis

Paper trading

Method Path Purpose
GET /api/paper/state Account state
POST /api/paper/open Open paper position
POST /api/paper/update Update mark price
POST /api/paper/close Close paper position
GET /api/paper/history In-memory history
GET /api/paper/trades Persistent trade log
GET /api/paper/daily/{date} Daily PnL row
GET /api/paper/stats Aggregate stats

Auto trading

Method Path Purpose
GET /api/paper/auto/status Auto trading status
POST /api/paper/auto/toggle Enable / disable
POST /api/paper/auto Run one auto cycle

Kill switch

Method Path Purpose
GET /api/kill/status Current state
POST /api/kill/trigger Activate
POST /api/kill/release Release

Backtesting

Method Path Purpose
POST /api/backtest Historical backtest
POST /api/backtest/walk-forward Walk-forward test
GET /api/backtest/available List CSV fixtures

Strategy

Deterministic, rule-based, no ML model:

· EMA 9 vs EMA 21 → trend bias
· RSI 14 → momentum confirmation
· 10-bar momentum → short-term bias
· ATR 14 → volatility measure

Signals: BUY, SELL, WAIT.
Confidence range: 0.0 – 1.0.
Entry threshold: 0.75 (configurable).

Risk Engine

Controls enforced on every entry:

1. Position size must be > 0
2. Maximum open positions (1)
3. Stale-data protection (30s freshness)
4. Consecutive-loss cooldown (3 losses → 5 min)
5. Daily loss limit (5% of daily starting balance)
6. Absolute notional cap ($1000)
7. Volatility-based position sizing (risk_amount / stop_distance)
8. Daily realized PnL persisted in SQLite
9. Kill switch integration

Position sizing:

```
risk_amount    = equity * risk_per_trade_pct   (1%)
stop_distance  = price * stop_distance_pct      (1%)
position_size  = min(risk_amount / stop_distance,
                     max_notional / price)
```

Kill Switch

· Blocks all new positions (HTTP 403)
· Forces auto trading off
· Leaves existing positions closeable
· Persists across backend restarts
· Visible as a red bar on the dashboard

Use POST /api/kill/trigger or the red button on the dashboard.

Backtesting

Fully offline. Two data sources:

· synthetic — random walk with realistic volatility
· csv — historical OHLCV from backend/data/historical/

CSV format:

```csv
timestamp,open,high,low,close,volume,quote_volume
```

Metrics reported:

· Total return
· Win rate
· Profit factor
· Maximum drawdown
· Average trade / win / loss
· Maximum consecutive losses
· Equity curve
· Trade history

Walk-Forward Testing

Splits the series into N sequential windows. For each window:

```
[ in-sample ][ out-of-sample ]
```

Reports in-sample vs out-of-sample metrics per window plus:

· Average IS return
· Average OOS return
· Stability ratio (OOS / IS; near 1.0 = robust)
· Positive OOS windows
· Total OOS trades

Rate Limiting

WEEX enforces 500 weight per 10 seconds per IP on public
endpoints. Exceeding it triggers a 10-second IP ban.

rate_limiter.py implements a sliding-window budget with:

· 500 weight budget
· 10-second window
· 50 weight safety margin
· Server-reported weight tracking via X-REMAINING-WEIGHT-10S
· Automatic cooldown on HTTP 429
· Transport-level cooldown on connection resets

Logging

Structured logs written to console and backend/logs/trader.log
(rotating, 5 files × 2 MB).

Categories:

```
[MARKET] [STRATEGY] [RISK] [EXECUTION]
[KILL]   [AUTO]     [STORAGE] [API]
[ERROR]  [SYSTEM]
```

Format:

```
2026-10-10 10:42:46 | INFO    | [MARKET   ] requesting ticker symbol=cmt_btcusdt
2026-10-10 10:43:52 | ERROR   | [MARKET   ] ticker failed symbol=cmt_btcusdt error=...
2026-10-10 10:46:15 | WARNING | [KILL     ] kill switch ACTIVATED reason=MANUAL_EMERGENCY_STOP
```

The formatter redacts anything that looks like an API key, secret,
passphrase, token, or signature.

Transport Layer

WEEXClient uses two transports, chosen automatically:

Platform Transport Why
Windows curl.exe (schannel) Python's OpenSSL cannot complete a TLS handshake with api-contract.weex.com from some residential IPs
Linux / Railway httpx (native OpenSSL) Works from cloud IPs without issue

The public API of WEEXClient is identical on both platforms.
No changes required in MarketService, strategy, or anywhere else.

Deployment

See DEPLOY.md for the full VPS setup guide.

Current live deployment:

· Backend: Railway (Railpack builder, Python 3.12.8)
· Frontend: Vercel (Vite build)

To redeploy after changes:

```powershell
git add .
git commit -m "description"
git push
```

Both Railway and Vercel watch the main branch and redeploy
automatically.

Current Status

Handoff item Status
Market data (V3 client) ✅ Working on Railway
Strategy engine ✅ Working
Risk engine (9 controls) ✅ Working
Paper trading ✅ Working
Daily PnL tracking ✅ Working
SQLite persistence ✅ Working
Auto trading wiring ✅ Working
Frontend dashboard ✅ Deployed
Backtesting ✅ Working
Walk-forward testing ✅ Working
Kill switch ✅ Working
Structured logging ✅ Working
Rate limiter ✅ Working
Live execution ⏸ Intentionally disabled

Do Not

· Enable live trading before the checklist in COMPETITION.md is green
· Disable SSL verification
· Hardcode a WEEX IP
· Commit .env, keys, or secrets
· Optimize the strategy on synthetic data
· Bypass the kill switch