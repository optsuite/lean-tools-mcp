# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for lean_build tool formatting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from lean_tools_mcp.project.manager import BuildResult
from lean_tools_mcp.tools.build import _format_build_result, lean_build


def test_format_build_success():
    result = BuildResult(
        success=True,
        returncode=0,
        stdout="ok\n",
        stderr="",
        restarted_lsp=True,
        commands=[["lake", "build"]],
    )

    text = _format_build_result(result, output_lines=20)
    assert "Build succeeded" in text
    assert "LSP pool restarted" in text
    assert "lake build" in text


def test_format_build_failure():
    result = BuildResult(
        success=False,
        returncode=1,
        stdout="",
        stderr="compile failed\nat Foo.lean:10\n",
        restarted_lsp=False,
        commands=[["lake", "build"]],
    )

    text = _format_build_result(result, output_lines=5)
    assert "Build failed" in text
    assert "exit 1" in text
    assert "compile failed" in text


@pytest.mark.asyncio
async def test_lean_build_wrapper_calls_manager():
    manager = AsyncMock()
    manager.build.return_value = BuildResult(
        success=True,
        returncode=0,
        stdout="ok\n",
        stderr="",
        restarted_lsp=True,
        commands=[["lake", "build"]],
    )

    text = await lean_build(manager, target="MyTarget", clean=True, output_lines=10)
    assert "Build succeeded" in text
    manager.build.assert_awaited_once_with(target="MyTarget", clean=True)
