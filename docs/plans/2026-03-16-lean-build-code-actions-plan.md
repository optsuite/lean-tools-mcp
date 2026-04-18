# Lean Build and Code Actions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `lean_build` and `lean_code_actions` through a small `LeanProjectManager` layer that coordinates project-level operations with the LSP pool.

**Architecture:** Introduce `lean_tools_mcp/project/manager.py` as the owner of project lifecycle concerns. Put build subprocess execution, environment preparation, locking, and LSP restart there. Keep tool modules thin. Extend `LSPClient` / `LSPPool` only where true LSP requests are needed.

**Tech Stack:** Python 3.11, `asyncio`, MCP server registry in `lean_tools_mcp/server.py`, Lean JSON-RPC over stdio, `pytest`, `monkeypatch`, `AsyncMock`.

---

### Task 1: Create project-manager skeleton

**Files:**
- Create: `lean_tools_mcp/project/__init__.py`
- Create: `lean_tools_mcp/project/manager.py`
- Test: `tests/test_project_manager.py`

**Step 1: Write the failing test for manager construction**

```python
from pathlib import Path

from lean_tools_mcp.project.manager import LeanProjectManager


class DummyPool:
    async def restart(self) -> None:
        raise AssertionError("restart should not be called here")


def test_manager_keeps_project_root_and_lean_path(tmp_path: Path):
    manager = LeanProjectManager(
        project_root=tmp_path,
        lsp_pool=DummyPool(),
        lean_path="/tmp/lean-bin/lean",
    )
    assert manager.project_root == tmp_path.resolve()
    assert manager.lean_path == "/tmp/lean-bin/lean"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_project_manager.py::test_manager_keeps_project_root_and_lean_path -q`

Expected: import failure because `lean_tools_mcp.project.manager` does not exist yet.

**Step 3: Write minimal implementation**

```python
from dataclasses import dataclass
from pathlib import Path
import asyncio


@dataclass
class BuildResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    restarted_lsp: bool
    commands: list[list[str]]


class LeanProjectManager:
    def __init__(self, project_root, lsp_pool, lean_path="lean", build_timeout=900.0):
        self.project_root = Path(project_root).resolve()
        self.lsp_pool = lsp_pool
        self.lean_path = lean_path
        self.build_timeout = build_timeout
        self._build_lock = asyncio.Lock()
```

**Step 4: Run the test again**

Run: `pytest tests/test_project_manager.py::test_manager_keeps_project_root_and_lean_path -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_project_manager.py lean_tools_mcp/project/__init__.py lean_tools_mcp/project/manager.py
git commit -m "feat: add lean project manager skeleton"
```

---

### Task 2: Add build orchestration to the project manager

**Files:**
- Modify: `lean_tools_mcp/project/manager.py`
- Test: `tests/test_project_manager.py`

**Step 1: Write the failing success-path test**

```python
import asyncio

import pytest

from lean_tools_mcp.project.manager import LeanProjectManager


class DummyPool:
    def __init__(self):
        self.restarted = False

    async def restart(self) -> None:
        self.restarted = True


class DummyProcess:
    def __init__(self, returncode=0, stdout=b"build ok\n", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_build_success_restarts_pool(tmp_path, monkeypatch):
    pool = DummyPool()
    manager = LeanProjectManager(tmp_path, pool, lean_path="/tmp/bin/lean")

    async def fake_exec(*args, **kwargs):
        assert list(args) == ["lake", "build"]
        return DummyProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await manager.build()
    assert result.success is True
    assert result.restarted_lsp is True
    assert pool.restarted is True
```

**Step 2: Write the failing failure-path test**

```python
@pytest.mark.asyncio
async def test_build_failure_does_not_restart_pool(tmp_path, monkeypatch):
    pool = DummyPool()
    manager = LeanProjectManager(tmp_path, pool, lean_path="/tmp/bin/lean")

    async def fake_exec(*args, **kwargs):
        return DummyProcess(returncode=1, stdout=b"", stderr=b"build failed\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await manager.build()
    assert result.success is False
    assert result.restarted_lsp is False
    assert pool.restarted is False
```

**Step 3: Run the tests to confirm failure**

Run: `pytest tests/test_project_manager.py -q`

Expected: `LeanProjectManager` has no `build` method yet.

**Step 4: Implement `build`, `_run_lake_command`, and `_build_env`**

Implementation requirements:

