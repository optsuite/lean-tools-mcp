"""
unified_search — parallel multi-backend theorem search with deduplication.

Runs leansearch, loogle, and leanfinder in parallel, merges results,
and removes duplicates by theorem name.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..clients.rate_limiter import SlidingWindowLimiter
from ..clients.search import (
    SearchResponse,
    SearchResult,
    leanfinder_query,
    leansearch_query,
    loogle_query,
)

logger = logging.getLogger(__name__)

# Available backend names
ALL_BACKENDS = ("leansearch", "loogle", "leanfinder")


async def _run_backend(
    limiter: SlidingWindowLimiter,
    backend: str,
    query: str,
    num_results: int,
) -> tuple[str, SearchResponse]:
    """Run a single backend search with rate limiting. Returns (backend_name, response)."""
    try:
        if backend == "leansearch":
            async with limiter.acquire("leansearch"):
                resp = await leansearch_query(query, num_results)
            return backend, resp
        elif backend == "loogle":
            async with limiter.acquire("loogle"):
                resp = await loogle_query(query, num_results)
            return backend, resp
        elif backend == "leanfinder":
            async with limiter.acquire("leanfinder"):
                resp = await leanfinder_query(query, num_results)
            return backend, resp
        else:
            return backend, SearchResponse(error=f"Unknown backend: {backend}")
    except Exception as e:
        logger.warning("Backend %s failed: %s", backend, e)
        return backend, SearchResponse(error=str(e))


def _deduplicate(results: list[tuple[str, SearchResult]]) -> list[tuple[str, SearchResult]]:
    """Deduplicate results by theorem name, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[tuple[str, SearchResult]] = []
    for source, r in results:
        # Normalize name for dedup
        key = r.name.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append((source, r))
    return unique


def _format_unified_results(
    results: list[tuple[str, SearchResult]],
    backend_errors: dict[str, str],
) -> str:
    """Format unified search results into a readable string."""
    parts: list[str] = []

    if not results and not backend_errors:
        return "No results found from any backend."

    # Report any backend errors
    if backend_errors:
        error_lines = [f"  - {name}: {err}" for name, err in backend_errors.items()]
        parts.append("Backend errors:\n" + "\n".join(error_lines))
        parts.append("")

    if not results:
        if backend_errors:
            parts.append("No results found (all backends errored).")
        return "\n".join(parts)

    parts.append(f"Found {len(results)} unique result(s):\n")

    for i, (source, r) in enumerate(results, 1):
        lines: list[str] = [f"{i}. [{source}] {r.name}"]
        if r.type:
            lines.append(f"   Type: {r.type}")
        if r.doc:
            doc = r.doc.strip().replace("\n", " ")
            if len(doc) > 200:
                doc = doc[:200] + "..."
            lines.append(f"   Doc: {doc}")
        if r.module:
            lines.append(f"   Module: {r.module}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


async def lean_unified_search(
    limiter: SlidingWindowLimiter,
    query: str,
    num_results: int = 5,
    backends: list[str] | None = None,
) -> str:
    """Run parallel search across multiple backends and return deduplicated results.

    Runs leansearch, loogle, and leanfinder in parallel, collects all results,
    deduplicates by theorem name, and returns a unified list.

    Args:
        limiter: Rate limiter instance.
        query: Search query (natural language or type pattern).
        num_results: Max results per backend (default 5).
        backends: List of backends to use. Default: all available.

    Returns:
        Formatted unified search results.
    """
    if backends is None:
        backends = list(ALL_BACKENDS)
    else:
        # Validate backend names
        backends = [b for b in backends if b in ALL_BACKENDS]
        if not backends:
            return f"No valid backends specified. Available: {', '.join(ALL_BACKENDS)}"

    # Run all backends in parallel
    tasks = [
        _run_backend(limiter, backend, query, num_results)
        for backend in backends
    ]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect results and errors
    all_results: list[tuple[str, SearchResult]] = []
    backend_errors: dict[str, str] = {}

    for item in results_raw:
        if isinstance(item, Exception):
            backend_errors["unknown"] = str(item)
            continue
        backend_name, response = item
        if response.error:
            backend_errors[backend_name] = response.error
        else:
            for r in response.results:
                all_results.append((backend_name, r))

    # Deduplicate
    unique_results = _deduplicate(all_results)

    return _format_unified_results(unique_results, backend_errors)
