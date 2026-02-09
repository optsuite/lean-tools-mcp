# Lean Tools MCP

A high-concurrency **Model Context Protocol (MCP)** server for **Lean 4** development tools. It provides 21 tools covering LSP interaction, theorem search, LLM integration, and Lean metaprogramming — all backed by a pooled LSP architecture for massive parallelism with bounded memory.

## Features

- **LSP-backed architecture** — uses `lean --server` instances in a pool (no REPL), supporting high parallelism with low memory footprint
- **Dual transport** — stdio for local IDE integration (Cursor, Claude Desktop) and SSE/HTTP for remote deployment
- **21 MCP tools** in 5 categories:
  - Proof state & diagnostics (goal, hover, completions, etc.)
  - File operations (outline, contents, declarations, local search)
  - External search (LeanSearch, Loogle, LeanFinder, StateSearch, HammerPremise)
  - LLM integration (multi-provider chat, unified search)
  - Lean metaprogramming (have/let extraction, dependency analysis, declaration export)

## Quick Start

### Installation

```bash
# Clone and install
git clone <this-repo>
cd lean-tools-mcp
pip install -e ".[sse,dev]"
```

### Prerequisites

- **Python** >= 3.11
- **Lean 4** installed via [elan](https://github.com/leanprover/elan)
- A Lean project with `lakefile.lean` (for LSP to work properly)

### Usage — stdio (for Cursor / Claude Desktop)

```bash
# Run against a Lean project
lean-tools-mcp --project-root /path/to/lean-project

# With debug logging
lean-tools-mcp --project-root /path/to/lean-project -v

# With LLM config
lean-tools-mcp --project-root /path/to/lean-project --config /path/to/config.json
```

### Usage — SSE (remote service)

```bash
# Start SSE server
lean-tools-mcp --transport sse --port 8080 --project-root /path/to/lean-project

# Bind to all interfaces (for remote access)
lean-tools-mcp --transport sse --host 0.0.0.0 --port 8080 --project-root /path/to/lean-project
```

Once running, endpoints are:
- `GET /sse` — SSE event stream (MCP clients connect here)
- `POST /messages` — JSON-RPC message endpoint
- `GET /health` — health check / status

### Cursor IDE Configuration

Add to your Cursor MCP settings (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "lean-tools": {
      "command": "lean-tools-mcp",
      "args": ["--project-root", "/path/to/lean-project"]
    }
  }
}
```

### Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "lean-tools": {
      "command": "lean-tools-mcp",
      "args": ["--project-root", "/path/to/lean-project"]
    }
  }
}
```

## Tools Reference

### Proof State & Diagnostics

| Tool | Description |
|------|-------------|
| `lean_goal` | Get proof goals at a position (most important tool) |
| `lean_term_goal` | Get expected type at a position |
| `lean_diagnostic_messages` | Get compiler errors, warnings, infos |
| `lean_hover_info` | Get type signature and docs for a symbol |
| `lean_completions` | Get IDE autocompletions |

### File Operations

| Tool | Description |
|------|-------------|
| `lean_file_outline` | Get imports and declarations with type signatures |
| `lean_file_contents` | Get file contents with optional line numbers |
| `lean_declaration_file` | Find where a symbol is declared |
| `lean_local_search` | Fast local search for declaration names |

### Code Execution

| Tool | Description |
|------|-------------|
| `lean_run_code` | Run self-contained Lean code snippets |
| `lean_multi_attempt` | Try multiple tactics without modifying files |

### External Search (Mathlib)

| Tool | Description |
|------|-------------|
| `lean_leansearch` | Natural language search via leansearch.net |
| `lean_loogle` | Type signature search via loogle.lean-lang.org |
| `lean_leanfinder` | Semantic/conceptual search via Lean Finder |
| `lean_state_search` | Find lemmas to close a goal |
| `lean_hammer_premise` | Get premise suggestions for simp/aesop |
| `lean_unified_search` | Parallel multi-backend search with deduplication |

### LLM Integration

| Tool | Description |
|------|-------------|
| `lean_llm_query` | Query LLM for Lean 4 / math reasoning |

### Lean Metaprogramming

| Tool | Description |
|------|-------------|
| `lean_havelet_extract` | Extract have/let bindings as top-level declarations |
| `lean_analyze_deps` | Analyze theorem dependencies |
| `lean_export_decls` | Export module declarations to JSONL |

## Configuration

### CLI Arguments

```
--project-root PATH    Root directory of the Lean project (default: cwd)
--lean-path PATH       Path to the lean executable (default: auto-detect)
--pool-size N          Number of LSP server instances (default: 2)
--transport MODE       Transport mode: stdio or sse (default: stdio)
--host HOST            SSE server host (default: 127.0.0.1)
--port PORT            SSE server port (default: 8080)
--config PATH          Path to config.json for LLM providers
-v, --verbose          Enable debug logging
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LEAN_EXECUTABLE` | Path to the lean binary | `lean` |
| `LEAN_LSP_POOL_SIZE` | Number of LSP instances | `2` |
| `LEAN_LSP_TIMEOUT` | LSP request timeout (seconds) | `60` |
| `LLM_DEFAULT_MODEL` | Default LLM model name | `deepseek-chat` |
| `MCP_TRANSPORT` | Transport mode | `stdio` |
| `MCP_SSE_HOST` | SSE server host | `127.0.0.1` |
| `MCP_SSE_PORT` | SSE server port | `8080` |

