"""
Global configuration for Lean Tools MCP Server.

Configuration is loaded from (in order of precedence):
  1. CLI arguments (highest priority)
  2. Environment variables
  3. config.json file
  4. Default values (lowest priority)

Environment variables:
  LEAN_EXECUTABLE    Path to the lean binary (default: "lean", auto-detected via elan)
  LEAN_LSP_POOL_SIZE Number of LSP server instances (default: 2)
  LEAN_LSP_TIMEOUT   LSP request timeout in seconds (default: 60)
  LLM_DEFAULT_MODEL  Default LLM model name (default: "deepseek-chat")
  MCP_TRANSPORT      Transport mode: "stdio" or "sse" (default: "stdio")
  MCP_SSE_HOST       SSE server host (default: "127.0.0.1")
  MCP_SSE_PORT       SSE server port (default: 8080)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LSPConfig:
    """Configuration for the LSP connection pool."""

    # Path to the lean executable (auto-detected if not set)
    lean_path: str = "lean"
    # Number of LSP server instances in the pool
    pool_size: int = 2
    # Timeout for LSP requests (seconds)
    request_timeout: float = 60.0
    # Timeout for waiting for file checking to complete (seconds)
    file_check_timeout: float = 120.0


@dataclass
class LLMProviderEntry:
    """A single LLM API provider entry."""

    api_key: str
    api_base: str


@dataclass
class LLMConfig:
    """Configuration for LLM API access."""

    providers: dict[str, list[LLMProviderEntry]] = field(default_factory=dict)
    default_model: str = "deepseek-chat"
    default_source: str = ""


@dataclass
class ServerConfig:
    """Top-level server configuration."""

    # Root directory of the Lean project being served
    project_root: Path = field(default_factory=lambda: Path.cwd())
    # Transport mode: "stdio" or "sse"
    transport: str = "stdio"
    # SSE host/port (only used when transport="sse")
    sse_host: str = "127.0.0.1"
    sse_port: int = 8080

    lsp: LSPConfig = field(default_factory=LSPConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)


def load_llm_providers(config_path: Path | str | None = None) -> dict[str, list[LLMProviderEntry]]:
    """Load LLM provider entries from a config.json file.

    Expected format::

        {
            "api": {
                "openai": [{"api_key": "...", "api_base": "..."}],
                "deepseek": [{"api_key": "...", "api_base": "..."}],
                ...
            }
        }
    """
    if config_path is None:
        # Look in current directory, then home directory
        candidates = [
            Path.cwd() / "config.json",
            Path.home() / ".lean-tools-mcp" / "config.json",
        ]
        for c in candidates:
            if c.exists():
                config_path = c
                break

    if config_path is None:
        return {}

    config_path = Path(config_path)
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        data: dict[str, Any] = json.load(f)

    api_section = data.get("api", {})
    providers: dict[str, list[LLMProviderEntry]] = {}
    for provider_name, entries in api_section.items():
        providers[provider_name] = [
            LLMProviderEntry(api_key=e["api_key"], api_base=e["api_base"])
            for e in entries
            if "api_key" in e and "api_base" in e
        ]
    return providers


def load_config(
    project_root: Path | str | None = None,
    config_path: Path | str | None = None,
) -> ServerConfig:
    """Build a ServerConfig from environment variables and config files.

    Args:
        project_root: Root directory of the Lean project. Falls back to cwd.
        config_path: Path to config.json for LLM providers.

    Returns:
        Fully populated ServerConfig.
    """
    root = Path(project_root) if project_root else Path.cwd()

    # NOTE: We use LEAN_EXECUTABLE (not LEAN_PATH) to avoid collision
    # with Lean's own LEAN_PATH environment variable for search paths.
    lsp = LSPConfig(
        lean_path=os.environ.get("LEAN_EXECUTABLE", "lean"),
        pool_size=int(os.environ.get("LEAN_LSP_POOL_SIZE", "2")),
        request_timeout=float(os.environ.get("LEAN_LSP_TIMEOUT", "60")),
    )

    providers = load_llm_providers(config_path)
    llm = LLMConfig(
        providers=providers,
        default_model=os.environ.get("LLM_DEFAULT_MODEL", "deepseek-chat"),
    )

    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    sse_host = os.environ.get("MCP_SSE_HOST", "127.0.0.1")
    sse_port = int(os.environ.get("MCP_SSE_PORT", "8080"))

    return ServerConfig(
        project_root=root,
        transport=transport,
        sse_host=sse_host,
        sse_port=sse_port,
        lsp=lsp,
        llm=llm,
    )
