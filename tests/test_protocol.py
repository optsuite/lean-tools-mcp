# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
Unit tests for the JSON-RPC 2.0 protocol layer.

These tests do NOT require Lean — they test encoding/decoding in isolation.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from lean_tools_mcp.lsp.protocol import (
    JsonRpcMessage,
    JsonRpcTransport,
    LSPProtocolError,
    encode_message,
    read_message,
)


class TestEncodeMessage:
    """Test JSON-RPC message encoding."""

    def test_basic_encoding(self):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        encoded = encode_message(msg)

        # Should have Content-Length header
        assert encoded.startswith(b"Content-Length: ")
        assert b"\r\n\r\n" in encoded

        # Extract and verify body
        header_end = encoded.index(b"\r\n\r\n") + 4
        body = encoded[header_end:]
        parsed = json.loads(body)
        assert parsed == msg

    def test_content_length_is_correct(self):
        msg = {"jsonrpc": "2.0", "id": 42, "result": {"foo": "bar"}}
        encoded = encode_message(msg)

        header_line = encoded.split(b"\r\n")[0].decode("ascii")
        claimed_length = int(header_line.split(":")[1].strip())

        header_end = encoded.index(b"\r\n\r\n") + 4
        actual_length = len(encoded) - header_end

        assert claimed_length == actual_length

    def test_unicode_content(self):
        msg = {"jsonrpc": "2.0", "id": 1, "result": {"text": "∀ α β : Prop, α → β"}}
        encoded = encode_message(msg)

        header_end = encoded.index(b"\r\n\r\n") + 4
        body = encoded[header_end:]
        parsed = json.loads(body.decode("utf-8"))
        assert parsed["result"]["text"] == "∀ α β : Prop, α → β"


class TestReadMessage:
    """Test reading JSON-RPC messages from a stream."""

    @pytest.mark.asyncio
    async def test_read_basic_message(self):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        raw = encode_message(msg)

        reader = asyncio.StreamReader()
        reader.feed_data(raw)
        reader.feed_eof()

        result = await read_message(reader)
        assert result is not None
        assert result.data == msg

    @pytest.mark.asyncio
    async def test_read_eof(self):
        reader = asyncio.StreamReader()
        reader.feed_eof()

        result = await read_message(reader)
        assert result is None

    @pytest.mark.asyncio
    async def test_read_multiple_messages(self):
        msg1 = {"jsonrpc": "2.0", "id": 1, "method": "first"}
        msg2 = {"jsonrpc": "2.0", "id": 2, "method": "second"}

        reader = asyncio.StreamReader()
        reader.feed_data(encode_message(msg1))
        reader.feed_data(encode_message(msg2))
        reader.feed_eof()

        r1 = await read_message(reader)
        r2 = await read_message(reader)

        assert r1 is not None and r1.data["method"] == "first"
        assert r2 is not None and r2.data["method"] == "second"


class TestJsonRpcMessage:
    """Test message type classification."""

    def test_request(self):
        msg = JsonRpcMessage({"jsonrpc": "2.0", "id": 1, "method": "test"})
        assert msg.is_request
        assert not msg.is_response
        assert not msg.is_notification

    def test_response(self):
        msg = JsonRpcMessage({"jsonrpc": "2.0", "id": 1, "result": {}})
        assert msg.is_response
        assert not msg.is_request
        assert not msg.is_notification

    def test_error_response(self):
        msg = JsonRpcMessage(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "fail"}}
        )
        assert msg.is_response
        assert msg.error is not None

    def test_notification(self):
        msg = JsonRpcMessage({"jsonrpc": "2.0", "method": "$/progress"})
        assert msg.is_notification
        assert not msg.is_request


class TestJsonRpcTransport:
    """Test the transport layer with mock streams."""

    @pytest.mark.asyncio
    async def test_send_and_receive_request(self):
        """Test that a request gets the correct response via the transport.

        Uses asyncio pipe-based streams to avoid StreamWriter.drain() issues
        with mock transports.
        """
        # Use a real pipe pair for client_reader <- server writes responses
        client_reader = asyncio.StreamReader()
        # Use a real pipe pair for server_reader <- client writes requests
        server_reader = asyncio.StreamReader()

        transport = JsonRpcTransport(client_reader, _FakeWriter(server_reader))
        await transport.start()

        # Simulate server: read from server_reader, send response to client_reader
        async def mock_server():
            msg = await read_message(server_reader)
            if msg and msg.id is not None:
                response = encode_message(
                    {"jsonrpc": "2.0", "id": msg.id, "result": {"status": "ok"}}
                )
                client_reader.feed_data(response)

        server_task = asyncio.create_task(mock_server())
        result = await transport.send_request("test/method", {"key": "value"}, timeout=5.0)

        assert result == {"status": "ok"}

        await server_task
        await transport.close()

    @pytest.mark.asyncio
    async def test_notification_dispatch(self):
        """Test that notifications are dispatched to registered handlers."""
        client_reader = asyncio.StreamReader()

        transport = JsonRpcTransport(client_reader, _FakeWriter(asyncio.StreamReader()))

        received = []
        transport.on_notification("test/notify", lambda params: received.append(params))

        await transport.start()

        # Feed a notification
        notification = encode_message(
            {"jsonrpc": "2.0", "method": "test/notify", "params": {"data": 42}}
        )
        client_reader.feed_data(notification)

        # Give the reader loop time to process
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0]["data"] == 42

        await transport.close()


class _FakeWriter:
    """Minimal duck-typed replacement for asyncio.StreamWriter.

    Directly feeds bytes into a target StreamReader, avoiding the need
    for real asyncio transports/protocols which have drain() issues in tests.
    """

    def __init__(self, target_reader: asyncio.StreamReader):
        self._reader = target_reader
        self._closed = False

    def write(self, data: bytes) -> None:
        if not self._closed:
            self._reader.feed_data(data)

    async def drain(self) -> None:
        pass  # No-op for tests

    def close(self) -> None:
        self._closed = True

    def is_closing(self) -> bool:
        return self._closed

    def get_extra_info(self, name: str, default: object = None) -> object:
        return default
