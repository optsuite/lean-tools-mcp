# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for lean_code_actions and LSP code-action plumbing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lean_tools_mcp.lsp.client import LSPClient
from lean_tools_mcp.lsp.types import Diagnostic, DiagnosticSeverity, Position, Range
from lean_tools_mcp.tools.code_actions import _format_code_actions, lean_code_actions


class DummyTransport:
    def __init__(self):
        self.calls: list[tuple[str, dict, float]] = []

    async def send_request(self, method, params, timeout=60.0):
        self.calls.append((method, params, timeout))
        return [{"title": "Use simp", "kind": "quickfix"}]


class DummyFileManager:
    def __init__(self, diagnostics):
        self._diagnostics = diagnostics
        self.open_files = {}

    async def wait_for_diagnostics(self, file_path, timeout):
        return self._diagnostics


@pytest.mark.asyncio
async def test_get_code_actions_sends_text_document_code_action(tmp_path: Path):
    matching = Diagnostic(
        range=Range(
            start=Position(line=9, character=4),
            end=Position(line=9, character=8),
        ),
        message="try simp",
        severity=DiagnosticSeverity.WARNING,
    )
    non_matching = Diagnostic(
        range=Range(
            start=Position(line=1, character=0),
            end=Position(line=1, character=2),
        ),
        message="unrelated",
        severity=DiagnosticSeverity.INFORMATION,
    )

    client = LSPClient(project_root=tmp_path)
    client._transport = DummyTransport()
    client._file_manager = DummyFileManager([matching, non_matching])
    client._initialized = True
    client._ensure_file_open = AsyncMock()

    result = await client.get_code_actions(
        tmp_path / "Foo.lean",
        line=10,
        character=5,
        end_line=10,
        end_character=9,
    )

    assert result == [{"title": "Use simp", "kind": "quickfix"}]
    method, params, _timeout = client.transport.calls[0]
    assert method == "textDocument/codeAction"
    assert params["range"]["start"] == {"line": 9, "character": 4}
    assert params["range"]["end"] == {"line": 9, "character": 8}
    assert len(params["context"]["diagnostics"]) == 1
    assert params["context"]["diagnostics"][0]["message"] == "try simp"


def test_format_code_actions_empty():
    assert "No code actions" in _format_code_actions([], max_actions=20)


def test_format_code_actions_truncates():
    text = _format_code_actions(
        [
            {"title": "Action 1", "kind": "quickfix"},
            {"title": "Action 2", "kind": "refactor"},
        ],
        max_actions=1,
    )
    assert "Action 1" in text
    assert "Action 2" not in text
    assert "omitted" in text


@pytest.mark.asyncio
async def test_lean_code_actions_wrapper_formats_manager_result():
    manager = AsyncMock()
    manager.code_actions.return_value = [
        {"title": "Use simp", "kind": "quickfix", "isPreferred": True}
    ]

    text = await lean_code_actions(
        manager,
        file_path="/tmp/Foo.lean",
        line=10,
        column=5,
        max_actions=5,
    )

    assert "Use simp" in text
    assert "quickfix" in text
    manager.code_actions.assert_awaited_once()
