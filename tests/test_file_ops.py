"""
Unit tests for file operation tools.

No Lean dependency — tests formatting and local logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lean_tools_mcp.tools.file_ops import (
    _find_project_root,
    _format_symbol,
    _symbol_kind_name,
    lean_file_contents,
    lean_local_search,
)


class TestSymbolKindName:
    def test_known_kinds(self):
        assert _symbol_kind_name(5) == "class"
        assert _symbol_kind_name(12) == "function"
        assert _symbol_kind_name(14) == "constant"

    def test_unknown_kind(self):
        assert "kind_" in _symbol_kind_name(999)


class TestFormatSymbol:
    def test_basic_symbol(self):
        sym = {
            "name": "Nat.add",
            "kind": 12,
            "detail": "Nat → Nat → Nat",
            "range": {"start": {"line": 10, "character": 0}, "end": {"line": 10, "character": 7}},
        }
        lines = _format_symbol(sym)
        assert len(lines) == 1
        assert "function" in lines[0]
        assert "Nat.add" in lines[0]
        assert "Nat → Nat → Nat" in lines[0]
        assert "line 11" in lines[0]

    def test_nested_symbols(self):
        sym = {
            "name": "MyModule",
            "kind": 2,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 50, "character": 0}},
            "children": [
                {
                    "name": "helper",
                    "kind": 12,
                    "range": {"start": {"line": 5, "character": 0}, "end": {"line": 10, "character": 0}},
                }
            ],
        }
        lines = _format_symbol(sym)
        assert len(lines) == 2
        assert "MyModule" in lines[0]
        assert "  " in lines[1]  # Indented
        assert "helper" in lines[1]


class TestFileContents:
    @pytest.mark.asyncio
    async def test_read_full_file(self, tmp_path: Path):
        lean_file = tmp_path / "test.lean"
        lean_file.write_text("line1\nline2\nline3\n")

        result = await lean_file_contents(str(lean_file))
        assert "1|line1" in result
        assert "2|line2" in result
        assert "3|line3" in result

    @pytest.mark.asyncio
    async def test_read_line_range(self, tmp_path: Path):
        lean_file = tmp_path / "test.lean"
        lean_file.write_text("aaa\nbbb\nccc\nddd\neee\n")

        result = await lean_file_contents(str(lean_file), start_line=2, end_line=4)
        assert "bbb" in result
        assert "ccc" in result
        assert "ddd" in result
        assert "aaa" not in result
        assert "eee" not in result

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        result = await lean_file_contents("/nonexistent/file.lean")
        assert "not found" in result.lower()


class TestFindProjectRoot:
    def test_finds_lakefile(self, tmp_path: Path):
        (tmp_path / "lakefile.lean").touch()
        sub = tmp_path / "src" / "Module"
        sub.mkdir(parents=True)

        root = _find_project_root(sub)
        assert root == tmp_path

    def test_finds_lakefile_toml(self, tmp_path: Path):
        (tmp_path / "lakefile.toml").touch()

        root = _find_project_root(tmp_path)
        assert root == tmp_path

    def test_no_lakefile(self, tmp_path: Path):
        sub = tmp_path / "orphan"
        sub.mkdir()

        root = _find_project_root(sub)
        # May or may not find one depending on parent dirs
        # Just check it doesn't crash


class TestLocalSearch:
    @pytest.mark.asyncio
    async def test_search_finds_declarations(self, tmp_path: Path):
        # Create a mini Lean project
        (tmp_path / "lakefile.lean").write_text('import Lake\nopen Lake DSL\npackage test\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "Main.lean").write_text(
            "def myHelper : Nat := 42\n"
            "theorem myTheorem : 1 = 1 := rfl\n"
            "private def _internal : Bool := true\n"
        )

        result = await lean_local_search(str(src / "Main.lean"), "my")
        assert "myHelper" in result
        assert "myTheorem" in result

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, tmp_path: Path):
        (tmp_path / "lakefile.lean").write_text('import Lake\n')
        src = tmp_path / "src"
        src.mkdir()
        # Create many declarations
        lines = [f"def item{i} : Nat := {i}" for i in range(20)]
        (src / "Many.lean").write_text("\n".join(lines))

        result = await lean_local_search(str(src / "Many.lean"), "item", limit=5)
        assert "5 match" in result

    @pytest.mark.asyncio
    async def test_search_no_matches(self, tmp_path: Path):
        (tmp_path / "lakefile.lean").write_text('import Lake\n')
        (tmp_path / "Main.lean").write_text("def x := 1\n")

        result = await lean_local_search(str(tmp_path / "Main.lean"), "nonexistent")
        assert "No declarations" in result
