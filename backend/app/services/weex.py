"""
WEEX V3 public market-data client.

LIVE EXECUTION IS INTENTIONALLY NOT IMPLEMENTED HERE.

TRANSPORT LAYER:
    - On Windows  : uses curl.exe (Windows SChannel) because Python's
                    OpenSSL stack cannot complete a TLS handshake with
                    api-contract.weex.com from some residential IPs.
    - On Linux    : uses httpx (native OpenSSL), which works normally
                    from cloud / VPS IPs.

    Both paths share the same RateLimiter and the same public API.

RATE LIMITS:
    WEEX enforces 500 weight per 10 seconds per IP on public
    endpoints. The RateLimiter module tracks the server-reported
    remaining weight and applies a defensive budget.
"""

import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

from .rate_limiter import RateLimiter
from ..core.logging_setup import get_logger, kv

log = get_logger("market")

# Weight costs per WEEX public endpoint (conservative).
ENDPOINT_WEIGHTS = {
    "ticker/24hr": 1,
    "ticker/bookTicker": 1,
    "klines": 1,
    "apiTradingSymbols": 1,
}
DEFAULT_WEIGHT = 2


class WEEXClientError(RuntimeError):
    """Raised when a WEEX market-data request fails."""


class WEEXClient:
    def __init__(self):
        self.base_url = "https://api-contract.weex.com/capi/v3"

        is_windows = platform.system().lower() == "windows"

        self._curl_path: Optional[str] = None
        if is_windows:
            self._curl_path = (
                shutil.which("curl.exe") or shutil.which("curl")
            )

        # On Linux, self._curl_path stays None → use native httpx.
        self._use_native: bool = self._curl_path is None

        self.limiter = RateLimiter(
            budget=500,
            window_seconds=10.0,
            safety_margin=50,
        )

        log.info(
            "WEEXClient initialised %s",
            kv(
                transport="httpx" if self._use_native else "curl",
                curl=self._curl_path,
            ),
        )

    # ------------------------------------------------------------------
    # Symbol helpers
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return symbol.lower().replace("cmt_", "").upper()

    # ------------------------------------------------------------------
    # Weight estimation
    # ------------------------------------------------------------------
    def _weight_for(self, path: str) -> int:
        for key, w in ENDPOINT_WEIGHTS.items():
            if key in path:
                return w
        return DEFAULT_WEIGHT

    # ------------------------------------------------------------------
    # Public transport dispatcher
    # ------------------------------------------------------------------
    def _curl_get_json(
        self, path: str, params: Dict[str, Any]
    ) -> Any:
        if self._use_native:
            return self._native_get_json(path, params)
        return self._curl_subprocess_get_json(path, params)

    # ------------------------------------------------------------------
    # Native httpx (Linux / Railway)
    # ------------------------------------------------------------------
    def _native_get_json(
        self, path: str, params: Dict[str, Any]
    ) -> Any:
        import httpx

        url = f"{self.base_url}{path}"
        weight = self._weight_for(path)
        max_attempts = 4
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            self.limiter.acquire(cost=weight, blocking=True)

            try:
                r = httpx.get(
                    url,
                    params=params,
                    timeout=20.0,
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                self.limiter.apply_transport_cooldown(1.0 * attempt)
                continue

            remaining = r.headers.get("X-REMAINING-WEIGHT-10S")
            self.limiter.observe_response(
                remaining_weight=(
                    int(remaining) if remaining is not None else None
                ),
                status_code=r.status_code,
            )

            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError as exc:
                    raise WEEXClientError(
                        f"Invalid JSON from {url}: {r.text[:200]}"
                    ) from exc

            if r.status_code == 429:
                time.sleep(2.0 * attempt)
                last_error = "429 rate limited"
                continue

            if 500 <= r.status_code < 600:
                time.sleep(1.0 * attempt)
                last_error = f"HTTP {r.status_code}"
                continue

            raise WEEXClientError(
                f"HTTP {r.status_code} from {url}: {r.text[:200]}"
            )

        raise WEEXClientError(
            f"Failed after {max_attempts} attempts for {url}: {last_error}"
        )

    # ------------------------------------------------------------------
    # curl.exe subprocess (Windows)
    # ------------------------------------------------------------------
    _REMAINING_RE = re.compile(
        r"x-remaining-weight-10s:\s*(\d+)", re.IGNORECASE
    )

    def _extract_remaining_weight(
        self, headers_bytes: bytes
    ) -> Optional[int]:
        try:
            text = headers_bytes.decode(errors="replace")
        except Exception:
            return None
        m = self._REMAINING_RE.search(text)
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    def _curl_subprocess_get_json(
        self, path: str, params: Dict[str, Any]
    ) -> Any:
        url = f"{self.base_url}{path}"

        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"

        weight = self._weight_for(path)
        max_attempts = 5
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            self.limiter.acquire(cost=weight, blocking=True)

            cmd = [
                self._curl_path,
                "-4",
                "--http1.1",
                "--silent",
                "--show-error",
                "--fail-with-body",
                "-D", "-",
                "-H", "Accept: application/json",
                url,
            ]

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=20,
                    check=False,
                    env=os.environ.copy(),
                )
            except subprocess.TimeoutExpired:
                last_error = f"timeout attempt {attempt}"
                self.limiter.apply_transport_cooldown(1.0 * attempt)
                continue

            header_blob, body_bytes = self._split_headers_body(
                proc.stdout
            )
            remaining = self._extract_remaining_weight(header_blob)
            status_code = self._parse_status(header_blob)

            self.limiter.observe_response(
                remaining_weight=remaining,
                status_code=status_code,
            )

            stderr = proc.stderr.decode(errors="replace").strip()

            if proc.returncode == 0:
                body = body_bytes.decode(errors="replace").strip()
                if not body:
                    last_error = "empty body"
                    time.sleep(0.3 * attempt)
                    continue
                try:
                    return json.loads(body)
                except json.JSONDecodeError as exc:
                    raise WEEXClientError(
                        f"Invalid JSON from {url}: {body[:200]}"
                    ) from exc

            last_error = stderr or f"curl code {proc.returncode}"

            if proc.returncode in (35, 56, 28):
                self.limiter.apply_transport_cooldown(
                    seconds=min(2.0 * attempt, 10.0)
                )
                continue

            raise WEEXClientError(
                f"curl.exe failed (code {proc.returncode}) "
                f"for {url}: {last_error}"
            )

        raise WEEXClientError(
            f"curl.exe failed after {max_attempts} attempts "
            f"for {url}: {last_error}"
        )

    @staticmethod
    def _split_headers_body(raw: bytes) -> tuple[bytes, bytes]:
        marker = b"\r\n\r\n"
        idx = raw.find(marker)
        if idx == -1:
            idx2 = raw.find(b"\n\n")
            if idx2 == -1:
                return b"", raw
            return raw[:idx2], raw[idx2 + 2 :]
        return raw[:idx], raw[idx + 4 :]

    @staticmethod
    def _parse_status(header_blob: bytes) -> Optional[int]:
        if not header_blob:
            return None
        first_line = header_blob.split(b"\r\n", 1)[0]
        parts = first_line.split(b" ", 2)
        if len(parts) < 2:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Async wrapper
    # ------------------------------------------------------------------
    async def _async_get_json(
        self, path: str, params: Dict[str, Any]
    ) -> Any:
        return await asyncio.to_thread(self._curl_get_json, path, params)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_ticker(
        self, symbol: str = "cmt_btcusdt"
    ) -> Dict[str, Any]:
        v3_symbol = self.normalize_symbol(symbol)

        ticker = await self._async_get_json(
            "/market/ticker/24hr",
            {"symbol": v3_symbol},
        )
        book = await self._async_get_json(
            "/market/ticker/bookTicker",
            {"symbol": v3_symbol},
        )

        if isinstance(ticker, dict) and "value" in ticker:
            ticker = ticker["value"][0]
        elif isinstance(ticker, list):
            ticker = ticker[0]

        if isinstance(book, dict) and "value" in book:
            book = book["value"][0]
        elif isinstance(book, list):
            book = book[0]

        return {
            "symbol": symbol,
            "last": ticker["lastPrice"],
            "best_ask": book["askPrice"],
            "best_bid": book["bidPrice"],
            "high_24h": ticker["highPrice"],
            "low_24h": ticker["lowPrice"],
            "volume_24h": ticker["quoteVolume"],
            "timestamp": str(book.get("time", "")),
            "priceChangePercent": ticker["priceChangePercent"],
            "base_volume": ticker["volume"],
            "markPrice": ticker["markPrice"],
            "indexPrice": ticker["indexPrice"],
        }

    async def get_candles(
        self,
        symbol: str = "cmt_btcusdt",
        granularity: str = "5m",
        limit: int = 100,
    ) -> Any:
        v3_symbol = self.normalize_symbol(symbol)

        raw = await self._async_get_json(
            "/market/klines",
            {
                "symbol": v3_symbol,
                "interval": granularity,
                "limit": limit,
            },
        )

        if isinstance(raw, dict) and "value" in raw:
            return raw["value"]
        return raw

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def rate_limiter_state(self) -> dict:
        return self.limiter.snapshot()