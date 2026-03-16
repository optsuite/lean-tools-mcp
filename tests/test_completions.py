# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for lean_completions tool.

No Lean dependency — tests the formatting logic.
"""

from __future__ import annotations

from lean_tools_mcp.tools.completions import _completion_kind_name, _format_completion_item


class TestCompletionKindName:
    def test_known_kinds(self):
        assert _completion_kind_name(3) == "function"
        assert _completion_kind_name(5) == "field"
        assert _completion_kind_name(7) == "class"
        assert _completion_kind_name(12) == "value"

    def test_unknown_kind(self):
        assert _completion_kind_name(999) == ""


class TestFormatCompletionItem:
    def test_basic_item(self):
        item = {"label": "Nat.add", "detail": "Nat → Nat → Nat", "kind": 3}
        text = _format_completion_item(item)
        assert "Nat.add" in text
        assert "Nat → Nat → Nat" in text
        assert "function" in text

    def test_item_without_detail(self):
        item = {"label": "simp", "kind": 14}
        text = _format_completion_item(item)
        assert "simp" in text
        assert "keyword" in text

    def test_item_minimal(self):
        item = {"label": "x"}
        text = _format_completion_item(item)
        assert "x" in text
