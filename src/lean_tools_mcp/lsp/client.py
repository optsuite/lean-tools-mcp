"""
LSP Client — manages a single `lean --server` subprocess.

Handles the full lifecycle: spawn, initialize, requests, and shutdown.
Provides high-level methods for Lean-specific LSP operations.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .file_manager import FileManager, path_to_uri
from .protocol import JsonRpcTransport, LSPProtocolError
from .types import (
    Diagnostic,
    DiagnosticSeverity,
    PlainGoal,
    PlainTermGoal,
    Position,
    TacticResult,
)

logger = logging.getLogger(__name__)


class LSPClient:
    """A single LSP connection to a `lean --server` process.

    Usage:
        client = LSPClient(project_root="/path/to/lean/project")
        await client.start()
        goal = await client.get_goal("/path/to/file.lean", line=10, character=0)
        await client.shutdown()
    """

    def __init__(
        self,
        project_root: Path | str,
        lean_path: str = "lean",
        request_timeout: float = 60.0,
        file_check_timeout: float = 120.0,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._lean_path = lean_path
        self._request_timeout = request_timeout
        self._file_check_timeout = file_check_timeout

        self._process: asyncio.subprocess.Process | None = None
        self._transport: JsonRpcTransport | None = None
        self._file_manager: FileManager | None = None
        self._initialized = False

        # Track file progress for knowing when checking is complete
        self._file_progress: dict[str, list[dict[str, Any]]] = {}

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def file_check_timeout(self) -> float:
        return self._file_check_timeout

    @property
    def file_manager(self) -> FileManager:
        assert self._file_manager is not None, "LSP client not started"
        return self._file_manager

    @property
    def transport(self) -> JsonRpcTransport:
        assert self._transport is not None, "LSP client not started"
        return self._transport

    @property
    def is_alive(self) -> bool:
        return (
            self._process is not None
            and self._process.returncode is None
            and self._initialized
        )

    async def start(self) -> None:
        """Spawn `lean --server` and perform the LSP initialization handshake."""
        logger.info(
            "Starting LSP server: %s --server (root=%s)",
            self._lean_path,
            self._project_root,
        )

        self._process = await asyncio.create_subprocess_exec(
            self._lean_path,
            "--server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_root),
        )

        assert self._process.stdin is not None
        assert self._process.stdout is not None

        reader = self._process.stdout
        writer = asyncio.StreamWriter(
            self._process.stdin._transport,  # type: ignore[union-attr]
            self._process.stdin._protocol,  # type: ignore[union-attr]
            None,
            asyncio.get_event_loop(),
        )

        self._transport = JsonRpcTransport(reader, writer)

        # Register for file progress notifications
        self._transport.on_notification(
            "$/lean/fileProgress",
            self._on_file_progress,
        )

        await self._transport.start()
        await self._initialize()
        self._file_manager = FileManager(self._transport)
        self._initialized = True
        logger.info("LSP server initialized successfully")

    async def shutdown(self) -> None:
        """Gracefully shut down the LSP server."""
        if self._transport and self._initialized:
            try:
                await self._transport.send_request("shutdown", timeout=10.0)
                await self._transport.send_notification("exit")
            except Exception:
                logger.debug("Error during LSP shutdown", exc_info=True)

        if self._transport:
            await self._transport.close()

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                self._process.kill()

        self._initialized = False
        logger.info("LSP server shut down")

    async def restart(self) -> None:
        """Restart the LSP server (e.g., after lake build)."""
        await self.shutdown()
        await self.start()

    # -----------------------------------------------------------------
    # High-level Lean LSP operations
    # -----------------------------------------------------------------

    async def get_goal(
        self,
        file_path: Path | str,
        line: int,
        character: int | None = None,
    ) -> dict[str, Any]:
        """Get proof goal state at a position.

        Args:
            file_path: Path to the .lean file
            line: 1-indexed line number
            character: 1-indexed column (None = query both line start and end)

        Returns:
            dict with 'goals' or 'goals_before'/'goals_after' if character is None
        """
        file_path = Path(file_path).resolve()
        await self._ensure_file_open(file_path)

        uri = path_to_uri(file_path)
        # Convert to 0-indexed for LSP
        lsp_line = line - 1

        if character is not None:
            lsp_char = character - 1
            result = await self._plain_goal(uri, lsp_line, lsp_char)
            return {"goals": result}
        else:
            # Query at line start (goals_before) and line end (goals_after)
            goals_before = await self._plain_goal(uri, lsp_line, 0)
            # Get line length for end position
            content = self.file_manager.open_files.get(uri)
            if content:
                lines = content.content.split("\n")
                if lsp_line < len(lines):
                    end_char = len(lines[lsp_line])
                else:
                    end_char = 0
            else:
                end_char = 999
            goals_after = await self._plain_goal(uri, lsp_line, end_char)
            return {
                "goals_before": goals_before,
                "goals_after": goals_after,
            }

    async def get_term_goal(
        self,
        file_path: Path | str,
        line: int,
        character: int | None = None,
    ) -> dict[str, Any] | None:
        """Get expected type at a position via $/lean/plainTermGoal."""
        file_path = Path(file_path).resolve()
        await self._ensure_file_open(file_path)

        uri = path_to_uri(file_path)
        lsp_line = line - 1
        lsp_char = (character - 1) if character is not None else 0

        result = await self.transport.send_request(
            "$/lean/plainTermGoal",
            {
                "textDocument": {"uri": uri},
                "position": {"line": lsp_line, "character": lsp_char},
            },
            timeout=self._request_timeout,
        )

        if result is None:
            return None

        goal = PlainTermGoal.from_dict(result)
        return {"goal": goal.goal if goal else ""} if goal else None

    async def get_diagnostics(
        self,
        file_path: Path | str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get diagnostics for a file, optionally filtered by line range.

        Args:
            file_path: Path to the .lean file
            start_line: 1-indexed start line (inclusive, optional)
            end_line: 1-indexed end line (inclusive, optional)

        Returns:
            List of diagnostic dicts with severity, range, message.
        """
        file_path = Path(file_path).resolve()
        await self._ensure_file_open(file_path)

        # Wait for diagnostics to arrive
        diagnostics = await self.file_manager.wait_for_diagnostics(
            file_path, timeout=self._file_check_timeout
        )

        # Filter by line range if specified
        if start_line is not None or end_line is not None:
            filtered = []
            for d in diagnostics:
                diag_start = d.range.start.line + 1  # Convert to 1-indexed
                diag_end = d.range.end.line + 1
                if start_line is not None and diag_end < start_line:
                    continue
                if end_line is not None and diag_start > end_line:
                    continue
                filtered.append(d)
            diagnostics = filtered

        return [d.to_dict() for d in diagnostics]

    async def get_hover(
        self,
        file_path: Path | str,
        line: int,
        character: int,
    ) -> dict[str, Any] | None:
        """Get hover information at a position."""
        file_path = Path(file_path).resolve()
        await self._ensure_file_open(file_path)

        uri = path_to_uri(file_path)
        result = await self.transport.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
            },
            timeout=self._request_timeout,
        )

        return result

    async def get_completions(
        self,
        file_path: Path | str,
        line: int,
        character: int,
    ) -> list[dict[str, Any]]:
        """Get IDE completions at a position."""
        file_path = Path(file_path).resolve()
        await self._ensure_file_open(file_path)

        uri = path_to_uri(file_path)
        result = await self.transport.send_request(
            "textDocument/completion",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
            },
            timeout=self._request_timeout,
        )

        if result is None:
            return []
        # LSP completion can return CompletionList or CompletionItem[]
        if isinstance(result, dict):
            return result.get("items", [])
        return result

    async def get_definition(
        self,
        file_path: Path | str,
        line: int,
        character: int,
    ) -> list[dict[str, Any]]:
        """Get definition location for a symbol."""
        file_path = Path(file_path).resolve()
        await self._ensure_file_open(file_path)

        uri = path_to_uri(file_path)
        result = await self.transport.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
            },
            timeout=self._request_timeout,
        )

        if result is None:
            return []
        if isinstance(result, dict):
            return [result]
        return result

    async def get_document_symbols(
        self,
        file_path: Path | str,
    ) -> list[dict[str, Any]]:
        """Get document symbols (outline) for a file."""
        file_path = Path(file_path).resolve()
        await self._ensure_file_open(file_path)

        uri = path_to_uri(file_path)
        result = await self.transport.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
            timeout=self._request_timeout,
        )

        return result if result else []

    async def try_tactics(
        self,
        file_path: Path | str,
        line: int,
        column: int | None = None,
        tactics: list[str] | None = None,
    ) -> list[TacticResult]:
        """Try multiple tactics at a position via $/lean/tryTactics.

        Requires a modified Lean binary with the tryTactics endpoint.

        Args:
            file_path: Path to the .lean file (must already contain a tactic hole).
            line: 1-indexed line number where goals exist.
            column: 1-indexed column (defaults to line start).
            tactics: Tactic strings to try in parallel.

        Returns:
            List of TacticResult with goals or error for each tactic.
        """
        file_path = Path(file_path).resolve()
        await self._ensure_file_open(file_path)

        uri = path_to_uri(file_path)
        lsp_line = line - 1
        lsp_char = (column - 1) if column is not None else 0

        result = await self.transport.send_request(
            "$/lean/tryTactics",
            {
                "textDocument": {"uri": uri},
                "position": {"line": lsp_line, "character": lsp_char},
                "tactics": tactics or [],
            },
            timeout=self._request_timeout,
        )

        if not result:
            return []
        return [TacticResult.from_dict(r) for r in result]

    # -----------------------------------------------------------------
    # Temp file operations (for run_code / multi_attempt)
    # -----------------------------------------------------------------

    async def check_temp_content(
        self,
        content: str,
        temp_name: str = "LeanToolsMcpTemp.lean",
    ) -> list[dict[str, Any]]:
        """Open a virtual file with the given content and return diagnostics.

        Used for lean_run_code and lean_multi_attempt — avoids subprocess.
        Temp files are NOT deleted — kept for inspection.
        """
        temp_path = self._project_root / ".lake" / "lean_tools_mcp" / temp_name
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(content, encoding="utf-8")

        try:
            of = await self.file_manager.open_file(temp_path, content=content)
            diagnostics = await self.file_manager.wait_for_diagnostics(
                temp_path, timeout=self._file_check_timeout
            )
            return [d.to_dict() for d in diagnostics]
        finally:
            await self.file_manager.close_file(temp_path)
            # NOTE: temp file is intentionally kept for manual inspection.

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    async def _initialize(self) -> None:
        """Perform the LSP initialize / initialized handshake."""
        result = await self.transport.send_request(
            "initialize",
            {
                "processId": None,
                "rootUri": self._project_root.as_uri(),
                "capabilities": {
                    "textDocument": {
                        "hover": {"contentFormat": ["markdown", "plaintext"]},
                        "completion": {
                            "completionItem": {"snippetSupport": False},
                        },
                        "publishDiagnostics": {},
                        "synchronization": {
                            "didSave": True,
                            "willSave": False,
                        },
                    },
                },
                "initializationOptions": {},
            },
            timeout=30.0,
        )
        logger.debug("LSP initialize response: %s", result)

        await self.transport.send_notification("initialized", {})

    async def _ensure_file_open(self, file_path: Path) -> None:
        """Ensure a file is open in the LSP server."""
        uri = path_to_uri(file_path)
        if uri not in self.file_manager.open_files:
            await self.file_manager.open_file(file_path)

    async def _plain_goal(
        self,
        uri: str,
        line: int,
        character: int,
    ) -> str:
        """Send $/lean/plainGoal request and return formatted goal string."""
        try:
            result = await self.transport.send_request(
                "$/lean/plainGoal",
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": character},
                },
                timeout=self._request_timeout,
            )
        except LSPProtocolError:
            return "no goals"

        if result is None:
            return "no goals"

        goal = PlainGoal.from_dict(result)
        if goal is None:
            return "no goals"

        return goal.rendered or "\n".join(goal.goals) or "no goals"

    def _on_file_progress(self, params: dict[str, Any] | None) -> None:
        """Handle $/lean/fileProgress notifications.

        When processing list becomes empty, the file is fully checked.
        At that point, signal diagnostics_ready so waiters can proceed.
        """
        if params is None:
            return
        uri = params.get("textDocument", {}).get("uri", "")
        processing = params.get("processing", [])
        self._file_progress[uri] = processing

        # When processing list is empty, the file is fully checked
        if not processing:
            of = self.file_manager.open_files.get(uri)
            if of:
                of.is_checked = True
                of.diagnostics_ready.set()
                logger.debug("File fully checked: %s (diags=%d)", uri, len(of.diagnostics))
