# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for lean_hover_info tool.

No Lean dependency — tests the formatting logic.
"""

from __future__ import annotations

from lean_tools_mcp.tools.hover import _extract_hover_content, _format_hover_with_range


class TestExtractHoverContent:
    def test_none_result(self):
        assert "No hover" in _extract_hover_content(None)

    def test_none_contents(self):
        assert "No hover" in _extract_hover_content({"contents": None})

    def test_markup_content(self):
        result = {
            "contents": {
                "kind": "markdown",
                "value": "```lean\nNat.add : Nat → Nat → Nat\n```",
            }
        }
        text = _extract_hover_content(result)
        assert "Nat.add" in text
        assert "Nat → Nat → Nat" in text

    def test_plain_string_contents(self):
        result = {"contents": "def hello : Nat"}
        text = _extract_hover_content(result)
        assert "hello" in text

    def test_marked_string_list(self):
        result = {
            "contents": [
                {"language": "lean", "value": "Nat.succ : Nat → Nat"},
                "Successor function",
            ]
        }
        text = _extract_hover_content(result)
        assert "Nat.succ" in text
        assert "Successor" in text


class TestFormatHoverWithRange:
    def test_with_range(self):
        result = {
            "contents": {"kind": "markdown", "value": "Nat"},
            "range": {
                "start": {"line": 4, "character": 5},
                "end": {"line": 4, "character": 8},
            },
        }
        text = _format_hover_with_range(result)
        assert "Nat" in text
        assert "5:6" in text  # 0-indexed -> 1-indexed

    def test_without_range(self):
        result = {"contents": {"kind": "markdown", "value": "Bool"}}
        text = _format_hover_with_range(result)
        assert "Bool" in text
        assert "range" not in text.lower()
