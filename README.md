# Lean Tools MCP

Lean Tools MCP is a Lean 4 MCP server focused on two engineering goals:

- Better parallel throughput for proof-assistant workflows.
- Lower memory usage under heavy imports (especially Mathlib).

The core strategy is an LSP pool plus optional in-process workers, so high-concurrency requests stay responsive while memory remains bounded.

## Why This Project

Compared with existing Lean MCP servers, this project emphasizes:

- High-concurrency LSP dispatch with pooled `lean --server` workers.
- Memory optimization path for Mathlib-heavy workloads (`--inprocess`).
- A broader integrated toolset (LSP + search + LLM + Lean metaprogramming + patching).

| Category | Tool union |
|---|---|
| Proof state / diagnostics | `lean_goal`, `lean_term_goal`, `lean_diagnostic_messages`, `lean_hover_info`, `lean_completions`, `lean_code_actions`, `lean_get_widgets`, `lean_get_widget_source`, `lean_verify`, `check_lean` |
| File / project operations | `lean_file_outline`, `lean_file_contents`, `lean_declaration_file`, `lean_local_search`, `lean_build`, `lean_apply_patch`, `execute-lean`, `execute-lean-persistent`, `cleanup-session` |
| Code execution / profiling | `lean_run_code`, `lean_multi_attempt`, `lean_profile_proof` |
| Mathlib search | `lean_leansearch`, `lean_loogle`, `lean_leanfinder`, `lean_state_search`, `lean_hammer_premise`, `lean_unified_search` |
| LLM / metaprogramming | `lean_llm_query`, `lean_havelet_extract`, `lean_analyze_deps`, `lean_export_decls` |


## Tool Signatures and Examples

Call format (MCP):

```json
{
  "method": "tools/call",
  "params": {
    "name": "lean_goal",
    "arguments": {
      "file_path": "/abs/path/to/File.lean",
      "line": 10
    }
  }
}
```

Each row includes signature + one example.  

| Tool | Purpose | Example `arguments` |
|---|---|---|
| `lean_goal` | Inspect proof goals at a cursor position. | `{"file_path":"/abs/path/to/Foo.lean","line":120,"column":17}` |
| `lean_term_goal` | Check the expected type at a position. | `{"file_path":"/abs/path/to/Foo.lean","line":120}` |
| `lean_diagnostic_messages` | Read Lean errors, warnings, and infos. | `{"file_path":"/abs/path/to/Foo.lean","start_line":1,"end_line":200}` |
| `lean_hover_info` | Get symbol type and documentation. | `{"file_path":"/abs/path/to/Foo.lean","line":18,"column":9}` |
| `lean_completions` | Return IDE completion candidates. | `{"file_path":"/abs/path/to/Foo.lean","line":34,"column":12,"max_completions":20}` |
| `lean_file_outline` | Show imports and declaration outline. | `{"file_path":"/abs/path/to/Foo.lean"}` |
| `lean_file_contents` | Read file content with optional range. | `{"file_path":"/abs/path/to/Foo.lean","start_line":1,"end_line":80}` |
| `lean_declaration_file` | Locate the file defining a symbol. | `{"file_path":"/abs/path/to/Foo.lean","symbol":"Nat.add_assoc"}` |
| `lean_local_search` | Search local declarations by name prefix. | `{"file_path":"/abs/path/to/Foo.lean","query":"simp","limit":10}` |
| `lean_run_code` | Run a standalone Lean snippet and report diagnostics. | `{"code":"import Mathlib\\n#check Nat.succ"}` |
| `lean_multi_attempt` | Try multiple tactics on one goal state. | `{"file_path":"/abs/path/to/Foo.lean","line":88,"tactics":["simp","aesop","linarith"]}` |
| `lean_apply_patch` | Apply targeted edits to a Lean file. | `{"file_path":"/abs/path/to/Foo.lean","start_line":20,"end_line":22,"new_content":"  simp"}` |
| `lean_leansearch` | Search Mathlib by natural language query. | `{"query":"sum of two even numbers is even","num_results":5}` |
| `lean_loogle` | Search by type pattern via Loogle. | `{"query":"(?a -> ?b) -> List ?a -> List ?b","num_results":8}` |
| `lean_leanfinder` | Run semantic theorem search via LeanFinder. | `{"query":"commutativity of addition on natural numbers","num_results":5}` |
| `lean_state_search` | Find lemmas relevant to current goal state. | `{"file_path":"/abs/path/to/Foo.lean","line":102,"column":7,"num_results":5}` |
| `lean_hammer_premise` | Suggest premises for `simp` or `aesop`. | `{"file_path":"/abs/path/to/Foo.lean","line":102,"column":7,"num_results":20}` |
| `lean_unified_search` | Merge multiple theorem-search backends in parallel. | `{"query":"Cauchy-Schwarz inequality","num_results":5,"backends":["leansearch","loogle","leanfinder"]}` |
| `lean_llm_query` | Ask an LLM for Lean/math assistance. | `{"prompt":"Translate this statement into Lean 4:","model":"deepseek-chat","temperature":0.0}` |
| `lean_havelet_extract` | Extract local `have/let` into top-level declarations. | `{"file_path":"/abs/path/to/Foo.lean","prefix":"Extracted"}` |
| `lean_analyze_deps` | Analyze theorem-level dependency graph in a file. | `{"file_path":"/abs/path/to/Foo.lean"}` |
| `lean_export_decls` | Export module declarations to JSONL dataset. | `{"modules":["Mathlib.Topology","Mathlib.Algebra"],"output_path":"/tmp/decls.jsonl"}` |


