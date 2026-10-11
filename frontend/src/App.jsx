import { useEffect, useState } from "react";
import "./index.css";

const API = "https://weex-ai-trader-production.up.railway.app/api";

function App() {
  const [status, setStatus] = useState("CONNECTING");
  const [ticker, setTicker] = useState(null);
  const [symbol, setSymbol] = useState("cmt_btcusdt");
  const [analysis, setAnalysis] = useState(null);
  const [paper, setPaper] = useState(null);
  const [loading, setLoading] = useState(false);

  // Backtest
  const [backtest, setBacktest] = useState(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestSource, setBacktestSource] = useState("synthetic");

  // Walk-forward
  const [wfResult, setWfResult] = useState(null);
  const [wfLoading, setWfLoading] = useState(false);
  const [wfWindows, setWfWindows] = useState(5);
  const [wfIsRatio, setWfIsRatio] = useState(0.7);

  // Auto trading
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [autoData, setAutoData] = useState(null);
  const [autoLoading, setAutoLoading] = useState(false);

  // Kill switch
  const [killState, setKillState] = useState({
    active: false,
    reason: null,
    since: null,
  });
  const [killLoading, setKillLoading] = useState(false);

  // ------------------------------------------------------------------
  // Backend + market loaders
  // ------------------------------------------------------------------
  async function checkBackend() {
    try {
      const response = await fetch(`${API}/health`);
      if (!response.ok) throw new Error("Backend unavailable");
      setStatus("ONLINE");
    } catch {
      setStatus("OFFLINE");
    }
  }

  async function loadMarket() {
    try {
      const response = await fetch(`${API}/market/${symbol}`);
      if (!response.ok) throw new Error("Market request failed");
      const data = await response.json();
      setTicker(data.ticker ?? null);
    } catch (error) {
      console.error(error);
    }
  }

  async function loadPaperState() {
    try {
      const response = await fetch(`${API}/paper/state`);
      if (!response.ok) throw new Error("Paper state request failed");
      const data = await response.json();
      setPaper(data);
    } catch (error) {
      console.error(error);
    }
  }

  async function loadAutoStatus() {
    try {
      const response = await fetch(`${API}/paper/auto/status`);
      if (!response.ok) throw new Error("Auto status request failed");
      const data = await response.json();
      setAutoEnabled(data.auto_trading_enabled);
    } catch (error) {
      console.error(error);
    }
  }

  async function loadKillStatus() {
    try {
      const response = await fetch(`${API}/kill/status`);
      if (!response.ok) return;
      const data = await response.json();
      setKillState(data);
    } catch (error) {
      console.error(error);
    }
  }

  // ------------------------------------------------------------------
  // Auto trading
  // ------------------------------------------------------------------
  async function toggleAutoTrading() {
    if (autoLoading) return;
    setAutoLoading(true);
    try {
      const nextState = !autoEnabled;
      const response = await fetch(
        `${API}/paper/auto/toggle?enabled=${nextState}`,
        { method: "POST" }
      );
      if (!response.ok) {
        throw new Error("Unable to change auto trading state");
      }
      const data = await response.json();
      setAutoEnabled(data.auto_trading_enabled);
      setAutoData({
        ...autoData,
        mode: data.auto_trading_enabled
          ? "AUTO_ENABLED"
          : "AUTO_DISABLED",
        message: data.message,
      });
    } catch (error) {
      console.error(error);
    } finally {
      setAutoLoading(false);
    }
  }

  async function runAutoTrading() {
    if (!autoEnabled) return;
    try {
      const response = await fetch(
        `${API}/paper/auto?symbol=${symbol}`,
        { method: "POST" }
      );
      if (!response.ok) {
        throw new Error("Automatic trading cycle failed");
      }
      const data = await response.json();
      setPaper(data.paper_state);
      setAutoData(data);
    } catch (error) {
      console.error(error);
    }
  }

  // ------------------------------------------------------------------
  // Analysis
  // ------------------------------------------------------------------
  async function analyze() {
    setLoading(true);
    try {
      const response = await fetch(`${API}/analyze/${symbol}`);
      if (!response.ok) throw new Error("Analysis request failed");
      const data = await response.json();
      setAnalysis(data.analysis ?? data);
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }

  // ------------------------------------------------------------------
  // Backtest
  // ------------------------------------------------------------------
  async function runBacktest() {
    setBacktestLoading(true);
    try {
      const params = new URLSearchParams({
        symbol,
        source: backtestSource,
        count: "2000",
        starting_balance: "1000",
        confidence_threshold: "0.75",
      });
      const response = await fetch(
        `${API}/backtest?${params.toString()}`,
        { method: "POST" }
      );
      if (!response.ok) throw new Error("Backtest request failed");
      const data = await response.json();
      setBacktest(data);
    } catch (error) {
      console.error(error);
    } finally {
      setBacktestLoading(false);
    }
  }

  // ------------------------------------------------------------------
  // Walk-forward
  // ------------------------------------------------------------------
  async function runWalkForward() {
    setWfLoading(true);
    try {
      const params = new URLSearchParams({
        symbol,
        source: backtestSource,
        count: "5000",
        windows: String(wfWindows),
        is_ratio: String(wfIsRatio),
        starting_balance: "1000",
        confidence_threshold: "0.75",
      });
      const response = await fetch(
        `${API}/backtest/walk-forward?${params.toString()}`,
        { method: "POST" }
      );
      if (!response.ok) throw new Error("Walk-forward request failed");
      const data = await response.json();
      setWfResult(data);
    } catch (error) {
      console.error(error);
    } finally {
      setWfLoading(false);
    }
  }

  // ------------------------------------------------------------------
  // Kill switch
  // ------------------------------------------------------------------
  async function triggerKill() {
    if (
      !window.confirm(
        "EMERGENCY STOP\n\nThis will:\n" +
          "- Disable auto trading\n" +
          "- Block all new positions\n" +
          "- Keep existing positions closeable\n\n" +
          "Continue?"
      )
    )
      return;

    setKillLoading(true);
    try {
      const response = await fetch(`${API}/kill/trigger`, {
        method: "POST",
      });
      if (!response.ok) throw new Error("Kill trigger failed");
      const data = await response.json();
      setKillState(data);
      setAutoEnabled(false);
    } catch (error) {
      console.error(error);
    } finally {
      setKillLoading(false);
    }
  }

  async function releaseKill() {
    if (
      !window.confirm(
        "RELEASE KILL SWITCH\n\nThis will re-allow new positions.\n" +
          "Auto trading will remain OFF until you enable it again.\n\n" +
          "Continue?"
      )
    )
      return;

    setKillLoading(true);
    try {
      const response = await fetch(`${API}/kill/release`, {
        method: "POST",
      });
      if (!response.ok) throw new Error("Kill release failed");
      const data = await response.json();
      setKillState(data);
    } catch (error) {
      console.error(error);
    } finally {
      setKillLoading(false);
    }
  }

  // ------------------------------------------------------------------
  // Effects
  // ------------------------------------------------------------------
  useEffect(() => {
    const initialize = async () => {
      await Promise.all([
        checkBackend(),
        loadMarket(),
        loadPaperState(),
        loadAutoStatus(),
        loadKillStatus(),
      ]);
    };
    void initialize();
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      loadMarket();
      loadPaperState();
      loadAutoStatus();
      loadKillStatus();

      if (autoEnabled) {
        runAutoTrading();
      } else {
        // Keep strategy features fresh when auto is off.
        analyze();
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [symbol, autoEnabled]);

  // ------------------------------------------------------------------
  // Derived values
  // ------------------------------------------------------------------
  const signal = autoData?.signal || analysis?.signal || "WAIT";

  const confidenceValue =
    autoData?.confidence ?? analysis?.confidence ?? 0;

  const confidence = Math.round(confidenceValue * 100);

  // Try analysis first, then auto-cycle features, then nothing.
  const features = analysis?.features || autoData?.features || {};

  // Live price — prefer ticker, fall back to strategy price.
  const livePrice =
    ticker?.last ?? features.price ?? null;

  const price = livePrice
    ? Number(livePrice).toLocaleString()
    : "--";

  const balance = paper?.balance ?? 0;
  const equity = paper?.equity ?? 0;
  const realizedPnl = paper?.realized_pnl ?? 0;
  const unrealizedPnl = paper?.unrealized_pnl ?? 0;
  const drawdown = paper?.drawdown_percent ?? 0;

  const totalTrades = paper?.statistics?.total_trades ?? 0;
  const winningTrades = paper?.statistics?.winning_trades ?? 0;
  const losingTrades = paper?.statistics?.losing_trades ?? 0;

  const winRate =
    totalTrades > 0
      ? ((winningTrades / totalTrades) * 100).toFixed(1)
      : "0.0";

  const position = paper?.position;

  const autoMode =
    autoData?.mode || (autoEnabled ? "READY" : "AUTO_DISABLED");

  const lastAction =
    autoData?.position_update?.reason ||
    autoData?.position_opened?.message ||
    autoData?.message ||
    (position
      ? "Position being monitored"
      : "Waiting for next scan");

  return (
    <div className="app">
      {/* TOP BAR */}

      <header className="topbar">
        <div>
          <h1>ABBAGIGO AI</h1>
          <span>Autonomous Trading Intelligence</span>
        </div>

        <div className="status">
          <span
            className={`status-dot ${
              status === "ONLINE" ? "online" : ""
            }`}
          />
          {status}
        </div>
      </header>

      {/* KILL SWITCH BAR */}

      <section
        className={`kill-bar ${killState.active ? "killed" : ""}`}
      >
        <div className="kill-status">
          <span
            className={`kill-dot ${
              killState.active ? "active" : ""
            }`}
          />
          <strong>
            {killState.active
              ? "EMERGENCY STOP ACTIVE"
              : "SYSTEM ARMED"}
          </strong>
          {killState.active && killState.reason && (
            <span className="muted">
              — {killState.reason}
              {killState.since ? ` @ ${killState.since}` : ""}
            </span>
          )}
        </div>

        {killState.active ? (
          <button
            className="kill-btn release"
            onClick={releaseKill}
            disabled={killLoading}
          >
            {killLoading ? "RELEASING..." : "RELEASE KILL SWITCH"}
          </button>
        ) : (
          <button
            className="kill-btn trigger"
            onClick={triggerKill}
            disabled={killLoading}
          >
            {killLoading ? "TRIGGERING..." : "EMERGENCY STOP"}
          </button>
        )}
      </section>

      <main className="dashboard">
        {/* HERO */}

        <section className="hero-card">
          <div>
            <p className="eyebrow">WEEX AI WARS II</p>
            <h2>AI Trading Command Center</h2>
            <p className="description">
              Market intelligence, strategy analysis and risk-controlled
              execution.
            </p>
          </div>

          <div className="mode">
            <span>MODE</span>
            <strong>PAPER TRADING</strong>
          </div>
        </section>

        {/* AUTONOMOUS ENGINE */}

        <section className="card auto-engine">
          <div className="auto-header">
            <div>
              <span className="metric-label">AUTONOMOUS ENGINE</span>
              <h3>
                {autoEnabled ? "SYSTEM ACTIVE" : "SYSTEM PAUSED"}
              </h3>
            </div>

            <button
              className={
                autoEnabled ? "auto-toggle active" : "auto-toggle"
              }
              onClick={toggleAutoTrading}
              disabled={autoLoading || killState.active}
            >
              <span
                className={
                  autoEnabled ? "engine-dot active" : "engine-dot"
                }
              />
              {autoLoading
                ? "CHANGING..."
                : autoEnabled
                ? "AUTO ON"
                : "AUTO OFF"}
            </button>
          </div>

          <div className="auto-grid">
            <div>
              <span>ENGINE STATUS</span>
              <strong>{autoEnabled ? "ACTIVE" : "PAUSED"}</strong>
            </div>

            <div>
              <span>MODE</span>
              <strong>{autoMode}</strong>
            </div>

            <div>
              <span>SIGNAL</span>
              <strong
                className={
                  signal === "BUY"
                    ? "profit"
                    : signal === "SELL"
                    ? "loss"
                    : ""
                }
              >
                {signal}
              </strong>
            </div>

            <div>
              <span>CONFIDENCE</span>
              <strong>{confidence}%</strong>
            </div>
          </div>

          <div className="auto-action">
            <span>LAST ACTION</span>
            <strong>{lastAction}</strong>
          </div>
        </section>

        {/* ACCOUNT */}

        <section className="account-grid">
          <div className="card account-card">
            <span className="metric-label">BALANCE</span>
            <strong>${Number(balance).toFixed(2)}</strong>
          </div>

          <div className="card account-card">
            <span className="metric-label">EQUITY</span>
            <strong>${Number(equity).toFixed(2)}</strong>
          </div>

          <div className="card account-card">
            <span className="metric-label">REALIZED PNL</span>
            <strong
              className={
                realizedPnl > 0
                  ? "profit"
                  : realizedPnl < 0
                  ? "loss"
                  : ""
              }
            >
              {realizedPnl >= 0 ? "+" : ""}$
              {Number(realizedPnl).toFixed(4)}
            </strong>
          </div>

          <div className="card account-card">
            <span className="metric-label">UNREALIZED PNL</span>
            <strong
              className={
                unrealizedPnl > 0
                  ? "profit"
                  : unrealizedPnl < 0
                  ? "loss"
                  : ""
              }
            >
              {unrealizedPnl >= 0 ? "+" : ""}$
              {Number(unrealizedPnl).toFixed(4)}
            </strong>
          </div>
        </section>

        {/* MAIN GRID */}

        <section className="grid">
          {/* MARKET */}

          <div className="card market-card">
            <div className="card-header">
              <span>MARKET</span>
              <select
                value={symbol}
                onChange={(event) => {
                  setSymbol(event.target.value);
                }}
              >
                <option value="cmt_btcusdt">BTC/USDT</option>
                <option value="cmt_ethusdt">ETH/USDT</option>
                <option value="cmt_solusdt">SOL/USDT</option>
                <option value="cmt_dogeusdt">DOGE/USDT</option>
                <option value="cmt_xrpusdt">XRP/USDT</option>
              </select>
            </div>

            <div className="price">${price}</div>

            <p className="muted">
              {symbol.replace("cmt_", "").toUpperCase()}
            </p>

            <button onClick={loadMarket}>REFRESH MARKET</button>
          </div>

          {/* AI SIGNAL */}

          <div className="card">
            <div className="card-header">
              <span>AI SIGNAL</span>
            </div>

            <div className={`signal ${signal.toLowerCase()}`}>
              {signal}
            </div>

            <div className="confidence">
              <span>CONFIDENCE</span>
              <strong>{confidence}%</strong>
            </div>

            <p className="muted">
              {autoData?.reason ||
                analysis?.reason ||
                "Run analysis to generate a market signal."}
            </p>

            <button onClick={analyze} disabled={loading}>
              {loading ? "ANALYZING..." : "RUN AI ANALYSIS"}
            </button>
          </div>

          {/* RISK */}

          <div className="card">
            <div className="card-header">
              <span>RISK ENGINE</span>
            </div>

            <div className="risk-number">
              {Number(drawdown).toFixed(2)}%
            </div>

            <p className="muted">Current drawdown</p>

            <div className="risk-bar">
              <div
                style={{
                  width: `${Math.min(drawdown, 100)}%`,
                }}
              />
            </div>
          </div>

          {/* EXECUTION */}

          <div className="card">
            <div className="card-header">
              <span>EXECUTION</span>
            </div>

            <div className="execution-status">
              <span />
              LOCKED
            </div>

            <p className="muted">Live execution is disabled.</p>
          </div>
        </section>

        {/* ACTIVE POSITION */}

        <section className="card position-card">
          <div className="card-header">
            <span>ACTIVE POSITION</span>
            <span className="muted">
              {position ? "OPEN" : "NONE"}
            </span>
          </div>

          {position ? (
            <div className="position-grid">
              <div>
                <span>SYMBOL</span>
                <strong>{position.symbol}</strong>
              </div>

              <div>
                <span>SIDE</span>
                <strong
                  className={
                    position.side === "BUY" ? "profit" : "loss"
                  }
                >
                  {position.side}
                </strong>
              </div>

              <div>
                <span>SIZE</span>
                <strong>{position.size}</strong>
              </div>

              <div>
                <span>ENTRY</span>
                <strong>
                  ${Number(position.entry_price).toLocaleString()}
                </strong>
              </div>

              <div>
                <span>CURRENT</span>
                <strong>
                  $
                  {Number(
                    position.current_price
                  ).toLocaleString()}
                </strong>
              </div>

              <div>
                <span>STOP LOSS</span>
                <strong>
                  ${Number(position.stop_loss).toLocaleString()}
                </strong>
              </div>

              <div>
                <span>TAKE PROFIT</span>
                <strong>
                  ${Number(position.take_profit).toLocaleString()}
                </strong>
              </div>
            </div>
          ) : (
            <div className="empty-position">
              No active paper position.
            </div>
          )}
        </section>

        {/* MARKET INTELLIGENCE */}

        <section className="card indicators">
          <div className="card-header">
            <span>MARKET INTELLIGENCE</span>
            <span className="muted">5M</span>
          </div>

          <div className="indicator-grid">
            <div>
              <span>PRICE</span>
              <strong>
                {livePrice
                  ? `$${Number(livePrice).toLocaleString()}`
                  : "--"}
              </strong>
            </div>

            <div>
              <span>EMA 9</span>
              <strong>
                {features.ema9
                  ? Number(features.ema9).toLocaleString()
                  : "--"}
              </strong>
            </div>

            <div>
              <span>EMA 21</span>
              <strong>
                {features.ema21
                  ? Number(features.ema21).toLocaleString()
                  : "--"}
              </strong>
            </div>

            <div>
              <span>RSI 14</span>
              <strong>{features.rsi14 ?? "--"}</strong>
            </div>

            <div>
              <span>MOMENTUM</span>
              <strong>
                {features.momentum_percent !== undefined
                  ? `${features.momentum_percent}%`
                  : "--"}
              </strong>
            </div>

            <div>
              <span>ATR 14</span>
              <strong>{features.atr14 ?? "--"}</strong>
            </div>

            <div>
              <span>SCORE</span>
              <strong>{features.score ?? "--"}</strong>
            </div>

            <div>
              <span>CANDLES</span>
              <strong>{features.candles_used ?? "--"}</strong>
            </div>
          </div>
        </section>

        {/* PERFORMANCE */}

        <section className="card performance-card">
          <div className="card-header">
            <span>PAPER PERFORMANCE</span>
            <span className="muted">LIVE</span>
          </div>

          <div className="performance-grid">
            <div>
              <span>TOTAL TRADES</span>
              <strong>{totalTrades}</strong>
            </div>

            <div>
              <span>WINNING</span>
              <strong>{winningTrades}</strong>
            </div>

            <div>
              <span>LOSING</span>
              <strong>{losingTrades}</strong>
            </div>

            <div>
              <span>WIN RATE</span>
              <strong>{winRate}%</strong>
            </div>
          </div>
        </section>

        {/* BACKTEST */}

        <section className="card performance-card">
          <div className="card-header">
            <span>BACKTEST</span>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <select
                value={backtestSource}
                onChange={(e) =>
                  setBacktestSource(e.target.value)
                }
              >
                <option value="synthetic">Synthetic</option>
                <option value="csv">CSV</option>
              </select>

              <button
                onClick={runBacktest}
                disabled={backtestLoading}
              >
                {backtestLoading ? "RUNNING..." : "RUN BACKTEST"}
              </button>
            </div>
          </div>

          {backtest ? (
            <div className="performance-grid">
              <div>
                <span>RETURN</span>
                <strong
                  className={
                    backtest.total_return_pct > 0
                      ? "profit"
                      : backtest.total_return_pct < 0
                      ? "loss"
                      : ""
                  }
                >
                  {backtest.total_return_pct >= 0 ? "+" : ""}
                  {backtest.total_return_pct}%
                </strong>
              </div>

              <div>
                <span>TRADES</span>
                <strong>{backtest.total_trades}</strong>
              </div>

              <div>
                <span>WIN RATE</span>
                <strong>{backtest.win_rate}%</strong>
              </div>

              <div>
                <span>PROFIT FACTOR</span>
                <strong>{backtest.profit_factor ?? "∞"}</strong>
              </div>

              <div>
                <span>MAX DD</span>
                <strong className="loss">
                  -{backtest.max_drawdown_pct}%
                </strong>
              </div>

              <div>
                <span>AVG TRADE</span>
                <strong>${backtest.average_trade}</strong>
              </div>

              <div>
                <span>AVG WIN</span>
                <strong className="profit">
                  ${backtest.average_win}
                </strong>
              </div>

              <div>
                <span>AVG LOSS</span>
                <strong className="loss">
                  ${backtest.average_loss}
                </strong>
              </div>

              <div>
                <span>MAX LOSS STREAK</span>
                <strong>{backtest.max_consecutive_losses}</strong>
              </div>

              <div>
                <span>CANDLES</span>
                <strong>{backtest.candles_processed}</strong>
              </div>
            </div>
          ) : (
            <p className="muted">
              Run a backtest to see historical performance.
            </p>
          )}
        </section>

        {/* WALK-FORWARD */}

        <section className="card performance-card">
          <div className="card-header">
            <span>WALK-FORWARD TEST</span>
            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                alignItems: "center",
              }}
            >
              <label style={{ fontSize: "0.75rem", opacity: 0.8 }}>
                WINDOWS
              </label>
              <input
                type="number"
                min="2"
                max="20"
                value={wfWindows}
                onChange={(e) =>
                  setWfWindows(Number(e.target.value))
                }
                style={{ width: "60px" }}
              />

              <label style={{ fontSize: "0.75rem", opacity: 0.8 }}>
                IS RATIO
              </label>
              <input
                type="number"
                min="0.1"
                max="0.95"
                step="0.05"
                value={wfIsRatio}
                onChange={(e) =>
                  setWfIsRatio(Number(e.target.value))
                }
                style={{ width: "70px" }}
              />

              <button
                onClick={runWalkForward}
                disabled={wfLoading}
              >
                {wfLoading ? "RUNNING..." : "RUN WALK-FORWARD"}
              </button>
            </div>
          </div>

          {wfResult ? (
            <>
              <div className="performance-grid">
                <div>
                  <span>WINDOWS</span>
                  <strong>{wfResult.summary.window_count}</strong>
                </div>

                <div>
                  <span>AVG IS RETURN</span>
                  <strong
                    className={
                      wfResult.summary.avg_is_return_pct > 0
                        ? "profit"
                        : "loss"
                    }
                  >
                    {wfResult.summary.avg_is_return_pct >= 0
                      ? "+"
                      : ""}
                    {wfResult.summary.avg_is_return_pct}%
                  </strong>
                </div>

                <div>
                  <span>AVG OOS RETURN</span>
                  <strong
                    className={
                      wfResult.summary.avg_oos_return_pct > 0
                        ? "profit"
                        : "loss"
                    }
                  >
                    {wfResult.summary.avg_oos_return_pct >= 0
                      ? "+"
                      : ""}
                    {wfResult.summary.avg_oos_return_pct}%
                  </strong>
                </div>

                <div>
                  <span>STABILITY RATIO</span>
                  <strong>
                    {wfResult.summary.stability_ratio ?? "n/a"}
                  </strong>
                </div>

                <div>
                  <span>POSITIVE OOS</span>
                  <strong>
                    {wfResult.summary.positive_oos_windows} /{" "}
                    {wfResult.summary.window_count}
                  </strong>
                </div>

                <div>
                  <span>OOS TRADES</span>
                  <strong>
                    {wfResult.summary.total_trades_oos}
                  </strong>
                </div>
              </div>

              <div
                className="wf-table"
                style={{ marginTop: "1rem" }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "40px 1fr 1fr 1fr 1fr 1fr 1fr",
                    gap: "0.5rem",
                    fontSize: "0.75rem",
                    opacity: 0.7,
                    padding: "0.25rem 0",
                    borderBottom: "1px solid #232733",
                  }}
                >
                  <span>#</span>
                  <span>IS RET</span>
                  <span>IS WR</span>
                  <span>OOS RET</span>
                  <span>OOS WR</span>
                  <span>OOS PF</span>
                  <span>OOS DD</span>
                </div>

                {wfResult.windows.map((w) => (
                  <div
                    key={w.window}
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "40px 1fr 1fr 1fr 1fr 1fr 1fr",
                      gap: "0.5rem",
                      fontSize: "0.78rem",
                      padding: "0.35rem 0",
                      borderBottom: "1px solid #1a1d24",
                    }}
                  >
                    <span>{w.window}</span>
                    <span
                      className={
                        w.is.return_pct >= 0 ? "profit" : "loss"
                      }
                    >
                      {w.is.return_pct}%
                    </span>
                    <span>{w.is.win_rate}%</span>
                    <span
                      className={
                        w.oos.return_pct >= 0
                          ? "profit"
                          : "loss"
                      }
                    >
                      {w.oos.return_pct}%
                    </span>
                    <span>{w.oos.win_rate}%</span>
                    <span>{w.oos.profit_factor ?? "∞"}</span>
                    <span className="loss">
                      -{w.oos.max_dd_pct}%
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="muted">
              Run walk-forward to compare in-sample vs
              out-of-sample performance across multiple windows.
              A stability ratio near 1.0 indicates the strategy
              generalises.
            </p>
          )}
        </section>

        {/* AI ACTIVITY */}

        <section className="terminal card">
          <div className="card-header">
            <span>AI ACTIVITY</span>
            <span className="muted">LIVE</span>
          </div>

          <div className="logs">
            <p>
              <span>[SYSTEM]</span> Abbagigo AI Trader initialized
            </p>

            <p>
              <span>[RISK]</span> Live execution disabled
            </p>

            <p>
              <span>[KILL]</span>{" "}
              {killState.active
                ? `ACTIVE — ${killState.reason}`
                : "Armed"}
            </p>

            <p>
              <span>[AUTO]</span> Autonomous engine:{" "}
              {autoEnabled ? "ACTIVE" : "PAUSED"}
            </p>

            <p>
              <span>[PAPER]</span> Balance: $
              {Number(balance).toFixed(2)}
            </p>

            <p>
              <span>[MARKET]</span>{" "}
              {ticker
                ? `${symbol} market data connected`
                : "Waiting for market data"}
            </p>

            {autoData && (
              <>
                <p>
                  <span>[ENGINE]</span> Mode: {autoMode}
                </p>

                {autoData.signal && (
                  <p>
                    <span>[SIGNAL]</span> {autoData.signal} (
                    {Math.round(autoData.confidence * 100)}%
                    confidence)
                  </p>
                )}
              </>
            )}

            {position && (
              <p>
                <span>[POSITION]</span> {position.side}{" "}
                {position.size} {position.symbol}
              </p>
            )}

            {analysis && (
              <>
                <p>
                  <span>[STRATEGY]</span> Signal generated:{" "}
                  {analysis.signal}
                </p>

                <p>
                  <span>[CONFIDENCE]</span>{" "}
                  {Math.round(analysis.confidence * 100)}%
                  confidence
                </p>

                <p>
                  <span>[ENGINE]</span>{" "}
                  {analysis.features.candles_used} candles
                  analyzed
                </p>
              </>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;