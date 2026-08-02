"""Client-side token buckets for the J-Quants API.

Standard plan allows 120 requests/min globally and 60 requests/min on the
financial endpoints. Exceeding the limit returns 429 and, when grossly
exceeded, a ~5 minute full block — so the client throttles below the
documented ceiling instead of racing it: 100/min global, 50/min fins.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class MinuteRateLimiter:
    """Sliding-window limiter; ``acquire`` blocks until a slot is free."""

    def __init__(self, max_requests_per_minute: int, *, clock=time.monotonic) -> None:
        if max_requests_per_minute < 1:
            raise ValueError("max_requests_per_minute must be >= 1")
        self._limit = int(max_requests_per_minute)
        self._window_seconds = 60.0
        self._clock = clock
        self._events: deque[float] = deque()
        self._lock = threading.Lock()
        # A provider-imposed block (429 escalation) pauses every caller.
        self._blocked_until = 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._events and self._events[0] <= cutoff:
            self._events.popleft()

    def next_delay_seconds(self) -> float:
        """How long a caller must wait before the next request may start."""

        with self._lock:
            now = self._clock()
            delays = [max(0.0, self._blocked_until - now)]
            self._prune(now)
            if len(self._events) >= self._limit:
                delays.append(self._events[0] + self._window_seconds - now)
            return max(delays)

    def acquire(self, *, sleep=time.sleep) -> None:
        """Block until a request slot is available, then consume it."""

        while True:
            with self._lock:
                now = self._clock()
                self._prune(now)
                if now >= self._blocked_until and len(self._events) < self._limit:
                    self._events.append(now)
                    return
                waits = [max(0.0, self._blocked_until - now)]
                if len(self._events) >= self._limit:
                    waits.append(self._events[0] + self._window_seconds - now)
                delay = max(0.05, min(w for w in waits if w > 0.0) if any(w > 0.0 for w in waits) else 0.05)
            sleep(min(delay, 5.0))

    def block_for(self, seconds: float) -> None:
        """Honor a server-imposed cooldown (429 escalation guard)."""

        if seconds <= 0.0:
            return
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._clock() + seconds)


class JQuantsRateLimits:
    """The documented buckets: global, financial, and intraday add-ons."""

    def __init__(
        self,
        *,
        global_per_minute: int = 100,
        fins_per_minute: int = 50,
        addon_per_minute: int = 50,
        clock=time.monotonic,
    ) -> None:
        self.global_bucket = MinuteRateLimiter(global_per_minute, clock=clock)
        self.fins_bucket = MinuteRateLimiter(fins_per_minute, clock=clock)
        # 分足（OHLC-Min）とティック（Tick）のアドオンは各 60/min の独立枠。
        self.addon_bucket = MinuteRateLimiter(addon_per_minute, clock=clock)

    def acquire_for_path(self, path: str, *, sleep=time.sleep) -> None:
        # /fins/summary and /fins/details carry their own 60/min cap; the
        # request still counts against the global bucket as well.
        if path.startswith("/fins/"):
            self.fins_bucket.acquire(sleep=sleep)
        if path.startswith("/equities/bars/minute") or path.startswith("/equities/trades"):
            self.addon_bucket.acquire(sleep=sleep)
        self.global_bucket.acquire(sleep=sleep)

    def block_all_for(self, seconds: float) -> None:
        self.global_bucket.block_for(seconds)
        self.fins_bucket.block_for(seconds)
        self.addon_bucket.block_for(seconds)


__all__ = ["JQuantsRateLimits", "MinuteRateLimiter"]
