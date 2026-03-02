# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for the LLM client module (no network dependency).
"""

from __future__ import annotations

import pytest

from lean_tools_mcp.config import LLMConfig, LLMProviderEntry
from lean_tools_mcp.llm.client import ChatMessage, LLMClient, LLMResponse


class TestChatMessage:
    """Test ChatMessage dataclass."""

    def test_create(self):
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"


class TestLLMResponse:
    """Test LLMResponse dataclass."""

    def test_defaults(self):
        resp = LLMResponse()
        assert resp.content == ""
        assert resp.model == ""
        assert resp.provider == ""
        assert resp.error == ""
        assert resp.usage == {}
        assert resp.latency_ms == 0.0

    def test_with_content(self):
        resp = LLMResponse(
            content="Hello world",
            model="deepseek-chat",
            provider="deepseek",
            usage={"total_tokens": 10},
            latency_ms=500.0,
        )
        assert resp.content == "Hello world"
        assert resp.model == "deepseek-chat"

    def test_with_error(self):
        resp = LLMResponse(error="Connection failed")
        assert resp.error == "Connection failed"
        assert resp.content == ""


class TestLLMClient:
    """Test LLM client initialization and configuration."""

    def test_no_providers(self):
        """Client with no providers is not configured."""
        config = LLMConfig(providers={})
        client = LLMClient(config)
        assert not client.is_configured
        assert client.available_providers == []

    def test_with_providers(self):
        """Client with providers is configured."""
        config = LLMConfig(
            providers={
                "deepseek": [
                    LLMProviderEntry(api_key="sk-test", api_base="https://api.deepseek.com")
                ],
            }
        )
        client = LLMClient(config)
        assert client.is_configured
        assert "deepseek" in client.available_providers

    def test_multiple_providers(self):
        """Multiple providers are tracked."""
        config = LLMConfig(
            providers={
                "deepseek": [
                    LLMProviderEntry(api_key="sk-1", api_base="https://api.deepseek.com"),
                ],
                "openai": [
                    LLMProviderEntry(api_key="sk-2", api_base="https://api.openai.com/v1"),
                ],
            }
        )
        client = LLMClient(config)
        assert len(client.available_providers) == 2

    def test_key_rotation(self):
        """Keys rotate round-robin."""
        config = LLMConfig(
            providers={
                "deepseek": [
                    LLMProviderEntry(api_key="sk-1", api_base="https://api.deepseek.com"),
                    LLMProviderEntry(api_key="sk-2", api_base="https://api.deepseek.com"),
                    LLMProviderEntry(api_key="sk-3", api_base="https://api.deepseek.com"),
                ],
            }
        )
        client = LLMClient(config)
        e1 = client._pick_entry("deepseek")
        e2 = client._pick_entry("deepseek")
        e3 = client._pick_entry("deepseek")
        e4 = client._pick_entry("deepseek")  # Wraps around

        assert e1.api_key == "sk-1"
        assert e2.api_key == "sk-2"
        assert e3.api_key == "sk-3"
        assert e4.api_key == "sk-1"  # Round-robin

    def test_fallback_order_default(self):
        """Fallback order prefers deepseek first."""
        config = LLMConfig(
            providers={
                "openai": [LLMProviderEntry(api_key="k1", api_base="b1")],
                "deepseek": [LLMProviderEntry(api_key="k2", api_base="b2")],
                "google": [LLMProviderEntry(api_key="k3", api_base="b3")],
            }
        )
        client = LLMClient(config)
        assert client._fallback_order[0] == "deepseek"

    def test_fallback_order_custom(self):
        """Custom default_source is tried first."""
        config = LLMConfig(
            providers={
                "openai": [LLMProviderEntry(api_key="k1", api_base="b1")],
                "deepseek": [LLMProviderEntry(api_key="k2", api_base="b2")],
            },
            default_source="openai",
        )
        client = LLMClient(config)
        assert client._fallback_order[0] == "openai"

    def test_empty_provider_skipped(self):
        """Provider with empty entry list is not available."""
        config = LLMConfig(
            providers={
                "anthropic": [],  # Empty
                "deepseek": [LLMProviderEntry(api_key="k", api_base="b")],
            }
        )
        client = LLMClient(config)
        assert "anthropic" not in client.available_providers
        assert "deepseek" in client.available_providers


@pytest.mark.asyncio
class TestLLMClientChat:
    """Test chat method error handling (no real API calls)."""

    async def test_chat_no_providers(self):
        """Chat with no providers returns error."""
        config = LLMConfig(providers={})
        client = LLMClient(config)
        response = await client.chat([ChatMessage(role="user", content="Hi")])
        assert response.error
        assert "No LLM providers" in response.error
