# Lean Tools MCP Server - Project Summary

## 1. Project Overview

This project implements an **MCP (Model Context Protocol) server** for **Lean 4** formal proving workflows, so AI coding assistants such as Cursor and Claude Desktop can call Lean tooling directly. The server currently provides **21 tools** across four capability groups: LSP interaction, theorem search, LLM integration, and Lean metaprogramming.

**Key metrics:**
- About **4,600 lines** of Python source code (excluding tests), and about **1,800 lines** of Lean metaprogramming code
- About **2,900 lines** of test code, with **193 test cases all passing**
- Supports both **stdio** and **SSE/HTTP** transport modes
- Repository: https://github.com/TropicalFatFish/lean-tools-mcp (private)

---

## 2. Overall Architecture

```text
┌──────────────────┐         ┌──────────────────────────────────────────┐
│   MCP Clients     │◄──────►│            MCP Server (Python)           │
│ Cursor / Claude   │ stdio  │                                          │
│ Remote clients    │ SSE    │  ┌────────────┐    ┌──────────────────┐  │
│                   │        │  │ Tool Registry│   │   LSP Pool        │  │
└──────────────────┘         │  │ 21 tools     │   │ lean --server ×N │  │
                             │  └────────────┘    │ (round-robin)     │  │
                             │                    └──────────────────┘  │
                             │  ┌────────────┐    ┌──────────────────┐  │
                             │  │ External   │    │   LLM Client      │  │
                             │  │ Search HTTP│    │ Multi-provider +  │  │
                             │  │ + sliding  │    │ key rotation +    │  │
                             │  │ window rate│    │ retry + fallback  │  │
                             │  │ limiter    │    └──────────────────┘  │
                             │  └────────────┘                          │
                             │  ┌──────────────────────────────────┐   │
                             │  │ Lean metaprogramming CLI tools   │   │
                             │  │ (subprocess calls)               │   │
                             │  │ havelet_generator / definition_tool│ │
                             │  │ decl_exporter                     │   │
                             │  └──────────────────────────────────┘   │
                             └──────────────────────────────────────────┘
```

**Design highlights:**
- **LSP pooling architecture**: instead of a REPL, requests are handled by a pool of `lean --server` LSP instances. Each instance has a fixed memory cost and supports high-concurrency calls.
- **End-to-end async stack**: built on Python `asyncio`, with asynchronous I/O for LSP communication, HTTP search, and LLM requests.
- **Dual transport modes**: stdio for local IDE integration, SSE/HTTP for remote deployment.

---

## 3. Phase-by-Phase Implementation

### Phase 1: Base framework and LSP protocol layer

| Module | File | Description |
|------|------|------|
| JSON-RPC 2.0 protocol | `lsp/protocol.py` | Full message encode/decode, request-response matching, and notification dispatch |
| LSP client | `lsp/client.py` | Manages one `lean --server` process, including `initialize`, `textDocument/didOpen`, and related protocol calls |
| File manager | `lsp/file_manager.py` | Manages LSP document versions, temp files, and diagnostics events |
| LSP types | `lsp/types.py` | Position, Range, Diagnostic, PlainGoal, and related data structures |
| Configuration system | `config.py` | Three-layer configuration: environment variables + config.json + CLI arguments |

### Phase 2: LSP connection pool and core tools

| Module | File | Description |
|------|------|------|
| Connection pool | `lsp/pool.py` | Manages N LSP instances, round-robin scheduling, and fault detection |
| Goal tools | `tools/goal.py` | `lean_goal`, `lean_term_goal` - fetch proof goals and expected types |
| Diagnostics | `tools/diagnostics.py` | `lean_diagnostic_messages` - compiler errors and warnings |
| Hover info | `tools/hover.py` | `lean_hover_info` - type signatures and docs |
| Completions | `tools/completions.py` | `lean_completions` - IDE completion candidates |

### Phase 3: File operations and code execution

| Module | File | Description |
|------|------|------|
| File operations | `tools/file_ops.py` | `lean_file_outline`, `lean_file_contents`, `lean_declaration_file`, `lean_local_search` |
| Code execution | `tools/run_code.py` | `lean_run_code` - run standalone Lean snippets |
| Multi-strategy attempts | `tools/multi_attempt.py` | `lean_multi_attempt` - try multiple tactics and return each resulting goal state |

### Phase 4: External search tools

| Module | File | Description |
|------|------|------|
| Sliding-window rate limiter | `clients/rate_limiter.py` | Generic async rate limiter to avoid API rate-limit violations |
| HTTP search client | `clients/search.py` | HTTP client wrappers for five external APIs |
| Search tools | `tools/search.py` | `lean_leansearch`, `lean_loogle`, `lean_leanfinder`, `lean_state_search`, `lean_hammer_premise` |

### Phase 5: LLM integration and unified search

| Module | File | Description |
|------|------|------|
| LLM client | `llm/client.py` | Multi-provider support (DeepSeek, OpenAI, etc.), key rotation, exponential backoff retries, and provider fallback |
| Unified search | `tools/unified_search.py` | `lean_unified_search` - parallel LeanSearch + Loogle + LeanFinder with deduplication and merge |
| LLM tools | `tools/llm_tools.py` | `lean_llm_query` - request Lean 4 / math reasoning help from LLMs |

### Phase 6: Lean metaprogramming tool migration

