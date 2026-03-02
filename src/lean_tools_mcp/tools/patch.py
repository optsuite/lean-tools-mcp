# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_apply_patch — apply partial edits to a .lean file.

Supports two modes:
  1. Line-range replacement: replace lines [start_line, end_line] with new content.
  2. Search-and-replace: find exact text and replace it (with optional occurrence index).

After applying the patch, returns the modified region with surrounding context.
"""

from __future__ import annotations

import shutil
from pathlib import Path


async def lean_apply_patch(
    file_path: str,
    *,
    new_content: str,
    start_line: int | None = None,
    end_line: int | None = None,
    search: str | None = None,
    occurrence: int = 1,
    context_lines: int = 5,
) -> str:
    """Apply a partial edit to a .lean file.

    Two modes (mutually exclusive):

    Mode 1 — Line replacement (start_line + end_line):
        Replaces lines [start_line, end_line] (inclusive, 1-indexed) with new_content.
        If start_line == end_line and new_content is empty, the line is deleted.

    Mode 2 — Search and replace (search):
        Finds the Nth occurrence (default 1st) of `search` in the file
        and replaces it with new_content.

    Args:
        file_path: Absolute path to the .lean file.
        new_content: Replacement text.
        start_line: First line to replace (1-indexed, inclusive).
        end_line: Last line to replace (1-indexed, inclusive).
        search: Exact text to find and replace.
        occurrence: Which occurrence to replace (1-indexed, default 1).
        context_lines: Lines of context to show around the edit (default 5).

    Returns:
        The modified region with context, or an error message.
    """
    p = Path(file_path).resolve()
    if not p.exists():
        return f"Error: file not found: {file_path}"
    if not p.suffix == ".lean":
        return f"Error: not a .lean file: {file_path}"

    line_mode = start_line is not None and end_line is not None
    search_mode = search is not None

    if line_mode == search_mode:
        return (
            "Error: specify either (start_line + end_line) for line replacement, "
            "or (search) for search-and-replace, but not both."
        )

    try:
        original = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    # Create a backup before modifying
    backup = p.with_suffix(".lean.bak")
    try:
        shutil.copy2(p, backup)
    except OSError:
        pass

    try:
        if line_mode:
            result_text, edit_start, edit_end = _apply_line_patch(
                original, new_content, start_line, end_line  # type: ignore[arg-type]
            )
        else:
            result_text, edit_start, edit_end = _apply_search_patch(
                original, new_content, search, occurrence  # type: ignore[arg-type]
            )
    except PatchError as e:
        _remove_backup(backup)
        return f"Error: {e}"

    # Write the modified content
    try:
        p.write_text(result_text, encoding="utf-8")
    except Exception as e:
        # Restore backup on write failure
        if backup.exists():
            shutil.copy2(backup, p)
        _remove_backup(backup)
        return f"Error writing file: {e}"

    _remove_backup(backup)

    # Format output with context
    return _format_result(result_text, edit_start, edit_end, context_lines, str(p))


class PatchError(Exception):
    pass


def _apply_line_patch(
    content: str,
    new_content: str,
    start_line: int,
    end_line: int,
) -> tuple[str, int, int]:
    """Replace lines [start_line, end_line] (1-indexed, inclusive)."""
    lines = content.split("\n")
    total = len(lines)

    if start_line < 1 or end_line < 1:
        raise PatchError("Line numbers must be >= 1")
    if start_line > end_line:
        raise PatchError(f"start_line ({start_line}) > end_line ({end_line})")
    if start_line > total:
        raise PatchError(f"start_line ({start_line}) exceeds file length ({total})")

    end_line = min(end_line, total)
    s = start_line - 1  # convert to 0-indexed
    e = end_line         # exclusive end for slice

    new_lines = new_content.split("\n") if new_content else []

    result_lines = lines[:s] + new_lines + lines[e:]
    edit_end_line = s + len(new_lines)

    return "\n".join(result_lines), s, edit_end_line


def _apply_search_patch(
    content: str,
    new_content: str,
    search: str,
    occurrence: int,
) -> tuple[str, int, int]:
    """Find the Nth occurrence of `search` and replace with new_content."""
    if occurrence < 1:
        raise PatchError("occurrence must be >= 1")

    # Find all occurrences
    positions: list[int] = []
    start = 0
    while True:
        idx = content.find(search, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1

    if not positions:
        preview = search[:80] + ("..." if len(search) > 80 else "")
        raise PatchError(f"search text not found in file: {preview!r}")
    if occurrence > len(positions):
        raise PatchError(
            f"only {len(positions)} occurrence(s) found, "
            f"but occurrence={occurrence} requested"
        )

    target_pos = positions[occurrence - 1]
    result = content[:target_pos] + new_content + content[target_pos + len(search):]

    # Compute line range of the edit
    edit_start_line = content[:target_pos].count("\n")
    edit_end_line = edit_start_line + new_content.count("\n")

    return result, edit_start_line, edit_end_line


def _format_result(
    content: str,
    edit_start: int,
    edit_end: int,
    context: int,
    file_path: str,
) -> str:
    """Format the result showing the edited region with context."""
    lines = content.split("\n")
    total = len(lines)

    ctx_start = max(0, edit_start - context)
    ctx_end = min(total, edit_end + context)

    width = len(str(ctx_end + 1))
    output_lines = [f"Patch applied to {file_path}"]
    output_lines.append(f"Showing lines {ctx_start + 1}-{ctx_end} (edited: {edit_start + 1}-{edit_end}):\n")

    for i in range(ctx_start, ctx_end):
        num = f"{i + 1:>{width}}"
        marker = ">" if edit_start <= i < edit_end else " "
        output_lines.append(f"{marker} {num}|{lines[i]}")

    return "\n".join(output_lines)


def _remove_backup(backup: Path) -> None:
    try:
        backup.unlink(missing_ok=True)
    except OSError:
        pass
