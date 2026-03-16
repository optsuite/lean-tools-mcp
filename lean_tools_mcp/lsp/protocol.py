# Author: Ziyu Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
JSON-RPC 2.0 over stdio protocol layer for LSP communication.

Handles framing (Content-Length headers), encoding/decoding, and
request ID management for multiplexed async communication.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LSPProtocolError(Exception):
    """Raised on protocol-level errors (malformed headers, bad JSON, etc.)."""


class JsonRpcMessage:
    """A JSON-RPC 2.0 message (request, response, or notification)."""

    __slots__ = ("data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    @property
    def id(self) -> int | str | None:
        return self.data.get("id")

    @property
    def method(self) -> str | None:
        return self.data.get("method")

    @property
    def params(self) -> Any:
        return self.data.get("params")

    @property
    def result(self) -> Any:
        return self.data.get("result")

    @property
    def error(self) -> dict[str, Any] | None:
        return self.data.get("error")

    @property
    def is_response(self) -> bool:
        return "id" in self.data and ("result" in self.data or "error" in self.data)

    @property
    def is_notification(self) -> bool:
        return "method" in self.data and "id" not in self.data

    @property
    def is_request(self) -> bool:
        return "method" in self.data and "id" in self.data


def encode_message(data: dict[str, Any]) -> bytes:
    """Encode a JSON-RPC message with Content-Length header."""
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


async def read_message(reader: asyncio.StreamReader) -> JsonRpcMessage | None:
    """Read a single JSON-RPC message from the stream.

    Returns None on EOF.
    """
    # Read headers until blank line
    content_length = -1
    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            return None  # EOF
        line = line_bytes.decode("ascii", errors="replace").strip()
        if not line:
            break  # End of headers
        if line.lower().startswith("content-length:"):
            try:
                content_length = int(line.split(":", 1)[1].strip())
            except ValueError as e:
                raise LSPProtocolError(f"Invalid Content-Length: {line}") from e

    if content_length < 0:
        raise LSPProtocolError("Missing Content-Length header")

    # Read body
    body_bytes = await reader.readexactly(content_length)
    try:
        data = json.loads(body_bytes.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise LSPProtocolError(f"Invalid JSON body: {e}") from e

    return JsonRpcMessage(data)


class JsonRpcTransport:
    """Manages async JSON-RPC 2.0 communication over stdin/stdout streams.

    Supports multiplexed requests (multiple pending requests with different IDs),
    notification dispatch, and clean shutdown.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 1
        self._pending: dict[int | str, asyncio.Future[JsonRpcMessage]] = {}
        self._notification_handlers: dict[str, list[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background reader loop."""
        self._reader_task = asyncio.create_task(self._read_loop(), name="lsp-reader")

    async def close(self) -> None:
        """Shut down the transport."""
        self._closed = True
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        # Cancel all pending requests
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        self._writer.close()

    def on_notification(self, method: str, handler: Any) -> None:
        """Register a handler for a specific notification method."""
        self._notification_handlers.setdefault(method, []).append(handler)

    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        """Send a JSON-RPC request and wait for the response.

        Returns the result field of the response.
        Raises LSPProtocolError on error responses.
        """
        async with self._lock:
            request_id = self._next_id
            self._next_id += 1

        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            msg["params"] = params

        fut: asyncio.Future[JsonRpcMessage] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut

        await self._write(msg)

        try:
            response = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise LSPProtocolError(
                f"Request {method} (id={request_id}) timed out after {timeout}s"
            )

        if response.error:
            err = response.error
            raise LSPProtocolError(
                f"LSP error {err.get('code', '?')}: {err.get('message', 'unknown')}"
            )

        return response.result

    async def send_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        await self._write(msg)

    async def _write(self, data: dict[str, Any]) -> None:
        """Write an encoded message to the stream."""
        payload = encode_message(data)
        self._writer.write(payload)
        await self._writer.drain()

    async def _read_loop(self) -> None:
        """Background loop that reads messages and dispatches them."""
        try:
            while not self._closed:
                msg = await read_message(self._reader)
                if msg is None:
                    logger.debug("LSP reader: EOF reached")
                    break
                self._dispatch(msg)
        except asyncio.CancelledError:
            pass
        except LSPProtocolError as e:
            logger.error("LSP protocol error: %s", e)
        except Exception:
            logger.exception("Unexpected error in LSP reader loop")
        finally:
            # Cancel all pending on reader exit
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(LSPProtocolError("LSP connection closed"))
            self._pending.clear()

    def _dispatch(self, msg: JsonRpcMessage) -> None:
        """Route a received message to the correct handler."""
        if msg.is_response:
            fut = self._pending.pop(msg.id, None)
            if fut and not fut.done():
                fut.set_result(msg)
            elif fut is None:
                logger.warning("Received response for unknown id=%s", msg.id)
        elif msg.is_request:
            # Server-to-client request (e.g., client/registerCapability).
            # Respond with an empty result to acknowledge.
            asyncio.create_task(self._respond_to_server_request(msg))
        elif msg.is_notification:
            method = msg.method
            handlers = self._notification_handlers.get(method, [])
            if handlers:
                for handler in handlers:
                    try:
                        result = handler(msg.params)
                        if asyncio.iscoroutine(result):
                            asyncio.create_task(result)
                    except Exception:
                        logger.exception(
                            "Error in notification handler for %s", method
                        )
            else:
                logger.debug("Unhandled notification: %s", method)
        else:
            logger.warning("Unexpected message type: %s", msg.data)

    async def _respond_to_server_request(self, msg: JsonRpcMessage) -> None:
        """Send an empty success response to a server-to-client request."""
        logger.debug("Responding to server request: %s (id=%s)", msg.method, msg.id)
        response = {
            "jsonrpc": "2.0",
            "id": msg.id,
            "result": None,
        }
        await self._write(response)
