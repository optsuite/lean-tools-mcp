"""
Unit tests for lean_multi_attempt tool (no Lean dependency).

Tests the formatting functions and result structure.
"""

from __future__ import annotations

import json

from lean_tools_mcp.tools.multi_attempt import _format_results


class TestFormatResults:
    """Test _format_results output formatting."""

    def test_single_success(self):
        """A single tactic that closes the proof."""
        results = [
            {
                "tactic": "simp",
                "goal_state": "no goals",
                "errors": [],
            }
        ]
        output = _format_results(results)
        assert "1 tactic" in output
        assert "simp" in output
        assert "no goals" in output.lower()
        assert "Proof complete" in output

    def test_single_failure(self):
        """A single tactic with an error."""
        results = [
            {
                "tactic": "ring",
                "goal_state": "",
                "errors": ["tactic 'ring' failed"],
            }
        ]
        output = _format_results(results)
        assert "ring" in output
        assert "Errors" in output
        assert "tactic 'ring' failed" in output

    def test_multiple_attempts(self):
        """Multiple tactics with mixed results."""
        results = [
            {
                "tactic": "simp",
                "goal_state": "⊢ 0 = 0",
                "errors": [],
            },
            {
                "tactic": "ring",
                "goal_state": "no goals",
                "errors": [],
            },
            {
                "tactic": "omega",
                "goal_state": "",
                "errors": ["omega failed"],
            },
        ]
        output = _format_results(results)
        assert "3 tactic" in output
        assert "Attempt 1" in output
        assert "Attempt 2" in output
        assert "Attempt 3" in output
        assert "simp" in output
        assert "ring" in output
        assert "omega" in output

    def test_remaining_goals_shown(self):
        """A tactic that makes progress but doesn't close the proof."""
        results = [
            {
                "tactic": "  intro h",
                "goal_state": "h : Nat\n⊢ h = h",
                "errors": [],
            }
        ]
        output = _format_results(results)
        assert "Remaining goals" in output
        assert "h : Nat" in output
        assert "⊢ h = h" in output

    def test_json_included(self):
        """Raw JSON is included in the output."""
        results = [
            {
                "tactic": "simp",
                "goal_state": "no goals",
                "errors": [],
            }
        ]
        output = _format_results(results)
        assert "Raw JSON" in output
        json_start = output.index("--- Raw JSON ---") + len("--- Raw JSON ---\n")
        json_str = output[json_start:]
        parsed = json.loads(json_str)
        assert len(parsed) == 1
        assert parsed[0]["tactic"] == "simp"

    def test_empty_results(self):
        """No tactics tried."""
        results = []
        output = _format_results(results)
        assert "0 tactic" in output
