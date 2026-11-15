"""Run the web UI: ``python -m claimclear_graph.webapp [--host 127.0.0.1] [--port 8000]``.

Expects the MCP servers to be running over HTTP (``CLAIMCLEAR_MCP_MODE=http``; ``start.py`` arranges this).
Prints ``CLAIMCLEAR_UI_READY <url>`` once it is serving, and exits when the last page has been closed.
"""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from .server import create_app


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    os.environ.setdefault("CLAIMCLEAR_MCP_MODE", "http")
    server: uvicorn.Server

    def stop(reason: str) -> None:
        print(f"[web] stopping: {reason}", flush=True)
        server.should_exit = True

    config = uvicorn.Config(create_app(stop), host=args.host, port=args.port, log_level="warning", ws="websockets")
    server = uvicorn.Server(config)
    original = server.startup

    async def startup(sockets=None):
        await original(sockets)
        print(f"CLAIMCLEAR_UI_READY http://{args.host}:{args.port}/", flush=True)
    server.startup = startup
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
