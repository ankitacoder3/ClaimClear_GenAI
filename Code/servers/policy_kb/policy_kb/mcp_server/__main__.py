"""Run the policy-kb MCP server.

    python -m policy_kb.mcp_server                                  # stdio (development)
    python -m policy_kb.mcp_server --transport streamable-http      # HTTP on 127.0.0.1:8103 (Docker)
    python -m policy_kb.mcp_server --dump-schemas                   # print every tool's schemas as JSON

Run from ``servers/policy_kb`` with the servers' virtual environment. Configuration:
``CLAIMCLEAR_POLICY_KB_INDEX`` (default ``var/policy_kb/index.json``),
``CLAIMCLEAR_POLICY_KB_REWRITER`` (default ``glossary``) and
``CLAIMCLEAR_POLICY_KB_RERANKER`` (default ``none``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .app import create_server


async def tool_schemas() -> list[dict]:
    server = create_server(index_path="unused-for-schemas.json", rewriter="none")
    out = []
    for t in sorted(await server.list_tools(), key=lambda t: t.name):
        out.append({
            "name": t.name,
            "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None,
            "meta": t.meta,
            "input_schema": t.input_schema,
            "output_schema": t.output_schema,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m policy_kb.mcp_server",
                                     description="ClaimClear policy-kb MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8103)
    parser.add_argument("--index", help="index file (default: $CLAIMCLEAR_POLICY_KB_INDEX or var/policy_kb/index.json)")
    parser.add_argument("--dump-schemas", action="store_true", help="print tool schemas as JSON and exit")
    args = parser.parse_args(argv)

    if args.dump_schemas:
        json.dump(asyncio.run(tool_schemas()), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    server = create_server(index_path=args.index)
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
