# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_goal and lean_term_goal — proof state inspection tools.

The most important and most frequently used tools.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..lsp.pool import LSPPool


async def lean_goal(
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    column: int | None = None,
) -> str:
    """Get proof goals at a position in a Lean file.

    Args:
        file_path: Absolute path to the .lean file
        line: Line number (1-indexed)
        column: Column number (1-indexed). Omit to see goals_before (line start)
                and goals_after (line end), showing how the tactic transforms state.

    Returns:
        Formatted goal state string. "no goals" means the proof is complete at
        that point — consider removing redundant tactics.
    """
    result = await lsp_pool.get_goal(file_path, line, column)

    if column is not None:
        # Single position query
        goals = result.get("goals", "no goals")
        return goals
    else:
        # Before/after query
        before = result.get("goals_before", "no goals")
        after = result.get("goals_after", "no goals")
        parts = []
        parts.append(f"Goals BEFORE (line {line} start):\n{before}")
        parts.append(f"\nGoals AFTER (line {line} end):\n{after}")
        return "\n".join(parts)


async def lean_term_goal(
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    column: int | None = None,
) -> str:
    """Get the expected type at a position.

    Args:
        file_path: Absolute path to the .lean file
        line: Line number (1-indexed)
        column: Column number (1-indexed). Defaults to end of line.

    Returns:
        The expected type as a string.
    """
    result = await lsp_pool.get_term_goal(file_path, line, column)
    if result is None:
        return "No term goal at this position."
    return result.get("goal", "No term goal at this position.")
