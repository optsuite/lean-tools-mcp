"""
Sliding window rate limiter for external HTTP search APIs.

Each category (leansearch, loogle, etc.) has its own rate limit config.
The limiter tracks request timestamps and blocks if the limit is exceeded.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for a single rate limit category."""

    # Maximum number of requests allowed in the window
    max_requests: int
    # Window size in seconds
    window_seconds: float


class SlidingWindowLimiter:
    """Async sliding window rate limiter.

    Thread-safe via asyncio.Lock. Tracks request timestamps per category
    and enforces max_requests/window_seconds.

    Usage:
        limiter = SlidingWindowLimiter()
        limiter.configure("leansearch", max_requests=3, window_seconds=30)

        # Will wait if rate limit is hit
        async with limiter.acquire("leansearch"):
            result = await http_call(...)

        # Or check without blocking
        if limiter.check("leansearch"):
            limiter.record("leansearch")
            ...
    """

    def __init__(self) -> None:
        self._configs: dict[str, RateLimitConfig] = {}
        self._timestamps: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    def configure(
        self,
        category: str,
        max_requests: int,
        window_seconds: float,
    ) -> None:
        """Register a rate limit for a category."""
        self._configs[category] = RateLimitConfig(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        if category not in self._timestamps:
            self._timestamps[category] = []

    def _cleanup(self, category: str) -> None:
        """Remove expired timestamps from the window."""
        config = self._configs.get(category)
        if config is None:
            return
        cutoff = time.monotonic() - config.window_seconds
        self._timestamps[category] = [
            t for t in self._timestamps[category] if t > cutoff
        ]

    def check(self, category: str) -> bool:
        """Check if a request is allowed without recording it.

        Returns True if allowed, False if rate limited.
        """
        config = self._configs.get(category)
        if config is None:
            return True  # No config = no limit
        self._cleanup(category)
        return len(self._timestamps[category]) < config.max_requests

    def record(self, category: str) -> None:
        """Record a request timestamp."""
        self._timestamps.setdefault(category, []).append(time.monotonic())

    def time_until_available(self, category: str) -> float:
        """Return seconds until the next request is allowed. 0 = available now."""
        config = self._configs.get(category)
        if config is None:
            return 0.0
        self._cleanup(category)
        if len(self._timestamps[category]) < config.max_requests:
            return 0.0
        # Oldest timestamp in window determines when the next slot opens
        oldest = self._timestamps[category][0]
        return max(0.0, oldest + config.window_seconds - time.monotonic())

    def acquire(self, category: str) -> _RateLimitContext:
        """Async context manager that waits if rate limited, then records.

        Usage:
            async with limiter.acquire("leansearch"):
                result = await http_call(...)
        """
        return _RateLimitContext(self, category)

    def remaining(self, category: str) -> int:
        """Return the number of remaining requests in the current window."""
        config = self._configs.get(category)
        if config is None:
            return 999
        self._cleanup(category)
        return max(0, config.max_requests - len(self._timestamps[category]))


class _RateLimitContext:
    """Async context manager for rate-limited operations."""

    def __init__(self, limiter: SlidingWindowLimiter, category: str) -> None:
        self._limiter = limiter
        self._category = category

    async def __aenter__(self) -> None:
        while True:
            async with self._limiter._lock:
                if self._limiter.check(self._category):
                    self._limiter.record(self._category)
                    return
                wait_time = self._limiter.time_until_available(self._category)

            if wait_time > 0:
                logger.debug(
                    "Rate limited [%s]: waiting %.1fs",
                    self._category,
                    wait_time,
                )
                await asyncio.sleep(wait_time + 0.1)  # Small buffer

    async def __aexit__(self, *exc: object) -> None:
        pass


# ---------------------------------------------------------------------------
# Default global limiter with standard configs
# ---------------------------------------------------------------------------

def create_default_limiter() -> SlidingWindowLimiter:
    """Create a limiter with standard configs for all search categories."""
    limiter = SlidingWindowLimiter()
    limiter.configure("leansearch", max_requests=3, window_seconds=30)
    limiter.configure("loogle", max_requests=3, window_seconds=30)
    limiter.configure("leanfinder", max_requests=10, window_seconds=30)
    limiter.configure("state_search", max_requests=3, window_seconds=30)
    limiter.configure("hammer_premise", max_requests=3, window_seconds=30)
    return limiter