- `build(clean=False, target=None, output_lines=80)` acquires `_build_lock`
- if `clean=True`, run `["lake", "clean"]` first
- always run `["lake", "build"] + [target] if target`
- use `project_root` as subprocess cwd
- if `lean_path` is absolute, prepend its parent directory to `PATH`
- on successful build, call `await self.lsp_pool.restart()`
- return `BuildResult`

**Step 5: Add a clean-path test**

```python
@pytest.mark.asyncio
async def test_build_clean_runs_clean_then_build(tmp_path, monkeypatch):
    pool = DummyPool()
    manager = LeanProjectManager(tmp_path, pool)
    commands = []

    async def fake_exec(*args, **kwargs):
        commands.append(list(args))
        return DummyProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await manager.build(clean=True)
    assert commands == [["lake", "clean"], ["lake", "build"]]
```

**Step 6: Run the manager test file again**

Run: `pytest tests/test_project_manager.py -q`

Expected: PASS.

**Step 7: Commit**

```bash
git add tests/test_project_manager.py lean_tools_mcp/project/manager.py
git commit -m "feat: add project-managed lean build orchestration"
```

---

### Task 3: Add code-action support to the LSP layers

**Files:**
- Modify: `lean_tools_mcp/lsp/client.py`
- Modify: `lean_tools_mcp/lsp/pool.py`
- Test: `tests/test_code_actions.py`

**Step 1: Write the failing client-level test**

```python
import pytest

from lean_tools_mcp.lsp.client import LSPClient


class DummyTransport:
    def __init__(self):
        self.calls = []

    async def send_request(self, method, params, timeout=60.0):
        self.calls.append((method, params, timeout))
        return [{"title": "Use simp", "kind": "quickfix"}]


class DummyFileManager:
    open_files = {}

    async def wait_for_diagnostics(self, file_path, timeout):
        return []


@pytest.mark.asyncio
async def test_get_code_actions_sends_text_document_code_action(tmp_path):
    client = LSPClient(project_root=tmp_path)
    client._transport = DummyTransport()
    client._file_manager = DummyFileManager()
    client._initialized = True

    async def fake_ensure(_):
        return None

    client._ensure_file_open = fake_ensure
    result = await client.get_code_actions(
        tmp_path / "Foo.lean",
        line=10,
        column=5,
    )
    assert result == [{"title": "Use simp", "kind": "quickfix"}]
    assert client.transport.calls[0][0] == "textDocument/codeAction"
```

**Step 2: Run the test to verify failure**

Run: `pytest tests/test_code_actions.py::test_get_code_actions_sends_text_document_code_action -q`

Expected: `LSPClient` has no `get_code_actions`.

**Step 3: Implement `LSPClient.get_code_actions(...)`**

Implementation requirements:

- ensure file is open
- convert positions to 0-indexed
- default `end_line/end_column` to the same position if omitted
- fetch diagnostics from the same client
- filter diagnostics intersecting the requested range
- send `textDocument/codeAction`
- return `[]` when result is `None`

**Step 4: Implement `LSPPool.get_code_actions(...)`**

Match the existing delegation style used by `get_hover`, `get_completions`, and `get_goal`.

**Step 5: Add a truncation/empty-results test at tool-facing level**

```python
def test_format_code_actions_empty():
    from lean_tools_mcp.tools.code_actions import _format_code_actions
    assert "No code actions" in _format_code_actions([], max_actions=20)
```

**Step 6: Run the new test file**

Run: `pytest tests/test_code_actions.py -q`

Expected: PASS.

**Step 7: Commit**

```bash
git add tests/test_code_actions.py lean_tools_mcp/lsp/client.py lean_tools_mcp/lsp/pool.py
git commit -m "feat: add LSP code action support"
```

---

### Task 4: Add `lean_code_actions` MCP tool

**Files:**
- Create: `lean_tools_mcp/tools/code_actions.py`
- Modify: `lean_tools_mcp/server.py`
- Modify: `tests/test_server.py`
- Test: `tests/test_code_actions.py`

**Step 1: Write the failing server-registry test**

Add to `tests/test_server.py`:

```python
"lean_code_actions",
```

and assert the schema includes:

```python
tool = next(t for t in TOOLS if t.name == "lean_code_actions")
props = tool.inputSchema["properties"]
assert "file_path" in props
assert "line" in props
assert "column" in props
```

**Step 2: Run the server test**

Run: `pytest tests/test_server.py -q`

