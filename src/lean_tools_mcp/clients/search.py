"""
HTTP search clients for external Lean theorem search services.

All clients are async and use httpx for HTTP requests with proper
error handling, timeouts, and rate limiting integration.

API endpoints:
  - LeanSearch:    POST https://leansearch.net/search
  - Loogle:        GET  https://loogle.lean-lang.org/json
  - LeanFinder:    POST https://delta-lab-ai-lean-finder.hf.space/api/predict
  - StateSearch:   GET  https://premise-search.com/api/search
  - HammerPremise: POST http://leanpremise.net/api/predict
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default timeout for all HTTP requests
DEFAULT_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """A single search result from any backend."""

    name: str
    type: str = ""
    doc: str = ""
    module: str = ""
    kind: str = ""


@dataclass
class SearchResponse:
    """Response from a search backend."""

    results: list[SearchResult] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# LeanSearch client — https://leansearch.net
# ---------------------------------------------------------------------------

LEANSEARCH_URL = os.environ.get(
    "LEANSEARCH_URL", "https://leansearch.net/search"
)


async def leansearch_query(
    query: str,
    num_results: int = 5,
    timeout: float = DEFAULT_TIMEOUT,
) -> SearchResponse:
    """Search Mathlib theorems via LeanSearch (natural language).

    API: POST https://leansearch.net/search
    Body: {"query": ["<query>"], "num_results": N}
    Response: [[{result: {name: [...], type, docstring, kind, ...}, distance}, ...]]
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                LEANSEARCH_URL,
                json={"query": [query], "num_results": num_results},
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return SearchResponse(error="LeanSearch request timed out")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return SearchResponse(error="LeanSearch rate limited (429). Try again later.")
        return SearchResponse(error=f"LeanSearch HTTP error: {e.response.status_code}")
    except Exception as e:
        return SearchResponse(error=f"LeanSearch error: {e}")

    # Parse nested array response: [[item, ...]]
    results: list[SearchResult] = []
    try:
        outer = data if isinstance(data, list) else []
        items = outer[0] if outer and isinstance(outer[0], list) else outer
        for item in items:
            r = item.get("result", item)
            # name can be a list of parts or a string
            name_raw = r.get("name", "")
            if isinstance(name_raw, list):
                name = ".".join(name_raw)
            else:
                name = str(name_raw)

            results.append(SearchResult(
                name=name,
                type=r.get("type", r.get("signature", "")),
                doc=r.get("docstring", r.get("informal_description", "")),
                module=".".join(r.get("module_name", [])) if isinstance(r.get("module_name"), list) else r.get("module_name", ""),
                kind=r.get("kind", ""),
            ))
    except (IndexError, KeyError, TypeError) as e:
        logger.warning("LeanSearch parse error: %s", e)

    return SearchResponse(results=results)


# ---------------------------------------------------------------------------
# Loogle client — https://loogle.lean-lang.org
# ---------------------------------------------------------------------------

LOOGLE_URL = os.environ.get(
    "LOOGLE_URL", "https://loogle.lean-lang.org/json"
)


async def loogle_query(
    query: str,
    num_results: int = 8,
    timeout: float = DEFAULT_TIMEOUT,
) -> SearchResponse:
    """Search Mathlib by type signature via Loogle.

    API: GET https://loogle.lean-lang.org/json?q=<query>
    Response: {"hits": [{name, type, doc, module}, ...]} or [{name, type, doc}, ...]
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                LOOGLE_URL,
                params={"q": query},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return SearchResponse(error="Loogle request timed out")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return SearchResponse(error="Loogle rate limited (429). Try again later.")
        return SearchResponse(error=f"Loogle HTTP error: {e.response.status_code}")
    except Exception as e:
        return SearchResponse(error=f"Loogle error: {e}")

    results: list[SearchResult] = []
    try:
        # Loogle may return {hits: [...]} or [...] or {error: "..."}
        if isinstance(data, dict):
            if "error" in data:
                return SearchResponse(error=f"Loogle: {data['error']}")
            items = data.get("hits", [])
        elif isinstance(data, list):
            items = data
        else:
            items = []

        for item in items[:num_results]:
            results.append(SearchResult(
                name=item.get("name", ""),
                type=item.get("type", ""),
                doc=item.get("doc", ""),
                module=item.get("module", ""),
            ))
    except (KeyError, TypeError) as e:
        logger.warning("Loogle parse error: %s", e)

    return SearchResponse(results=results)


# ---------------------------------------------------------------------------
# LeanFinder client — HuggingFace Spaces
# ---------------------------------------------------------------------------

LEANFINDER_URL = os.environ.get(
    "LEANFINDER_URL",
    "https://bxrituxuhpc70w8w.us-east-1.aws.endpoints.huggingface.cloud",
)


async def leanfinder_query(
    query: str,
    num_results: int = 5,
    timeout: float = DEFAULT_TIMEOUT,
) -> SearchResponse:
    """Semantic search for Mathlib via Lean Finder (HuggingFace endpoint).

    API: POST https://bxrituxuhpc70w8w.us-east-1.aws.endpoints.huggingface.cloud
    Body: {"inputs": "<query>", "top_k": N}
    Response: {"results": [{url, formal_statement, informal_statement}, ...]}
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                LEANFINDER_URL,
                json={"inputs": query, "top_k": int(num_results)},
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "lean-tools-mcp/0.1",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return SearchResponse(error="LeanFinder request timed out")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return SearchResponse(error="LeanFinder rate limited (429). Try again later.")
        return SearchResponse(error=f"LeanFinder HTTP error: {e.response.status_code}")
    except Exception as e:
        return SearchResponse(error=f"LeanFinder error: {e}")

    results: list[SearchResult] = []
    try:
        items = data.get("results", [])
        for item in items:
            url = item.get("url", "")
            formal = item.get("formal_statement", "")
            informal = item.get("informal_statement", "")

            # Extract name from URL pattern: ...pattern=Name#doc...
            name = ""
            if "pattern=" in url:
                import re
                match = re.search(r"pattern=(.*?)(?:#|$)", url)
                if match:
                    name = match.group(1)
            if not name:
                name = _extract_name_from_lean_code(formal)

            # Only include mathlib4 results
            if "mathlib4_docs" in url or not url:
                results.append(SearchResult(
                    name=name,
                    type=formal,
                    doc=informal,
                ))
    except (IndexError, KeyError, TypeError) as e:
        logger.warning("LeanFinder parse error: %s", e)

    return SearchResponse(results=results)


