# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_run_code_cli — run Lean code using lake env lean command.

This is a fallback implementation that uses the Lean compiler directly
instead of LSP, providing more reliable error detection for temporary files.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def lean_run_code_cli(
    project_root: Path,
    code: str,
    timeout: float = 120.0,
) -> str:
    """Run a self-contained Lean code snippet using lake env lean.

    The code MUST include all necessary imports (e.g. `import Mathlib`).
    A temporary file is created in <project>/.lake/lean_tools_mcp/ and
    compiled via `lake env lean`. The temp file is kept for inspection.

    Note: First run may be slow (60-120s) due to Mathlib loading.
    Subsequent runs should be faster if Lean caches are warm.

    Args:
        project_root: The Lean project root directory.
        code: Self-contained Lean code with all imports.
        timeout: Maximum time to wait for compilation (seconds).

    Returns:
        Formatted diagnostics string. Empty diagnostics = code compiles clean.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temp_name = f"run_code_{ts}.lean"

    temp_dir = project_root / ".lake" / "lean_tools_mcp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / temp_name
    temp_path.write_text(code, encoding="utf-8")

    logger.info("lean_run_code_cli: temp file = %s (timeout=%ds)", temp_path, timeout)

    try:
        # Use lake env lean to get proper LEAN_PATH with built dependencies
        proc = await asyncio.create_subprocess_exec(
            "lake", "env", "lean", str(temp_path),
            cwd=project_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("lean_run_code_cli: timeout after %ds", timeout)
            return _format_timeout_result(temp_path, timeout)

        # Parse Lean compiler output
        diagnostics = _parse_lean_output(stdout, stderr, temp_path)
        return _format_result(temp_path, diagnostics)

    except Exception as e:
        logger.error("lean_run_code_cli failed: %s", e)
        return f"File: {temp_path}\nResult: ✗ Execution failed: {e}"


def _parse_lean_output(
    stdout: bytes,
    stderr: bytes,
    temp_path: Path,
) -> list[dict[str, Any]]:
    """Parse Lean compiler output into diagnostic format.

    Lean outputs errors in the format:
    /path/to/file.lean:line:col: error: message
    /path/to/file.lean:line:col: warning: message
    """
    diagnostics = []
    output = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")

    # Pattern: filepath:line:col: severity: message
    pattern = r"^(.+?):(\d+):(\d+):\s*(error|warning|info):\s*(.+?)(?=\n\S|$)"

    for match in re.finditer(pattern, output, re.MULTILINE | re.DOTALL):
        filepath, line_str, col_str, severity, message = match.groups()

        # Only include diagnostics for our temp file
        if Path(filepath).name != temp_path.name:
            continue

        line = int(line_str) - 1  # LSP uses 0-based line numbers
        col = int(col_str) - 1    # LSP uses 0-based column numbers

        severity_map = {"error": 1, "warning": 2, "info": 3}

        diagnostics.append({
            "severity": severity_map.get(severity, 1),
            "range": {
                "start": {"line": line, "character": col},
                "end": {"line": line, "character": col + 1},
            },
            "message": message.strip(),
        })

    return diagnostics


def _format_timeout_result(temp_path: Path, timeout: float) -> str:
    """Format timeout result."""
    return (
        f"File: {temp_path}\n"
        f"Result: ✗ Compilation timeout (exceeded {timeout}s limit).\n"
        f"Note: First run with 'import Mathlib' may take 60-120s due to module loading."
    )


def _format_result(
    temp_path: Path,
    diagnostics: list[dict[str, Any]],
) -> str:
    """Format the run_code result into a readable string."""
    parts: list[str] = []
    parts.append(f"File: {temp_path}")

    if not diagnostics:
        parts.append("Result: ✓ Code compiles clean (no diagnostics).")
        return "\n".join(parts)

    errors = [d for d in diagnostics if d.get("severity") == 1]
    warnings = [d for d in diagnostics if d.get("severity") == 2]
    infos = [d for d in diagnostics if d.get("severity") == 3]

    parts.append(
        f"Diagnostics: {len(errors)} error(s), {len(warnings)} warning(s), "
        f"{len(infos)} info(s), {len(diagnostics)} total"
    )
    parts.append("")

    for d in diagnostics:
        parts.append(_format_diagnostic(d))

    return "\n".join(parts)


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
