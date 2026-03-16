# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Project-level orchestration for Lean Tools MCP.

Coordinates lifecycle operations that should not live directly in individual
tool wrappers, such as `lake build` and LSP-pool restarts.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..lsp.pool import LSPPool


@dataclass(slots=True)
class BuildResult:
    """Outcome of a project build command."""

    success: bool
    returncode: int
    stdout: str
    stderr: str
    restarted_lsp: bool
    commands: list[list[str]]


class LeanProjectManager:
    """Manage project-scoped Lean operations.

    This layer exists to keep project lifecycle logic in one place:
    subprocess execution, environment preparation, serialization, and LSP restarts.
    """

    def __init__(
        self,
        project_root: Path | str,
        lsp_pool: LSPPool,
        lean_path: str = "lean",
        build_timeout: float = 900.0,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.lsp_pool = lsp_pool
        self.lean_path = lean_path
        self.build_timeout = build_timeout
        self._build_lock = asyncio.Lock()

    async def build(
        self,
        *,
        target: str | None = None,
        clean: bool = False,
    ) -> BuildResult:
        """Run `lake build`, optionally with a prior `lake clean`.

        Successful builds trigger a full LSP-pool restart so future requests
        observe the updated build products.
        """
        commands: list[list[str]] = []

        async with self._build_lock:
            if clean:
                clean_cmd = ["lake", "clean"]
                commands.append(clean_cmd)
                clean_code, clean_out, clean_err = await self._run_lake_command(clean_cmd)
                if clean_code != 0:
                    return BuildResult(
                        success=False,
                        returncode=clean_code,
                        stdout=clean_out,
                        stderr=clean_err,
                        restarted_lsp=False,
                        commands=commands,
                    )

            build_cmd = ["lake", "build"]
            if target:
                build_cmd.append(target)
            commands.append(build_cmd)

            code, stdout, stderr = await self._run_lake_command(build_cmd)
            if code != 0:
                return BuildResult(
                    success=False,
                    returncode=code,
                    stdout=stdout,
                    stderr=stderr,
                    restarted_lsp=False,
                    commands=commands,
                )

            restarted_lsp = False
            restart_error = ""
            try:
                await self.lsp_pool.restart()
                restarted_lsp = True
            except Exception as exc:
                restart_error = f"LSP restart failed: {exc}"

            if restart_error:
                stderr = f"{stderr}\n{restart_error}".strip()

            return BuildResult(
                success=True,
                returncode=code,
                stdout=stdout,
                stderr=stderr,
                restarted_lsp=restarted_lsp,
                commands=commands,
            )

    async def code_actions(
        self,
        *,
        file_path: str,
        line: int,
        column: int,
        end_line: int | None = None,
        end_column: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch code actions for a location or range."""
        return await self.lsp_pool.get_code_actions(
            file_path=file_path,
            line=line,
            column=column,
            end_line=end_line,
            end_column=end_column,
        )

    def _build_env(self) -> dict[str, str]:
        """Construct an environment aligned with the configured Lean binary."""
        env = os.environ.copy()
        lean_path = Path(self.lean_path)
        if lean_path.is_absolute():
            lean_bin_dir = str(lean_path.resolve().parent)
            current_path = env.get("PATH", "")
            env["PATH"] = (
                f"{lean_bin_dir}{os.pathsep}{current_path}"
                if current_path
                else lean_bin_dir
            )
        return env

    async def _run_lake_command(self, command: list[str]) -> tuple[int, str, str]:
        """Run a `lake` command inside the configured project root."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(self.project_root),
                env=self._build_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return 127, "", f"Failed to start {' '.join(command)}: {exc}"

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.build_timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            timeout_msg = (
                f"Command {' '.join(command)} timed out after {self.build_timeout:.0f}s"
            )
            stderr = f"{stderr}\n{timeout_msg}".strip()
            return 124, stdout, stderr

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return proc.returncode or 0, stdout, stderr
