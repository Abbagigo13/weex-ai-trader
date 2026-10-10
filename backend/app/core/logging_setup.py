"""
Centralized structured logging.

Categories:
    [MARKET]      market data requests / responses
    [STRATEGY]    strategy analysis + signals
    [RISK]        risk engine decisions
    [EXECUTION]   paper trades + position lifecycle
    [KILL]        kill switch events
    [AUTO]        auto trading loop
    [STORAGE]     SQLite writes / loads
    [API]         incoming HTTP requests / errors
    [ERROR]       unexpected exceptions
    [SYSTEM]      startup / shutdown

Format:
    2026-10-09 12:00:00.123 | [MARKET]  message key=value ...

Writes to:
    backend/logs/trader.log   (rotating, 5 files x 2 MB)

Never logs API secrets. A sanitizer strips anything that looks
like a key / secret / passphrase / token.
"""

import logging
import logging.handlers
import os
import re
from typing import Any

_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
LOG_DIR = os.path.join(_BACKEND_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "trader.log")

# ----------------------------------------------------------------------
# Sanitizer — strips anything that looks like a credential.
# ----------------------------------------------------------------------
_SECRET_PATTERNS = [
    # Query-string / JSON style key=... or "key":"..."
    re.compile(
        r'(?i)(api[_-]?key|secret|passphrase|token|signature|authorization)'
        r'(["\']?\s*[:=]\s*["\']?)([A-Za-z0-9\-_\.]{6,})'
    ),
    # Bearer / ApiKey headers
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9\-_\.]{6,})"),
]


def sanitize(text: str) -> str:
    """Redact anything that looks like a credential."""
    if not text:
        return text
    redacted = text
    for pat in _SECRET_PATTERNS:
        redacted = pat.sub(r"\1\2***REDACTED***", redacted)
    return redacted


class _SanitizingFormatter(logging.Formatter):
    """Formatter that runs sanitize() on every message."""

    def format(self, record: logging.LogRecord) -> str:
        return sanitize(super().format(record))


def _short_category(name: str) -> str:
    """Map logger name to a [TAG] label."""
    aliases = {
        "market": "MARKET",
        "strategy": "STRATEGY",
        "risk": "RISK",
        "execution": "EXECUTION",
        "kill": "KILL",
        "auto": "AUTO",
        "storage": "STORAGE",
        "api": "API",
        "system": "SYSTEM",
        "error": "ERROR",
    }
    last = name.rsplit(".", 1)[-1].lower()
    return aliases.get(last, name.upper())


class _CategoryFormatter(_SanitizingFormatter):
    """Adds a padded [CATEGORY] tag before the message."""

    def format(self, record: logging.LogRecord) -> str:
        tag = _short_category(record.name)
        original = record.msg
        try:
            if isinstance(record.msg, str):
                record.msg = f"[{tag:<9}] {record.msg}"
            return super().format(record)
        finally:
            record.msg = original


_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Idempotent — safe to call from main.py at import time."""
    global _configured
    if _configured:
        return

    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any pre-existing handlers so uvicorn's defaults don't
    # double-print.
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = "%(asctime)s | %(levelname)-7s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # Console
    console = logging.StreamHandler()
    console.setFormatter(_CategoryFormatter(fmt, datefmt=datefmt))
    console.setLevel(level)
    root.addHandler(console)

    # Rotating file
    fileh = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fileh.setFormatter(_CategoryFormatter(fmt, datefmt=datefmt))
    fileh.setLevel(level)
    root.addHandler(fileh)

    # Tame noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.getLogger("system").info(
        "Logging initialised. File: %s", LOG_FILE
    )

    _configured = True


# ----------------------------------------------------------------------
# Convenience getters
# ----------------------------------------------------------------------
def get_logger(category: str) -> logging.Logger:
    """
    Return a logger whose name maps to a category tag.

    Example:
        log = get_logger("market")
        log.info("requested %s", "BTCUSDT")
        # => 2026-... | INFO | [MARKET] requested BTCUSDT
    """
    return logging.getLogger(category)


def kv(**kwargs: Any) -> str:
    """Format kwargs as `key=value` pairs for log lines."""
    parts = []
    for k, v in kwargs.items():
        if v is None:
            continue
        parts.append(f"{k}={v}")
    return " ".join(parts)