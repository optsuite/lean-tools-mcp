"""
Unit tests for unified_search tool (no network dependency).
"""

from __future__ import annotations

from lean_tools_mcp.clients.search import SearchResult
from lean_tools_mcp.tools.unified_search import (
    _deduplicate,
    _format_unified_results,
)


class TestDeduplicate:
    """Test result deduplication."""

    def test_no_duplicates(self):
        results = [
            ("leansearch", SearchResult(name="Foo")),
            ("loogle", SearchResult(name="Bar")),
        ]
        deduped = _deduplicate(results)
        assert len(deduped) == 2

    def test_removes_duplicates(self):
        results = [
            ("leansearch", SearchResult(name="Nat.add_comm", type="type1")),
            ("loogle", SearchResult(name="Nat.add_comm", type="type2")),
            ("leanfinder", SearchResult(name="Nat.add_zero")),
        ]
        deduped = _deduplicate(results)
        assert len(deduped) == 2
        # First occurrence kept
        assert deduped[0][0] == "leansearch"
        assert deduped[0][1].name == "Nat.add_comm"

    def test_empty_names_skipped(self):
        results = [
            ("leansearch", SearchResult(name="")),
            ("loogle", SearchResult(name="Foo")),
        ]
        deduped = _deduplicate(results)
        assert len(deduped) == 1
        assert deduped[0][1].name == "Foo"

    def test_whitespace_normalized(self):
        results = [
            ("leansearch", SearchResult(name="  Foo  ")),
            ("loogle", SearchResult(name="Foo")),
        ]
        deduped = _deduplicate(results)
        assert len(deduped) == 1

    def test_empty_input(self):
        assert _deduplicate([]) == []


class TestFormatUnifiedResults:
    """Test unified result formatting."""

    def test_no_results_no_errors(self):
        output = _format_unified_results([], {})
        assert "No results" in output

    def test_with_results(self):
        results = [
            ("leansearch", SearchResult(name="Foo", type="Type")),
            ("loogle", SearchResult(name="Bar", type="Type")),
        ]
        output = _format_unified_results(results, {})
        assert "2 unique" in output
        assert "[leansearch] Foo" in output
        assert "[loogle] Bar" in output

    def test_with_errors(self):
        results = [
            ("leansearch", SearchResult(name="Foo")),
        ]
        errors = {"loogle": "rate limited"}
        output = _format_unified_results(results, errors)
        assert "loogle" in output
        assert "rate limited" in output
        assert "Foo" in output

    def test_all_errored(self):
        errors = {"leansearch": "timeout", "loogle": "500"}
        output = _format_unified_results([], errors)
        assert "timeout" in output
        assert "No results" in output

    def test_doc_truncated(self):
        results = [
            ("leansearch", SearchResult(name="X", doc="A" * 300)),
        ]
        output = _format_unified_results(results, {})
        assert "..." in output
