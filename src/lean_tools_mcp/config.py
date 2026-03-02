# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Global configuration for Lean Tools MCP Server.

Configuration is loaded from (in order of precedence):
  1. CLI arguments (highest priority)
  2. Environment variables
  3. config.json file
  4. Default values (lowest priority)

Environment variables:
  LEAN_EXECUTABLE        Path to the lean binary (default: "lean", auto-detected via elan)
  LEAN_LSP_POOL_SIZE     Number of LSP server instances (default: 2)
  LEAN_LSP_TIMEOUT       LSP request timeout in seconds (default: 60)
  LEAN_WORKER_INPROCESS  Set to "1" to use in-process workers (shared Environment, saves memory)
  LEAN_BUILDS_DIR        Directory containing modified lean builds (default: ~/lean-builds/)
  LLM_DEFAULT_MODEL      Default LLM model name (default: "deepseek-chat")
  MCP_TRANSPORT          Transport mode: "stdio" or "sse" (default: "stdio")
  MCP_SSE_HOST           SSE server host (default: "127.0.0.1")
  MCP_SSE_PORT           SSE server port (default: 8080)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
    # Use in-process workers (requires modified lean with Phase 2 changes).
    # Shares Environment across workers, reducing memory by ~80% for Mathlib.
    use_inprocess_workers: bool = False
    # Directory containing modified lean builds produced by scripts/build_lean.py.
    # Structure: <builds_dir>/<version_tag>/bin/lean
    lean_builds_dir: Path | None = None


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


def read_lean_toolchain(project_root: Path) -> str | None:
    """Read the Lean version from the project's lean-toolchain file.

    Returns the version tag (e.g. 'v4.28.0') or None if not found.
    """
    toolchain_file = project_root / "lean-toolchain"
    if not toolchain_file.exists():
        return None
    text = toolchain_file.read_text().strip()
    # Format: "leanprover/lean4:v4.28.0" or just "v4.28.0"
    if ":" in text:
        text = text.split(":", 1)[1]
    text = text.strip()
    if re.match(r"v?\d+\.\d+\.\d+", text):
        return text if text.startswith("v") else f"v{text}"
    return None


def find_modified_lean_binary(
    lean_builds_dir: Path,
    version_tag: str,
) -> Path | None:
    """Find a modified lean binary matching the given version.

    Searches for exact version match first, then tries the minor-version
    family (e.g. v4.28.0 matches a build at v4.28.0-rc2).
    """
    # Exact match
    exact = lean_builds_dir / version_tag / "bin" / "lean"
    if exact.exists():
        return exact

    # Try matching any build in the same minor-version family
    m = re.match(r"(v\d+\.\d+)\.\d+", version_tag)
    if m:
        prefix = m.group(1)
        if lean_builds_dir.exists():
            candidates = sorted(lean_builds_dir.iterdir(), reverse=True)
            for d in candidates:
                if d.is_dir() and d.name.startswith(prefix):
                    binary = d / "bin" / "lean"
                    if binary.exists():
                        return binary
    return None


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
    lean_path_explicit = os.environ.get("LEAN_EXECUTABLE", "")
    use_inprocess = os.environ.get("LEAN_WORKER_INPROCESS", "") == "1"
    builds_dir_str = os.environ.get("LEAN_BUILDS_DIR", "")
    builds_dir = Path(builds_dir_str) if builds_dir_str else Path.home() / "lean-builds"

    lean_path = lean_path_explicit or "lean"

    # Auto-detect modified binary when inprocess mode is requested
    # and no explicit lean binary was specified.
    if use_inprocess and not lean_path_explicit:
        version_tag = read_lean_toolchain(root)
        if version_tag and builds_dir.exists():
            modified_bin = find_modified_lean_binary(builds_dir, version_tag)
            if modified_bin:
                lean_path = str(modified_bin)
                logger.info(
                    "Auto-detected modified lean binary for %s: %s",
                    version_tag,
                    lean_path,
                )
            else:
                logger.warning(
                    "In-process mode requested but no modified lean binary "
                    "found for %s in %s. Falling back to default lean.",
                    version_tag,
                    builds_dir,
                )
        elif version_tag:
            logger.debug(
                "Lean version %s detected but builds dir %s does not exist.",
                version_tag,
                builds_dir,
            )

    lsp = LSPConfig(
        lean_path=lean_path,
        pool_size=int(os.environ.get("LEAN_LSP_POOL_SIZE", "2")),
        request_timeout=float(os.environ.get("LEAN_LSP_TIMEOUT", "60")),
        use_inprocess_workers=use_inprocess,
        lean_builds_dir=builds_dir if builds_dir.exists() else None,
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