### LLM Provider Config (`config.json`)

```json
{
  "api": {
    "deepseek": [
      {"api_key": "sk-...", "api_base": "https://api.deepseek.com"}
    ],
    "openai": [
      {"api_key": "sk-...", "api_base": "https://api.openai.com/v1"}
    ]
  }
}
```

Multiple entries per provider enable **key rotation** for higher throughput. The LLM client automatically falls back across providers if one fails.

## Architecture

```
┌─────────────┐      ┌──────────────────────────────────────┐
│  MCP Client │◄────►│         MCP Server (Python)          │
│  (Cursor /  │      │                                      │
│   Claude)   │      │  ┌──────────┐  ┌─────────────────┐  │
│             │      │  │ Tool     │  │ LSP Pool        │  │
│  stdio/SSE  │      │  │ Registry │  │ ┌─────────────┐ │  │
│             │      │  │          │  │ │lean --server│ │  │
└─────────────┘      │  │ 21 tools │  │ │lean --server│ │  │
                     │  │          │  │ │     ...     │ │  │
                     │  └──────────┘  │ └─────────────┘ │  │
                     │                └─────────────────┘  │
                     │  ┌──────────┐  ┌─────────────────┐  │
                     │  │ Search   │  │ LLM Client      │  │
                     │  │ Clients  │  │ (multi-provider) │  │
                     │  │ + Rate   │  │ + key rotation   │  │
                     │  │ Limiter  │  │ + fallback       │  │
                     │  └──────────┘  └─────────────────┘  │
                     │  ┌──────────────────────────────┐   │
                     │  │ Lean Meta Tools (CLI)        │   │
                     │  │ havelet_generator            │   │
                     │  │ definition_tool              │   │
                     │  │ decl_exporter                │   │
                     │  └──────────────────────────────┘   │
                     └──────────────────────────────────────┘
```

## Project Structure

```
lean-tools-mcp/
├── src/lean_tools_mcp/
│   ├── server.py              # Main MCP server (tool registry, transport)
│   ├── config.py              # Configuration management
│   ├── lsp/
│   │   ├── pool.py            # LSP connection pool
│   │   ├── client.py          # Single LSP client
│   │   ├── protocol.py        # JSON-RPC 2.0 transport
│   │   ├── file_manager.py    # Temporary file management
│   │   └── types.py           # LSP type definitions
│   ├── tools/
│   │   ├── goal.py            # lean_goal, lean_term_goal
│   │   ├── diagnostics.py     # lean_diagnostic_messages
│   │   ├── hover.py           # lean_hover_info
│   │   ├── completions.py     # lean_completions
│   │   ├── file_ops.py        # file_outline, file_contents, declaration_file, local_search
│   │   ├── run_code.py        # lean_run_code
│   │   ├── multi_attempt.py   # lean_multi_attempt
│   │   ├── search.py          # External search tool wrappers
│   │   ├── unified_search.py  # Parallel multi-backend search
│   │   ├── llm_tools.py       # lean_llm_query
│   │   └── lean_meta.py       # Lean metaprogramming tool wrappers
│   ├── clients/
│   │   ├── rate_limiter.py    # Sliding window rate limiter
│   │   └── search.py          # HTTP clients for external APIs
│   ├── llm/
│   │   └── client.py          # Multi-provider LLM client
│   └── utils/
│       └── version.py         # Version detection
├── lean/                       # Lean metaprogramming tools
│   ├── lakefile.lean
│   ├── lean-toolchain
│   └── src/
│       ├── HaveletGenerator/  # have/let extraction
│       ├── DeclExporter/      # Declaration export
│       ├── DefinitionTool/    # Dependency analysis
│       └── StateExpr/         # Proof state expression tree
├── tests/
│   ├── test_server.py
│   ├── test_config.py
│   ├── test_protocol.py
│   ├── test_sse.py
│   ├── test_rate_limiter.py
│   ├── test_search.py
│   ├── test_llm_client.py
│   ├── test_unified_search.py
│   ├── test_lean_meta.py
│   └── test_integration.py
└── pyproject.toml
```

## Development

### Run Tests

```bash
# Unit tests (no Lean needed)
python -m pytest tests/ -v --ignore=tests/test_integration.py --ignore=tests/test_sse.py

# Integration tests (requires Lean + network)
python -m pytest tests/test_integration.py -v -s

# SSE transport tests
python -m pytest tests/test_sse.py -v -s

# All tests
python -m pytest tests/ -v -s
```

### Build Lean Meta Tools

```bash
cd lean
lake update
lake build havelet_generator
lake build decl_exporter
lake build definition_tool
```

If network access requires a proxy:

```bash
export https_proxy=http://127.0.0.1:7897
export http_proxy=http://127.0.0.1:7897
lake update && lake build
```

## License

MIT
