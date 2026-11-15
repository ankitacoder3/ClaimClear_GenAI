"""Where the MCP servers are, and how to reach them.

Two modes:

* ``stdio`` (default, development): each server is started as a child process with
  the **servers'** Python (``<repo>/.venv``), not the agents' Python.
* ``http`` (Docker): each server is already running; connect to its URL.

Everything can be overridden with environment variables, so the same agent code
runs on a laptop and in Docker Compose:

=================================  ===============================================
``CLAIMCLEAR_MCP_MODE``            ``stdio`` (default) or ``http``
``CLAIMCLEAR_REPO``                repository root (default: found automatically)
``CLAIMCLEAR_SERVER_PYTHON``       Python with the server packages (default: ``<repo>/.venv``)
``CLAIMCLEAR_SETTLEMENT_URL``      default ``http://127.0.0.1:8101/mcp``
``CLAIMCLEAR_CASE_RECORDS_URL``    default ``http://127.0.0.1:8102/mcp``
``CLAIMCLEAR_POLICY_KB_URL``       default ``http://127.0.0.1:8103/mcp``
``CLAIMCLEAR_INSURER_PORTAL_URL``  default ``http://127.0.0.1:8104/mcp``
``CLAIMCLEAR_CASE_STORE``          passed through to case-records (stdio mode)
``CLAIMCLEAR_REFERENCE_DIR``       passed through to case-records (stdio mode)
``CLAIMCLEAR_POLICY_RULES``        passed through to settlement-engine (stdio mode)
``CLAIMCLEAR_POLICY_KB_INDEX``     passed through to policy-kb (stdio mode)
=================================  ===============================================
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

Mode = Literal["stdio", "http"]

SETTLEMENT_ENGINE = "settlement-engine"
CASE_RECORDS = "case-records"
POLICY_KB = "policy-kb"
INSURER_PORTAL = "insurer-portal"


@dataclass(frozen=True)
class ServerSpec:
    """How a server is started (stdio) and where it listens (http)."""

    name: str
    module: str          # python -m <module>
    folder: str          # relative to the repo root
    port: int
    url_env: str


SERVERS: dict[str, ServerSpec] = {
    SETTLEMENT_ENGINE: ServerSpec(SETTLEMENT_ENGINE, "mcp_server", "servers/settlement_engine", 8101,
                                  "CLAIMCLEAR_SETTLEMENT_URL"),
    CASE_RECORDS: ServerSpec(CASE_RECORDS, "case_records", "servers/case_records", 8102,
                             "CLAIMCLEAR_CASE_RECORDS_URL"),
    POLICY_KB: ServerSpec(POLICY_KB, "policy_kb.mcp_server", "servers/policy_kb", 8103,
                          "CLAIMCLEAR_POLICY_KB_URL"),
    INSURER_PORTAL: ServerSpec(INSURER_PORTAL, "insurer_portal", "servers/insurer_portal", 8104,
                               "CLAIMCLEAR_INSURER_PORTAL_URL"),
}


@dataclass(frozen=True)
class Endpoint:
    """One connection, in the form ``langchain-mcp-adapters`` expects."""

    name: str
    transport: Literal["stdio", "streamable_http"]
    command: Optional[str] = None
    args: tuple[str, ...] = ()
    cwd: Optional[str] = None
    env: dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None

    def connection(self) -> dict:
        if self.transport == "stdio":
            return {"transport": "stdio", "command": self.command, "args": list(self.args),
                    "cwd": self.cwd, "env": dict(self.env)}
        return {"transport": "streamable_http", "url": self.url}


def find_repo(start: Optional[Path] = None) -> Path:
    """The repository root: ``$CLAIMCLEAR_REPO``, else the first parent holding ``servers/settlement_engine``."""
    env = os.environ.get("CLAIMCLEAR_REPO")
    if env:
        return Path(env)
    for base in [start, Path(__file__).resolve(), Path.cwd()]:
        if base is None:
            continue
        for p in [base, *base.parents]:
            if (p / "servers" / "settlement_engine").is_dir() and (p / "servers" / "case_records").is_dir():
                return p
    raise FileNotFoundError("ClaimClear repository not found; set CLAIMCLEAR_REPO")


def server_python(repo: Path) -> str:
    """The Python that has the server packages (mcp 2.x, pymupdf)."""
    env = os.environ.get("CLAIMCLEAR_SERVER_PYTHON")
    if env:
        return env
    win = repo / ".venv" / "Scripts" / "python.exe"
    nix = repo / ".venv" / "bin" / "python"
    if win.exists():
        return str(win)
    if nix.exists():
        return str(nix)
    raise FileNotFoundError(f"server virtual environment not found under {repo / '.venv'}; "
                            "set CLAIMCLEAR_SERVER_PYTHON")


def endpoints(mode: Optional[Mode] = None, repo: Optional[Path] = None,
              names: Optional[list[str]] = None) -> dict[str, Endpoint]:
    """Endpoints for the requested servers (default: all built ones)."""
    mode = mode or os.environ.get("CLAIMCLEAR_MCP_MODE", "stdio")  # type: ignore[assignment]
    if mode not in ("stdio", "http"):
        raise ValueError("CLAIMCLEAR_MCP_MODE must be 'stdio' or 'http'")
    wanted = names or list(SERVERS)
    out: dict[str, Endpoint] = {}
    if mode == "http":
        for n in wanted:
            spec = SERVERS[n]
            out[n] = Endpoint(n, "streamable_http", url=os.environ.get(spec.url_env, f"http://127.0.0.1:{spec.port}/mcp"))
        return out
    root = repo or find_repo()
    python = server_python(root)
    env = {k: v for k, v in os.environ.items()}  # keeps SYSTEMROOT etc. on Windows, and CLAIMCLEAR_* settings
    for n in wanted:
        spec = SERVERS[n]
        out[n] = Endpoint(n, "stdio", command=python, args=("-m", spec.module), cwd=str(root / spec.folder), env=env)
    return out


def connections(mode: Optional[Mode] = None, repo: Optional[Path] = None,
                names: Optional[list[str]] = None) -> dict[str, dict]:
    """The dict to pass to ``MultiServerMCPClient``."""
    return {n: e.connection() for n, e in endpoints(mode, repo, names).items()}


__all__ = ["Endpoint", "ServerSpec", "SERVERS", "SETTLEMENT_ENGINE", "CASE_RECORDS", "POLICY_KB", "INSURER_PORTAL", "connections", "endpoints",
           "find_repo", "server_python"]