def _extract_name_from_lean_code(code: str) -> str:
    """Try to extract a declaration name from a Lean code snippet."""
    # Look for patterns like "theorem Name", "def Name", "lemma Name"
    for keyword in ("theorem", "lemma", "def", "abbrev", "instance"):
        if keyword in code:
            parts = code.split(keyword, 1)
            if len(parts) > 1:
                name_part = parts[1].strip().split()[0] if parts[1].strip() else ""
                # Clean up trailing characters
                name_part = name_part.rstrip(":({[")
                if name_part:
                    return name_part
    # Fallback: first line or truncated code
    first_line = code.split("\n")[0].strip()
    return first_line[:80] if first_line else "(unknown)"


# ---------------------------------------------------------------------------
# StateSearch client — https://premise-search.com
# ---------------------------------------------------------------------------

STATE_SEARCH_URL = os.environ.get(
    "LEAN_STATE_SEARCH_URL", "https://premise-search.com"
)


async def state_search_query(
    goal_state: str,
    num_results: int = 5,
    rev: str = "v4.22.0",
    timeout: float = DEFAULT_TIMEOUT,
) -> SearchResponse:
    """Search applicable theorems based on proof state via premise-search.com.

    API: GET https://premise-search.com/api/search?query=<state>&results=N&rev=<rev>
    Response: [{name, formal_type, module, kind, doc}, ...]
    """
    try:
        api_url = f"{STATE_SEARCH_URL.rstrip('/')}/api/search"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                api_url,
                params={
                    "query": goal_state,
                    "results": num_results,
                    "rev": rev,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return SearchResponse(error="StateSearch request timed out")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return SearchResponse(error="StateSearch rate limited (429). Try again later.")
        return SearchResponse(error=f"StateSearch HTTP error: {e.response.status_code}")
    except Exception as e:
        return SearchResponse(error=f"StateSearch error: {e}")

    results: list[SearchResult] = []
    try:
        items = data if isinstance(data, list) else []
        for item in items[:num_results]:
            results.append(SearchResult(
                name=item.get("name", ""),
                type=item.get("formal_type", ""),
                doc=item.get("doc", ""),
                module=item.get("module", ""),
                kind=item.get("kind", ""),
            ))
    except (KeyError, TypeError) as e:
        logger.warning("StateSearch parse error: %s", e)

    return SearchResponse(results=results)


# ---------------------------------------------------------------------------
# HammerPremise client — http://leanpremise.net
# ---------------------------------------------------------------------------

HAMMER_URL = os.environ.get(
    "LEAN_HAMMER_URL", "http://leanpremise.net"
)


async def hammer_premise_query(
    goal_state: str,
    num_results: int = 32,
    timeout: float = DEFAULT_TIMEOUT,
) -> SearchResponse:
    """Get premise suggestions for automation tactics via Lean Hammer.

    API: POST http://leanpremise.net/retrieve
    Body: {"state": "<goal_state>", "new_premises": [], "k": num_results}
    Response: [{"name": "premise1"}, {"name": "premise2"}, ...]

    Returns lemma names to try with `simp only [...]`, `aesop`, or as hints.
    """
    try:
        api_url = f"{HAMMER_URL.rstrip('/')}/retrieve"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                api_url,
                json={
                    "state": goal_state,
                    "new_premises": [],
                    "k": num_results,
                },
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "lean-tools-mcp/0.1",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return SearchResponse(error="HammerPremise request timed out")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return SearchResponse(error="HammerPremise rate limited (429). Try again later.")
        return SearchResponse(error=f"HammerPremise HTTP error: {e.response.status_code}")
    except Exception as e:
        return SearchResponse(error=f"HammerPremise error: {e}")

    results: list[SearchResult] = []
    try:
        # Response: [{"name": "..."}, ...] or a list of strings
        items = data if isinstance(data, list) else data.get("results", data.get("data", []))
        for item in items[:num_results]:
            if isinstance(item, str):
                results.append(SearchResult(name=item))
            elif isinstance(item, dict):
                results.append(SearchResult(
                    name=item.get("name", str(item)),
                    type=item.get("type", ""),
                ))
    except (IndexError, KeyError, TypeError) as e:
        logger.warning("HammerPremise parse error: %s", e)

    return SearchResponse(results=results)
