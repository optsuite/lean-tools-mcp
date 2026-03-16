# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_completions — IDE autocompletion tool.

Use on INCOMPLETE code (after `.` or partial name).
"""

from __future__ import annotations

import json
from typing import Any

from ..lsp.pool import LSPPool


def _format_completion_item(item: dict[str, Any]) -> str:
    """Format a single completion item into a readable line."""
    label = item.get("label", "?")
    detail = item.get("detail", "")
    kind = _completion_kind_name(item.get("kind", 0))

    parts = [label]
    if detail:
        parts.append(f": {detail}")
    if kind:
        parts.append(f"  ({kind})")
    return "".join(parts)


def _completion_kind_name(kind: int) -> str:
    """Map LSP CompletionItemKind to a human-readable name."""
    names = {
        1: "text", 2: "method", 3: "function", 4: "constructor",
        5: "field", 6: "variable", 7: "class", 8: "interface",
        9: "module", 10: "property", 11: "unit", 12: "value",
        13: "enum", 14: "keyword", 15: "snippet", 16: "color",
        17: "file", 18: "reference", 19: "folder", 20: "enum_member",
        21: "constant", 22: "struct", 23: "event", 24: "operator",
        25: "type_parameter",
    }
    return names.get(kind, "")


async def lean_completions(
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    column: int,
    max_completions: int = 32,
) -> str:
    """Get IDE autocompletions at a position.

    Use on INCOMPLETE code — after `.` or a partial name.

    Args:
        file_path: Absolute path to the .lean file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
        max_completions: Maximum number of completions to return (default 32)

    Returns:
        Formatted list of completion suggestions.
    """
    items = await lsp_pool.get_completions(file_path, line, column)

    if not items:
        return "No completions available at this position."

    # Limit results
    items = items[:max_completions]

    lines = [_format_completion_item(item) for item in items]

    header = f"Completions ({len(lines)} of {len(items)} shown):"
    return header + "\n" + "\n".join(lines)
