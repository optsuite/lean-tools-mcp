# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_patch_syntax — syntax-aware code patching using Lean metaprogramming.

This module provides a Python wrapper for the patch_tool Lean executable,
which performs syntax-aware code modifications instead of string-based patching.

Advantages over string-based patching:
- Robust to whitespace and formatting changes
- Understands Lean syntax structure
- Won't accidentally modify comments or strings
- Preserves code structure and formatting
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .lean_meta import _run_lean_tool

logger = logging.getLogger(__name__)


async def lean_patch_by_name(
    file_path: str,
    old_name: str,
    new_name: str,
    user_project_root: str | None = None,
) -> str:
    """Rename a declaration using syntax-aware patching.

    Args:
        file_path: Absolute path to the .lean file.
        old_name: Current name of the declaration.
        new_name: New name for the declaration.
        user_project_root: Root of the user's Lean project (for LEAN_PATH).

    Returns:
        Success message or error description.
    """
    input_path = Path(file_path)
    if not input_path.exists():
        return f"Error: File not found: {file_path}"

    exit_code, stdout, stderr = await _run_lean_tool(
        "patch_tool",
        ["replace-name", str(input_path), old_name, new_name],
        cwd=user_project_root,
        user_project_root=user_project_root,
    )

    if exit_code != 0:
        return f"[patch_tool] Error (exit {exit_code}):\n{stderr}"

    return stdout


async def lean_patch_by_content(
    file_path: str,
    search_text: str,
    replacement_file: str,
    user_project_root: str | None = None,
) -> str:
    """Replace declarations containing search text using syntax-aware patching.

    Args:
        file_path: Absolute path to the .lean file to modify.
        search_text: Text to search for in declarations.
        replacement_file: Path to file containing replacement content.
        user_project_root: Root of the user's Lean project (for LEAN_PATH).

    Returns:
        Success message or error description.
    """
    input_path = Path(file_path)
    if not input_path.exists():
        return f"Error: File not found: {file_path}"

    replacement_path = Path(replacement_file)
    if not replacement_path.exists():
        return f"Error: Replacement file not found: {replacement_file}"

    exit_code, stdout, stderr = await _run_lean_tool(
        "patch_tool",
        ["replace-content", str(input_path), search_text, str(replacement_path)],
        cwd=user_project_root,
        user_project_root=user_project_root,
    )

    if exit_code != 0:
        return f"[patch_tool] Error (exit {exit_code}):\n{stderr}"

    return stdout


async def lean_search_declarations(
    file_path: str,
    pattern: str,
    user_project_root: str | None = None,
) -> str:
    """Search for declarations matching a pattern.

    Args:
        file_path: Absolute path to the .lean file.
        pattern: Text pattern to search for.
        user_project_root: Root of the user's Lean project (for LEAN_PATH).

    Returns:
        Search results or error description.
    """
    input_path = Path(file_path)
    if not input_path.exists():
        return f"Error: File not found: {file_path}"

    exit_code, stdout, stderr = await _run_lean_tool(
        "patch_tool",
        ["search", str(input_path), pattern],
        cwd=user_project_root,
        user_project_root=user_project_root,
    )

    if exit_code != 0:
        return f"[patch_tool] Error (exit {exit_code}):\n{stderr}"

    return stdout


# Backward compatibility: provide a drop-in replacement for the old patch.py
async def lean_apply_patch_syntax(
    file_path: str,
    *,
    new_content: str,
    search: str | None = None,
    occurrence: int = 1,
    context_lines: int = 5,
    user_project_root: str | None = None,
) -> str:
    """Apply a syntax-aware patch (drop-in replacement for lean_apply_patch).

    This function provides backward compatibility with the old string-based
    patch.py API, but uses syntax-aware patching internally.

    Args:
        file_path: Absolute path to the .lean file.
        new_content: Replacement content.
        search: Text to search for (required for this mode).
        occurrence: Which occurrence to replace (not yet supported).
        context_lines: Lines of context to show (not used in syntax mode).
        user_project_root: Root of the user's Lean project.

    Returns:
        Formatted result or error message.
    """
    if search is None:
        return "Error: search parameter is required for syntax-aware patching"

    if occurrence != 1:
        logger.warning(
            "occurrence parameter not yet supported in syntax-aware mode, "
            "will replace first match only"
        )

    # Create a temporary file for the replacement content
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.lean', delete=False, encoding='utf-8'
    ) as tmp:
        tmp.write(new_content)
        tmp_path = tmp.name

    try:
        result = await lean_patch_by_content(
            file_path, search, tmp_path, user_project_root
        )
        return result
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)
