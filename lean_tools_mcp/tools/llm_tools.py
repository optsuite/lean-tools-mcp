# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
LLM-powered tools for Lean theorem proving assistance.

Provides:
  - lean_llm_query: General LLM query for math reasoning, translation, etc.
"""

from __future__ import annotations

import logging
from typing import Any

from ..llm.client import ChatMessage, LLMClient, LLMResponse

logger = logging.getLogger(__name__)

# System prompt for math/Lean assistance
LEAN_SYSTEM_PROMPT = """\
You are a Lean 4 / Mathlib expert assistant. You help with:
- Translating informal math to Lean 4 formal statements
- Suggesting proof strategies and tactics
- Explaining Lean 4 syntax, type theory, and Mathlib conventions
- Identifying relevant Mathlib theorems for a given goal

Be concise and precise. When suggesting Lean code, use valid Lean 4 syntax.
"""


async def lean_llm_query(
    llm_client: LLMClient,
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> str:
    """Query an LLM for Lean 4 / math reasoning assistance.

    Uses the configured LLM providers with automatic fallback.

    Args:
        llm_client: The LLM client instance.
        prompt: User query (e.g., "Translate: every even number > 2 is sum of 2 primes").
        system_prompt: Override the default system prompt.
        model: Override the default model.
        temperature: Sampling temperature (default 0.0 for deterministic).
        max_tokens: Maximum response tokens.

    Returns:
        LLM response text or error message.
    """
    if not llm_client.is_configured:
        return (
            "[LLM] Error: No LLM providers configured.\n"
            "Set up a config.json with API keys, or pass --config to the server."
        )

    messages = [
        ChatMessage(role="system", content=system_prompt or LEAN_SYSTEM_PROMPT),
        ChatMessage(role="user", content=prompt),
    ]

    response = await llm_client.chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if response.error:
        return f"[LLM] Error: {response.error}"

    # Format the response with metadata
    parts: list[str] = []
    parts.append(response.content)
    parts.append("")
    parts.append(
        f"--- model: {response.model} | provider: {response.provider} | "
        f"tokens: {response.usage.get('total_tokens', '?')} | "
        f"latency: {response.latency_ms:.0f}ms ---"
    )
    return "\n".join(parts)
