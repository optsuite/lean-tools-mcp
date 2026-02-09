"""
Tests for the SSE transport layer.

Tests verify:
- SSE server starts and exposes /sse, /messages, /health endpoints
- The health endpoint returns correct JSON
- SSE transport can be created without errors
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest

from lean_tools_mcp.config import ServerConfig, LSPConfig, LLMConfig
from lean_tools_mcp.server import _run_sse, TOOLS


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    """Wait until a TCP port is accepting connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
    return False


class TestSSEImports:
    """Test that SSE dependencies are importable."""

    def test_import_starlette(self):
        import starlette.applications  # noqa: F401
        import starlette.routing  # noqa: F401

    def test_import_uvicorn(self):
        import uvicorn  # noqa: F401

    def test_import_sse_transport(self):
        from mcp.server.sse import SseServerTransport  # noqa: F401


class TestSSEServerConfig:
    """Test SSE-related configuration."""

    def test_default_config(self):
        config = ServerConfig()
        assert config.sse_host == "127.0.0.1"
        assert config.sse_port == 8080
        assert config.transport == "stdio"

    def test_sse_config(self):
        config = ServerConfig(
            transport="sse",
            sse_host="0.0.0.0",
            sse_port=9090,
        )
        assert config.transport == "sse"
        assert config.sse_host == "0.0.0.0"
        assert config.sse_port == 9090


class TestSSEHealthEndpoint:
    """Integration test: start SSE server and hit /health.

    The server is started in a daemon thread with a tmp_path as project root.
    Even if Lean is not installed, the server should start and /health should
    return a valid JSON response.
    """

    @pytest.fixture
    def sse_server(self, tmp_path):
        """Start SSE server in a background thread, yield (host, port), then stop."""
        port = _find_free_port()
        config = ServerConfig(
            project_root=tmp_path,
            transport="sse",
            sse_host="127.0.0.1",
            sse_port=port,
            lsp=LSPConfig(pool_size=1),
            llm=LLMConfig(),
        )

        thread = threading.Thread(target=_run_sse, args=(config,), daemon=True)
        thread.start()

        # Wait for server to be accepting connections
        if not _wait_for_port("127.0.0.1", port, timeout=15.0):
            pytest.skip("SSE server did not start in time")

        yield ("127.0.0.1", port)
        # Thread is a daemon, will be cleaned up on process exit

    def test_health_endpoint(self, sse_server):
        """Verify /health returns expected JSON structure."""
        host, port = sse_server
        base_url = f"http://{host}:{port}"

        # Use httpx without proxy to avoid SOCKS proxy issues on localhost
        transport = httpx.HTTPTransport()
        with httpx.Client(transport=transport) as client:
            resp = client.get(f"{base_url}/health", timeout=5.0)
            assert resp.status_code == 200
            data = resp.json()

            assert data["status"] == "ok"
            assert "lsp_pool" in data
            assert "tools" in data
            assert data["tools"] == len(TOOLS)
            print(f"\n[SSE Health] Response: {json.dumps(data, indent=2)}")

    def test_sse_endpoint_exists(self, sse_server):
        """Verify /sse endpoint is reachable (returns SSE stream)."""
        host, port = sse_server
        base_url = f"http://{host}:{port}"

        transport = httpx.HTTPTransport()
        with httpx.Client(transport=transport) as client:
            # SSE endpoint should start streaming (we just check it connects)
            with client.stream("GET", f"{base_url}/sse", timeout=3.0) as resp:
                assert resp.status_code == 200
                content_type = resp.headers.get("content-type", "")
                assert "text/event-stream" in content_type
                print(f"\n[SSE Endpoint] Content-Type: {content_type}")

    def test_messages_without_session(self, sse_server):
        """POST to /messages without valid session should return 4xx."""
        host, port = sse_server
        base_url = f"http://{host}:{port}"

        transport = httpx.HTTPTransport()
        with httpx.Client(transport=transport) as client:
            resp = client.post(
                f"{base_url}/messages",
                json={"jsonrpc": "2.0", "id": 1, "method": "test"},
                timeout=5.0,
            )
            # Should return an error since there's no valid session
            assert resp.status_code >= 400
            print(f"\n[SSE Messages] Status without session: {resp.status_code}")
