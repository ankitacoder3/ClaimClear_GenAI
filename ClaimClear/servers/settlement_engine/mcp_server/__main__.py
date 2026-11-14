"""Run the settlement-engine MCP server.

    python -m mcp_server                                   # stdio (development)
    python -m mcp_server --transport streamable-http       # HTTP on 127.0.0.1:8101 (Docker)
    python -m mcp_server --dump-schemas                    # print every tool's schemas as JSON
    python -m mcp_server --case-payload SET-01             # dev: a dataset case as tool arguments

Run from ``servers/settlement_engine`` with the project virtual environment.

``--case-payload`` prints ``{"claim": ..., "letter": ...}`` for a dataset
settlement letter (or ``{"claim": ...}`` for a bill), exactly as the document
reader should produce them. It is a stand-in for the document reader in
development and tests only; never use it in an evaluation run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .app import create_server


async def tool_schemas() -> list[dict]:
    """Name, annotations, meta and input/output schema of every tool, sorted by name."""
    server = create_server()
    tools = await server.list_tools()
    out = []
    for t in sorted(tools, key=lambda t: t.name):
        out.append({
            "name": t.name,
            "annotations": t.annotations.model_dump(exclude_none=True, by_alias=False) if t.annotations else None,
            "meta": t.meta,
            "input_schema": t.input_schema,
            "output_schema": t.output_schema,
        })
    return out


def case_payload_for(doc_id: str) -> dict:
    """``{"claim", "letter"?}`` for a dataset document, as the document reader would extract them."""
    from engine.dataset import load_case, load_letter

    from .convert import claim_payload, letter_payload

    case = load_case(doc_id)
    out = {"claim": claim_payload(case.claim)}
    try:
        out["letter"] = letter_payload(load_letter(doc_id))
    except ValueError:
        pass  # a bill, not a settlement letter
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mcp_server", description="ClaimClear settlement-engine MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8101)
    parser.add_argument("--dump-schemas", action="store_true", help="print tool schemas as JSON and exit")
    parser.add_argument("--case-payload", metavar="DOC_ID",
                        help="dev only: print a dataset case (e.g. SET-01) as claim/letter tool arguments and exit")
    args = parser.parse_args(argv)

    if args.case_payload:
        json.dump(case_payload_for(args.case_payload), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if args.dump_schemas:
        json.dump(asyncio.run(tool_schemas()), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    # stdout carries the protocol on stdio, so logs go to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    server = create_server()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
