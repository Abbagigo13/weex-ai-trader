"""
Sliding-window rate limiter for WEEX public endpoints.

WEEX enforces 500 weight per 10 seconds per IP on public endpoints.
Exceeding it triggers a 10-second IP ban.

This module tracks the server-reported remaining weight and also
applies its own defensive budget, so we never come close to the
server-side limit even if the header is missing.
"""

import threading
import time
from collections import deque
from typing import Optional


class RateLimiter:
    def __init__(
        self,
        budget: int = 500,
        window_seconds: float = 10.0,
        safety_margin: int = 50,
        server_weight_header: str = "X-REMAINING-WEIGHT-10S",
    ):
        self.budget = budget
        self.window_seconds = window_seconds
        self.safety_margin = safety_margin
        self.server_weight_header = server_weight_header

        # (timestamp, cost) pairs
        self._events: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

        self._server_weight: Optional[int] = None
        self._server_weight_at: Optional[float] = None
        self._cooldown_until: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def acquire(self, cost: int = 1, blocking: bool = True) -> bool:
        """
        Reserve `cost` weight.

        If blocking=True, sleeps (in bounded slices) until the
        reservation can be granted, then returns True.

        If blocking=False and the reservation would require waiting,
        returns False immediately.
        """
        while True:
            with self._lock:
                now = time.time()
                cutoff = now - self.window_seconds

                # Prune events older than the window.
                while self._events and self._events[0][0] <= cutoff:
                    self._events.popleft()

                # Cooldown check (HTTP 429 etc.).
                if now < self._cooldown_until:
                    wait = self._cooldown_until - now
                    can_acquire = False
                else:
                    used = sum(c for _, c in self._events)

                    # Local budget check.
                    if used + cost <= self.budget - self.safety_margin:
                        # Server-reported weight check.
                        if (
                            self._server_weight is not None
                            and self._server_weight
                            < self.safety_margin + cost
                        ):
                            age = now - (self._server_weight_at or now)
                            wait = max(0.0, self.window_seconds - age)
                            can_acquire = False
                        else:
                            # Grant.
                            self._events.append((now, cost))
                            return True
                    else:
                        # Wait for the oldest event to expire.
                        if not self._events:
                            return False
                        wait = (
                            self._events[0][0]
                            + self.window_seconds
                            - now
                        )
                        can_acquire = False

            if can_acquire:
                # Defensive — should not happen, but prevents a
                # pathological loop.
                return True

            if not blocking:
                return False

            # Sleep in bounded slices so we re-check state.
            time.sleep(max(min(wait, 0.5), 0.01))

    def observe_response(
        self,
        remaining_weight: Optional[int] = None,
        status_code: Optional[int] = None,
    ) -> None:
        """
        Call after every HTTP response.
        """
        now = time.time()
        with self._lock:
            if remaining_weight is not None:
                try:
                    self._server_weight = int(remaining_weight)
                    self._server_weight_at = now
                except (TypeError, ValueError):
                    pass

            if status_code == 429:
                until = now + self.window_seconds
                if until > self._cooldown_until:
                    self._cooldown_until = until

    def apply_transport_cooldown(self, seconds: float = 2.0) -> None:
        """
        Called by the transport layer when curl exits with a
        connection error that suggests a server-side throttle.
        """
        now = time.time()
        with self._lock:
            until = now + seconds
            if until > self._cooldown_until:
                self._cooldown_until = until

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "local_events": len(self._events),
                "budget": self.budget,
                "window_seconds": self.window_seconds,
                "server_weight": self._server_weight,
                "server_weight_age": (
                    None
                    if self._server_weight_at is None
                    else round(time.time() - self._server_weight_at, 2)
                ),
                "cooldown_remaining": max(
                    0.0, self._cooldown_until - time.time()
                ),
            }

    # ------------------------------------------------------------------
    # Internal — must be called while holding self._lock
    # ------------------------------------------------------------------
    def _wait_time_locked(self, cost: int) -> float:
        """
        Preview how long we would need to wait for `cost` to be
        available. Does not mutate state. Used by diagnostics.
        """
        now = time.time()

        if now < self._cooldown_until:
            return self._cooldown_until - now

        cutoff = now - self.window_seconds
        # Note: iterate over a copy — don't mutate state.
        events = [e for e in self._events if e[0] > cutoff]
        used = sum(c for _, c in events)

        if used + cost <= self.budget - self.safety_margin:
            if (
                self._server_weight is not None
                and self._server_weight < self.safety_margin + cost
            ):
                age = now - (self._server_weight_at or now)
                return max(0.0, self.window_seconds - age)
            return 0.0

        if not events:
            return 0.0
        return max(0.0, events[0][0] + self.window_seconds - now)