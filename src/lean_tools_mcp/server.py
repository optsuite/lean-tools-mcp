"""
Lean Tools MCP Server — main entry point.

Registers all tools and handles MCP protocol communication
over stdio or SSE transport.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .clients.rate_limiter import SlidingWindowLimiter, create_default_limiter
from .config import ServerConfig, load_config
from .llm.client import LLMClient
from .lsp.pool import LSPPool
from .tools.completions import lean_completions
from .tools.diagnostics import lean_diagnostic_messages
from .tools.file_ops import (
    lean_declaration_file,
    lean_file_contents,
    lean_file_outline,
    lean_local_search,
)
from .tools.goal import lean_goal, lean_term_goal
from .tools.hover import lean_hover_info
from .tools.llm_tools import lean_llm_query
from .tools.multi_attempt import lean_multi_attempt
from .tools.run_code import lean_run_code
from .tools.search import (
    lean_hammer_premise,
    lean_leanfinder,
    lean_leansearch,
    lean_loogle,
    lean_state_search,
)
from .tools.unified_search import lean_unified_search
from .tools.lean_meta import lean_havelet_extract, lean_analyze_deps, lean_export_decls
from .tools.patch import lean_apply_patch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (JSON Schema for MCP)
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="lean_goal",
        description=(
            "Get proof goals at a position. MOST IMPORTANT tool — use often!\n\n"
            "Omit column to see goals_before (line start) and goals_after (line end), "
            'showing how the tactic transforms the state. "no goals" = proof complete.'
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (1-indexed)",
                    "minimum": 1,
                },
                "column": {
                    "type": "integer",
                    "description": "Column (1-indexed). Omit for before/after",
                    "minimum": 1,
                },
            },
            "required": ["file_path", "line"],
        },
    ),
    Tool(
        name="lean_term_goal",
        description="Get the expected type at a position.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (1-indexed)",
                    "minimum": 1,
                },
                "column": {
                    "type": "integer",
                    "description": "Column (defaults to end of line)",
                    "minimum": 1,
                },
            },
            "required": ["file_path", "line"],
        },
    ),
    Tool(
        name="lean_diagnostic_messages",
        description=(
            "Get compiler diagnostics (errors, warnings, infos) for a Lean file.\n\n"
            '"no goals to be solved" = remove tactics.'
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Filter from line (1-indexed)",
                    "minimum": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": "Filter to line (1-indexed)",
                    "minimum": 1,
                },
                "severity": {
                    "type": "string",
                    "description": "Filter by severity: error, warning, information, hint",
                    "enum": ["error", "warning", "information", "hint"],
                },
                "declaration_name": {
                    "type": "string",
                    "description": "Filter to declaration (slow)",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="lean_hover_info",
        description=(
            "Get type signature and docs for a symbol. Essential for understanding APIs.\n\n"
            "Column must be at the START of the identifier."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (1-indexed)",
                    "minimum": 1,
                },
                "column": {
                    "type": "integer",
                    "description": "Column at START of identifier (1-indexed)",
                    "minimum": 1,
                },
            },
            "required": ["file_path", "line", "column"],
        },
    ),
    Tool(
        name="lean_completions",
        description=(
            "Get IDE autocompletions. Use on INCOMPLETE code (after `.` or partial name)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (1-indexed)",
                    "minimum": 1,
                },
                "column": {
                    "type": "integer",
                    "description": "Column number (1-indexed)",
                    "minimum": 1,
                },
                "max_completions": {
                    "type": "integer",
                    "description": "Max completions (default 32)",
                    "default": 32,
                    "minimum": 1,
                },
            },
            "required": ["file_path", "line", "column"],
        },
    ),
    Tool(
        name="lean_file_outline",
        description="Get imports and declarations with type signatures. Token-efficient.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to Lean file",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="lean_file_contents",
        description="Get file contents with optional line numbers.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to Lean file",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line (1-indexed)",
                    "minimum": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line (1-indexed)",
                    "minimum": 1,
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="lean_declaration_file",
        description="Get file where a symbol is declared. Symbol must be present in file first.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to Lean file containing the symbol",
                },
                "symbol": {
                    "type": "string",
                    "description": "Symbol name (case sensitive, must be in file)",
                },
            },
            "required": ["file_path", "symbol"],
        },
    ),
    Tool(
        name="lean_local_search",
        description=(
            "Fast local search to verify declarations exist. "
            "Use BEFORE trying a lemma name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to any .lean file in the project",
                },
                "query": {
                    "type": "string",
                    "description": "Declaration name or prefix",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max matches (default 10)",
                    "default": 10,
                    "minimum": 1,
                },
            },
            "required": ["file_path", "query"],
        },
    ),
    Tool(
        name="lean_run_code",
        description=(
            "Run a self-contained Lean code snippet and return diagnostics.\n\n"
            "Must include all imports. Creates a temp file, checks via LSP."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Self-contained Lean code with all imports",
                },
            },
            "required": ["code"],
        },
    ),
    Tool(
        name="lean_multi_attempt",
        description=(
            "Try multiple tactics at a position without modifying the file.\n\n"
            "Uses native parallel tactic evaluation when available ($/lean/tryTactics), "
            "falling back to sequential file-based checking. Recommended: 3+ tactics per call."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (1-indexed) where proof goals exist",
                    "minimum": 1,
                },
                "column": {
                    "type": "integer",
                    "description": "Column (1-indexed, defaults to line start)",
                    "minimum": 1,
                },
                "tactics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tactics to try (3+ recommended)",
                },
            },
            "required": ["file_path", "line", "tactics"],
        },
    ),
    Tool(
        name="lean_apply_patch",
        description=(
            "Apply a partial edit to a .lean file. Two modes:\n\n"
            "1. Line replacement: set start_line + end_line to replace that range.\n"
            "2. Search-and-replace: set search to find exact text and replace it.\n\n"
            "Returns the modified region with surrounding context lines."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file",
                },
                "new_content": {
                    "type": "string",
                    "description": "Replacement text (use empty string to delete)",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to replace (1-indexed, inclusive). Use with end_line.",
                    "minimum": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to replace (1-indexed, inclusive). Use with start_line.",
                    "minimum": 1,
                },
                "search": {
                    "type": "string",
                    "description": "Exact text to find and replace. Alternative to line mode.",
                },
                "occurrence": {
                    "type": "integer",
                    "description": "Which occurrence to replace (default 1)",
                    "default": 1,
                    "minimum": 1,
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context around edit (default 5)",
                    "default": 5,
                    "minimum": 0,
                },
            },
            "required": ["file_path", "new_content"],
        },
    ),
    # --- External search tools ---
    Tool(
        name="lean_leansearch",
        description=(
            "Search Mathlib via leansearch.net using natural language.\n\n"
            "Examples: \"sum of two even numbers is even\", \"Cauchy-Schwarz inequality\", "
            "\"{f : A → B} (hf : Injective f) : ∃ h, Bijective h\""
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language or Lean term query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                    "default": 5,
                    "minimum": 1,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="lean_loogle",
        description=(
            "Search Mathlib by type signature via loogle.lean-lang.org.\n\n"
            "Examples: `Real.sin`, `\"comm\"`, `(?a → ?b) → List ?a → List ?b`, "
            "`_ * (_ ^ _)`, `|- _ < _ → _ + 1 < _ + 1`"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Type pattern, constant, or name substring",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max results (default 8)",
                    "default": 8,
                    "minimum": 1,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="lean_leanfinder",
        description=(
            "Semantic search for Mathlib via Lean Finder.\n\n"
            "Examples: \"commutativity of addition on natural numbers\", "
            "\"I have h : n < m and need n + 1 < m + 1\", proof state text."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Mathematical concept or proof state",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                    "default": 5,
                    "minimum": 1,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="lean_state_search",
        description=(
            "Find lemmas to close the goal at a position. Searches premise-search.com.\n\n"
            "Uses the proof goal at the given (line, column) to search for applicable theorems."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (1-indexed)",
                    "minimum": 1,
                },
                "column": {
                    "type": "integer",
                    "description": "Column number (1-indexed)",
                    "minimum": 1,
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                    "default": 5,
                    "minimum": 1,
                },
            },
            "required": ["file_path", "line", "column"],
        },
    ),
    Tool(
        name="lean_hammer_premise",
        description=(
            "Get premise suggestions for automation tactics at a goal position.\n\n"
            "Returns lemma names to try with `simp only [...]`, `aesop`, or as hints."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (1-indexed)",
                    "minimum": 1,
                },
                "column": {
                    "type": "integer",
                    "description": "Column number (1-indexed)",
                    "minimum": 1,
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max results (default 32)",
                    "default": 32,
                    "minimum": 1,
                },
            },
            "required": ["file_path", "line", "column"],
        },
    ),
    # --- Unified search ---
    Tool(
        name="lean_unified_search",
        description=(
            "Parallel multi-backend theorem search with deduplication.\n\n"
            "Runs leansearch, loogle, and leanfinder in parallel on the same query, "
            "merges results, and removes duplicates by theorem name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (natural language or type pattern)",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max results per backend (default 5)",
                    "default": 5,
                    "minimum": 1,
                },
                "backends": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Backends to use (default: all). "
                        "Options: leansearch, loogle, leanfinder"
                    ),
                },
            },
            "required": ["query"],
        },
    ),
    # --- LLM tools ---
    Tool(
        name="lean_llm_query",
        description=(
            "Query an LLM for Lean 4 / math reasoning assistance.\n\n"
            "Uses configured LLM providers (deepseek, openai, etc.) for:\n"
            "- Translating informal math to Lean 4 statements\n"
            "- Suggesting proof strategies and tactics\n"
            "- Explaining Lean 4 syntax and Mathlib conventions"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Your question or request about Lean 4 / math",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (default: from config, e.g. deepseek-chat)",
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature (default 0.0)",
                    "default": 0.0,
                },
            },
            "required": ["prompt"],
        },
    ),
    # --- Lean metaprogramming tools ---
    Tool(
        name="lean_havelet_extract",
        description=(
            "Extract have/let bindings from a Lean file as top-level declarations.\n\n"
            "Parses the input file, finds all local have/let bindings, "
            "closes over free variables (using mkForallFVars/mkLambdaFVars), "
            "and generates a new .lean file with standalone theorem/def declarations."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the input .lean file",
                },
                "prefix": {
                    "type": "string",
                    "description": "Name prefix for generated declarations (default: Extracted)",
                    "default": "Extracted",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="lean_analyze_deps",
        description=(
            "Analyze theorem dependencies in a Lean file.\n\n"
            "For each theorem in the file, extracts all definitions, classes, "
            "structures, and inductives used in the theorem statement. "
            "Returns structured JSON with dependency info including docstrings "
            "and source locations."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .lean file to analyze",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="lean_export_decls",
        description=(
            "Export declarations from Lean/Mathlib modules to JSONL.\n\n"
            "Bulk-exports all declarations from specified modules. "
            "Each record contains: name, kind, module, type (pretty + raw), "
            "value/proof, tactic proof source, dependencies, file path, and position."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "modules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Module name prefixes to export (e.g., ['Mathlib.Topology'])",
                },
                "output_path": {
                    "type": "string",
                    "description": "Path for output JSONL file (auto-generated if omitted)",
                },
            },
            "required": ["modules"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(config: ServerConfig) -> tuple[Server, LSPPool, SlidingWindowLimiter, LLMClient]:
    """Create the MCP server, LSP pool, rate limiter, and LLM client."""

    app = Server("lean-tools-mcp")
    lsp_pool = LSPPool(
        project_root=config.project_root,
        pool_size=config.lsp.pool_size,
        lean_path=config.lsp.lean_path,
        request_timeout=config.lsp.request_timeout,
        file_check_timeout=config.lsp.file_check_timeout,
        use_inprocess_workers=config.lsp.use_inprocess_workers,
    )
    rate_limiter = create_default_limiter()
    llm_client = LLMClient(config.llm)

    # --- Register tool listing ---

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    # --- Register tool handler ---

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            result = await _dispatch_tool(
                lsp_pool, rate_limiter, llm_client, name, arguments
            )
            return [TextContent(type="text", text=result)]
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return [TextContent(type="text", text=f"Error: {e}")]

    return app, lsp_pool, rate_limiter, llm_client


async def _dispatch_tool(
    lsp_pool: LSPPool,
    limiter: SlidingWindowLimiter,
    llm_client: LLMClient,
    name: str,
    args: dict[str, Any],
) -> str:
    """Route a tool call to the correct handler."""

    # --- LSP core tools ---
    if name == "lean_goal":
        return await lean_goal(
            lsp_pool,
            file_path=args["file_path"],
            line=args["line"],
            column=args.get("column"),
        )
    elif name == "lean_term_goal":
        return await lean_term_goal(
            lsp_pool,
            file_path=args["file_path"],
            line=args["line"],
            column=args.get("column"),
        )
    elif name == "lean_diagnostic_messages":
        return await lean_diagnostic_messages(
            lsp_pool,
            file_path=args["file_path"],
            start_line=args.get("start_line"),
            end_line=args.get("end_line"),
            severity=args.get("severity"),
            declaration_name=args.get("declaration_name"),
        )
    elif name == "lean_hover_info":
        return await lean_hover_info(
            lsp_pool,
            file_path=args["file_path"],
            line=args["line"],
            column=args["column"],
        )
    elif name == "lean_completions":
        return await lean_completions(
            lsp_pool,
            file_path=args["file_path"],
            line=args["line"],
            column=args["column"],
            max_completions=args.get("max_completions", 32),
        )

    # --- File operation tools ---
    elif name == "lean_file_outline":
        return await lean_file_outline(
            lsp_pool,
            file_path=args["file_path"],
        )
    elif name == "lean_file_contents":
        return await lean_file_contents(
            file_path=args["file_path"],
            start_line=args.get("start_line"),
            end_line=args.get("end_line"),
        )
    elif name == "lean_declaration_file":
        return await lean_declaration_file(
            lsp_pool,
            file_path=args["file_path"],
            symbol=args["symbol"],
        )
    elif name == "lean_local_search":
        return await lean_local_search(
            file_path=args["file_path"],
            query=args["query"],
            limit=args.get("limit", 10),
        )

    # --- Run code / Multi-attempt tools ---
    elif name == "lean_run_code":
        return await lean_run_code(
            lsp_pool,
            code=args["code"],
        )
    elif name == "lean_multi_attempt":
        return await lean_multi_attempt(
            lsp_pool,
            file_path=args["file_path"],
            line=args["line"],
            tactics=args.get("tactics", args.get("snippets", [])),
            column=args.get("column"),
        )

    # --- Patch tool ---
    elif name == "lean_apply_patch":
        return await lean_apply_patch(
            file_path=args["file_path"],
            new_content=args["new_content"],
            start_line=args.get("start_line"),
            end_line=args.get("end_line"),
            search=args.get("search"),
            occurrence=args.get("occurrence", 1),
            context_lines=args.get("context_lines", 5),
        )

    # --- External search tools ---
    elif name == "lean_leansearch":
        return await lean_leansearch(
            limiter,
            query=args["query"],
            num_results=args.get("num_results", 5),
        )
    elif name == "lean_loogle":
        return await lean_loogle(
            limiter,
            query=args["query"],
            num_results=args.get("num_results", 8),
        )
    elif name == "lean_leanfinder":
        return await lean_leanfinder(
            limiter,
            query=args["query"],
            num_results=args.get("num_results", 5),
        )
    elif name == "lean_state_search":
        return await lean_state_search(
            limiter,
            lsp_pool,
            file_path=args["file_path"],
            line=args["line"],
            column=args["column"],
            num_results=args.get("num_results", 5),
        )
    elif name == "lean_hammer_premise":
        return await lean_hammer_premise(
            limiter,
            lsp_pool,
            file_path=args["file_path"],
            line=args["line"],
            column=args["column"],
            num_results=args.get("num_results", 32),
        )

    # --- Unified search ---
    elif name == "lean_unified_search":
        return await lean_unified_search(
            limiter,
            query=args["query"],
            num_results=args.get("num_results", 5),
            backends=args.get("backends"),
        )

    # --- LLM tools ---
    elif name == "lean_llm_query":
        return await lean_llm_query(
            llm_client,
            prompt=args["prompt"],
            model=args.get("model"),
            temperature=args.get("temperature", 0.0),
        )

    # --- Lean metaprogramming tools ---
    elif name == "lean_havelet_extract":
        return await lean_havelet_extract(
            file_path=args["file_path"],
            prefix=args.get("prefix", "Extracted"),
            user_project_root=str(lsp_pool.project_root),
        )
    elif name == "lean_analyze_deps":
        return await lean_analyze_deps(
            file_path=args["file_path"],
            user_project_root=str(lsp_pool.project_root),
        )
    elif name == "lean_export_decls":
        return await lean_export_decls(
            modules=args["modules"],
            output_path=args.get("output_path"),
            user_project_root=str(lsp_pool.project_root),
        )

    else:
        return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_stdio(config: ServerConfig) -> None:
    """Run the MCP server over stdio transport."""
    app, lsp_pool, _rate_limiter, _llm_client = create_server(config)

    try:
        await lsp_pool.start()
        logger.info("MCP server starting on stdio")
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        await lsp_pool.shutdown()


def _run_sse(config: ServerConfig) -> None:
    """Run the MCP server over SSE/HTTP transport.

    Uses Starlette + uvicorn to serve:
      GET  /sse          — SSE event stream (client connects here)
      POST /messages     — client sends JSON-RPC messages here
      GET  /health       — health check / status endpoint

    This allows remote clients to connect to the server over HTTP.
    """
    try:
        import uvicorn
        from contextlib import asynccontextmanager
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware
        from starlette.routing import Route
        from starlette.responses import JSONResponse
        from mcp.server.sse import SseServerTransport
    except ImportError as e:
        raise RuntimeError(
            f"SSE transport requires extra dependencies: {e}\n"
            "Install with: pip install uvicorn starlette sse-starlette"
        ) from e

    mcp_app, lsp_pool, _rate_limiter, _llm_client = create_server(config)
    sse_transport = SseServerTransport("/messages")

    async def handle_sse(request):
        """Handle SSE connection from client."""
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await mcp_app.run(
                read_stream, write_stream, mcp_app.create_initialization_options()
            )

    async def handle_messages(request):
        """Handle POST messages from client."""
        try:
            await sse_transport.handle_post_message(
                request.scope, request.receive, request._send
            )
        except Exception as e:
            from starlette.responses import Response

            logger.debug("SSE message handling error: %s", e)
            return Response(str(e), status_code=400)

    async def handle_health(request):
        """Health check endpoint."""
        alive = (
            sum(1 for c in lsp_pool.clients if c.is_alive)
            if lsp_pool.is_started
            else 0
        )
        return JSONResponse({
            "status": "ok",
            "lsp_pool": {
                "started": lsp_pool.is_started,
                "alive": alive,
                "total": len(lsp_pool.clients),
            },
            "tools": len(TOOLS),
        })

    @asynccontextmanager
    async def lifespan(app):
        """Manage LSP pool lifecycle with the ASGI server."""
        try:
            await lsp_pool.start()
        except Exception:
            logger.warning("LSP pool failed to start (Lean not available?)")
        logger.info(
            "MCP SSE server ready at http://%s:%d",
            config.sse_host,
            config.sse_port,
        )
        yield
        await lsp_pool.shutdown()
        logger.info("MCP SSE server shut down")

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
            Route("/health", endpoint=handle_health),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ],
        lifespan=lifespan,
    )

    uvicorn.run(
        starlette_app,
        host=config.sse_host,
        port=config.sse_port,
        log_level="info" if not logger.isEnabledFor(logging.DEBUG) else "debug",
    )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Lean Tools MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  # stdio mode (for Cursor / Claude Desktop)
  lean-tools-mcp --project-root ~/my-lean-project

  # SSE mode (remote service, accessible over HTTP)
  lean-tools-mcp --transport sse --port 8080 --project-root ~/my-lean-project

  # with LLM config and debug logging
  lean-tools-mcp --config config.json --verbose
""",
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="Root directory of the Lean project (default: current dir)",
    )
    parser.add_argument(
        "--lean-path",
        type=str,
        default=None,
        help="Path to the lean executable (default: auto-detect via elan)",
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=None,
        help="Number of LSP server instances (default: 2)",
    )
    parser.add_argument(
        "--inprocess",
        action="store_true",
        default=None,
        help="Use in-process workers (shared Environment, saves ~80%% memory with Mathlib)",
    )
    parser.add_argument(
        "--lean-builds-dir",
        type=str,
        default=None,
        help="Directory containing modified lean builds (default: ~/lean-builds/)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=None,
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="SSE server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="SSE server port (default: 8080)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config.json for LLM providers",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,  # MCP uses stdout for protocol
    )

    config = load_config(
        project_root=args.project_root,
        config_path=args.config,
    )

    # Override config with CLI args
    if args.lean_path:
        config.lsp.lean_path = args.lean_path
    if args.pool_size:
        config.lsp.pool_size = args.pool_size
    if args.inprocess:
        config.lsp.use_inprocess_workers = True
    if args.lean_builds_dir:
        from pathlib import Path as _P
        config.lsp.lean_builds_dir = _P(args.lean_builds_dir)
    if args.transport:
        config.transport = args.transport
    if args.host:
        config.sse_host = args.host
    if args.port:
        config.sse_port = args.port

    if config.transport == "stdio":
        asyncio.run(_run_stdio(config))
    elif config.transport == "sse":
        _run_sse(config)
    else:
        raise ValueError(f"Unknown transport: {config.transport}")


if __name__ == "__main__":
    main()
