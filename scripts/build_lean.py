#!/usr/bin/env python3
"""
Build a modified Lean 4 binary with in-process worker support.

Automatically downloads the Lean 4 source at a given version tag,
applies the appropriate patches from patches/, and builds via cmake.

Usage:
    python scripts/build_lean.py --version v4.28.0 --output ~/lean-builds/
    python scripts/build_lean.py --version v4.29.0-rc2 --output ~/lean-builds/ --jobs 8
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PATCHES_DIR = PROJECT_ROOT / "patches"

SUPPORTED_PATCH_VERSIONS = ["v4.27", "v4.28", "v4.29"]

PATCH_FILE_MAP = {
    "Watchdog.lean": "src/Lean/Server/Watchdog.lean",
    "FileWorker.lean": "src/Lean/Server/FileWorker.lean",
    "ChannelStream.lean": "src/Lean/Server/ChannelStream.lean",
    "Import.lean": "src/Lean/Elab/Import.lean",
    "Shell.lean": "src/Lean/Shell.lean",
}


def parse_version(version_str: str) -> tuple[int, int, int, str]:
    """Parse 'v4.27.0' or 'v4.29.0-rc2' into (major, minor, patch, suffix)."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(.*)", version_str)
    if not m:
        print(f"Error: cannot parse version '{version_str}'", file=sys.stderr)
        sys.exit(1)
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)


def find_patch_version(version_str: str) -> str:
    """Map an exact Lean version to the closest supported patch version."""
    major, minor, _patch, _suffix = parse_version(version_str)
    key = f"v{major}.{minor}"
    if key in SUPPORTED_PATCH_VERSIONS:
        return key
    if minor > 29:
        return "v4.29"
    if minor < 27:
        print(
            f"Error: version {version_str} (minor={minor}) is too old. "
            f"Supported: v4.27+",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    """Run a command, printing it first."""
    print(f"  $ {' '.join(cmd)}", flush=True)
    merged_env = None
    if env:
        merged_env = os.environ.copy()
        merged_env.update(env)
    result = subprocess.run(cmd, cwd=cwd, env=merged_env)
    if result.returncode != 0:
        print(f"Error: command failed with exit code {result.returncode}", file=sys.stderr)
        sys.exit(1)


def clone_lean(version_tag: str, dest: Path) -> None:
    """Shallow-clone lean4 at a specific git tag."""
    if dest.exists():
        print(f"  Directory {dest} already exists, skipping clone.")
        return
    print(f"\n[1/4] Cloning leanprover/lean4 at {version_tag} ...")
    run([
        "git", "clone", "--depth", "1",
        "--branch", version_tag,
        "https://github.com/leanprover/lean4.git",
        str(dest),
    ])


def apply_patches(patch_version: str, lean_src: Path) -> None:
    """Copy patch files over the lean4 source tree."""
    print(f"\n[2/4] Applying patches ({patch_version}) ...")

    common_dir = PATCHES_DIR / "common"
    if common_dir.exists():
        for patch_file in common_dir.iterdir():
            if patch_file.suffix == ".lean" and patch_file.name in PATCH_FILE_MAP:
                dest = lean_src / PATCH_FILE_MAP[patch_file.name]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(patch_file, dest)
                print(f"  [common] {patch_file.name} -> {dest.relative_to(lean_src)}")

    version_dir = PATCHES_DIR / patch_version
    if not version_dir.exists():
        print(f"Error: patch directory {version_dir} not found", file=sys.stderr)
        sys.exit(1)

    for patch_file in version_dir.iterdir():
        if patch_file.suffix == ".lean" and patch_file.name in PATCH_FILE_MAP:
            dest = lean_src / PATCH_FILE_MAP[patch_file.name]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(patch_file, dest)
            print(f"  [{patch_version}] {patch_file.name} -> {dest.relative_to(lean_src)}")


def build_lean(lean_src: Path, jobs: int) -> Path:
    """Build lean4 using cmake and return the binary path."""
    print(f"\n[3/4] Building Lean (jobs={jobs}) ...")
    run(["cmake", "--preset", "release"], cwd=lean_src)
    run(["cmake", "--build", "build/release", f"-j{jobs}"], cwd=lean_src)

    binary = lean_src / "build" / "release" / "stage1" / "bin" / "lean"
    if not binary.exists():
        print(f"Error: expected binary at {binary} not found", file=sys.stderr)
        sys.exit(1)
    return binary


def install_binary(binary: Path, output_dir: Path, version_tag: str) -> Path:
    """Copy the entire stage1 directory to the output directory.

    The lean binary depends on shared libraries at relative paths
    (lib/lean/*.dylib), so we must copy the full stage1 tree.
    """
    print(f"\n[4/4] Installing ...")
    stage1_dir = binary.parent.parent  # stage1/bin/lean -> stage1/
    dest_dir = output_dir / version_tag

    if dest_dir.exists():
        shutil.rmtree(dest_dir)

    shutil.copytree(stage1_dir, dest_dir, symlinks=True)
    dest = dest_dir / "bin" / "lean"
    os.chmod(dest, 0o755)

    lib_count = sum(1 for _ in (dest_dir / "lib").rglob("*.dylib")) if (dest_dir / "lib").exists() else 0
    so_count = sum(1 for _ in (dest_dir / "lib").rglob("*.so")) if (dest_dir / "lib").exists() else 0
    print(f"  Installed stage1 tree: {dest_dir}")
    print(f"  Shared libraries: {lib_count} .dylib, {so_count} .so")
    print(f"  Binary: {dest}")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a modified Lean 4 binary with in-process worker support",
    )
    parser.add_argument(
        "--version", "-v",
        required=True,
        help="Lean version tag (e.g. v4.28.0, v4.29.0-rc2)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path.home() / "lean-builds",
        help="Output directory for built binaries (default: ~/lean-builds/)",
    )
    parser.add_argument(
        "--jobs", "-j",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of parallel build jobs",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Working directory for cloning (default: /tmp/lean4-build-<version>)",
    )
    parser.add_argument(
        "--keep-source",
        action="store_true",
        help="Keep the cloned source tree after building",
    )
    args = parser.parse_args()

    version_tag = args.version
    if not version_tag.startswith("v"):
        version_tag = f"v{version_tag}"

    patch_version = find_patch_version(version_tag)
    print(f"Lean version:  {version_tag}")
    print(f"Patch version: {patch_version}")
    print(f"Output dir:    {args.output}")

    work_dir = args.work_dir or Path(f"/tmp/lean4-build-{version_tag}")
    clone_lean(version_tag, work_dir)
    apply_patches(patch_version, work_dir)
    binary = build_lean(work_dir, args.jobs)
    installed = install_binary(binary, args.output, version_tag)

    if not args.keep_source and not args.work_dir:
        print(f"\nCleaning up {work_dir} ...")
        shutil.rmtree(work_dir, ignore_errors=True)

    print(f"\nDone! Modified lean binary: {installed}")
    print(f"Usage: {installed} --server")
    print(f"  or set LEAN_EXECUTABLE={installed}")


if __name__ == "__main__":
    main()