## Comparison with other MCP tools

- [lean-lsp-mcp](https://github.com/oOo0oOo/lean-lsp-mcp)

| Tool | lean-tools-mcp | lean-lsp-mcp |
|---|---|---|
| `lean_goal` | ✅ | ✅ |
| `lean_term_goal` | ✅ | ✅ |
| `lean_diagnostic_messages` | ✅ | ✅ |
| `lean_hover_info` | ✅ | ✅ |
| `lean_completions` | ✅ | ✅ |
| `lean_file_outline` | ✅ | ✅ |
| `lean_file_contents` | ✅ |  |
| `lean_declaration_file` | ✅ | ✅ |
| `lean_local_search` | ✅ | ✅ |
| `lean_run_code` | ✅ | ✅ |
| `lean_multi_attempt` | ✅ | ✅ |
| `lean_apply_patch` | ✅ |  |
| `lean_code_actions` |  | ✅ |
| `lean_get_widgets` |  | ✅ |
| `lean_get_widget_source` |  | ✅ |
| `lean_profile_proof` |  | ✅ |
| `lean_verify` |  | ✅ |
| `lean_build` |  | ✅ |
| `lean_leansearch` | ✅ | ✅ |
| `lean_loogle` | ✅ | ✅ |
| `lean_leanfinder` | ✅ | ✅ |
| `lean_state_search` | ✅ | ✅ |
| `lean_hammer_premise` | ✅ | ✅ |
| `lean_unified_search` | ✅ |  |
| `lean_llm_query` | ✅ |  |
| `lean_havelet_extract` | ✅ |  |
| `lean_analyze_deps` | ✅ |  |
| `lean_export_decls` | ✅ |  |

还有一些其他的 MCP，可以参考 [lean-docker-mcp](https://github.com/misanthropic-ai/lean-docker-mcp) 和 [LeanTool](https://github.com/GasStationManager/LeanTool)。



## Quick Start

### Prerequisites

- Python >= 3.11
- Lean 4 via [elan](https://github.com/leanprover/elan)
- A Lean project containing `lakefile.lean`

### Install

```bash
git clone <this-repo>
cd lean-tools-mcp
pip install -e ".[sse,dev]"
```

### Run (stdio)

```bash
lean-tools-mcp --project-root /path/to/lean-project
```

### Run (SSE)

```bash
lean-tools-mcp --transport sse --host 0.0.0.0 --port 8080 --project-root /path/to/lean-project
```

SSE endpoints:

- `GET /sse`
- `POST /messages`
- `GET /health`

### Key flags

- `--project-root PATH`
- `--pool-size N`
- `--inprocess` (memory-optimized mode for heavy imports)
- `--transport stdio|sse`
- `--config PATH`
- `-v, --verbose`

## Local Archive Note

The previous full README has been archived locally at:

- `docs_inside/_private/README_original_2026-03-02.md`

This path is intentionally ignored by Git and not intended for GitHub publishing.


## Memory Optimization Setup (Read This First)

If you want the memory-saving behavior, `--inprocess` by itself is not enough. You also need a **patched Lean binary** (Phase 2 changes) and a correct Lean project root.
All build scripts, Lean helper sources, and patches are organized under `memory_optimization/`.

### Download + One-Click Install

```bash
git clone https://github.com/optsuite/lean-tools-mcp.git
cd lean-tools-mcp
bash memory_optimization/scripts/one_click_setup.sh
```

Default behavior of `memory_optimization/scripts/one_click_setup.sh`:

- Resolve Lean `v4.29.0` to build tag `v4.29.0-rc2` (upstream available tag for commit `83e54b65`).
- Build patched Lean and install it under `~/lean-builds/v4.29.0-rc2/bin/lean`.
- Create/update project `~/lean-mcp-v429` with matching `lean-toolchain` and pinned Mathlib revision (`v4.29.0-rc2`).
- Run `lake update` and `lake exe cache get`.
- Install this MCP package (`pip install -e ".[sse,dev]"`).
- Add MCP entries to Codex and Claude config files (Cursor optional).

Useful options (aligned with script flags):

```bash
# Use existing patched lean, skip pip install, and also write Cursor config
bash memory_optimization/scripts/one_click_setup.sh \
  --project-root /abs/path/to/my-lean-project \
  --lean-path /abs/path/to/patched/lean \
  --no-install-python \
  --install-cursor
```

### Add MCP in Codex / Claude

Auto mode:

- By default, one-click setup writes:
- Codex: `~/.codex/config.toml`
- Claude: `~/Library/Application Support/Claude/claude_desktop_config.json`

Manual mode (if you prefer not to let the script edit config):

```bash
bash memory_optimization/scripts/one_click_setup.sh --no-install-codex --no-install-claude
```

1. Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.lean-tools-mcp]
command = "lean-tools-mcp"
args = [
  "--project-root", "/abs/path/to/your/lean-project",
  "--inprocess",
  "--lean-path", "/abs/path/to/patched/lean"
]
```

2. Claude (`~/Library/Application Support/Claude/claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "lean-tools-mcp": {
      "command": "lean-tools-mcp",
      "args": [
        "--project-root", "/abs/path/to/your/lean-project",
        "--inprocess",
        "--lean-path", "/abs/path/to/patched/lean"
      ]
    }
  }
}
```

### Requirements

1. Patched Lean build is required.
   Use this repo's `memory_optimization/scripts/build_lean.py`; supported patch families are `v4.27.x`, `v4.28.x`, and `v4.29.x`.
2. Lean version must match your target project's `lean-toolchain`.
   Example: if the project uses `v4.29.0-rc2`, build and run the patched `v4.29.0-rc2` binary.
3. `--project-root` must point to the Lean project root.
   It should contain `lakefile.lean` and usually `lean-toolchain`.
4. Mathlib projects should prepare dependencies before MCP startup.
   Run `lake update` and `lake exe cache get` in the project root first.
5. Tool `file_path` arguments should be absolute paths under that project root.

### Install Patched Lean

```bash
# 1) Build patched Lean matching your project toolchain
python memory_optimization/scripts/build_lean.py --version v4.29.0-rc2 --output ~/lean-builds

