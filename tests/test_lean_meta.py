# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for the lean_meta module (no Lean dependency — tests path logic).
"""

from __future__ import annotations

from pathlib import Path

from lean_tools_mcp.tools.lean_meta import (
    _find_lean_project,
    _find_executable,
    _get_lean_path,
    _format_deps_analysis,
)


class TestFindLeanProject:
    """Test lean project discovery."""

    def test_finds_lean_dir(self):
        lean_dir = _find_lean_project()
        assert lean_dir is not None
        assert lean_dir.is_dir()
        assert (lean_dir / "lakefile.lean").exists()

    def test_lean_dir_has_src(self):
        lean_dir = _find_lean_project()
        assert lean_dir is not None
        assert (lean_dir / "src").is_dir()


class TestFindExecutable:
    """Test executable discovery."""

    def test_find_havelet_generator(self):
        exe = _find_executable("havelet_generator")
        # Might or might not exist depending on build state
        if exe is not None:
            assert exe.exists()
            assert exe.name == "havelet_generator"

    def test_find_nonexistent(self):
        exe = _find_executable("nonexistent_tool_12345")
        assert exe is None


class TestGetLeanPath:
    """Test LEAN_PATH construction."""

    def test_without_user_project(self):
        lp = _get_lean_path()
        # Should include at least our tools' lib dir
        assert isinstance(lp, str)

    def test_with_user_project(self):
        lp = _get_lean_path("/some/nonexistent/project")
        # Should still return a string (gracefully handles missing dirs)
        assert isinstance(lp, str)


class TestFormatDepsAnalysis:
    """Test dependency analysis formatting."""

    def test_empty(self):
        result = _format_deps_analysis({"theorems": []}, "test.json")
        assert "0 theorem(s)" in result

    def test_with_theorems(self):
        data = {
            "theorems": [
                {
                    "theoremName": "my_thm",
                    "statement": "∀ n : Nat, n + 0 = n",
                    "dependencies": [
                        {
                            "name": "Nat.add_zero",
                            "kind": "theorem",
                            "module": "Init.Data.Nat.Basic",
                        }
                    ],
                }
            ]
        }
        result = _format_deps_analysis(data, "test.json")
        assert "1 theorem(s)" in result
        assert "my_thm" in result
        assert "Nat.add_zero" in result

    def test_truncates_long_deps(self):
        deps = [
            {"name": f"dep_{i}", "kind": "definition", "module": f"M{i}"}
            for i in range(30)
        ]
        data = {
            "theorems": [
                {
                    "theoremName": "big_thm",
                    "statement": "...",
                    "dependencies": deps,
                }
            ]
        }
        result = _format_deps_analysis(data, "test.json")
        assert "and 10 more" in result
