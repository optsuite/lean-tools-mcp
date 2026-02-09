"""
LSP Connection Pool — manages multiple lean --server instances.

Distributes requests across a pool of LSP clients for better throughput
while keeping memory bounded.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .client import LSPClient

logger = logging.getLogger(__name__)


class LSPPool:
    """Pool of LSP server connections for high-concurrency workloads.

    Requests are distributed round-robin across the pool.
    A semaphore limits the number of concurrent in-flight requests.
    """

    def __init__(
        self,
        project_root: Path | str,
        pool_size: int = 2,
        lean_path: str = "lean",
        request_timeout: float = 60.0,
        file_check_timeout: float = 120.0,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._pool_size = pool_size
        self._lean_path = lean_path
        self._request_timeout = request_timeout
        self._file_check_timeout = file_check_timeout

        self._clients: list[LSPClient] = []
        self._robin_index = 0
        self._robin_lock = asyncio.Lock()
        self._started = False

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def file_check_timeout(self) -> float:
        return self._file_check_timeout

    @property
    def clients(self) -> list[LSPClient]:
        return self._clients

    @property
    def is_started(self) -> bool:
        return self._started

    async def start(self) -> None:
        """Start all LSP server instances in the pool."""
        logger.info("Starting LSP pool with %d instances", self._pool_size)

        tasks = []
        for i in range(self._pool_size):
            client = LSPClient(
                project_root=self._project_root,
                lean_path=self._lean_path,
                request_timeout=self._request_timeout,
                file_check_timeout=self._file_check_timeout,
            )
            self._clients.append(client)
            tasks.append(client.start())

        # Start all clients in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failed = [i for i, r in enumerate(results) if isinstance(r, Exception)]
        if failed:
            for i in failed:
                logger.error(
                    "LSP client %d failed to start: %s", i, results[i]
                )
            # If all failed, raise
            if len(failed) == self._pool_size:
                raise RuntimeError(
                    f"All {self._pool_size} LSP servers failed to start"
                )

        self._started = True
        alive = sum(1 for c in self._clients if c.is_alive)
        logger.info("LSP pool started: %d/%d alive", alive, self._pool_size)

    async def shutdown(self) -> None:
        """Shut down all LSP server instances."""
        logger.info("Shutting down LSP pool")
        tasks = [c.shutdown() for c in self._clients]
        await asyncio.gather(*tasks, return_exceptions=True)
        self._clients.clear()
        self._started = False
        logger.info("LSP pool shut down")

    async def restart(self) -> None:
        """Restart all LSP servers (e.g., after lake build)."""
        await self.shutdown()
        await self.start()

    async def pick_client(self) -> LSPClient:
        """Pick the next alive client using round-robin."""
        async with self._robin_lock:
            alive = [c for c in self._clients if c.is_alive]
            if not alive:
                raise RuntimeError("No alive LSP servers in the pool")

            idx = self._robin_index % len(alive)
            self._robin_index += 1
            return alive[idx]

    # -----------------------------------------------------------------
    # Convenience methods that delegate to a picked client
    # -----------------------------------------------------------------

    async def get_goal(
        self,
        file_path: Path | str,
        line: int,
        character: int | None = None,
    ) -> dict[str, Any]:
        """Get proof goal state at a position."""
        client = await self.pick_client()
        return await client.get_goal(file_path, line, character)

    async def get_term_goal(
        self,
        file_path: Path | str,
        line: int,
        character: int | None = None,
    ) -> dict[str, Any] | None:
        """Get expected type at a position."""
        client = await self.pick_client()
        return await client.get_term_goal(file_path, line, character)

    async def get_diagnostics(
        self,
        file_path: Path | str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get diagnostics for a file."""
        client = await self.pick_client()
        return await client.get_diagnostics(file_path, start_line, end_line)

    async def get_hover(
        self,
        file_path: Path | str,
        line: int,
        character: int,
    ) -> dict[str, Any] | None:
        """Get hover information at a position."""
        client = await self.pick_client()
        return await client.get_hover(file_path, line, character)

    async def get_completions(
        self,
        file_path: Path | str,
        line: int,
        character: int,
    ) -> list[dict[str, Any]]:
        """Get completions at a position."""
        client = await self.pick_client()
        return await client.get_completions(file_path, line, character)

    async def get_definition(
        self,
        file_path: Path | str,
        line: int,
        character: int,
    ) -> list[dict[str, Any]]:
        """Get definition location for a symbol."""
        client = await self.pick_client()
        return await client.get_definition(file_path, line, character)

    async def get_document_symbols(
        self,
        file_path: Path | str,
    ) -> list[dict[str, Any]]:
        """Get document symbols for a file."""
        client = await self.pick_client()
        return await client.get_document_symbols(file_path)

    async def check_temp_content(
        self,
        content: str,
        temp_name: str = "LeanToolsMcpTemp.lean",
    ) -> list[dict[str, Any]]:
        """Check temporary content via LSP."""
        client = await self.pick_client()
        return await client.check_temp_content(content, temp_name)
