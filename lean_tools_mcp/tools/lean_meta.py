# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Lean metaprogramming tools — Python wrappers for CLI executables.

Wraps the Lean 4 metaprogramming tools (built via lake) as async
subprocess calls, providing MCP-friendly output.

Tools:
  - lean_havelet_extract: Extract have/let bindings as top-level declarations
  - lean_analyze_deps: Analyze theorem dependencies in a file
  - lean_export_decls: Export declarations to JSONL
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Path to the Lean tools project (relative to the MCP package root)
_LEAN_PROJECT_DIR: Path | None = None


def _find_lean_project() -> Path | None:
    """Find the Lean sub-project directory."""
    global _LEAN_PROJECT_DIR
    if _LEAN_PROJECT_DIR is not None:
        return _LEAN_PROJECT_DIR

    # Search upward so this works for:
    # - current layout: memory_optimization/lean
    # - legacy layout: lean/
    for parent in Path(__file__).resolve().parents:
        candidates = [
            parent / "memory_optimization" / "lean",
            parent / "lean",
        ]
        for lean_dir in candidates:
            if lean_dir.is_dir() and (lean_dir / "lakefile.lean").exists():
                _LEAN_PROJECT_DIR = lean_dir
                return lean_dir
    return None


def _find_executable(name: str) -> Path | None:
    """Find a built Lean executable."""
    lean_dir = _find_lean_project()
    if lean_dir is None:
        return None
    exe = lean_dir / ".lake" / "build" / "bin" / name
    if exe.exists():
        return exe
    return None


def _get_lean_path(user_project_root: Path | str | None = None) -> str:
    """Build LEAN_PATH that includes both our tools and the user's project.

    This allows the CLI tools to find oleans from the user's project
    (including Mathlib) when elaborating files.
    """
    paths: list[str] = []

    # Our lean tools project
    lean_dir = _find_lean_project()
    if lean_dir:
        build_lib = lean_dir / ".lake" / "build" / "lib"
        if build_lib.exists():
            paths.append(str(build_lib))

    # User's project .lake paths
    if user_project_root:
        user_root = Path(user_project_root)
        # Standard lake build output
        for subdir in [
            user_root / ".lake" / "build" / "lib",
            user_root / ".lake" / "packages",
        ]:
            if subdir.exists():
                paths.append(str(subdir))
                # Also add all sub-package lib dirs
                for pkg_dir in subdir.iterdir():
                    pkg_lib = pkg_dir / "lib"
                    if pkg_lib.is_dir():
                        paths.append(str(pkg_lib))

    # Preserve any existing LEAN_PATH
    existing = os.environ.get("LEAN_PATH", "")
    if existing:
        paths.append(existing)

    return ":".join(paths)


async def _run_lean_tool(
    executable: str,
    args: list[str],
    *,
    cwd: Path | str | None = None,
    user_project_root: Path | str | None = None,
    timeout: float = 120.0,
) -> tuple[int, str, str]:
    """Run a Lean CLI tool as a subprocess.

    Returns (exit_code, stdout, stderr).
    """
    exe_path = _find_executable(executable)
    if exe_path is None:
        return (
            -1,
            "",
            f"Lean tool '{executable}' not found. "
            f"Run 'lake build {executable}' in memory_optimization/lean first.",
        )

    env = os.environ.copy()
    lean_path = _get_lean_path(user_project_root)
    if lean_path:
        env["LEAN_PATH"] = lean_path

    cmd = [str(exe_path)] + args

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        proc.kill()
        return (-1, "", f"Tool '{executable}' timed out after {timeout}s")
    except Exception as e:
        return (-1, "", str(e))


# ---------------------------------------------------------------------------
# MCP Tool: lean_havelet_extract
# ---------------------------------------------------------------------------

async def lean_havelet_extract(
    file_path: str,
    prefix: str = "Extracted",
    user_project_root: str | None = None,
) -> str:
    """Extract have/let bindings from a Lean file as top-level declarations.

    Parses the input file, finds all local have/let bindings,
    closes over free variables, and generates a new .lean file with
    standalone theorem/def declarations.

    Args:
        file_path: Absolute path to the input .lean file.
        prefix: Name prefix for generated declarations.
        user_project_root: Root of the user's Lean project (for LEAN_PATH).

    Returns:
        Generated Lean source code or error message.
    """
    input_path = Path(file_path)
    if not input_path.exists():
        return f"Error: File not found: {file_path}"

    # Create timestamped output file in the same directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = input_path.parent
    out_name = f"{input_path.stem}_havelet_{ts}.lean"
    out_path = out_dir / out_name

    exit_code, stdout, stderr = await _run_lean_tool(
        "havelet_generator",
        [str(input_path), str(out_path), prefix],
        cwd=user_project_root,
        user_project_root=user_project_root,
    )

    if exit_code != 0:
        return f"[havelet_generator] Error (exit {exit_code}):\n{stderr}"

    # Read and return the generated file
    if out_path.exists():
        content = out_path.read_text(encoding="utf-8")
        return (
            f"[havelet_generator] Generated: {out_path}\n"
            f"({len(content)} chars)\n\n"
            f"{content}"
        )
    else:
        return f"[havelet_generator] Completed but output not found.\nstdout: {stdout}\nstderr: {stderr}"


