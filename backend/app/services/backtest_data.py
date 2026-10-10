"""
Backtest data sources.

Two loaders:

  load_csv(path)        -- reads OHLCV from a CSV file
  generate_synthetic()  -- produces a realistic random-walk dataset

Both return a list of dicts, each shaped:
    {
        "timestamp": int (ms),
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": float,
        "quote_volume": float,
    }
"""

import csv
import os
import random
from typing import List, Optional


_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DEFAULT_HISTORY_DIR = os.path.join(_BACKEND_DIR, "data", "historical")


def _ensure_columns(fieldnames: list[str]) -> None:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - {f.lower() for f in fieldnames}
    if missing:
        raise ValueError(
            f"CSV is missing required columns: {sorted(missing)}"
        )


def load_csv(path: str) -> List[dict]:
    """
    Load OHLCV candles from a CSV file.

    Expected headers (case-insensitive):
        timestamp, open, high, low, close, volume, quote_volume

    Only timestamp, open, high, low, close are required. Volume
    defaults to 0.0 if not present.
    """
    if not os.path.isabs(path):
        path = os.path.join(DEFAULT_HISTORY_DIR, path)

    if not os.path.exists(path):
        raise FileNotFoundError(f"Historical file not found: {path}")

    candles: List[dict] = []

    with open(path, "r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row.")

        _ensure_columns(reader.fieldnames)
        lower = {f.lower(): f for f in reader.fieldnames}

        for row in reader:
            try:
                candles.append(
                    {
                        "timestamp": int(float(row[lower["timestamp"]])),
                        "open": float(row[lower["open"]]),
                        "high": float(row[lower["high"]]),
                        "low": float(row[lower["low"]]),
                        "close": float(row[lower["close"]]),
                        "volume": float(
                            row.get(lower.get("volume", ""), 0.0) or 0.0
                        ),
                        "quote_volume": float(
                            row.get(lower.get("quote_volume", ""), 0.0) or 0.0
                        ),
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid row in {path}: {row} ({exc})"
                ) from exc

    candles.sort(key=lambda c: c["timestamp"])
    return candles


def generate_synthetic(
    count: int = 2000,
    starting_price: float = 83000.0,
    volatility: float = 0.004,
    drift: float = 0.00002,
    seed: Optional[int] = 42,
    interval_ms: int = 5 * 60 * 1000,
    end_timestamp: Optional[int] = None,
) -> List[dict]:
    """
    Generate a synthetic OHLCV series using a random walk with
    realistic intrabar high/low and volume.

    Default: 2000 bars of 5m candles (≈ 7 days), 0.4% per-bar vol.
    """
    rng = random.Random(seed)

    candles: List[dict] = []
    price = starting_price

    if end_timestamp is None:
        # Anchor the series to "now" going backwards.
        import time
        end_timestamp = int(time.time() * 1000)

    start_ts = end_timestamp - (count - 1) * interval_ms

    for i in range(count):
        ts = start_ts + i * interval_ms

        # Geometric random walk for close
        ret = rng.gauss(drift, volatility)
        new_price = max(1.0, price * (1.0 + ret))

        open_price = price
        close_price = new_price

        # Intrabar wick size proportional to bar volatility
        wick = abs(rng.gauss(0, volatility * 0.5)) * price

        high = max(open_price, close_price) + wick
        low = min(open_price, close_price) - wick
        if low <= 0:
            low = min(open_price, close_price) * 0.999

        volume = abs(rng.gauss(50, 15))
        quote_volume = volume * close_price

        candles.append(
            {
                "timestamp": ts,
                "open": round(open_price, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close_price, 4),
                "volume": round(volume, 6),
                "quote_volume": round(quote_volume, 6),
            }
        )

        price = close_price

    return candles