# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for lean_run_code tool (no Lean dependency).

Tests the formatting functions and result structure.
"""

from __future__ import annotations

from lean_tools_mcp.tools.run_code import _format_result, _severity_name
from pathlib import Path


class TestSeverityName:
    """Test the severity name helper."""

    def test_error(self):
        assert _severity_name(1) == "error"

    def test_warning(self):
        assert _severity_name(2) == "warning"

    def test_information(self):
        assert _severity_name(3) == "information"

    def test_hint(self):
        assert _severity_name(4) == "hint"

    def test_unknown(self):
        assert _severity_name(99) == "unknown"


class TestFormatResult:
    """Test _format_result output formatting."""

    def test_clean_code(self):
        """No diagnostics -> clean compile message."""
        result = _format_result(
            temp_path=Path("/tmp/test.lean"),
            code="def x : Nat := 42",
            diagnostics=[],
        )
        assert "compiles clean" in result.lower() or "no diagnostics" in result.lower()
        assert "/tmp/test.lean" in result

    def test_with_errors(self):
        """Diagnostics present -> shows errors."""
        diags = [
            {
                "severity": 1,
                "range": {"start": {"line": 0, "character": 10}},
                "message": "type mismatch",
            },
        ]
        result = _format_result(
            temp_path=Path("/tmp/test.lean"),
            code='def x : Nat := "hello"',
            diagnostics=diags,
        )
        assert "error" in result.lower()
        assert "type mismatch" in result
        assert "1 error" in result

    def test_with_warnings(self):
        """Warnings are counted separately from errors."""
        diags = [
            {
                "severity": 2,
                "range": {"start": {"line": 0, "character": 0}},
                "message": "unused variable",
            },
        ]
        result = _format_result(
            temp_path=Path("/tmp/test.lean"),
            code="def x : Nat := 42",
            diagnostics=diags,
        )
        assert "warning" in result.lower()
        assert "0 error" in result
        assert "1 warning" in result

    def test_mixed_diagnostics(self):
        """Mix of errors, warnings, and infos."""
        diags = [
            {
                "severity": 1,
                "range": {"start": {"line": 2, "character": 5}},
                "message": "unknown identifier",
            },
            {
                "severity": 2,
                "range": {"start": {"line": 0, "character": 0}},
                "message": "unused variable",
            },
            {
                "severity": 3,
                "range": {"start": {"line": 1, "character": 0}},
                "message": "Nat : Type",
            },
        ]
        result = _format_result(
            temp_path=Path("/tmp/test.lean"),
            code="-- some code",
            diagnostics=diags,
        )
        assert "1 error" in result
        assert "1 warning" in result
        assert "1 info" in result
        assert "3 total" in result
