# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_multi_attempt — try multiple tactics at a position without modifying the file.

Primary path: uses $/lean/tryTactics (requires modified Lean binary) for true
in-process parallel tactic evaluation with shared environment.

Fallback path: creates a temp file, replaces the target line with each snippet
sequentially, and checks via standard LSP.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..lsp.pool import LSPPool
from ..lsp.protocol import LSPProtocolError

logger = logging.getLogger(__name__)


async def lean_multi_attempt(
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    tactics: list[str],
    column: int | None = None,
) -> str:
    """Try multiple tactics at a position and return goal state for each.

    First attempts the native $/lean/tryTactics endpoint (parallel, no file
    modification). Falls back to file-based sequential approach if the
    endpoint is unavailable.

    Args:
        lsp_pool: The LSP connection pool.
        file_path: Absolute path to the .lean file.
        line: Line number (1-indexed) where goals exist.
        tactics: List of tactic strings to try (3+ recommended).
        column: Column number (1-indexed, defaults to line start).

    Returns:
        Formatted string with results for each tactic attempt.
    """
    original_path = Path(file_path).resolve()
    if not original_path.exists():
        return json.dumps({"error": f"File not found: {file_path}"})

    try:
        return await _multi_attempt_native(
            lsp_pool, str(original_path), line, tactics, column
        )
    except LSPProtocolError as e:
        msg = str(e).lower()
        if "method not found" in msg or "unknown" in msg or "no request handler" in msg or "-32601" in msg:
            logger.info(
                "$/lean/tryTactics not available, falling back to file-based approach: %s",
                e,
            )
            return await _multi_attempt_file_based(
                lsp_pool, str(original_path), line, tactics
            )
        raise


async def _multi_attempt_native(
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    tactics: list[str],
    column: int | None = None,
) -> str:
    """Try tactics via $/lean/tryTactics (parallel, in-process)."""
    logger.info(
        "lean_multi_attempt (native): file=%s line=%d col=%s tactics=%d",
        file_path, line, column, len(tactics),
    )

    results = await lsp_pool.try_tactics(
        file_path=file_path,
        line=line,
        column=column,
        tactics=tactics,
    )

    formatted: list[dict[str, Any]] = []
    for r in results:
        entry: dict[str, Any] = {"tactic": r.tactic}
        if r.error:
            entry["goal_state"] = ""
            entry["errors"] = [r.error]
        elif r.goals is not None:
            if len(r.goals) == 0:
                entry["goal_state"] = "no goals"
            else:
                entry["goal_state"] = "\n".join(r.goals)
            entry["errors"] = []
        else:
            entry["goal_state"] = ""
            entry["errors"] = []
        formatted.append(entry)

    return _format_results(formatted)


async def _multi_attempt_file_based(
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    snippets: list[str],
) -> str:
    """Fallback: try tactics by replacing the target line in a temp file."""
    original_path = Path(file_path).resolve()
    original_content = original_path.read_text(encoding="utf-8")
    original_lines = original_content.split("\n")

    if line < 1 or line > len(original_lines):
        return json.dumps(
            {"error": f"Line {line} out of range (file has {len(original_lines)} lines)"}
        )

    client = await lsp_pool.pick_client()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temp_name = f"multi_attempt_{ts}.lean"
    temp_dir = client.project_root / ".lake" / "lean_tools_mcp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / temp_name

    logger.info(
        "lean_multi_attempt (fallback): file=%s line=%d snippets=%d temp=%s",
        file_path, line, len(snippets), temp_path,
    )

    results: list[dict[str, Any]] = []

    try:
        for i, snippet in enumerate(snippets):
            snippet_lines = snippet.split("\n")
            new_lines = (
                original_lines[: line - 1]
                + snippet_lines
                + original_lines[line:]
            )
            new_content = "\n".join(new_lines)

            temp_path.write_text(new_content, encoding="utf-8")

            if i == 0:
                await client.file_manager.open_file(temp_path, content=new_content)
            else:
                await client.file_manager.change_file(temp_path, new_content)

            diagnostics = await client.file_manager.wait_for_diagnostics(
                temp_path, timeout=client.file_check_timeout
            )

            last_snippet_line = line + len(snippet_lines) - 1
            goal_result = await client.get_goal(str(temp_path), line=last_snippet_line)
            goals_after = goal_result.get("goals_after", goal_result.get("goals", ""))

            snippet_errors: list[str] = []
            for d in diagnostics:
                d_dict = d.to_dict()
                sev = d_dict.get("severity", 0)
                d_start = d_dict.get("range", {}).get("start", {}).get("line", -1)
                if sev == 1 and line - 1 <= d_start < line - 1 + len(snippet_lines):
                    snippet_errors.append(d_dict.get("message", ""))

            results.append({
                "tactic": snippet,
                "goal_state": goals_after,
                "errors": snippet_errors,
            })

    finally:
        await client.file_manager.close_file(temp_path)

    return _format_results(results)


def _format_results(results: list[dict[str, Any]]) -> str:
    """Format multi_attempt results into a human-readable string."""
    parts: list[str] = []
    parts.append(f"Tried {len(results)} tactic(s):\n")

    for i, r in enumerate(results, 1):
        tactic = r.get("tactic", r.get("snippet", "?"))
        goal = r["goal_state"]
        errors = r["errors"]

        parts.append(f"--- Attempt {i}: `{tactic}` ---")

        if errors:
            parts.append("  Errors:")
            for e in errors:
                parts.append(f"    {e}")
        elif goal == "no goals":
            parts.append("  ✓ Proof complete! (no goals)")
        elif goal:
            parts.append("  Remaining goals:")
            for goal_line in goal.strip().split("\n"):
                parts.append(f"    {goal_line}")
        else:
            parts.append("  (no goal state returned)")
        parts.append("")

    parts.append("--- Raw JSON ---")
    parts.append(json.dumps(results, ensure_ascii=False, indent=2))

    return "\n".join(parts)
