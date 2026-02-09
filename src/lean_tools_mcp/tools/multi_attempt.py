"""
lean_multi_attempt — try multiple tactics at a position without modifying the file.

For each tactic snippet, creates a modified copy of the file (replacing the
target line), checks via LSP, and returns the resulting goal state.
Uses a single temp file with didChange for efficiency (incremental re-checking).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..lsp.pool import LSPPool

logger = logging.getLogger(__name__)


async def lean_multi_attempt(
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    snippets: list[str],
) -> str:
    """Try multiple tactics at a position and return goal state for each.

    Replaces the content at `line` with each snippet, checks the file via LSP,
    and returns the resulting proof goal state. The original file is NEVER modified.

    A single temp file is used with LSP didChange for incremental re-checking,
    which is much faster than opening a new file for each attempt.

    Args:
        lsp_pool: The LSP connection pool.
        file_path: Absolute path to the .lean file.
        line: Line number (1-indexed) to replace with each snippet.
        snippets: List of tactic strings to try (3+ recommended).

    Returns:
        JSON array of results, each with {snippet, goal_state, diagnostics}.
    """
    original_path = Path(file_path).resolve()
    if not original_path.exists():
        return json.dumps({"error": f"File not found: {file_path}"})

    original_content = original_path.read_text(encoding="utf-8")
    original_lines = original_content.split("\n")

    if line < 1 or line > len(original_lines):
        return json.dumps(
            {"error": f"Line {line} out of range (file has {len(original_lines)} lines)"}
        )

    # Pick a single client for all attempts (reuse the same LSP connection)
    client = await lsp_pool.pick_client()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temp_name = f"multi_attempt_{ts}.lean"
    temp_dir = client.project_root / ".lake" / "lean_tools_mcp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / temp_name

    logger.info(
        "lean_multi_attempt: file=%s line=%d snippets=%d temp=%s",
        file_path, line, len(snippets), temp_path,
    )

    results: list[dict[str, Any]] = []

    try:
        for i, snippet in enumerate(snippets):
            # Build modified content: replace the target line with the snippet
            snippet_lines = snippet.split("\n")
            new_lines = (
                original_lines[: line - 1]
                + snippet_lines
                + original_lines[line:]
            )
            new_content = "\n".join(new_lines)

            # Write to temp file on disk (for persistence and debugging)
            temp_path.write_text(new_content, encoding="utf-8")

            if i == 0:
                # First attempt: open the file in LSP
                await client.file_manager.open_file(temp_path, content=new_content)
            else:
                # Subsequent attempts: use didChange for incremental checking
                await client.file_manager.change_file(temp_path, new_content)

            # Wait for file to be fully checked
            diagnostics = await client.file_manager.wait_for_diagnostics(
                temp_path, timeout=client.file_check_timeout
            )

            # Get goal state at the end of the snippet
            # The snippet replaces line `line` (1-indexed).
            # The last snippet line is at 1-indexed: line + len(snippet_lines) - 1
            # We want the goal AFTER the last snippet line.
            last_snippet_line = line + len(snippet_lines) - 1
            goal_result = await client.get_goal(str(temp_path), line=last_snippet_line)

            # Extract the goals_after (state after the tactic)
            goals_after = goal_result.get("goals_after", goal_result.get("goals", ""))

            # Collect diagnostics on the snippet lines (errors only)
            snippet_errors: list[str] = []
            for d in diagnostics:
                d_dict = d.to_dict()
                sev = d_dict.get("severity", 0)
                d_start = d_dict.get("range", {}).get("start", {}).get("line", -1)
                # Check if the diagnostic is on one of the snippet lines (0-indexed)
                if sev == 1 and line - 1 <= d_start < line - 1 + len(snippet_lines):
                    snippet_errors.append(d_dict.get("message", ""))

            results.append({
                "snippet": snippet,
                "goal_state": goals_after,
                "errors": snippet_errors,
            })

            logger.debug(
                "  attempt %d/%d: snippet=%r goal=%s errors=%d",
                i + 1, len(snippets), snippet[:40],
                goals_after[:60] if goals_after else "(empty)",
                len(snippet_errors),
            )

    finally:
        # Close the temp file in LSP (but keep the file on disk)
        await client.file_manager.close_file(temp_path)
        # NOTE: temp file is intentionally kept for inspection.
        # The file on disk reflects the LAST attempted snippet.

    return _format_results(results)


def _format_results(results: list[dict[str, Any]]) -> str:
    """Format multi_attempt results into a human-readable string.

    Also includes a JSON representation for programmatic consumption.
    """
    parts: list[str] = []
    parts.append(f"Tried {len(results)} tactic(s):\n")

    for i, r in enumerate(results, 1):
        snippet = r["snippet"]
        goal = r["goal_state"]
        errors = r["errors"]

        parts.append(f"--- Attempt {i}: `{snippet}` ---")

        if errors:
            parts.append(f"  Errors:")
            for e in errors:
                parts.append(f"    {e}")
        elif goal == "no goals":
            parts.append(f"  ✓ Proof complete! (no goals)")
        elif goal:
            parts.append(f"  Remaining goals:")
            for goal_line in goal.strip().split("\n"):
                parts.append(f"    {goal_line}")
        else:
            parts.append(f"  (no goal state returned)")
        parts.append("")

    # Append raw JSON for programmatic use
    parts.append("--- Raw JSON ---")
    parts.append(json.dumps(results, ensure_ascii=False, indent=2))

    return "\n".join(parts)
