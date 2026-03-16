# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for LeanProjectManager.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lean_tools_mcp.project.manager import LeanProjectManager


class DummyPool:
    def __init__(self):
        self.restarted = False

    async def restart(self) -> None:
        self.restarted = True


class DummyProcess:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.returncode = -9


def test_manager_keeps_project_root_and_lean_path(tmp_path: Path):
    manager = LeanProjectManager(
        project_root=tmp_path,
        lsp_pool=DummyPool(),
        lean_path="/tmp/lean-bin/lean",
    )
    assert manager.project_root == tmp_path.resolve()
    assert manager.lean_path == "/tmp/lean-bin/lean"


def test_build_env_prepends_absolute_lean_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    expected_prefix = str(Path("/tmp/custom/bin/lean").resolve().parent)
    manager = LeanProjectManager(
        project_root=tmp_path,
        lsp_pool=DummyPool(),
        lean_path="/tmp/custom/bin/lean",
    )

    env = manager._build_env()
    assert env["PATH"].startswith(expected_prefix)


@pytest.mark.asyncio
async def test_build_success_restarts_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pool = DummyPool()
    manager = LeanProjectManager(tmp_path, pool, lean_path="/tmp/bin/lean")

    async def fake_exec(*args, **kwargs):
        assert list(args) == ["lake", "build"]
        assert kwargs["cwd"] == str(tmp_path.resolve())
        return DummyProcess(stdout=b"build ok\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await manager.build()
    assert result.success is True
    assert result.restarted_lsp is True
    assert pool.restarted is True
    assert result.commands == [["lake", "build"]]


@pytest.mark.asyncio
async def test_build_failure_does_not_restart_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pool = DummyPool()
    manager = LeanProjectManager(tmp_path, pool, lean_path="/tmp/bin/lean")

    async def fake_exec(*args, **kwargs):
        return DummyProcess(returncode=1, stderr=b"build failed\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await manager.build()
    assert result.success is False
    assert result.restarted_lsp is False
    assert pool.restarted is False
    assert "build failed" in result.stderr


@pytest.mark.asyncio
async def test_build_clean_runs_clean_then_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pool = DummyPool()
    manager = LeanProjectManager(tmp_path, pool)
    commands: list[list[str]] = []

    async def fake_exec(*args, **kwargs):
        commands.append(list(args))
        return DummyProcess(stdout=b"ok\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await manager.build(clean=True)
    assert result.success is True
    assert commands == [["lake", "clean"], ["lake", "build"]]
