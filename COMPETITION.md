# WEEX AI Wars II — Competition Readiness

**Project:** Abbagigo AI Trader
**Track:** Team AI — Automated futures trading via WEEX API
**Mode:** Paper trading during development · Live execution gated
**Status as of:** 2026-10-10

---

## 1. Executive Summary

An automated quantitative futures trading agent built for WEEX AI Wars II.

The system:

- Reads live WEEX V3 futures market data
- Computes technical indicators (EMA9, EMA21, RSI14, Momentum, ATR14)
- Generates BUY / SELL / WAIT signals with confidence scores
- Applies 9 deterministic risk controls before any entry
- Simulates and monitors positions with a persistent paper engine
- Persists everything in SQLite (survives restarts)
- Exposes a FastAPI backend and a React dashboard
- Includes a persistent emergency kill switch
- Includes backtesting and walk-forward validation
- Includes a client-side rate limiter that respects WEEX's
  500 weight / 10s per-IP budget

**Everything that can be built without WEEX access is built, tested,
and durable.** The only remaining work depends on external access:
a non-blocked IP (VPS or proxy) and a WEEX API key.

---

## 2. Competition Rules Compliance

| Rule | Status |
| --- | --- |
| AI track = only API orders count | ✅ Once live execution is wired |
| Custom API program allowed | ✅ This is exactly what we built |
| WEEX Skills optional | ✅ Not required, skipped |
| API key + secret + passphrase required | ⚠️ To create on VPS |
| 2FA on WEEX account required | ⚠️ User to confirm |
| Dedicated key recommended for AI Wars II | ⚠️ To create |
| Read-only until ready | ✅ All market data calls are public |
| API trading permissions required for orders | ⚠️ Enable at key creation |
| Never share key / secret / passphrase | ✅ Log sanitizer strips them |
| Wash trading / self-trading / manipulation banned | ✅ Single account, single client |
| Rankings by live trading performance | ✅ Once live execution is enabled |
| Multi-metric evaluation (profit, risk, stability) | ✅ Addressed by risk engine + walk-forward |

---

## 3. Deliverables

| Artifact | Path |
| --- | --- |
| Backend (FastAPI) | `backend/app/` |
| Frontend (React + Vite) | `frontend/src/` |
| Paper trading DB | `backend/data/paper_trading.db` |
| Structured logs | `backend/logs/trader.log` |
| Project README | `README.md` |
| Deployment guide | `DEPLOY.md` |
| Competition summary | `COMPETITION.md` (this file) |

---

## 4. System Capabilities

### 4.1 Market Data

- WEEX V3 public endpoints
- Symbol normalization (`cmt_btcusdt` → `BTCUSDT`)
- Ticker + book ticker + candles
- Candle normalization and ascending sort

### 4.2 Strategy

- EMA 9 vs EMA 21 trend bias
- RSI 14 momentum confirmation
- 10-bar momentum filter
- ATR 14 volatility measure
- Weighted scoring → BUY / SELL / WAIT
- Confidence 0.0 – 1.0
- Confidence threshold: 0.75 (configurable)

### 4.3 Risk Engine (9 controls)

1. Position size > 0
2. Maximum open positions
3. Stale-data protection (30s freshness)
4. Consecutive-loss cooldown (3 losses → 5 min)
5. Daily loss limit (5% of daily starting balance)
6. Absolute notional cap ($1000)
7. Volatility-based position sizing
8. Daily realized PnL tracked in SQLite
9. Emergency kill switch integration

### 4.4 Paper Trading

- Starting balance $1000
- Single active position
- Stop-loss and take-profit
- Realized and unrealized PnL
- Daily PnL tracking with date rollover
- Full trade history
- SQLite persistence across restarts

### 4.5 Auto Trading

- Enable / disable via UI or API
- Runs one cycle per invocation
- Position monitor mode when in trade
- Soft-fails on market unavailability
- Real daily loss fed to the risk engine

### 4.6 Kill Switch

- Persists across restarts
- Blocks new positions (HTTP 403)
- Forces auto trading off
- Leaves existing positions closeable
- Visible as a red bar in the dashboard

### 4.7 Backtesting

- Synthetic and CSV data sources
- Full performance metrics:
  - Total return
  - Win rate
  - Profit factor
  - Max drawdown
  - Average trade / win / loss
  - Max consecutive losses
  - Equity curve

### 4.8 Walk-Forward Testing

- N-window sequential split
- In-sample vs out-of-sample per window
- Stability ratio (OOS / IS)
- Positive OOS window count

### 4.9 Rate Limiting

- 500 weight / 10 seconds sliding window
- Reads `X-REMAINING-WEIGHT-10S` header
- Safety margin of 50 weight
- Automatic cooldown on HTTP 429
- Transport-level cooldown on connection resets

### 4.10 Logging

- Structured category tags
- Rotating file at `logs/trader.log` (5 × 2 MB)
- Secret sanitizer
- Categories: `[MARKET] [STRATEGY] [RISK] [EXECUTION] [KILL] [AUTO] [STORAGE] [ERROR] [SYSTEM]`

