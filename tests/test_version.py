"""
Unit tests for version detection utilities.
"""

from __future__ import annotations

from pathlib import Path

from lean_tools_mcp.utils.version import detect_lean_version, infer_module_name


class TestDetectLeanVersion:
    def test_standard_toolchain(self, tmp_path: Path):
        toolchain = tmp_path / "lean-toolchain"
        toolchain.write_text("leanprover/lean4:v4.24.0-rc1\n")
        assert detect_lean_version(tmp_path) == "v4.24.0-rc1"

    def test_stable_version(self, tmp_path: Path):
        toolchain = tmp_path / "lean-toolchain"
        toolchain.write_text("leanprover/lean4:v4.26.0\n")
        assert detect_lean_version(tmp_path) == "v4.26.0"

    def test_missing_toolchain(self, tmp_path: Path):
        assert detect_lean_version(tmp_path) is None


class TestInferModuleName:
    def test_basic(self, tmp_path: Path):
        name = infer_module_name(tmp_path / "Mathlib" / "Algebra" / "Group.lean", tmp_path)
        assert name == "Mathlib.Algebra.Group"

    def test_single_file(self, tmp_path: Path):
        name = infer_module_name(tmp_path / "Main.lean", tmp_path)
        assert name == "Main"

    def test_outside_project(self):
        name = infer_module_name("/some/other/File.lean", "/project")
        assert name == "File"
