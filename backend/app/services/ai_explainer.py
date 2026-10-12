import json
import os
import time
from pathlib import Path

import httpx

# Alibaba Cloud Model Studio (DashScope), international / Singapore region.
DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
CACHE_SECONDS = 60
REQUEST_TIMEOUT = 20.0

SYSTEM_PROMPT = (
    "You are the explanation layer of a paper-trading crypto futures "
    "bot. A deterministic rule engine has ALREADY decided the signal. "
    "Your job is to explain that decision, never to override it.\n\n"
    "The engine's EXACT scoring rules are:\n"
    "- EMA9 above EMA21: +2. EMA9 below EMA21: -2.\n"
    "- RSI14 between 50 and 70: +1. RSI14 between 30 and 50: -1. "
    "RSI14 at or above 70 (overbought) or at or below 30 (oversold): 0.\n"
    "- 10-bar momentum above +0.15%: +1. Below -0.15%: -1. "
    "Otherwise 0.\n"
    "- Total score >= 3 gives BUY. Total score <= -3 gives SELL. "
    "Anything else gives WAIT.\n"
    "- The bot only opens a paper trade when confidence >= 0.75.\n\n"
    "The input contains points_needed_for_buy and "
    "points_needed_for_sell. These are precomputed and correct. "
    "Quote them exactly and do NOT do your own arithmetic.\n\n"
    "Rules for your answer: start with the verdict (BUY, SELL or "
    "WAIT). Explain which rules added or subtracted points, using the "
    "numbers provided. If the verdict is WAIT, state both "
    "points_needed values. Use ONLY the rules above and NEVER invent "
    "other thresholds or conditions. Maximum 60 words, plain text, "
    "no markdown, no financial advice, never contradict the signal."
)


def _read_env_file() -> dict:
    """Read backend/.env without needing extra packages."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    values: dict = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _get_setting(name: str, default: str = "") -> str:
    return os.getenv(name) or _read_env_file().get(name) or default


def _points_needed(score: int) -> tuple:
    """Points still required to reach BUY (+3) or SELL (-3)."""
    return max(0, 3 - score), max(0, score + 3)


class AIExplainer:
    def __init__(self) -> None:
        self.api_key = _get_setting("DASHSCOPE_API_KEY")
        self.model = _get_setting("DASHSCOPE_MODEL", DEFAULT_MODEL)
        self.base_url = _get_setting(
            "DASHSCOPE_BASE_URL", DEFAULT_BASE_URL
        ).rstrip("/")
        self._cache: dict = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "provider": "alibaba-dashscope",
            "model": self.model,
        }

    def _fallback(self, analysis: dict) -> str:
        features = analysis.get("features", {})
        signal = analysis.get("signal", "WAIT")
        score = int(features.get("score", 0))
        reason = analysis.get("reason", "No reasoning available.")
        need_buy, need_sell = _points_needed(score)
        return (
            f"{signal}. Score {score}. Needs {need_buy} more point(s) "
            f"for BUY or {need_sell} more for SELL. {reason}."
        )

    async def explain(self, symbol: str, analysis: dict) -> dict:
        features = analysis.get("features", {})
        cache_key = (
            symbol,
            analysis.get("signal"),
            features.get("score"),
            round(features.get("rsi14", 0)),
        )

        cached = self._cache.get(cache_key)
        if cached and time.time() - cached["time"] < CACHE_SECONDS:
            return {**cached["result"], "cached": True}

        if not self.enabled:
            return {
                "explanation": self._fallback(analysis),
                "source": "fallback",
                "model": None,
                "cached": False,
            }

        score = int(features.get("score", 0))
        need_buy, need_sell = _points_needed(score)

        payload = {
            "symbol": symbol,
            "signal": analysis.get("signal"),
            "confidence": analysis.get("confidence"),
            "reason": analysis.get("reason"),
            "features": features,
            "points_needed_for_buy": need_buy,
            "points_needed_for_sell": need_sell,
        }

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "temperature": 0.2,
                        "max_tokens": 200,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": json.dumps(payload),
                            },
                        ],
                    },
                )
                response.raise_for_status()
                text = response.json()["choices"][0]["message"][
                    "content"
                ].strip()

            result = {
                "explanation": text,
                "source": "qwen",
                "model": self.model,
                "cached": False,
            }
            self._cache[cache_key] = {
                "time": time.time(),
                "result": result,
            }
            return result

        except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            return {
                "explanation": self._fallback(analysis),
                "source": "fallback",
                "model": None,
                "cached": False,
                "error": type(error).__name__,
            }
