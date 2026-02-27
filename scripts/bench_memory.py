#!/usr/bin/env python3
"""
Memory benchmark for Lean LSP server.

Measures total memory (RSS) when opening N files in the same Lean server process.
Each FileWorker is a separate OS process, so we measure the entire process tree.

Usage:
    python scripts/bench_memory.py --project-root /path/to/lean/project [--num-files 5]
    python scripts/bench_memory.py --project-root /path/to/lean/project --lean-bin /path/to/lean
    python scripts/bench_memory.py --project-root /path/to/lean/project --use-mathlib
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import signal
import sys
import tempfile
import time
from dataclasses import dataclass, field
from functools import partial

print = partial(print, flush=True)
from pathlib import Path

try:
    import psutil
except ImportError:
    print("ERROR: psutil is required. Install with: pip install psutil")
    sys.exit(1)


@dataclass
class MemorySnapshot:
    timestamp: float
    label: str
    num_processes: int
    total_rss_mb: float
    per_process_rss_mb: list[float] = field(default_factory=list)


@dataclass
class BenchResult:
    lean_version: str
    project_root: str
    num_files: int
    use_mathlib: bool
    snapshots: list[MemorySnapshot] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def get_process_tree_memory(pid: int) -> tuple[int, float, list[float]]:
    """Get total RSS of a process and all its children.

    Returns (num_processes, total_rss_mb, per_process_rss_mb).
    """
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return (0, 0.0, [])

    procs = [parent] + parent.children(recursive=True)
    rss_list = []
    for p in procs:
        try:
            rss_list.append(p.memory_info().rss / (1024 * 1024))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return (len(rss_list), sum(rss_list), rss_list)


class LeanLSPClient:
    """Minimal LSP client for benchmarking."""

    def __init__(self, lean_bin: str, project_root: str):
        self.lean_bin = lean_bin
        self.project_root = project_root
        self.proc: asyncio.subprocess.Process | None = None
        self._msg_id = 0

    async def start(self, inprocess: bool = False) -> None:
        env = os.environ.copy()
        env["LEAN_PATH"] = ""
        if inprocess:
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

    async def send(self, method: str, params: dict | None = None,
                   is_notification: bool = False) -> int | None:
        assert self.proc is not None and self.proc.stdin is not None
        if is_notification:
            msg: dict = {"jsonrpc": "2.0", "method": method}
        else:
            self._msg_id += 1
            msg = {"jsonrpc": "2.0", "id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        data = json.dumps(msg)
        content = f"Content-Length: {len(data)}\r\n\r\n{data}"
        self.proc.stdin.write(content.encode())
        await self.proc.stdin.drain()
        return None if is_notification else self._msg_id

    async def recv(self, timeout: float = 30.0) -> dict | None:
        assert self.proc is not None and self.proc.stdout is not None
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

    async def recv_until_id(self, target_id: int, timeout: float = 60.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            resp = await self.recv(timeout=remaining)
            if resp is None:
                break
            if resp.get("id") == target_id:
                return resp
        return None

    async def drain(self, timeout: float = 1.0) -> int:
        count = 0
        while True:
            resp = await self.recv(timeout=timeout)
            if resp is None:
                break
            count += 1
        return count

    async def shutdown(self) -> None:
        assert self.proc is not None
        try:
            rid = await self.send("shutdown")
            await self.recv_until_id(rid, timeout=5)
            await self.send("exit", is_notification=True)
            await asyncio.wait_for(self.proc.wait(), 5)
        except Exception:
            try:
                self.proc.kill()
                await self.proc.wait()
            except Exception:
                pass


def generate_file_content(index: int, use_mathlib: bool, import_name: str | None = None) -> str:
    if import_name:
        imp = import_name
    elif use_mathlib:
        imp = "Mathlib.Tactic"
    else:
        imp = "Init"
    return (
        f"import {imp}\n\n"
        f"theorem bench_{index} : {index} + 1 = {index + 1} := by omega\n"
    )


async def run_benchmark(
    lean_bin: str,
    project_root: str,
    num_files: int,
    use_mathlib: bool,
    wait_seconds: int,
    inprocess: bool = False,
    import_name: str | None = None,
) -> BenchResult:
    result = BenchResult(
        lean_version="",
        project_root=project_root,
        num_files=num_files,
        use_mathlib=use_mathlib,
    )

    # Get lean version
    proc = await asyncio.create_subprocess_exec(
        lean_bin, "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    result.lean_version = stdout.decode().strip()

    mode_str = "in-process" if inprocess else "process"
    import_str = import_name or ("Mathlib.Tactic" if use_mathlib else "Init")
    print(f"=== Lean Memory Benchmark ===")
    print(f"Lean:         {result.lean_version}")
    print(f"Project:      {project_root}")
    print(f"Files:        {num_files}")
    print(f"Import:       {import_str}")
    print(f"Worker mode:  {mode_str}")
    print(f"Wait time:    {wait_seconds}s per file")
    print(f"Platform:     {platform.machine()} {platform.system()}")
    print()

    # Create temp files
    tmpdir = tempfile.mkdtemp(prefix="lean_bench_", dir=project_root)
    tmp_files: list[Path] = []
    try:
        for i in range(num_files):
            f = Path(tmpdir) / f"Bench{i}.lean"
            f.write_text(generate_file_content(i, use_mathlib, import_name))
            tmp_files.append(f)

        # Start server
        client = LeanLSPClient(lean_bin, project_root)
        await client.start(inprocess=inprocess)
        t0 = time.monotonic()

        # Initialize
        await client.send("initialize", {
            "processId": os.getpid(),
            "rootUri": f"file://{project_root}",
            "capabilities": {},
        })
        await client.recv()
        await client.send("initialized", {}, is_notification=True)
        await asyncio.sleep(1)
        await client.drain(timeout=1)

        # Snapshot: after init
        n, rss, per_proc = get_process_tree_memory(client.pid)
        snap = MemorySnapshot(
            timestamp=time.monotonic() - t0,
            label="after_init",
            num_processes=n,
            total_rss_mb=rss,
            per_process_rss_mb=per_proc,
        )
        result.snapshots.append(snap)
        print(f"[{snap.timestamp:6.1f}s] {snap.label}: "
              f"{snap.num_processes} procs, {snap.total_rss_mb:.1f} MB total")

        # Open files one by one
        for i, f in enumerate(tmp_files):
            uri = f"file://{f.resolve()}"
            content = f.read_text()
            print(f"  Opening file {i} ({f.name})...")
            await client.send("textDocument/didOpen", {
                "textDocument": {
                    "uri": uri,
                    "languageId": "lean4",
                    "version": 1,
                    "text": content,
                }
            }, is_notification=True)

            for elapsed in range(wait_seconds):
                await asyncio.sleep(1)
                if (elapsed + 1) % 10 == 0:
                    n, rss, _ = get_process_tree_memory(client.pid)
                    print(f"    waiting... {elapsed+1}/{wait_seconds}s  "
                          f"({n} procs, {rss:.0f} MB)")
            await client.drain(timeout=2)

            # Snapshot after each file
            n, rss, per_proc = get_process_tree_memory(client.pid)
            snap = MemorySnapshot(
                timestamp=time.monotonic() - t0,
                label=f"after_file_{i}",
                num_processes=n,
                total_rss_mb=rss,
                per_process_rss_mb=per_proc,
            )
            result.snapshots.append(snap)
            print(f"[{snap.timestamp:6.1f}s] {snap.label}: "
                  f"{snap.num_processes} procs, {snap.total_rss_mb:.1f} MB total"
                  f"  (per-proc: {', '.join(f'{x:.1f}' for x in per_proc)} MB)")

        # Final stabilization
        print(f"\nWaiting {wait_seconds}s for final stabilization...")
        await asyncio.sleep(wait_seconds)
        n, rss, per_proc = get_process_tree_memory(client.pid)
        snap = MemorySnapshot(
            timestamp=time.monotonic() - t0,
            label="final",
            num_processes=n,
            total_rss_mb=rss,
            per_process_rss_mb=per_proc,
        )
        result.snapshots.append(snap)
        print(f"[{snap.timestamp:6.1f}s] {snap.label}: "
              f"{snap.num_processes} procs, {snap.total_rss_mb:.1f} MB total"
              f"  (per-proc: {', '.join(f'{x:.1f}' for x in per_proc)} MB)")

        result.elapsed_seconds = time.monotonic() - t0

        # Shutdown
        await client.shutdown()

    finally:
        # Cleanup temp files
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


def print_summary(result: BenchResult) -> None:
    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"Lean:        {result.lean_version}")
    print(f"Project:     {result.project_root}")
    print(f"Files:       {result.num_files}")
    print(f"Mathlib:     {result.use_mathlib}")
    print(f"Duration:    {result.elapsed_seconds:.1f}s")

    if result.snapshots:
        init_snap = result.snapshots[0]
        final_snap = result.snapshots[-1]
        print(f"\nMemory (RSS):")
        print(f"  After init:    {init_snap.total_rss_mb:8.1f} MB  ({init_snap.num_processes} processes)")
        print(f"  Final:         {final_snap.total_rss_mb:8.1f} MB  ({final_snap.num_processes} processes)")
        print(f"  Growth:        {final_snap.total_rss_mb - init_snap.total_rss_mb:8.1f} MB")

        if final_snap.num_processes > 1:
            watchdog_mb = final_snap.per_process_rss_mb[0] if final_snap.per_process_rss_mb else 0
            worker_mbs = final_snap.per_process_rss_mb[1:] if len(final_snap.per_process_rss_mb) > 1 else []
            print(f"\n  Watchdog:      {watchdog_mb:8.1f} MB")
            if worker_mbs:
                print(f"  Workers ({len(worker_mbs)}):   {sum(worker_mbs):8.1f} MB total")
                print(f"    avg:         {sum(worker_mbs)/len(worker_mbs):8.1f} MB")
                print(f"    min:         {min(worker_mbs):8.1f} MB")
                print(f"    max:         {max(worker_mbs):8.1f} MB")

        # Per-file memory growth
        file_snaps = [s for s in result.snapshots if s.label.startswith("after_file_")]
        if len(file_snaps) >= 2:
            growths = []
            prev = result.snapshots[0].total_rss_mb
            for s in file_snaps:
                growths.append(s.total_rss_mb - prev)
                prev = s.total_rss_mb
            print(f"\n  Per-file growth:")
            for i, g in enumerate(growths):
                print(f"    File {i}:     {g:+8.1f} MB")

    print(f"{'=' * 60}")


def save_result(result: BenchResult, output_path: str) -> None:
    data = {
        "lean_version": result.lean_version,
        "project_root": result.project_root,
        "num_files": result.num_files,
        "use_mathlib": result.use_mathlib,
        "elapsed_seconds": result.elapsed_seconds,
        "platform": f"{platform.machine()} {platform.system()}",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "snapshots": [
            {
                "timestamp": s.timestamp,
                "label": s.label,
                "num_processes": s.num_processes,
                "total_rss_mb": round(s.total_rss_mb, 1),
                "per_process_rss_mb": [round(x, 1) for x in s.per_process_rss_mb],
            }
            for s in result.snapshots
        ],
    }
    Path(output_path).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nResults saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Lean LSP Server Memory Benchmark")
    parser.add_argument(
        "--project-root", type=str, required=True,
        help="Root of the Lean project (must have lakefile.lean)",
    )
    parser.add_argument(
        "--lean-bin", type=str, default=None,
        help="Path to lean binary (default: auto-detect)",
    )
    parser.add_argument(
        "--num-files", type=int, default=5,
        help="Number of files to open (default: 5)",
    )
    parser.add_argument(
        "--use-mathlib", action="store_true",
        help="Generate files with `import Mathlib.Tactic`",
    )
    parser.add_argument(
        "--wait", type=int, default=5,
        help="Seconds to wait per file for elaboration (default: 5, use 60+ for Mathlib)",
    )
    parser.add_argument(
        "--inprocess", action="store_true",
        help="Use in-process workers (LEAN_WORKER_INPROCESS=1)",
    )
    parser.add_argument(
        "--import-name", type=str, default=None,
        help="Custom import name (e.g. 'Lean', 'Mathlib.Tactic')",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Save results to JSON file",
    )
    args = parser.parse_args()

    project_root = str(Path(args.project_root).resolve())

    # Find lean binary
    lean_bin = args.lean_bin
    if lean_bin is None:
        modified = Path("/Users/wzy/study/lean/lean4/build/release/stage1/bin/lean")
        if modified.exists():
            lean_bin = str(modified)
        else:
            lean_bin = "lean"
    print(f"Using lean: {lean_bin}")

    result = asyncio.run(run_benchmark(
        lean_bin=lean_bin,
        project_root=project_root,
        num_files=args.num_files,
        use_mathlib=args.use_mathlib,
        wait_seconds=args.wait,
        inprocess=args.inprocess,
        import_name=args.import_name,
    ))

    print_summary(result)

    output = args.output
    if output is None:
        script_dir = Path(__file__).resolve().parent.parent
        output = str(script_dir / f"docs/bench_memory_{time.strftime('%Y%m%d_%H%M%S')}.json")
    save_result(result, output)


if __name__ == "__main__":
    main()
