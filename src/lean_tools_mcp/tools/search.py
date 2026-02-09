"""
Search tools — external HTTP search for Lean theorems.

Each tool wraps an HTTP client with rate limiting and formats results
for MCP consumption. Tools that need proof state (state_search, hammer_premise)
first query the LSP for the goal at the given position.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..clients.rate_limiter import SlidingWindowLimiter
from ..clients.search import (
    SearchResponse,
    SearchResult,
    hammer_premise_query,
    leanfinder_query,
    leansearch_query,
    loogle_query,
    state_search_query,
)
from ..lsp.pool import LSPPool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_search_results(
    results: list[SearchResult],
    include_type: bool = True,
    include_doc: bool = True,
    include_module: bool = False,
) -> str:
    """Format search results into a readable string."""
    if not results:
        return "No results found."

    parts: list[str] = []
    for i, r in enumerate(results, 1):
        lines: list[str] = [f"{i}. {r.name}"]
        if include_type and r.type:
            lines.append(f"   Type: {r.type}")
        if include_doc and r.doc:
            # Truncate long docs
            doc = r.doc.strip().replace("\n", " ")
            if len(doc) > 200:
                doc = doc[:200] + "..."
            lines.append(f"   Doc: {doc}")
        if include_module and r.module:
            lines.append(f"   Module: {r.module}")
        if r.kind:
            lines.append(f"   Kind: {r.kind}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _format_premise_results(results: list[SearchResult]) -> str:
    """Format hammer premise results (just names, for use with simp/aesop)."""
    if not results:
        return "No premises found."

    names = [r.name for r in results]
    parts: list[str] = []
    parts.append(f"Found {len(names)} premise(s):\n")

    # List form
    for i, name in enumerate(names, 1):
        parts.append(f"  {i}. {name}")

    # Simp hint
    parts.append(f"\nsimp only [{', '.join(names[:10])}]")

    return "\n".join(parts)


def _format_error(response: SearchResponse, tool_name: str) -> str:
    """Format an error response."""
    return f"[{tool_name}] Error: {response.error}"


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

async def lean_leansearch(
    limiter: SlidingWindowLimiter,
    query: str,
    num_results: int = 5,
) -> str:
    """Search Mathlib via leansearch.net using natural language.

    Examples:
      - "sum of two even numbers is even"
      - "Cauchy-Schwarz inequality"
      - "{f : A → B} (hf : Injective f) : ∃ g, LeftInverse g f"

    Args:
        limiter: Rate limiter instance.
        query: Natural language or Lean term query.
        num_results: Max results (default 5).

    Returns:
        Formatted search results or error message.
    """
    async with limiter.acquire("leansearch"):
        response = await leansearch_query(query, num_results)

    if response.error:
        return _format_error(response, "LeanSearch")

    return _format_search_results(
        response.results,
        include_type=True,
        include_doc=True,
        include_module=True,
    )


async def lean_loogle(
    limiter: SlidingWindowLimiter,
    query: str,
    num_results: int = 8,
) -> str:
    """Search Mathlib by type signature via loogle.lean-lang.org.

    Examples:
      - `Real.sin`
      - `"comm"`
      - `(?a → ?b) → List ?a → List ?b`
      - `_ * (_ ^ _)`
      - `|- _ < _ → _ + 1 < _ + 1`

    Args:
        limiter: Rate limiter instance.
        query: Type pattern, constant, or name substring.
        num_results: Max results (default 8).

    Returns:
        Formatted search results or error message.
    """
    async with limiter.acquire("loogle"):
        response = await loogle_query(query, num_results)

    if response.error:
        return _format_error(response, "Loogle")

    return _format_search_results(
        response.results,
        include_type=True,
        include_doc=True,
        include_module=True,
    )


async def lean_leanfinder(
    limiter: SlidingWindowLimiter,
    query: str,
    num_results: int = 5,
) -> str:
    """Semantic search for Mathlib via Lean Finder.

    Examples:
      - "commutativity of addition on natural numbers"
      - "I have h : n < m and need n + 1 < m + 1"
      - proof state text

    Args:
        limiter: Rate limiter instance.
        query: Mathematical concept or proof state.
        num_results: Max results (default 5).

    Returns:
        Formatted search results or error message.
    """
    async with limiter.acquire("leanfinder"):
        response = await leanfinder_query(query, num_results)

    if response.error:
        return _format_error(response, "LeanFinder")

    return _format_search_results(
        response.results,
        include_type=True,
        include_doc=True,
        include_module=False,
    )


async def lean_state_search(
    limiter: SlidingWindowLimiter,
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    column: int,
    num_results: int = 5,
) -> str:
    """Find lemmas to close the goal at a position. Searches premise-search.com.

    First gets the proof goal at (line, column) from LSP, then sends it to
    premise-search.com to find applicable theorems.

    Args:
        limiter: Rate limiter instance.
        lsp_pool: LSP connection pool (for goal state).
        file_path: Absolute path to the .lean file.
        line: Line number (1-indexed).
        column: Column number (1-indexed).
        num_results: Max results (default 5).

    Returns:
        Formatted search results or error message.
    """
    # Step 1: Get goal state from LSP
    goal_result = await lsp_pool.get_goal(file_path, line, column)
    goal_state = goal_result.get("goals", "")
    if not goal_state or goal_state == "no goals":
        return "No goals at this position (proof may already be complete)."

    # Step 2: Search
    async with limiter.acquire("state_search"):
        response = await state_search_query(goal_state, num_results)

    if response.error:
        return _format_error(response, "StateSearch")

    header = f"Goal: {goal_state[:200]}\n\n"
    return header + _format_search_results(
        response.results,
        include_type=True,
        include_doc=False,
        include_module=True,
    )


async def lean_hammer_premise(
    limiter: SlidingWindowLimiter,
    lsp_pool: LSPPool,
    file_path: str,
    line: int,
    column: int,
    num_results: int = 32,
) -> str:
    """Get premise suggestions for automation tactics at a goal position.

    Returns lemma names to try with `simp only [...]`, `aesop`, or as hints.

    First gets the proof goal from LSP, then queries the Lean Hammer
    premise server for relevant lemmas.

    Args:
        limiter: Rate limiter instance.
        lsp_pool: LSP connection pool (for goal state).
        file_path: Absolute path to the .lean file.
        line: Line number (1-indexed).
        column: Column number (1-indexed).
        num_results: Max results (default 32).

    Returns:
        Formatted premise list or error message.
    """
    # Step 1: Get goal state from LSP
    goal_result = await lsp_pool.get_goal(file_path, line, column)
    goal_state = goal_result.get("goals", "")
    if not goal_state or goal_state == "no goals":
        return "No goals at this position (proof may already be complete)."

    # Step 2: Search
    async with limiter.acquire("hammer_premise"):
        response = await hammer_premise_query(goal_state, num_results)

    if response.error:
        return _format_error(response, "HammerPremise")

    header = f"Goal: {goal_state[:200]}\n\n"
    return header + _format_premise_results(response.results)