Expected: FAIL because the tool is not registered.

**Step 3: Implement the tool module**

Suggested public function:

```python
async def lean_code_actions(
    project_manager: LeanProjectManager,
    *,
    file_path: str,
    line: int,
    column: int,
    end_line: int | None = None,
    end_column: int | None = None,
    max_actions: int = 20,
) -> str:
    ...
```

Formatting requirements:

- numbered list output
- show `title`
- include `kind` when present
- handle both `CodeAction` and `Command`
- cap output to `max_actions`

**Step 4: Register and dispatch the tool**

Modify `lean_tools_mcp/server.py` to:

- import the new tool
- define MCP schema
- add a dispatch branch
- instantiate `LeanProjectManager` and pass it into dispatch

**Step 5: Run focused tests**

Run:

```bash
pytest tests/test_server.py tests/test_code_actions.py -q
```

Expected: PASS.

**Step 6: Commit**

```bash
git add tests/test_server.py tests/test_code_actions.py lean_tools_mcp/tools/code_actions.py lean_tools_mcp/server.py
git commit -m "feat: add lean_code_actions MCP tool"
```

---

### Task 5: Add `lean_build` MCP tool

**Files:**
- Create: `lean_tools_mcp/tools/build.py`
- Modify: `lean_tools_mcp/server.py`
- Modify: `tests/test_server.py`
- Create: `tests/test_build.py`

**Step 1: Write the failing build-tool test**

```python
import pytest

from lean_tools_mcp.tools.build import _format_build_result
from lean_tools_mcp.project.manager import BuildResult


def test_format_build_success():
    result = BuildResult(
        success=True,
        returncode=0,
        stdout="ok\n",
        stderr="",
        restarted_lsp=True,
        commands=[["lake", "build"]],
    )
    text = _format_build_result(result, output_lines=20)
    assert "Build succeeded" in text
    assert "LSP pool restarted" in text
```

**Step 2: Run the test to verify failure**

Run: `pytest tests/test_build.py -q`

Expected: import failure because the tool file does not exist.

**Step 3: Implement `lean_build`**

Suggested public function:

```python
async def lean_build(
    project_manager: LeanProjectManager,
    *,
    target: str | None = None,
    clean: bool = False,
    output_lines: int = 80,
) -> str:
    ...
```

Formatting requirements:

- first line states success or failure
- mention whether `clean` was run
- mention whether LSP restart happened
- print the last `output_lines` lines of combined output

**Step 4: Register and dispatch the tool**

Add schema and dispatch branch in `lean_tools_mcp/server.py`.

**Step 5: Run focused tests**

Run:

```bash
pytest tests/test_build.py tests/test_server.py tests/test_project_manager.py -q
```

Expected: PASS.

**Step 6: Commit**

```bash
git add tests/test_build.py tests/test_server.py lean_tools_mcp/tools/build.py lean_tools_mcp/server.py
git commit -m "feat: add lean_build MCP tool"
```

---

### Task 6: Update docs and optional integration coverage

**Files:**
- Modify: `README.md`
- Modify: `tests/test_integration.py`

**Step 1: Update README tool tables**

Add:

- `lean_code_actions`
- `lean_build`

Update:

- overview table
- signatures/examples table
- comparison table with `lean-lsp-mcp`

**Step 2: Add narrow integration tests if environment allows**

Examples:

- `lean_code_actions` on a file with a deliberately fixable issue
- `lean_build` on a tiny temp project or fixture project

If `lean_build` integration is too heavy, keep only the code-actions integration or skip with a clear reason.

**Step 3: Run the targeted test suite**

Run:

```bash
pytest tests/test_server.py tests/test_project_manager.py tests/test_code_actions.py tests/test_build.py -q
```

Optional:

```bash
pytest tests/test_integration.py -k "code_actions or build" -v -s
```

**Step 4: Commit**

```bash
git add README.md tests/test_integration.py
git commit -m "docs: document lean_build and lean_code_actions"
```

---

## Final Verification Checklist

- `lean_tools_mcp/server.py` registers both new tools
- `LeanProjectManager` owns build orchestration
- `LSPClient` supports `textDocument/codeAction`
- successful build restarts the full pool
- failed build does not restart the pool
- docs reflect the new tools

---

## Notes

- Do not add code-action application in this change.
- Do not refactor the entire server into a container object in this change.
- Keep Scheme C narrow: one project manager, two new tools, minimal surface-area changes.
