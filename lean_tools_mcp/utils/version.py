# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Lean version detection and tool path resolution.
"""

from __future__ import annotations

import re
from pathlib import Path


def detect_lean_version(project_root: Path | str) -> str | None:
    """Read the lean-toolchain file to detect the Lean version.

    Returns a version string like "v4.24.0-rc1" or None if not found.
    """
    toolchain_file = Path(project_root) / "lean-toolchain"
    if not toolchain_file.exists():
        return None

    content = toolchain_file.read_text().strip()
    # Format: leanprover/lean4:v4.24.0-rc1
    match = re.search(r"v[\d]+\.[\d]+\.[\d]+(?:-[\w.]+)?", content)
    return match.group(0) if match else content


def infer_module_name(file_path: Path | str, project_root: Path | str) -> str:
    """Convert a file path to a Lean module name.

    Example:
        /project/Mathlib/Algebra/Group.lean -> Mathlib.Algebra.Group
    """
    file_path = Path(file_path).resolve()
    project_root = Path(project_root).resolve()

    try:
        rel = file_path.relative_to(project_root)
    except ValueError:
        # File is not under project root, use stem
        return file_path.stem

    # Remove .lean extension and convert / to .
    parts = rel.with_suffix("").parts
    return ".".join(parts)
