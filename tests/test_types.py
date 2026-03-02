# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for LSP type definitions.

No Lean dependency — pure data structure tests.
"""

from __future__ import annotations

from lean_tools_mcp.lsp.types import (
    Diagnostic,
    DiagnosticSeverity,
    PlainGoal,
    PlainTermGoal,
    Position,
    Range,
    TextDocumentItem,
)


class TestPosition:
    def test_to_dict(self):
        p = Position(line=5, character=10)
        assert p.to_dict() == {"line": 5, "character": 10}

    def test_from_dict(self):
        p = Position.from_dict({"line": 3, "character": 7})
        assert p.line == 3
        assert p.character == 7


class TestRange:
    def test_roundtrip(self):
        r = Range(
            start=Position(line=0, character=0),
            end=Position(line=10, character=5),
        )
        d = r.to_dict()
        r2 = Range.from_dict(d)
        assert r2.start.line == 0
        assert r2.end.line == 10


class TestDiagnostic:
    def test_from_dict_error(self):
        d = Diagnostic.from_dict(
            {
                "range": {
                    "start": {"line": 5, "character": 0},
                    "end": {"line": 5, "character": 10},
                },
                "message": "unknown identifier 'foo'",
                "severity": 1,
                "source": "lean4",
            }
        )
        assert d.severity == DiagnosticSeverity.ERROR
        assert "foo" in d.message
        assert d.range.start.line == 5

    def test_from_dict_warning(self):
        d = Diagnostic.from_dict(
            {
                "range": {
                    "start": {"line": 10, "character": 2},
                    "end": {"line": 10, "character": 7},
                },
                "message": "declaration uses 'sorry'",
                "severity": 2,
            }
        )
        assert d.severity == DiagnosticSeverity.WARNING

    def test_to_dict_roundtrip(self):
        original = {
            "range": {
                "start": {"line": 1, "character": 0},
                "end": {"line": 1, "character": 5},
            },
            "message": "test error",
            "severity": 1,
            "source": "lean4",
        }
        d = Diagnostic.from_dict(original)
        result = d.to_dict()
        assert result["message"] == "test error"
        assert result["severity"] == 1

    def test_full_range(self):
        d = Diagnostic.from_dict(
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 5},
                },
                "message": "msg",
                "fullRange": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 10, "character": 0},
                },
            }
        )
        assert d.full_range is not None
        assert d.full_range.end.line == 10


class TestPlainGoal:
    def test_from_dict(self):
        g = PlainGoal.from_dict(
            {
                "rendered": "⊢ 1 + 1 = 2",
                "goals": ["⊢ 1 + 1 = 2"],
            }
        )
        assert g is not None
        assert g.rendered == "⊢ 1 + 1 = 2"
        assert len(g.goals) == 1

    def test_from_none(self):
        g = PlainGoal.from_dict(None)
        assert g is None


class TestPlainTermGoal:
    def test_from_dict(self):
        g = PlainTermGoal.from_dict(
            {
                "goal": "Nat → Nat",
                "range": {
                    "start": {"line": 5, "character": 0},
                    "end": {"line": 5, "character": 3},
                },
            }
        )
        assert g is not None
        assert g.goal == "Nat → Nat"
        assert g.range is not None


class TestTextDocumentItem:
    def test_to_dict(self):
        item = TextDocumentItem(
            uri="file:///test.lean",
            language_id="lean4",
            version=1,
            text="def hello := 42",
        )
        d = item.to_dict()
        assert d["uri"] == "file:///test.lean"
        assert d["languageId"] == "lean4"
        assert d["version"] == 1
