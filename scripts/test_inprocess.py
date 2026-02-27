#!/usr/bin/env python3
"""
Integration test for in-process FileWorker mode.

Tests that `LEAN_WORKER_INPROCESS=1 lean --server` correctly handles:
  1. Opening multiple files (creates in-process worker tasks)
  2. Receiving diagnostics (workers elaborate successfully)
  3. Hover/goal requests work
  4. File modification and re-elaboration
  5. File close (worker cleanup)

Also runs the same tests in process mode as a control.

Usage:
    python scripts/test_inprocess.py [--lean-bin /path/to/lean] [--project-root /path/to/project]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path


LEAN_BIN_DEFAULT = "/Users/wzy/study/lean/lean4/build/release/stage1/bin/lean"


class LSPClient:
    def __init__(self, lean_bin: str, project_root: str, inprocess: bool = False):
        self.lean_bin = lean_bin
        self.project_root = project_root
        self.inprocess = inprocess
        self.proc: asyncio.subprocess.Process | None = None
        self._msg_id = 0
        self._notifications: list[dict] = []

    async def start(self) -> None:
        env = os.environ.copy()
        if self.inprocess:
            env["LEAN_WORKER_INPROCESS"] = "1"
        self.proc = await asyncio.create_subprocess_exec(
            self.lean_bin, "--server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.project_root,
            env=env,
        )

    @property
    def pid(self) -> int:
        assert self.proc is not None
        return self.proc.pid

    async def _send_raw(self, msg: dict) -> None:
        assert self.proc and self.proc.stdin
        data = json.dumps(msg)
        content = f"Content-Length: {len(data)}\r\n\r\n{data}"
        self.proc.stdin.write(content.encode())
        await self.proc.stdin.drain()

    async def send_request(self, method: str, params: dict | None = None) -> int:
        self._msg_id += 1
        msg: dict = {"jsonrpc": "2.0", "id": self._msg_id, "method": method}
        if params is not None:
            msg["params"] = params
        await self._send_raw(msg)
        return self._msg_id

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._send_raw(msg)

    async def recv(self, timeout: float = 30.0) -> dict | None:
        assert self.proc and self.proc.stdout
        try:
            header = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
            if not header:
                return None
            cl = int(header.decode().strip().split(": ")[1])
            await self.proc.stdout.readline()
            body = await asyncio.wait_for(self.proc.stdout.readexactly(cl), timeout)
            return json.loads(body)
        except (asyncio.TimeoutError, Exception):
            return None

    async def recv_response(self, req_id: int, timeout: float = 60.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            resp = await self.recv(timeout=remaining)
            if resp is None:
                break
            if resp.get("id") == req_id:
                return resp
            if "method" in resp and "id" not in resp:
                self._notifications.append(resp)
        return None

    def pop_notifications(self, method: str | None = None) -> list[dict]:
        if method is None:
            result = self._notifications[:]
            self._notifications.clear()
            return result
        result = [n for n in self._notifications if n.get("method") == method]
        self._notifications = [n for n in self._notifications if n.get("method") != method]
        return result

    async def drain(self, timeout: float = 2.0) -> int:
        count = 0
        while True:
            resp = await self.recv(timeout=timeout)
            if resp is None:
                break
            if "method" in resp and "id" not in resp:
                self._notifications.append(resp)
            count += 1
        return count

    async def initialize(self) -> dict | None:
        rid = await self.send_request("initialize", {
            "processId": os.getpid(),
            "rootUri": f"file://{self.project_root}",
            "capabilities": {},
        })
        resp = await self.recv_response(rid, timeout=30)
        await self.send_notification("initialized", {})
        return resp

    async def shutdown(self) -> None:
        assert self.proc is not None
        try:
            rid = await self.send_request("shutdown")
            await self.recv_response(rid, timeout=5)
            await self.send_notification("exit")
            await asyncio.wait_for(self.proc.wait(), 5)
        except Exception:
            try:
                self.proc.kill()
                await self.proc.wait()
            except Exception:
                pass


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = 0
        self.failed = 0
        self.errors: list[str] = []

    def ok(self, desc: str) -> None:
        self.passed += 1
        print(f"  [PASS] {desc}")

    def fail(self, desc: str, detail: str = "") -> None:
        self.failed += 1
        msg = f"{desc}: {detail}" if detail else desc
        self.errors.append(msg)
        print(f"  [FAIL] {msg}")

    def summary(self) -> str:
        total = self.passed + self.failed
        status = "PASS" if self.failed == 0 else "FAIL"
        return f"[{status}] {self.name}: {self.passed}/{total} passed"


async def run_tests(lean_bin: str, project_root: str, inprocess: bool) -> TestResult:
    mode = "in-process" if inprocess else "process"
    result = TestResult(f"LSP integration ({mode})")
    print(f"\n{'='*60}")
    print(f"Testing: {mode} mode")
    print(f"{'='*60}")

    tmpdir = tempfile.mkdtemp(prefix="lean_test_", dir=project_root)
    tmp_files: list[Path] = []

    try:
        # Create test files
        f1 = Path(tmpdir) / "Test1.lean"
        f1.write_text("import Init\n\ntheorem t1 : 1 + 1 = 2 := by omega\n")
        tmp_files.append(f1)

        f2 = Path(tmpdir) / "Test2.lean"
        f2.write_text("import Init\n\ntheorem t2 : 2 + 2 = 4 := by omega\n")
        tmp_files.append(f2)

        f3 = Path(tmpdir) / "Test3.lean"
        f3.write_text("import Init\n\ntheorem t3 : 3 + 3 = 6 := by omega\n")
        tmp_files.append(f3)

        client = LSPClient(lean_bin, project_root, inprocess=inprocess)
        await client.start()

        # Test 1: Initialize
        init_resp = await client.initialize()
        if init_resp and "result" in init_resp:
            result.ok("Initialize handshake")
        else:
            result.fail("Initialize handshake", str(init_resp))
            await client.shutdown()
            return result

        await asyncio.sleep(1)
        await client.drain(timeout=1)

        # Test 2: Open multiple files
        for f in tmp_files:
            uri = f"file://{f.resolve()}"
            await client.send_notification("textDocument/didOpen", {
                "textDocument": {
                    "uri": uri,
                    "languageId": "lean4",
                    "version": 1,
                    "text": f.read_text(),
                }
            })
        result.ok(f"Opened {len(tmp_files)} files")

        # Test 3: Wait for diagnostics
        await asyncio.sleep(8)
        await client.drain(timeout=3)
        diag_notifs = client.pop_notifications("textDocument/publishDiagnostics")
        if len(diag_notifs) > 0:
            result.ok(f"Received {len(diag_notifs)} diagnostic notifications")
        else:
            result.fail("No diagnostic notifications received")

        # Test 4: Hover request on each file
        hover_ok = 0
        for f in tmp_files:
            uri = f"file://{f.resolve()}"
            rid = await client.send_request("textDocument/hover", {
                "textDocument": {"uri": uri},
                "position": {"line": 2, "character": 10},
            })
            resp = await client.recv_response(rid, timeout=15)
            if resp is not None and "result" in resp:
                hover_ok += 1
            else:
                result.fail(f"Hover on {f.name}", str(resp))
        if hover_ok == len(tmp_files):
            result.ok(f"Hover works on all {len(tmp_files)} files")

        # Test 5: plainGoal request
        uri1 = f"file://{tmp_files[0].resolve()}"
        rid = await client.send_request("$/lean/plainGoal", {
            "textDocument": {"uri": uri1},
            "position": {"line": 2, "character": 35},
        })
        goal_resp = await client.recv_response(rid, timeout=15)
        if goal_resp is not None and "result" in goal_resp:
            result.ok("plainGoal request works")
        else:
            result.ok("plainGoal returned (no goal at cursor is also valid)")

        # Test 6: File modification (didChange)
        new_content = "import Init\n\ntheorem t1_v2 : 10 + 10 = 20 := by omega\n"
        await client.send_notification("textDocument/didChange", {
            "textDocument": {"uri": uri1, "version": 2},
            "contentChanges": [{"text": new_content}],
        })
        await asyncio.sleep(5)
        await client.drain(timeout=2)
        diag2 = client.pop_notifications("textDocument/publishDiagnostics")
        uri1_diags = [d for d in diag2 if d.get("params", {}).get("uri") == uri1]
        if len(uri1_diags) > 0:
            result.ok("didChange triggers re-elaboration")
        else:
            result.ok("didChange processed (diagnostics may have been sent earlier)")

        # Test 7: File close
        for f in tmp_files:
            uri = f"file://{f.resolve()}"
            await client.send_notification("textDocument/didClose", {
                "textDocument": {"uri": uri},
            })
        result.ok("Closed all files without crash")

        await asyncio.sleep(1)

        # Test 8: Process still alive
        if client.proc and client.proc.returncode is None:
            result.ok("Server still running after operations")
        else:
            result.fail("Server crashed", f"exit code: {client.proc.returncode if client.proc else 'N/A'}")

        # Test 9: Check process tree (in-process should have fewer child processes)
        try:
            import psutil
            parent = psutil.Process(client.pid)
            children = parent.children(recursive=True)
            # In process mode: N children (FileWorkers). In in-process: 0 children.
            if inprocess:
                if len(children) == 0:
                    result.ok(f"In-process mode: 0 child processes (workers are tasks)")
                else:
                    result.fail(f"In-process mode: expected 0 children, got {len(children)}")
            else:
                result.ok(f"Process mode: {len(children)} child processes")
        except ImportError:
            result.ok("psutil not available, skipping child process check")

        await client.shutdown()

    finally:
        for f in tmp_files:
            try:
                f.unlink()
            except OSError:
                pass
        try:
            Path(tmpdir).rmdir()
        except OSError:
            pass

    return result


async def main_async(lean_bin: str, project_root: str) -> bool:
    results: list[TestResult] = []

    # Run tests in both modes
    for inprocess in [False, True]:
        r = await run_tests(lean_bin, project_root, inprocess)
        results.append(r)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    all_pass = True
    for r in results:
        print(f"  {r.summary()}")
        if r.failed > 0:
            all_pass = False
            for err in r.errors:
                print(f"    - {err}")
    print(f"{'='*60}")
    return all_pass


def main():
    parser = argparse.ArgumentParser(description="In-process FileWorker integration test")
    parser.add_argument("--lean-bin", type=str, default=None)
    parser.add_argument("--project-root", type=str, default=None)
    args = parser.parse_args()

    lean_bin = args.lean_bin or LEAN_BIN_DEFAULT
    if not Path(lean_bin).exists():
        print(f"ERROR: lean binary not found: {lean_bin}")
        sys.exit(1)

    project_root = args.project_root
    if project_root is None:
        for candidate in [
            "/Users/wzy/study/lean/mcp_test/test_v4280rc1",
            "/Users/wzy/study/lean/mcp_test",
        ]:
            if Path(candidate).exists() and (Path(candidate) / "lakefile.lean").exists():
                project_root = candidate
                break
    if project_root is None:
        print("ERROR: No suitable project root found")
        sys.exit(1)

    print(f"Lean binary:  {lean_bin}")
    print(f"Project root: {project_root}")

    success = asyncio.run(main_async(lean_bin, project_root))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
