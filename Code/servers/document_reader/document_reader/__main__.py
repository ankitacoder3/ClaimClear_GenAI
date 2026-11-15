"""Run the document-reader MCP server.

    python -m document_reader                                  # stdio (development)
    python -m document_reader --transport streamable-http      # HTTP on 127.0.0.1:8105 (Docker)
    python -m document_reader --dump-schemas                   # print every tool's schemas as JSON
    python -m document_reader --read FILE                      # read one file and print the result

Run from ``servers/document_reader`` with the servers' virtual environment.
Configuration: ``CLAIMCLEAR_OCR`` (auto/on/off), ``CLAIMCLEAR_OCR_LANGUAGE``,
``CLAIMCLEAR_OCR_DPI``, ``CLAIMCLEAR_DOCUMENT_CACHE`` (unset: no cache).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .app import DEFAULT_PORT, create_server
from .reader import DocumentReader, sniff_media_type


async def tool_schemas() -> list[dict]:
    server = create_server(cache_dir="", use_ocr=False)
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


def read_one(path: Path) -> int:
    data = path.read_bytes()
    media_type = sniff_media_type(data)
    if media_type is None:
        print(f"{path}: not a PDF, JPG or PNG", file=sys.stderr)
        return 2
    json.dump(DocumentReader().read_bytes(data, media_type), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m document_reader", description="ClaimClear document-reader MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--dump-schemas", action="store_true", help="print tool schemas as JSON and exit")
    parser.add_argument("--read", metavar="FILE", help="read one PDF, JPG or PNG, print the result as JSON and exit")
    args = parser.parse_args(argv)

    if args.dump_schemas:
        json.dump(asyncio.run(tool_schemas()), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if args.read:
        sys.stdout.reconfigure(encoding="utf-8")
        return read_one(Path(args.read))

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    server = create_server()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