| Module | File | Description |
|------|------|------|
| Lean project | `lean/` directory | Standalone Lake project with 4 Lean libraries and 3 executables |
| HaveletGenerator | `lean/src/HaveletGenerator/` | Extract `have`/`let` bindings into top-level declarations (InfoTree traversal) |
| DefinitionTool | `lean/src/DefinitionTool/` | Analyze theorem dependencies (recursive constant-reference analysis in `Expr`) |
| DeclExporter | `lean/src/DeclExporter/` | Batch-export Lean/Mathlib module declarations to JSONL |
| StateExpr | `lean/src/StateExpr/` | Custom tactic to serialize full proof-state expression trees |
| Python wrappers | `tools/lean_meta.py` | `lean_havelet_extract`, `lean_analyze_deps`, `lean_export_decls` via Lean CLI subprocess calls + dynamic `LEAN_PATH` construction |

### Phase 7: SSE transport, config hardening, and documentation

| Module | File | Description |
|------|------|------|
| SSE transport | `server.py` | Built with Starlette + uvicorn, provides `/sse` (event stream), `/messages` (JSON-RPC), `/health` (health check) |
| Configuration management | `config.py` | Fixed `LEAN_PATH` env var conflicts, added SSE host/port config, improved CLI options |
| Project docs | `README.md` | Full usage guide, tool reference, architecture diagram, configuration details |

---

## 4. List of 21 MCP Tools

| Category | Tool | Description |
|------|------|------|
| **Proof state** | `lean_goal` | Get the proof goal at a given position |
| | `lean_term_goal` | Get the expected type at a given position |
| | `lean_diagnostic_messages` | Get compiler diagnostics |
| | `lean_hover_info` | Get symbol type signature and docs |
| | `lean_completions` | Get code completion suggestions |
| **File ops** | `lean_file_outline` | Get declaration outline of a file |
| | `lean_file_contents` | Read file contents |
| | `lean_declaration_file` | Locate symbol definition |
| | `lean_local_search` | Local declaration-name search |
| **Execution** | `lean_run_code` | Run standalone Lean snippets |
| | `lean_multi_attempt` | Try multiple tactics in parallel |
| **External search** | `lean_leansearch` | Natural-language Mathlib search |
| | `lean_loogle` | Type-signature pattern search |
| | `lean_leanfinder` | Semantic concept search |
| | `lean_state_search` | Find closing lemmas from current goal state |
| | `lean_hammer_premise` | Suggest simp/aesop premises |
| | `lean_unified_search` | Parallel multi-backend search (dedupe + merge) |
| **LLM** | `lean_llm_query` | LLM-assisted Lean reasoning |
| **Metaprogramming** | `lean_havelet_extract` | Extract have/let into top-level declarations |
| | `lean_analyze_deps` | Analyze theorem dependencies |
| | `lean_export_decls` | Batch-export module declarations |

---

## 5. Test Coverage

| Test file | Number of tests | Covered area |
|------|------|------|
| `test_protocol.py` | 11 | JSON-RPC protocol layer |
| `test_types.py` | 11 | LSP data types |
| `test_file_manager.py` | 5 | File manager |
| `test_config.py` | 13 | Config loading (including env vars) |
| `test_server.py` | 6 | Tool registry |
| `test_file_ops.py` | 10 | File operation tools |
| `test_hover.py` | 6 | Hover tool |
| `test_completions.py` | 5 | Completion tool |
| `test_run_code.py` | 5 | Code execution |
| `test_multi_attempt.py` | 6 | Multi-strategy attempts |
| `test_rate_limiter.py` | 10 | Rate limiter |
| `test_search.py` | 10 | Search result formatting |
| `test_llm_client.py` | 9 | LLM client |
| `test_unified_search.py` | 10 | Unified search |
| `test_lean_meta.py` | 7 | Metaprogramming wrappers |
| `test_sse.py` | 8 | SSE transport layer |
| `test_version.py` | 5 | Version detection |
| `test_integration.py` | 35 | End-to-end integration tests |
| **Total** | **193** | **All passing** |

---

## 6. Project Structure

```text
lean-tools-mcp/
├── src/lean_tools_mcp/          # Python source (~4,600 LOC)
│   ├── server.py                # MCP server entry (tool registry + transport)
│   ├── config.py                # Configuration
│   ├── lsp/                     # LSP communication layer
│   │   ├── pool.py              # Connection pool
│   │   ├── client.py            # Single LSP client
│   │   ├── protocol.py          # JSON-RPC 2.0 protocol
│   │   ├── file_manager.py      # File manager
│   │   └── types.py             # Data types
│   ├── tools/                   # 21 MCP tools
│   │   ├── goal.py              # Proof-state tools
│   │   ├── diagnostics.py       # Diagnostics
│   │   ├── hover.py             # Hover info
│   │   ├── completions.py       # Completions
│   │   ├── file_ops.py          # File operations
│   │   ├── run_code.py          # Code execution
│   │   ├── multi_attempt.py     # Multi-strategy attempts
│   │   ├── search.py            # External search tools
│   │   ├── unified_search.py    # Unified search
│   │   ├── llm_tools.py         # LLM tools
│   │   └── lean_meta.py         # Metaprogramming wrappers
│   ├── clients/                 # External clients
│   │   ├── rate_limiter.py      # Sliding-window rate limiter
│   │   └── search.py            # HTTP search client
│   ├── llm/                     # LLM integration
│   │   └── client.py            # Multi-provider LLM client
│   └── utils/
│       └── version.py           # Version detection
├── lean/                        # Lean metaprogramming tools (~1,800 LOC)
│   ├── lakefile.lean            # Lake build config
│   ├── lean-toolchain           # Lean version lock
│   └── src/
│       ├── HaveletGenerator/    # have/let extraction
│       ├── DeclExporter/        # Declaration export
│       ├── DefinitionTool/      # Dependency analysis
│       └── StateExpr/           # Proof-state expression tree
├── tests/                       # Tests (~2,900 LOC, 193 cases)
├── docs/                        # Documentation
├── pyproject.toml               # Python project config
└── README.md                    # English README
```
