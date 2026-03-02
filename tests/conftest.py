# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Shared fixtures for tests.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

# Whether `lean` is available on PATH
LEAN_AVAILABLE = shutil.which("lean") is not None


def skip_without_lean(reason: str = "lean not found on PATH"):
    """Decorator to skip a test if lean is not installed."""
    return pytest.mark.skipif(not LEAN_AVAILABLE, reason=reason)