# 2) Verify binary version
~/lean-builds/v4.29.0-rc2/bin/lean --version
```

### Start MCP with Memory Optimization (Recommended: Explicit `--lean-path`)

```bash
lean-tools-mcp \
  --project-root /abs/path/to/your/lean-project \
  --inprocess \
  --lean-path ~/lean-builds/v4.29.0-rc2/bin/lean
```

### Alternative: Auto-Detect Patched Lean from `LEAN_BUILDS_DIR`

```bash
export LEAN_WORKER_INPROCESS=1
export LEAN_BUILDS_DIR=~/lean-builds

lean-tools-mcp --project-root /abs/path/to/your/lean-project
```

The auto-detect flow reads the project's `lean-toolchain` and looks for:
`$LEAN_BUILDS_DIR/<version_tag>/bin/lean`

### Quick Self-Check

1. Startup logs should show `In-process worker mode enabled`.
2. Startup logs should show the expected patched Lean binary path/version.
3. If memory does not drop, first check version mismatch between `lean-toolchain` and patched binary.



Data below is organized from project docs/source snapshots checked on 2026-03-02.


## Mathlib Memory Savings by Version / Scenario

Benchmark source files are under `docs/bench_memory_*.json`. Metric here is **peak total RSS (MB)** from `snapshots[].total_rss_mb`.

| Lean version | Mathlib scenario | Process peak RSS | In-process peak RSS | Memory saved |
|---|---:|---:|---:|---:|
| 4.29.0 (commit `83e54b65`) | 3 files | 8507.1 MB | 3060.1 MB | 64.0% |
| 4.29.0 (commit `83e54b65`) | 5 files | 13721.3 MB | 2934.9 MB | 78.6% |
| 4.29.0-rc2 patched build (reports `4.29.0`, commit `83e54b65`) | 3 files | 8577.7 MB | 3098.2 MB | 63.9% |

Principle (brief): in-process mode keeps workers in one process and reuses imported Lean environment data, so repeated Mathlib import cost is paid mainly once instead of once per worker.

Optimization scope:

- In-process optimization is implemented for patched Lean `v4.27.x` / `v4.28.x` / `v4.29.x` builds.
- Published Mathlib process-vs-in-process measurements in this README are currently complete for Lean `4.29.0` and patched `4.29.0-rc2` builds (commit `83e54b65`).




## The Authors
We hope that the package is useful for your application. If you have any bug reports or comments, please feel free to email one of the toolbox authors:
- Ziyu Wang, School of Mathematical Sciences, Peking University, China (`wangziyu-edu@stu.pku.edu.cn`)
- Zichen Wang, School of Mathematical Sciences, Peking University, China (`zichenwang25@stu.pku.edu.cn`)
- Zaiwen Wen, Beijing International Center for Mathematical Research, Peking University, China (`wenzw@pku.edu.cn`)

## Citation

If you use this project in your research, please cite:

```bibtex
@software{wang2026lean_tools_mcp,
  author       = {Ziyu Wang and Zichen Wang and Zaiwen Wen},
  title        = {lean-tools-mcp: MCP Server for Lean 4 with In-Process Memory Optimization},
  year         = {2026},
  version      = {0.1.0},
  url          = {https://github.com/optsuite/lean-tools-mcp},
  note         = {Accessed: 2026-03-07}
}
```

Contact: `wangziyu-edu@stu.pku.edu.cn`, `optsuite@lean-tools-mcp`

## License

MIT License. See [LICENSE](LICENSE).
