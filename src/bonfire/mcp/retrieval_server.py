# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Retrieval MCP server — exposes retrieve_context as an agent tool.

The server is launched as ``python -m bonfire.mcp.retrieval_server`` (stdio
transport). Agents that have it configured in their ``mcpServers`` block can
call ``retrieve_context(query, token_budget=4000)`` at any point during their
run.

The active RetrievalProvider is discovered once via ``bonfire._discovery`` —
Tier 2 (Arachne) when present, Tier 1 (Ripgrep) otherwise.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

from bonfire._discovery import discover_retrieval_provider

if TYPE_CHECKING:
    from bonfire.protocols import RetrievalProvider

DEFAULT_RETRIEVE_TIMEOUT_S: float = 30.0


def _retrieve_timeout() -> float:
    """Resolve the per-call retrieval timeout (seconds).

    Honors the BONFIRE_RETRIEVE_TIMEOUT_S env override; falls back to
    DEFAULT_RETRIEVE_TIMEOUT_S.
    """
    return float(os.getenv("BONFIRE_RETRIEVE_TIMEOUT_S", DEFAULT_RETRIEVE_TIMEOUT_S))


async def handle_retrieve_context(
    *,
    query: str,
    token_budget: int = 4000,
    provider: RetrievalProvider | None = None,
) -> str:
    """Run retrieval and format the result as a tool response string.

    Public for unit tests; the stdio server entry point delegates here.
    """
    active = provider if provider is not None else discover_retrieval_provider()
    timeout = _retrieve_timeout()
    try:
        atoms = await asyncio.wait_for(
            active.retrieve(query=query, token_budget=token_budget),
            timeout=timeout,
        )
    except TimeoutError:
        return f"retrieve_context: provider timed out after {timeout}s for query={query!r}"
    except Exception as exc:  # noqa: BLE001 — agent gets an error message
        return f"retrieve_context: provider raised {type(exc).__name__}: {exc}"

    if not atoms:
        return f"retrieve_context: 0 atoms for query={query!r}"

    sections: list[str] = [f"retrieve_context: {len(atoms)} atoms for query={query!r}"]
    for atom in atoms:
        sections.append(
            f"\n--- {atom.key} (score={atom.score:.3f}) ---\n"
            f"source: {atom.source_path}\n"
            f"{atom.body}"
        )
    return "\n".join(sections)


def _main() -> int:
    """Entry point for ``python -m bonfire.mcp.retrieval_server``.

    Spawns a stdio MCP server with one tool: retrieve_context.

    Wired against the ``mcp`` reference implementation (``mcp.server.Server``
    + ``mcp.server.stdio.stdio_server``). If the ``mcp`` package is missing
    at runtime, we print a clear error and exit non-zero — the handler is
    still callable in-process for testing.
    """
    try:
        import anyio
        import mcp.types as mcp_types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError as exc:  # pragma: no cover — covered by deploy environment
        print(
            f"bonfire.mcp.retrieval_server: required MCP framework missing "
            f"({exc.name}). Install the `mcp` package to launch the stdio "
            f"server. handle_retrieve_context() remains callable in-process.",
            file=sys.stderr,
        )
        return 2

    server: Server = Server("bonfire-retrieval")

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name="retrieve_context",
                description=(
                    "Retrieve relevant context atoms from the active "
                    "RetrievalProvider (Tier 2 Arachne if installed, "
                    "Tier 1 Ripgrep otherwise). Call this when you discover "
                    "a knowledge gap mid-run."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Free-text search query.",
                        },
                        "token_budget": {
                            "type": "integer",
                            "description": "Soft cap on retrieved atom tokens.",
                            "default": 4000,
                        },
                    },
                    "required": ["query"],
                },
            )
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, object]) -> list[mcp_types.TextContent]:
        if name != "retrieve_context":
            return [
                mcp_types.TextContent(type="text", text=f"retrieve_context: unknown tool {name!r}")
            ]
        query = str(arguments.get("query", ""))
        token_budget_raw = arguments.get("token_budget", 4000)
        try:
            token_budget = int(token_budget_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            token_budget = 4000
        text = await handle_retrieve_context(query=query, token_budget=token_budget)
        return [mcp_types.TextContent(type="text", text=text)]

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    anyio.run(_run)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
