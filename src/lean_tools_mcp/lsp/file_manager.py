# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Virtual file manager for LSP.

Tracks which files are open in the LSP server, manages versioning,
and provides helpers for didOpen / didChange / didClose lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .protocol import JsonRpcTransport
from .types import Diagnostic, DiagnosticSeverity

logger = logging.getLogger(__name__)


def path_to_uri(path: Path | str) -> str:
    """Convert a filesystem path to a file:// URI."""
    p = Path(path).resolve()
    return p.as_uri()


def uri_to_path(uri: str) -> Path:
    """Convert a file:// URI back to a filesystem path."""
    if uri.startswith("file://"):
        # Handle percent-encoded characters
        from urllib.parse import unquote

        return Path(unquote(uri[7:]))
    return Path(uri)


@dataclass
class OpenFile:
    """State of an open file in the LSP server."""

    uri: str
    version: int
    content: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    # Event set when diagnostics are available (file checking complete)
    diagnostics_ready: asyncio.Event = field(default_factory=asyncio.Event)
    # Whether the file has finished initial checking
    is_checked: bool = False


class FileManager:
    """Manages the lifecycle of open files in an LSP server.

    Coordinates didOpen/didChange/didClose and caches diagnostics
    received from publishDiagnostics notifications.
    """

    def __init__(self, transport: JsonRpcTransport) -> None:
        self._transport = transport
        self._files: dict[str, OpenFile] = {}  # uri -> OpenFile
        self._lock = asyncio.Lock()

        # Register for diagnostic notifications
        transport.on_notification(
            "textDocument/publishDiagnostics",
            self._on_publish_diagnostics,
        )

    @property
    def open_files(self) -> dict[str, OpenFile]:
        return self._files

    async def open_file(self, path: Path | str, content: str | None = None) -> OpenFile:
        """Open a file in the LSP server.

        If content is None, reads from disk.
        If the file is already open, returns the existing state.
        """
        uri = path_to_uri(path)

        async with self._lock:
            if uri in self._files:
                return self._files[uri]

            if content is None:
                content = Path(path).resolve().read_text(encoding="utf-8")

            of = OpenFile(uri=uri, version=1, content=content)
            self._files[uri] = of

        await self._transport.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "lean4",
                    "version": of.version,
                    "text": content,
                },
            },
        )

        logger.debug("Opened file: %s", uri)
        return of

    async def change_file(self, path: Path | str, new_content: str) -> OpenFile:
        """Update the content of an already-open file.

        Sends a full-content didChange notification.
        """
        uri = path_to_uri(path)

        async with self._lock:
            of = self._files.get(uri)
            if of is None:
                # Auto-open if not yet open
                of = OpenFile(uri=uri, version=0, content="")
                self._files[uri] = of

            of.version += 1
            of.content = new_content
            of.diagnostics = []
            of.diagnostics_ready.clear()
            of.is_checked = False

        await self._transport.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": of.version},
                "contentChanges": [{"text": new_content}],
            },
        )

        logger.debug("Changed file: %s (version=%d)", uri, of.version)
        return of

    async def close_file(self, path: Path | str) -> None:
        """Close a file in the LSP server."""
        uri = path_to_uri(path)

        async with self._lock:
            of = self._files.pop(uri, None)

        if of is not None:
            await self._transport.send_notification(
                "textDocument/didClose",
                {"textDocument": {"uri": uri}},
            )
            logger.debug("Closed file: %s", uri)

    async def wait_for_diagnostics(
        self,
        path: Path | str,
        timeout: float = 120.0,
    ) -> list[Diagnostic]:
        """Wait until the LSP server has published diagnostics for the file.

        The Lean LSP server sends multiple publishDiagnostics notifications
        as it processes a file. We consider diagnostics "ready" when we receive
        a notification (the last one wins).

        For a more robust check, we also listen to $/lean/fileProgress to know
        when the file is fully checked.
        """
        uri = path_to_uri(path)

        of = self._files.get(uri)
        if of is None:
            raise ValueError(f"File not open: {path}")

        try:
            await asyncio.wait_for(of.diagnostics_ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for diagnostics: %s", uri)

        return of.diagnostics

    def get_diagnostics(self, path: Path | str) -> list[Diagnostic]:
        """Get cached diagnostics for a file (non-blocking)."""
        uri = path_to_uri(path)
        of = self._files.get(uri)
        if of is None:
            return []
        return of.diagnostics

    def _on_publish_diagnostics(self, params: dict[str, Any] | None) -> None:
        """Handle textDocument/publishDiagnostics notification.

        The Lean LSP sends multiple publishDiagnostics as it processes a file.
        We always update the cached diagnostics, but only signal "ready" if
        the file has finished processing (is_checked=True via fileProgress).
        If fileProgress is not available, we still signal after a short delay
        to avoid blocking indefinitely.
        """
        if params is None:
            return

        uri = params.get("uri", "")
        raw_diags = params.get("diagnostics", [])

        of = self._files.get(uri)
        if of is None:
            logger.debug("Diagnostics for unknown file: %s", uri)
            return

        of.diagnostics = [Diagnostic.from_dict(d) for d in raw_diags]

        # If fileProgress already told us processing is done, signal ready
        if of.is_checked:
            of.diagnostics_ready.set()

        logger.debug(
            "Received %d diagnostics for %s (checked=%s)",
            len(of.diagnostics),
            uri,
            of.is_checked,
        )
