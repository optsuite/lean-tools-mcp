# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_diagnostic_messages — compiler diagnostics tool.

Returns errors, warnings, and info messages from the Lean compiler.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..lsp.pool import LSPPool


def _severity_name(severity: int) -> str:
    """Map LSP severity number to a human-readable name."""
    return {1: "error", 2: "warning", 3: "information", 4: "hint"}.get(
        severity, "unknown"
    )


def _format_diagnostic(d: dict[str, Any]) -> str:
    """Format a single diagnostic into a readable string."""
    sev = _severity_name(d.get("severity", 1))
    rng = d.get("range", {})
    start = rng.get("start", {})
    line = start.get("line", 0) + 1  # Convert to 1-indexed
    col = start.get("character", 0) + 1
    msg = d.get("message", "")
    return f"[{sev}] {line}:{col} — {msg}"


async def lean_diagnostic_messages(
    lsp_pool: LSPPool,
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    severity: str | None = None,
    declaration_name: str | None = None,
) -> str:
    """Get compiler diagnostics (errors, warnings, infos) for a Lean file.

    Args:
        file_path: Absolute path to the .lean file
        start_line: Filter from this line (1-indexed, inclusive)
        end_line: Filter to this line (1-indexed, inclusive)
        severity: Filter by severity: "error", "warning", "information", "hint"
        declaration_name: Filter to a specific declaration (slower — requires
                         scanning diagnostics for the declaration name in context)

    Returns:
        Formatted diagnostics string. Empty diagnostics = file compiles clean.
        "no goals to be solved" in an error message means you should remove
        redundant tactics.
    """
    diagnostics = await lsp_pool.get_diagnostics(
        file_path, start_line=start_line, end_line=end_line
    )

    # Filter by severity
    if severity:
        sev_map = {"error": 1, "warning": 2, "information": 3, "hint": 4}
        target_sev = sev_map.get(severity.lower())
        if target_sev:
            diagnostics = [d for d in diagnostics if d.get("severity") == target_sev]

    # Filter by declaration name (heuristic: check if name appears in message)
    if declaration_name:
        diagnostics = [
            d
            for d in diagnostics
            if declaration_name in d.get("message", "")
        ]

    if not diagnostics:
        return "No diagnostics found (file compiles clean for the specified range)."

    lines = [_format_diagnostic(d) for d in diagnostics]

    # Summary
    errors = sum(1 for d in diagnostics if d.get("severity") == 1)
    warnings = sum(1 for d in diagnostics if d.get("severity") == 2)
    summary = f"\nSummary: {errors} error(s), {warnings} warning(s), {len(diagnostics)} total"

    return "\n".join(lines) + summary
