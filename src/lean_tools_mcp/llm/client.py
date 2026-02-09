"""
Async LLM client with multi-provider support, key rotation, and fallback.

All providers use OpenAI-compatible chat completion APIs.
Supports: deepseek, openai (proxies), google (via proxy), and custom endpoints.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import LLMConfig, LLMProviderEntry

logger = logging.getLogger(__name__)

# Default parameters
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.0
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds


@dataclass
class ChatMessage:
    """A single chat message."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM call."""

    content: str = ""
    model: str = ""
    provider: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    error: str = ""
    latency_ms: float = 0.0


class LLMClient:
    """Async LLM client with key rotation and provider fallback.

    Usage:
        client = LLMClient(config)
        response = await client.chat([
            ChatMessage(role="user", content="What is 1+1?"),
        ])
        print(response.content)
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        # Key rotation index per provider
        self._key_index: dict[str, int] = {}
        # Provider fallback order (configurable)
        self._fallback_order: list[str] = []
        self._init_providers()

    def _init_providers(self) -> None:
        """Initialize provider indices and fallback order."""
        for name in self._config.providers:
            self._key_index[name] = 0

        # Build fallback order: prefer default_source first, then others
        default = self._config.default_source
        all_providers = list(self._config.providers.keys())

        if default and default in all_providers:
            self._fallback_order = [default] + [
                p for p in all_providers if p != default
            ]
        else:
            # Prefer deepseek first (cheapest), then others
            preferred = ["deepseek", "openai", "google", "anthropic", "other"]
            self._fallback_order = sorted(
                all_providers,
                key=lambda p: preferred.index(p) if p in preferred else 99,
            )

    def _pick_entry(self, provider: str) -> LLMProviderEntry | None:
        """Pick the next API key for a provider (round-robin)."""
        entries = self._config.providers.get(provider, [])
        if not entries:
            return None
        idx = self._key_index.get(provider, 0) % len(entries)
        self._key_index[provider] = idx + 1
        return entries[idx]

    @property
    def available_providers(self) -> list[str]:
        """Return list of providers that have at least one API key."""
        return [
            name
            for name, entries in self._config.providers.items()
            if entries
        ]

    @property
    def is_configured(self) -> bool:
        """Return True if at least one provider is configured."""
        return len(self.available_providers) > 0

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        provider: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> LLMResponse:
        """Send a chat completion request with automatic fallback.

        Args:
            messages: List of chat messages.
            model: Model name (defaults to config default_model).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.
            provider: Force a specific provider (skip fallback).
            timeout: Request timeout in seconds.

        Returns:
            LLMResponse with content or error.
        """
        if not self.is_configured:
            return LLMResponse(error="No LLM providers configured.")

        model = model or self._config.default_model
        providers = [provider] if provider else self._fallback_order

        last_error = ""
        for prov in providers:
            entry = self._pick_entry(prov)
            if entry is None:
                continue

            response = await self._call_openai_compat(
                entry=entry,
                provider_name=prov,
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            if not response.error:
                return response

            last_error = response.error
            logger.warning(
                "LLM provider %s failed: %s, trying next...",
                prov,
                response.error,
            )

        return LLMResponse(error=f"All providers failed. Last error: {last_error}")

    async def _call_openai_compat(
        self,
        entry: LLMProviderEntry,
        provider_name: str,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        """Call an OpenAI-compatible chat completions endpoint with retry."""
        url = f"{entry.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {entry.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for attempt in range(MAX_RETRIES):
            start = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, json=body, headers=headers)

                latency = (time.monotonic() - start) * 1000

                if resp.status_code == 429:
                    # Rate limited — wait and retry
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.debug(
                        "LLM %s rate limited (429), retrying in %.1fs",
                        provider_name,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                resp.raise_for_status()
                data = resp.json()

                # Parse OpenAI-compatible response
                choices = data.get("choices", [])
                if not choices:
                    return LLMResponse(
                        error="No choices in response",
                        provider=provider_name,
                        latency_ms=latency,
                    )

                content = choices[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})

                return LLMResponse(
                    content=content,
                    model=data.get("model", model),
                    provider=provider_name,
                    usage={
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                    latency_ms=latency,
                )

            except httpx.TimeoutException:
                latency = (time.monotonic() - start) * 1000
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.debug(
                        "LLM %s timed out, retrying in %.1fs",
                        provider_name,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                return LLMResponse(
                    error=f"Timeout after {MAX_RETRIES} attempts",
                    provider=provider_name,
                    latency_ms=latency,
                )

            except httpx.HTTPStatusError as e:
                latency = (time.monotonic() - start) * 1000
                return LLMResponse(
                    error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                    provider=provider_name,
                    latency_ms=latency,
                )

            except Exception as e:
                latency = (time.monotonic() - start) * 1000
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                return LLMResponse(
                    error=str(e),
                    provider=provider_name,
                    latency_ms=latency,
                )

        return LLMResponse(
            error=f"Max retries ({MAX_RETRIES}) exceeded",
            provider=provider_name,
        )
