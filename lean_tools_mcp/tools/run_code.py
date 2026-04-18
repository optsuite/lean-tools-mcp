# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_run_code — run a self-contained Lean code snippet.

Creates a temporary file in the project's .lake directory, opens it via LSP,
waits for diagnostics, and returns the results. Temp files are NOT deleted.

Note: Due to LSP limitations with dynamic files, this now uses `lake env lean`
by default. Set USE_LSP_FOR_RUN_CODE=1 environment variable to use LSP mode.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from ..lsp.pool import LSPPool
from .run_code_cli import lean_run_code_cli

logger = logging.getLogger(__name__)

# Feature flag: use CLI mode by default due to LSP dynamic file issues
USE_LSP_MODE = os.environ.get("USE_LSP_FOR_RUN_CODE", "0") == "1"


def _severity_name(severity: int) -> str:
    """Map LSP severity number to a human-readable name."""
    return {1: "error", 2: "warning", 3: "information", 4: "hint"}.get(
        severity, "unknown"
    )


def _format_diagnostic(d: dict[str, Any]) -> str:
    """Format a single diagnostic into a readable line."""
    sev = _severity_name(d.get("severity", 1))
    rng = d.get("range", {})
    start = rng.get("start", {})
    line = start.get("line", 0) + 1
    col = start.get("character", 0) + 1
    msg = d.get("message", "")
    return f"[{sev}] {line}:{col} — {msg}"


async def lean_run_code(
    lsp_pool: LSPPool,
    code: str,
) -> str:
    """Run a self-contained Lean code snippet and return diagnostics.

    The code MUST include all necessary imports (e.g. `import Mathlib.Tactic`).

    By default, uses `lake env lean` for reliable error detection.
    Set USE_LSP_FOR_RUN_CODE=1 to use LSP mode (experimental).

    Args:
        lsp_pool: The LSP connection pool.
        code: Self-contained Lean code with all imports.

    Returns:
        Formatted diagnostics string. Empty diagnostics = code compiles clean.
    """
    if not USE_LSP_MODE:
        # Use CLI mode (default, more reliable)
        client = await lsp_pool.pick_client()
        return await lean_run_code_cli(
            project_root=client.project_root,
            code=code,
            timeout=client.file_check_timeout,
        )

    # LSP mode (experimental, has issues with dynamic files)
    return await _lean_run_code_lsp(lsp_pool, code)


async def _lean_run_code_lsp(
    lsp_pool: LSPPool,
    code: str,
) -> str:
    """LSP-based implementation (experimental).

    Note: LSP has known issues with dynamically created files.
    Use CLI mode (default) for reliable error detection.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temp_name = f"run_code_{ts}.lean"

    client = await lsp_pool.pick_client()
    temp_dir = client.project_root / ".lake" / "lean_tools_mcp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / temp_name
    temp_path.write_text(code, encoding="utf-8")

    logger.info("lean_run_code (LSP mode): temp file = %s", temp_path)

    try:
        await client.file_manager.open_file(temp_path, content=code)
        diagnostics, timed_out = await client.file_manager.wait_for_diagnostics(
            temp_path, timeout=client.file_check_timeout
        )
        diag_dicts = [d.to_dict() for d in diagnostics]
    finally:
        await client.file_manager.close_file(temp_path)
        # NOTE: temp file is intentionally kept for inspection.

    return _format_result(temp_path, code, diag_dicts, timed_out=timed_out)


def _format_result(
    temp_path: Path,
    code: str,
    diagnostics: list[dict[str, Any]],
    timed_out: bool = False,
) -> str:
    """Format the run_code result into a readable string."""
    parts: list[str] = []
    parts.append(f"File: {temp_path}")

    if timed_out and not diagnostics:
        parts.append("Result: ✗ Diagnostics timeout (compile status unknown; not safe to treat as success).")
        return "\n".join(parts)

    if not diagnostics:
        parts.append("Result: ✓ Code compiles clean (no diagnostics).")
        return "\n".join(parts)

    errors = [d for d in diagnostics if d.get("severity") == 1]
    warnings = [d for d in diagnostics if d.get("severity") == 2]
    infos = [d for d in diagnostics if d.get("severity") == 3]

    parts.append(f"Diagnostics: {len(errors)} error(s), {len(warnings)} warning(s), "
                 f"{len(infos)} info(s), {len(diagnostics)} total")
    parts.append("")

    for d in diagnostics:
        parts.append(_format_diagnostic(d))

    return "\n".join(parts)
