# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for the sliding window rate limiter.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from lean_tools_mcp.clients.rate_limiter import (
    SlidingWindowLimiter,
    create_default_limiter,
)


class TestSlidingWindowLimiter:
    """Test the sliding window rate limiter."""

    def test_configure(self):
        """Configuring a category stores the config."""
        limiter = SlidingWindowLimiter()
        limiter.configure("test", max_requests=3, window_seconds=10)
        assert "test" in limiter._configs
        assert limiter._configs["test"].max_requests == 3

    def test_check_allows_within_limit(self):
        """Requests within limit are allowed."""
        limiter = SlidingWindowLimiter()
        limiter.configure("test", max_requests=2, window_seconds=10)
        assert limiter.check("test")
        limiter.record("test")
        assert limiter.check("test")
        limiter.record("test")
        assert not limiter.check("test")

    def test_check_unknown_category_allows(self):
        """Unknown categories are not rate limited."""
        limiter = SlidingWindowLimiter()
        assert limiter.check("unknown")

    def test_remaining(self):
        """Remaining count decreases with each request."""
        limiter = SlidingWindowLimiter()
        limiter.configure("test", max_requests=3, window_seconds=10)
        assert limiter.remaining("test") == 3
        limiter.record("test")
        assert limiter.remaining("test") == 2
        limiter.record("test")
        assert limiter.remaining("test") == 1
        limiter.record("test")
        assert limiter.remaining("test") == 0

    def test_remaining_unknown_category(self):
        """Unknown categories report 999 remaining."""
        limiter = SlidingWindowLimiter()
        assert limiter.remaining("unknown") == 999

    def test_time_until_available_immediate(self):
        """When under limit, time_until_available is 0."""
        limiter = SlidingWindowLimiter()
        limiter.configure("test", max_requests=3, window_seconds=10)
        assert limiter.time_until_available("test") == 0.0

    def test_time_until_available_when_limited(self):
        """When at limit, time_until_available > 0."""
        limiter = SlidingWindowLimiter()
        limiter.configure("test", max_requests=1, window_seconds=10)
        limiter.record("test")
        wait = limiter.time_until_available("test")
        assert wait > 0.0
        assert wait <= 10.0


class TestCreateDefaultLimiter:
    """Test the default limiter factory."""

    def test_has_all_categories(self):
        """Default limiter has all expected categories."""
        limiter = create_default_limiter()
        expected = ["leansearch", "loogle", "leanfinder", "state_search", "hammer_premise"]
        for cat in expected:
            assert cat in limiter._configs, f"Missing category: {cat}"

    def test_leansearch_config(self):
        """LeanSearch has 3/30s rate limit."""
        limiter = create_default_limiter()
        config = limiter._configs["leansearch"]
        assert config.max_requests == 3
        assert config.window_seconds == 30

    def test_leanfinder_config(self):
        """LeanFinder has 10/30s rate limit."""
        limiter = create_default_limiter()
        config = limiter._configs["leanfinder"]
        assert config.max_requests == 10
        assert config.window_seconds == 30


@pytest.mark.asyncio
class TestRateLimitContextManager:
    """Test the async context manager."""

    async def test_acquire_allows_within_limit(self):
        """Acquire succeeds within limit."""
        limiter = SlidingWindowLimiter()
        limiter.configure("test", max_requests=2, window_seconds=10)
        async with limiter.acquire("test"):
            pass
        assert limiter.remaining("test") == 1

    async def test_acquire_waits_when_limited(self):
        """Acquire waits when at limit (short window for test)."""
        limiter = SlidingWindowLimiter()
        limiter.configure("test", max_requests=1, window_seconds=0.5)
        limiter.record("test")  # Fill the limit

        start = time.monotonic()
        async with limiter.acquire("test"):
            elapsed = time.monotonic() - start
        # Should have waited ~0.5s
        assert elapsed >= 0.4
