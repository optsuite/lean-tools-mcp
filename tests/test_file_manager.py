"""
Unit tests for the FileManager.

Tests the file lifecycle (open/change/close) and diagnostics caching
using a mock transport — no Lean dependency.
"""

from __future__ import annotations

import asyncio

import pytest

from lean_tools_mcp.lsp.file_manager import FileManager, path_to_uri, uri_to_path
from lean_tools_mcp.lsp.protocol import JsonRpcTransport


class TestPathConversions:
    def test_path_to_uri(self):
        uri = path_to_uri("/tmp/test.lean")
        assert uri.startswith("file:///")
        assert "test.lean" in uri

    def test_uri_to_path(self):
        p = uri_to_path("file:///tmp/test.lean")
        assert str(p) == "/tmp/test.lean"

    def test_roundtrip(self, tmp_path):
        original = tmp_path / "hello.lean"
        uri = path_to_uri(original)
        recovered = uri_to_path(uri)
        assert recovered.resolve() == original.resolve()


class TestFileManager:
    """Test FileManager with a mock transport."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport that records sent notifications."""

        class MockTransport:
            def __init__(self):
                self.notifications: list[tuple[str, dict]] = []
                self._handlers: dict[str, list] = {}

            def on_notification(self, method: str, handler):
                self._handlers.setdefault(method, []).append(handler)

            async def send_notification(self, method: str, params=None):
                self.notifications.append((method, params or {}))

            def inject_notification(self, method: str, params: dict):
                """Simulate receiving a notification from the server."""
                for handler in self._handlers.get(method, []):
                    handler(params)

        return MockTransport()

    @pytest.mark.asyncio
    async def test_open_file(self, mock_transport, tmp_path):
        lean_file = tmp_path / "test.lean"
        lean_file.write_text("def hello := 42")

        fm = FileManager(mock_transport)
        of = await fm.open_file(lean_file)

        assert of.uri == path_to_uri(lean_file)
        assert of.version == 1
        assert of.content == "def hello := 42"

        # Check that didOpen was sent
        assert len(mock_transport.notifications) == 1
        method, params = mock_transport.notifications[0]
        assert method == "textDocument/didOpen"
        assert params["textDocument"]["languageId"] == "lean4"

    @pytest.mark.asyncio
    async def test_open_same_file_twice(self, mock_transport, tmp_path):
        lean_file = tmp_path / "test.lean"
        lean_file.write_text("def x := 1")

        fm = FileManager(mock_transport)
        of1 = await fm.open_file(lean_file)
        of2 = await fm.open_file(lean_file)

        assert of1 is of2
        # didOpen should only be sent once
        assert len(mock_transport.notifications) == 1

    @pytest.mark.asyncio
    async def test_change_file(self, mock_transport, tmp_path):
        lean_file = tmp_path / "test.lean"
        lean_file.write_text("def x := 1")

        fm = FileManager(mock_transport)
        await fm.open_file(lean_file)
        of = await fm.change_file(lean_file, "def x := 2")

        assert of.version == 2
        assert of.content == "def x := 2"
        assert not of.diagnostics_ready.is_set()

        # didOpen + didChange = 2 notifications
        assert len(mock_transport.notifications) == 2

    @pytest.mark.asyncio
    async def test_close_file(self, mock_transport, tmp_path):
        lean_file = tmp_path / "test.lean"
        lean_file.write_text("def x := 1")

        fm = FileManager(mock_transport)
        await fm.open_file(lean_file)
        await fm.close_file(lean_file)

        assert path_to_uri(lean_file) not in fm.open_files

        # didOpen + didClose = 2 notifications
        assert len(mock_transport.notifications) == 2

    @pytest.mark.asyncio
    async def test_diagnostics_notification(self, mock_transport, tmp_path):
        lean_file = tmp_path / "test.lean"
        lean_file.write_text("def x := sorry")

        fm = FileManager(mock_transport)
        await fm.open_file(lean_file)

        uri = path_to_uri(lean_file)
        of = fm.open_files[uri]

        # Simulate the server sending publishDiagnostics
        mock_transport.inject_notification(
            "textDocument/publishDiagnostics",
            {
                "uri": uri,
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 9},
                            "end": {"line": 0, "character": 14},
                        },
                        "message": "declaration uses 'sorry'",
                        "severity": 2,
                        "source": "lean4",
                    }
                ],
            },
        )

        # Diagnostics should be cached
        diags = fm.get_diagnostics(lean_file)
        assert len(diags) == 1
        assert "sorry" in diags[0].message

        # diagnostics_ready is NOT set yet — waiting for fileProgress
        assert not of.diagnostics_ready.is_set()

        # Simulate fileProgress indicating processing is complete
        of.is_checked = True
        of.diagnostics_ready.set()

        assert of.diagnostics_ready.is_set()
