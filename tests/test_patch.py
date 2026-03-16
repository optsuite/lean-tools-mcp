# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for lean_apply_patch tool.

No Lean dependency — tests file editing logic only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lean_tools_mcp.tools.patch import (
    PatchError,
    _apply_line_patch,
    _apply_search_patch,
    lean_apply_patch,
)


SAMPLE = "line1\nline2\nline3\nline4\nline5\n"


# ---------------------------------------------------------------------------
# Low-level: _apply_line_patch
# ---------------------------------------------------------------------------


class TestApplyLinePatch:
    def test_replace_single_line(self):
        result, s, e = _apply_line_patch(SAMPLE, "REPLACED", 2, 2)
        lines = result.split("\n")
        assert lines[1] == "REPLACED"
        assert lines[0] == "line1"
        assert lines[2] == "line3"

    def test_replace_range(self):
        result, s, e = _apply_line_patch(SAMPLE, "A\nB", 2, 4)
        lines = result.split("\n")
        assert lines[0] == "line1"
        assert lines[1] == "A"
        assert lines[2] == "B"
        assert lines[3] == "line5"

    def test_delete_line(self):
        result, s, e = _apply_line_patch(SAMPLE, "", 3, 3)
        assert "line3" not in result
        assert "line2" in result
        assert "line4" in result

    def test_insert_multiple_lines(self):
        result, s, e = _apply_line_patch(SAMPLE, "new1\nnew2\nnew3", 2, 2)
        lines = result.split("\n")
        assert lines[1] == "new1"
        assert lines[2] == "new2"
        assert lines[3] == "new3"
        assert lines[4] == "line3"

    def test_replace_first_line(self):
        result, s, e = _apply_line_patch(SAMPLE, "FIRST", 1, 1)
        assert result.startswith("FIRST\n")

    def test_replace_last_line(self):
        result, s, e = _apply_line_patch(SAMPLE, "LAST", 5, 5)
        lines = result.split("\n")
        assert lines[4] == "LAST"

    def test_invalid_range(self):
        with pytest.raises(PatchError, match="start_line.*end_line"):
            _apply_line_patch(SAMPLE, "x", 3, 2)

    def test_out_of_range(self):
        with pytest.raises(PatchError, match="exceeds"):
            _apply_line_patch(SAMPLE, "x", 100, 100)

    def test_zero_line(self):
        with pytest.raises(PatchError, match=">= 1"):
            _apply_line_patch(SAMPLE, "x", 0, 1)


# ---------------------------------------------------------------------------
# Low-level: _apply_search_patch
# ---------------------------------------------------------------------------


class TestApplySearchPatch:
    def test_simple_replace(self):
        result, s, e = _apply_search_patch(SAMPLE, "REPLACED", "line3", 1)
        assert "REPLACED" in result
        assert "line3" not in result

    def test_replace_second_occurrence(self):
        content = "aaa bbb aaa bbb aaa"
        result, s, e = _apply_search_patch(content, "XXX", "aaa", 2)
        assert result == "aaa bbb XXX bbb aaa"

    def test_replace_third_occurrence(self):
        content = "aaa bbb aaa bbb aaa"
        result, s, e = _apply_search_patch(content, "XXX", "aaa", 3)
        assert result == "aaa bbb aaa bbb XXX"

    def test_not_found(self):
        with pytest.raises(PatchError, match="not found"):
            _apply_search_patch(SAMPLE, "x", "nonexistent", 1)

    def test_occurrence_too_large(self):
        with pytest.raises(PatchError, match="occurrence"):
            _apply_search_patch(SAMPLE, "x", "line1", 2)

    def test_multiline_search(self):
        result, s, e = _apply_search_patch(SAMPLE, "A\nB", "line2\nline3", 1)
        assert "A\nB" in result
        assert "line2\nline3" not in result

    def test_replace_with_empty(self):
        result, s, e = _apply_search_patch(SAMPLE, "", "line3\n", 1)
        assert "line3" not in result


# ---------------------------------------------------------------------------
# High-level: lean_apply_patch (async)
# ---------------------------------------------------------------------------


class TestLeanApplyPatch:
    @pytest.mark.asyncio
    async def test_line_mode(self, tmp_path: Path):
        f = tmp_path / "test.lean"
        f.write_text("def a := 1\ndef b := 2\ndef c := 3\n")

        result = await lean_apply_patch(
            str(f), new_content="def b := 42", start_line=2, end_line=2
        )
        assert "Patch applied" in result
        assert "def b := 42" in f.read_text()

    @pytest.mark.asyncio
    async def test_search_mode(self, tmp_path: Path):
        f = tmp_path / "test.lean"
        f.write_text("theorem t : 1 = 1 := by\n  sorry\n")

        result = await lean_apply_patch(
            str(f), new_content="  rfl", search="  sorry"
        )
        assert "Patch applied" in result
        content = f.read_text()
        assert "rfl" in content
        assert "sorry" not in content

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        result = await lean_apply_patch(
            "/nonexistent/file.lean", new_content="x", start_line=1, end_line=1
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_not_lean_file(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")

        result = await lean_apply_patch(
            str(f), new_content="x", start_line=1, end_line=1
        )
        assert "not a .lean file" in result

    @pytest.mark.asyncio
    async def test_both_modes_error(self, tmp_path: Path):
        f = tmp_path / "test.lean"
        f.write_text("x\n")

        result = await lean_apply_patch(
            str(f), new_content="y", start_line=1, end_line=1, search="x"
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_neither_mode_error(self, tmp_path: Path):
        f = tmp_path / "test.lean"
        f.write_text("x\n")

        result = await lean_apply_patch(str(f), new_content="y")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_context_lines(self, tmp_path: Path):
        f = tmp_path / "test.lean"
        lines = [f"line{i}" for i in range(1, 21)]
        f.write_text("\n".join(lines) + "\n")

        result = await lean_apply_patch(
            str(f), new_content="EDITED", start_line=10, end_line=10, context_lines=2
        )
        assert "EDITED" in result
        assert "line8" in result   # 2 lines before
        assert "line12" in result  # 2 lines after

    @pytest.mark.asyncio
    async def test_replace_sorry_with_tactic(self, tmp_path: Path):
        """Realistic use case: replace sorry with actual proof."""
        f = tmp_path / "test.lean"
        f.write_text(
            "import Mathlib\n\n"
            "theorem test_thm : 1 + 1 = 2 := by\n"
            "  sorry\n"
        )

        result = await lean_apply_patch(
            str(f), new_content="  norm_num", search="  sorry"
        )
        assert "Patch applied" in result
        content = f.read_text()
        assert "norm_num" in content
        assert "sorry" not in content

    @pytest.mark.asyncio
    async def test_multiline_replace(self, tmp_path: Path):
        """Replace multiple lines of tactics."""
        f = tmp_path / "test.lean"
        f.write_text(
            "theorem t : True ∧ True := by\n"
            "  constructor\n"
            "  sorry\n"
            "  sorry\n"
        )

        result = await lean_apply_patch(
            str(f),
            new_content="  constructor\n  · trivial\n  · trivial",
            start_line=2, end_line=4,
        )
        assert "Patch applied" in result
        content = f.read_text()
        assert "trivial" in content
        assert "sorry" not in content
