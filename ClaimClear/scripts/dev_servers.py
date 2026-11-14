"""Start every built MCP server over streamable HTTP, for local agent development.

    python scripts/dev_servers.py            # settlement-engine :8101, case-records :8102, policy-kb :8103,
                                             # insurer-portal :8104 (dry run), document-reader :8105 (for the app)
    python scripts/dev_servers.py --check    # start, confirm every port answers, stop

Uses the servers' Python (``<repo>/.venv`` or ``$CLAIMCLEAR_SERVER_PYTHON``), so
it can be run from any Python, including the agents' environment. Stop with Ctrl+C.
Point the agents at the servers with ``CLAIMCLEAR_MCP_MODE=http``.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVERS = [
    # name, folder, module, port
    ("settlement-engine", "servers/settlement_engine", "mcp_server", 8101),
    ("case-records", "servers/case_records", "case_records", 8102),
    ("policy-kb", "servers/policy_kb", "policy_kb.mcp_server", 8103),
    ("insurer-portal", "servers/insurer_portal", "insurer_portal", 8104),
    ("document-reader", "servers/document_reader", "document_reader", 8105),
]


def server_python() -> str:
    env = os.environ.get("CLAIMCLEAR_SERVER_PYTHON")
    if env:
        return env
    for p in (REPO / ".venv" / "Scripts" / "python.exe", REPO / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    sys.exit("server venv not found under .venv; create it with requirements-servers.txt or set CLAIMCLEAR_SERVER_PYTHON")


def tie_children_to_this_process() -> None:
    """Make sure the servers stop whenever this launcher stops, even if it is killed.

    Windows: put this process in a job object with KILL_ON_JOB_CLOSE before starting
    the servers; they inherit the job, and the OS kills them when our handle closes.
    POSIX: turn SIGTERM into the same clean shutdown as Ctrl+C.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("Reads", "Writes", "Others", "ReadBytes", "WriteBytes", "OtherBytes")]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        job = k32.CreateJobObjectW(None, None)
        info = EXTENDED()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = job and k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) \
            and k32.AssignProcessToJobObject(job, k32.GetCurrentProcess())
        if not ok:
            print("warning: could not tie servers to this launcher; stop them yourself if it is killed", file=sys.stderr)
        globals()["_JOB_HANDLE"] = job  # keep the handle open for the launcher's lifetime
    else:
        import signal

        def _stop(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, _stop)


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--check", action="store_true", help="start, wait until every port answers, then stop")
    args = parser.parse_args(argv)

    python = server_python()
    busy = [f"{name} (:{port})" for name, _, _, port in SERVERS if port_open(port)]
    if busy:
        sys.exit(f"port already in use: {', '.join(busy)}")

    tie_children_to_this_process()
    procs = []
    for name, folder, module, port in SERVERS:
        cmd = [python, "-m", module, "--transport", "streamable-http", "--host", args.host, "--port", str(port)]
        procs.append((name, port, subprocess.Popen(cmd, cwd=REPO / folder)))
    try:
        deadline = time.time() + 60
        while time.time() < deadline and not all(port_open(p) for _, p, _ in procs):
            if any(proc.poll() is not None for _, _, proc in procs):
                sys.exit("a server exited during start-up; see its log above")
            time.sleep(0.3)
        for name, port, _ in procs:
            state = "up" if port_open(port) else "NOT RESPONDING"
            print(f"{name:18} http://{args.host}:{port}/mcp   {state}", flush=True)
        if args.check:
            return 0 if all(port_open(p) for _, p, _ in procs) else 1
        print("Set CLAIMCLEAR_MCP_MODE=http in the agents' environment. Ctrl+C to stop.", flush=True)
        while all(proc.poll() is None for _, _, proc in procs):
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for _, _, proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for _, _, proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
