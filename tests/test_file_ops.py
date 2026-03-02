# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for file operation tools.

No Lean dependency — tests formatting and local logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lean_tools_mcp.tools.file_ops import (
    _extract_declarations,
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


class TestExtractDeclarations:
    """Tests for namespace-aware declaration extraction."""

    def test_no_namespace(self):
        content = "def foo : Nat := 1\ntheorem bar : 1 = 1 := rfl\n"
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "foo" in names
        assert "bar" in names

    def test_single_namespace(self):
        content = (
            "namespace MyNS\n"
            "def foo : Nat := 1\n"
            "theorem bar : 1 = 1 := rfl\n"
            "end MyNS\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "MyNS.foo" in names
        assert "MyNS.bar" in names

    def test_nested_namespace(self):
        content = (
            "namespace A\n"
            "namespace B\n"
            "def foo : Nat := 1\n"
            "end B\n"
            "def bar : Nat := 2\n"
            "end A\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "A.B.foo" in names
        assert "A.bar" in names

    def test_section_does_not_add_prefix(self):
        content = (
            "section MySection\n"
            "def foo : Nat := 1\n"
            "end MySection\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "foo" in names
        assert "MySection.foo" not in names

    def test_namespace_inside_section(self):
        content = (
            "section Helpers\n"
            "namespace X\n"
            "def foo : Nat := 1\n"
            "end X\n"
            "end Helpers\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "X.foo" in names

    def test_section_inside_namespace(self):
        content = (
            "namespace X\n"
            "section Internal\n"
            "def foo : Nat := 1\n"
            "end Internal\n"
            "def bar : Nat := 2\n"
            "end X\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "X.foo" in names
        assert "X.bar" in names

    def test_reopened_namespace(self):
        content = (
            "namespace X\n"
            "def a : Nat := 1\n"
            "end X\n"
            "\n"
            "namespace X\n"
            "def b : Nat := 2\n"
            "end X\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "X.a" in names
        assert "X.b" in names

    def test_after_namespace_end(self):
        content = (
            "namespace X\n"
            "def inside : Nat := 1\n"
            "end X\n"
            "def outside : Nat := 2\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "X.inside" in names
        assert "outside" in names

    def test_line_numbers(self):
        content = (
            "namespace X\n"      # line 1
            "def foo := 1\n"     # line 2
            "end X\n"            # line 3
        )
        decls = _extract_declarations(content)
        assert decls == [("X.foo", 2)]

    def test_private_and_protected(self):
        content = (
            "namespace X\n"
            "private def secret : Nat := 1\n"
            "protected def visible : Nat := 2\n"
            "end X\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "X.secret" in names
        assert "X.visible" in names

    def test_noncomputable(self):
        content = (
            "namespace X\n"
            "noncomputable def foo : Nat := 1\n"
            "end X\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "X.foo" in names

    def test_all_decl_kinds(self):
        content = (
            "namespace N\n"
            "def d := 1\n"
            "theorem t : True := trivial\n"
            "lemma l : True := trivial\n"
            "abbrev a := Nat\n"
            "structure S where\n"
            "class C where\n"
            "inductive I where\n"
            "axiom ax : True\n"
            "opaque op : Nat\n"
            "end N\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        for expected in ["N.d", "N.t", "N.l", "N.a", "N.S", "N.C", "N.I", "N.ax", "N.op"]:
            assert expected in names, f"{expected} not found in {names}"

    def test_comments_ignored(self):
        content = (
            "namespace X\n"
            "-- def notADecl : Nat := 1\n"
            "def real : Nat := 2\n"
            "end X\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "X.real" in names
        assert len(decls) == 1

    def test_bare_end(self):
        content = (
            "namespace X\n"
            "def foo := 1\n"
            "end\n"
            "def bar := 2\n"
        )
        decls = _extract_declarations(content)
        names = [n for n, _ in decls]
        assert "X.foo" in names
        assert "bar" in names

    def test_empty_file(self):
        assert _extract_declarations("") == []
        assert _extract_declarations("\n\n\n") == []


class TestLocalSearch:
    @pytest.mark.asyncio
    async def test_search_finds_declarations(self, tmp_path: Path):
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

    @pytest.mark.asyncio
    async def test_search_by_namespace_prefix(self, tmp_path: Path):
        """Searching by namespace prefix should find declarations."""
        (tmp_path / "lakefile.lean").write_text('import Lake\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "Types.lean").write_text(
            "namespace ProofRunner\n"
            "structure RangePos where\n"
            "  line : Nat\n"
            "structure HypRec where\n"
            "  name : String\n"
            "end ProofRunner\n"
        )

        result = await lean_local_search(str(src / "Types.lean"), "ProofRunner")
        assert "ProofRunner.RangePos" in result
        assert "ProofRunner.HypRec" in result

    @pytest.mark.asyncio
    async def test_search_by_qualified_name(self, tmp_path: Path):
        """Searching by full qualified name should find the declaration."""
        (tmp_path / "lakefile.lean").write_text('import Lake\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "Lib.lean").write_text(
            "namespace MyLib\n"
            "def helper : Nat := 42\n"
            "end MyLib\n"
        )

        result = await lean_local_search(str(src / "Lib.lean"), "MyLib.helper")
        assert "MyLib.helper" in result

    @pytest.mark.asyncio
    async def test_search_by_short_name_in_namespace(self, tmp_path: Path):
        """Searching by short name still finds declarations inside namespaces."""
        (tmp_path / "lakefile.lean").write_text('import Lake\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "Lib.lean").write_text(
            "namespace X\n"
            "def myFunc : Nat := 1\n"
            "end X\n"
        )

        result = await lean_local_search(str(src / "Lib.lean"), "myFunc")
        assert "X.myFunc" in result

    @pytest.mark.asyncio
    async def test_section_not_in_prefix(self, tmp_path: Path):
        """Section names should not appear in qualified names."""
        (tmp_path / "lakefile.lean").write_text('import Lake\n')
        src = tmp_path / "src"
        src.mkdir()
        (src / "Lib.lean").write_text(
            "section Helpers\n"
            "def topLevel : Nat := 1\n"
            "end Helpers\n"
        )

        result = await lean_local_search(str(src / "Lib.lean"), "topLevel")
        assert "topLevel" in result
        assert "Helpers.topLevel" not in result
