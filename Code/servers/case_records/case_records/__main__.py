"""Run the case-records MCP server.

    python -m case_records                                  # stdio (development)
    python -m case_records --transport streamable-http      # HTTP on 127.0.0.1:8102 (Docker)
    python -m case_records --dump-schemas                   # print every tool's schemas as JSON

Run from ``servers/case_records`` with the project virtual environment.
Configuration: ``CLAIMCLEAR_CASE_STORE`` (default ``var/case_store``) and
``CLAIMCLEAR_REFERENCE_DIR`` (default ``data/dataset/dev/reference``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .app import create_server


async def tool_schemas() -> list[dict]:
    server = create_server(use_ocr=False)
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
    parser = argparse.ArgumentParser(prog="python -m case_records", description="ClaimClear case-records MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8102)
    parser.add_argument("--dump-schemas", action="store_true", help="print tool schemas as JSON and exit")
    args = parser.parse_args(argv)

    if args.dump_schemas:
        json.dump(asyncio.run(tool_schemas()), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    server = create_server()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