### 4.11 Dashboard

- Kill switch bar
- Auto engine control
- Account (balance, equity, realized, unrealized)
- Active position with SL/TP
- Market intelligence (all indicators)
- Paper performance statistics
- Backtest panel
- Walk-forward panel
- AI activity log

---

## 5. Pre-Competition Checklist

| # | Item | State |
| --- | --- | --- |
| 1 | WEEX connectivity stable | ❌ External — VPS required |
| 2 | V3 market data stable | ⚠️ Code correct, connection intermittent |
| 3 | Symbol mapping verified | ✅ |
| 4 | Candle normalization verified | ✅ |
| 5 | Strategy tested | ✅ |
| 6 | Backtesting completed | ✅ |
| 7 | Walk-forward testing completed | ✅ |
| 8 | Risk engine completed | ✅ |
| 9 | Daily loss protection completed | ✅ |
| 10 | Position sizing completed | ✅ |
| 11 | Paper trading stable | ✅ |
| 12 | SQLite persistence added | ✅ |
| 13 | Trade history verified | ✅ |
| 14 | Auto trading stable | ✅ |
| 15 | API authentication tested | ❌ Awaiting key |
| 16 | Kill switch implemented | ✅ |
| 17 | Error recovery implemented | ✅ |
| 18 | API limits respected | ✅ |
| 19 | Current competition rules rechecked | ✅ |

**14 / 19 green. 5 pending external access.**

---

## 6. Deployment Plan

See `DEPLOY.md` for exact commands. High-level:

1. Provision a VPS with a static IP.
2. Verify WEEX reachable from the VPS (`curl` test).
3. Clone the project, set up venv, install deps.
4. Swap `weex.py` transport from `curl.exe` to native `httpx`.
5. Configure `.env` with production settings.
6. Run backend as a systemd service.
7. Create WEEX API key on the VPS, bind to the VPS IP.
8. Store keys in `.env` (chmod 600).
9. Run paper trading for 24 hours to confirm stability.
10. Wire authenticated order submission into `trading_service`.
11. Enable live execution.

Steps 1–9 are safe. Step 10 is the only change touching real orders.

---

## 7. Risk Statement

- **No live trading during development.**
- **No disabling of SSL verification.**
- **No hardcoded IPs.**
- **No secrets committed.**
- **No strategy optimization against synthetic data.**
- **No bypass of the kill switch.**
- **No self-trading, wash trading, or account manipulation.**

The system enforces these constraints at the code level, not just
by policy:

- `trading_service.execute_order()` is disabled.
- `weex.py` uses TLS with verification.
- `.env` is in `.gitignore`.
- Log sanitizer redacts credentials.
- Kill switch blocks new positions in `routes.py`.
- Risk engine uses real daily PnL from SQLite.

---

## 8. Performance Metrics To Watch (Live)

Once live trading begins, the competition scores on:

- **Profitability** — realized PnL over the competition window
- **Risk management** — max drawdown, daily loss adherence
- **Strategy stability** — consistency across rounds

These are tracked by:

- `backend/data/paper_trading.db` (trades + daily_pnl tables)
- `GET /api/paper/stats`
- `POST /api/backtest`
- `POST /api/backtest/walk-forward`
- The React dashboard's performance and walk-forward cards

---

## 9. Change Log (Development Phase)

| Item | What was added |
| --- | --- |
| V2 → V3 migration | `BTCUSDT` symbol format, `response.value[0]` unwrapping |
| TLS diagnosis | Root-caused to OpenSSL renegotiation vs CloudFront |
| Temporary transport | curl.exe with retries (Windows), replaced on VPS |
| Paper engine | Persistent, SL/TP, daily PnL |
| SQLite | trades, daily_pnl, snapshots, signals |
| Risk engine | All 9 controls + volatility sizing |
| Kill switch | Persistent, blocks new positions |
| Backtest | Synthetic + CSV data sources |
| Walk-forward | IS/OOS with stability ratio |
| Rate limiter | 500/10s sliding window |
| Logging | Structured, sanitized, rotating |
| Frontend | Full dashboard with 10+ cards |

---

## 10. Final Statement

The system is architecturally complete and competition-ready
**except for external access**.

Everything that can be built without WEEX's network is built,
tested, and durable. The moment a VPS or proxy with a clean IP is
available, and a WEEX API key is created and bound, the remaining
work is a small, well-scoped change:

1. Swap the transport (one method in `weex.py`).
2. Wire authenticated order submission (one method in `trading.py`).
3. Set `.env` keys.

No changes to strategy, risk, paper trading, kill switch, logging,
rate limiter, storage, backtesting, walk-forward, or frontend.

---

## 11. Contact & Repository

- **Project path:** `C:\Users\PC\weex-ai-trader`
- **Backend entry:** `backend/app/main.py`
- **Frontend entry:** `frontend/src/App.jsx`
- **Repo:** (add when ready)
- **DoraHacks:** (add link)
