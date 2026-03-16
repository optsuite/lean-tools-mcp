# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_hover_info — type signature and documentation tool.

Essential for understanding APIs and inspecting symbol types.
"""

from __future__ import annotations

from typing import Any

from ..lsp.pool import LSPPool


def _extract_hover_content(result: dict[str, Any] | None) -> str:
    """Extract readable text from an LSP hover response.

    The Lean LSP returns hover content in MarkupContent format:
    { "contents": { "kind": "markdown", "value": "..." } }
    or sometimes as a plain string.
    """
    if result is None:
        return "No hover information at this position."

    contents = result.get("contents")
    if contents is None:
        return "No hover information at this position."

    # MarkupContent: { kind, value }
    if isinstance(contents, dict):
        value = contents.get("value", "")
        if value:
            return value
        return str(contents)

    # Plain string
    if isinstance(contents, str):
        return contents

    # MarkedString[] (legacy)
    if isinstance(contents, list):
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("value", str(item)))
        return "\n---\n".join(parts) if parts else "No hover information."

    return str(contents)


def _format_hover_with_range(result: dict[str, Any] | None) -> str:
    """Format hover info with optional source range."""
    text = _extract_hover_content(result)

    if result and "range" in result:
        rng = result["range"]
        start = rng.get("start", {})
        end = rng.get("end", {})
        line_start = start.get("line", 0) + 1
        col_start = start.get("character", 0) + 1
        line_end = end.get("line", 0) + 1
        col_end = end.get("character", 0) + 1
        text += f"\n\n(range: {line_start}:{col_start} - {line_end}:{col_end})"

    return text


async def lean_hover_info(
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    column: int,
) -> str:
    """Get type signature and docs for a symbol. Essential for understanding APIs.

    Args:
        file_path: Absolute path to the .lean file
        line: Line number (1-indexed)
        column: Column at START of identifier (1-indexed)

    Returns:
        Type signature and documentation in markdown format.
    """
    result = await lsp_pool.get_hover(file_path, line, column)
    return _format_hover_with_range(result)
