# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
lean_build — build the current Lean project and refresh the LSP pool.
"""

from __future__ import annotations

from ..project.manager import BuildResult, LeanProjectManager


def _format_command(command: list[str]) -> str:
    return " ".join(command)


def _tail_lines(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-limit:])


def _format_build_result(result: BuildResult, output_lines: int = 80) -> str:
    """Render a build result in the repo's text-first MCP style."""
    lines: list[str] = []
    if result.success:
        lines.append("Build succeeded.")
    else:
        lines.append(f"Build failed (exit {result.returncode}).")

    if result.commands:
        lines.append("Commands:")
        lines.extend(f"  - {_format_command(command)}" for command in result.commands)

    if result.restarted_lsp:
        lines.append("LSP pool restarted.")
    elif result.success:
        lines.append("Build succeeded, but LSP pool restart did not complete.")

    stdout_tail = _tail_lines(result.stdout, output_lines)
    stderr_tail = _tail_lines(result.stderr, output_lines)

    if stdout_tail:
        lines.append("\nStdout:")
        lines.append(stdout_tail)
    if stderr_tail:
        lines.append("\nStderr:")
        lines.append(stderr_tail)
    if not stdout_tail and not stderr_tail:
        lines.append("No build output.")

    return "\n".join(lines)


async def lean_build(
    project_manager: LeanProjectManager,
    *,
    target: str | None = None,
    clean: bool = False,
    output_lines: int = 80,
) -> str:
    """Run `lake build` for the current project and format the result."""
    result = await project_manager.build(target=target, clean=clean)
    return _format_build_result(result, output_lines=output_lines)
