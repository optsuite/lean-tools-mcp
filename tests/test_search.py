# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for search tools and clients (no network dependency).

Tests formatting functions and result structure.
For actual API integration tests, see test_integration.py.
"""

from __future__ import annotations

from lean_tools_mcp.clients.search import SearchResponse, SearchResult
from lean_tools_mcp.tools.search import (
    _format_error,
    _format_premise_results,
    _format_search_results,
)


class TestFormatSearchResults:
    """Test search result formatting."""

    def test_empty_results(self):
        """No results -> appropriate message."""
        result = _format_search_results([])
        assert "No results" in result

    def test_single_result(self):
        """Single result with all fields."""
        results = [
            SearchResult(
                name="Nat.add_comm",
                type="∀ (n m : ℕ), n + m = m + n",
                doc="Commutativity of addition.",
                module="Init.Data.Nat.Basic",
                kind="theorem",
            )
        ]
        output = _format_search_results(results, include_module=True)
        assert "Nat.add_comm" in output
        assert "n + m = m + n" in output
        assert "Commutativity" in output
        assert "Init.Data.Nat" in output
        assert "theorem" in output

    def test_multiple_results_numbered(self):
        """Multiple results are numbered."""
        results = [
            SearchResult(name="Foo", type="Type"),
            SearchResult(name="Bar", type="Type"),
            SearchResult(name="Baz", type="Type"),
        ]
        output = _format_search_results(results)
        assert "1. Foo" in output
        assert "2. Bar" in output
        assert "3. Baz" in output

    def test_long_doc_truncated(self):
        """Long doc strings are truncated."""
        results = [
            SearchResult(name="X", doc="A" * 300),
        ]
        output = _format_search_results(results)
        assert "..." in output

    def test_exclude_type(self):
        """Type can be excluded from output."""
        results = [
            SearchResult(name="Foo", type="some_type"),
        ]
        output = _format_search_results(results, include_type=False)
        assert "some_type" not in output

    def test_exclude_doc(self):
        """Doc can be excluded from output."""
        results = [
            SearchResult(name="Foo", doc="some_doc"),
        ]
        output = _format_search_results(results, include_doc=False)
        assert "some_doc" not in output


class TestFormatPremiseResults:
    """Test premise result formatting."""

    def test_empty_premises(self):
        """No premises -> appropriate message."""
        result = _format_premise_results([])
        assert "No premises" in result

    def test_premise_list(self):
        """Premises are listed with simp hint."""
        results = [
            SearchResult(name="Nat.add_zero"),
            SearchResult(name="Nat.zero_add"),
            SearchResult(name="Nat.add_comm"),
        ]
        output = _format_premise_results(results)
        assert "3 premise" in output
        assert "Nat.add_zero" in output
        assert "Nat.zero_add" in output
        assert "Nat.add_comm" in output
        assert "simp only" in output


class TestFormatError:
    """Test error formatting."""

    def test_format_error(self):
        response = SearchResponse(error="timed out")
        output = _format_error(response, "LeanSearch")
        assert "LeanSearch" in output
        assert "timed out" in output


class TestSearchResult:
    """Test SearchResult dataclass."""

    def test_defaults(self):
        """Default values for optional fields."""
        r = SearchResult(name="test")
        assert r.name == "test"
        assert r.type == ""
        assert r.doc == ""
        assert r.module == ""
        assert r.kind == ""

    def test_all_fields(self):
        r = SearchResult(
            name="Foo",
            type="Type",
            doc="A doc",
            module="Mod",
            kind="theorem",
        )
        assert r.name == "Foo"
        assert r.kind == "theorem"