# ---------------------------------------------------------------------------
# MCP Tool: lean_analyze_deps
# ---------------------------------------------------------------------------

async def lean_analyze_deps(
    file_path: str,
    user_project_root: str | None = None,
) -> str:
    """Analyze theorem dependencies in a Lean file.

    For each theorem in the file, extracts all definitions, classes,
    structures, and inductives used in the theorem statement.
    Returns structured JSON output.

    Args:
        file_path: Absolute path to the .lean file to analyze.
        user_project_root: Root of the user's Lean project.

    Returns:
        JSON analysis or error message.
    """
    input_path = Path(file_path)
    if not input_path.exists():
        return f"Error: File not found: {file_path}"

    # Output to a timestamped JSON file
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = input_path.parent / f"{input_path.stem}_deps_{ts}.json"

    exit_code, stdout, stderr = await _run_lean_tool(
        "definition_tool",
        [str(input_path), str(out_path)],
        cwd=user_project_root,
        user_project_root=user_project_root,
    )

    if exit_code != 0:
        return f"[definition_tool] Error (exit {exit_code}):\n{stderr}"

    # Parse and format the JSON output
    if out_path.exists():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            return _format_deps_analysis(data, str(out_path))
        except json.JSONDecodeError:
            return f"[definition_tool] Output written to {out_path} but couldn't parse JSON."
    else:
        # Tool might have written to stdout
        if stdout.strip():
            try:
                data = json.loads(stdout)
                return _format_deps_analysis(data, "(stdout)")
            except json.JSONDecodeError:
                pass
        return f"[definition_tool] Completed.\nstdout: {stdout}\nstderr: {stderr}"


def _format_deps_analysis(data: dict, source: str) -> str:
    """Format the DefinitionTool JSON analysis into readable text."""
    parts: list[str] = []
    parts.append(f"[definition_tool] Analysis from: {source}")

    theorems = data.get("theorems", [])
    parts.append(f"Found {len(theorems)} theorem(s)\n")

    for thm in theorems:
        name = thm.get("theoremName", "?")
        stmt = thm.get("statement", "")
        deps = thm.get("dependencies", [])
        parts.append(f"--- {name} ---")
        if stmt:
            parts.append(f"  Statement: {stmt[:200]}")
        parts.append(f"  Dependencies ({len(deps)}):")
        for dep in deps[:20]:  # Limit display
            dep_name = dep.get("name", "?")
            dep_kind = dep.get("kind", "?")
            dep_module = dep.get("module", "")
            parts.append(f"    - [{dep_kind}] {dep_name} ({dep_module})")
        if len(deps) > 20:
            parts.append(f"    ... and {len(deps) - 20} more")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# MCP Tool: lean_export_decls
# ---------------------------------------------------------------------------

async def lean_export_decls(
    modules: list[str],
    output_path: str | None = None,
    user_project_root: str | None = None,
) -> str:
    """Export declarations from Lean/Mathlib modules to JSONL.

    Bulk-exports all declarations from specified modules.
    Each record contains: name, kind, module, type, value, dependencies, etc.

    Args:
        modules: List of module name prefixes (e.g., ["Mathlib.Topology"]).
        output_path: Path for the output JSONL file.
        user_project_root: Root of the user's Lean project.

    Returns:
        Summary of exported declarations or error message.
    """
    if not modules:
        return "Error: No modules specified."

    # Default output path
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"decl_export_{ts}.jsonl"

    args = [output_path] + modules

    exit_code, stdout, stderr = await _run_lean_tool(
        "decl_exporter",
        args,
        cwd=user_project_root,
        user_project_root=user_project_root,
        timeout=600.0,  # Long timeout for large exports
    )

    if exit_code != 0:
        return f"[decl_exporter] Error (exit {exit_code}):\n{stderr}"

    # Count exported records
    out_file = Path(output_path)
    if out_file.exists():
        line_count = sum(1 for _ in open(out_file, encoding="utf-8") if _.strip())
        return (
            f"[decl_exporter] Exported {line_count} declaration(s) to {output_path}\n"
            f"Modules: {', '.join(modules)}\n\n"
            f"Process output:\n{stderr}"
        )
    else:
        return f"[decl_exporter] Completed.\nstderr: {stderr}"
