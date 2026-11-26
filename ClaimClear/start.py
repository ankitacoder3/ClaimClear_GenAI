"""ClaimClear in one command: install, configure, start the servers, open the chat (UI2) in your browser.

    Windows (CMD):    start.bat
    macOS / Linux:    ./start.sh
    any system:       python start.py

First run (a few minutes): creates the two Python environments, installs everything, tries to install
Tesseract OCR, loads the development cases and builds the policy index. Later runs skip all of that and
start in seconds. Then it starts the five MCP servers (ports 8101-8105) in the background and opens the chat
(UI2, Chainlit: http://localhost, port 80) in your browser: upload documents, the review starts by itself, ask
questions. Ctrl+C here stops everything. ``--ui1`` opens the earlier web UI (UI1, http://127.0.0.1:8000) instead
(it then stops when its page is closed). ``--port N`` or ``CLAIMCLEAR_CHAT_PORT=N`` picks another port for the chat; when port 80 is taken or not allowed
(Linux without root), the default falls back to 8001.

The chat model: if a local LLM is running (Ollama, LM Studio or llama.cpp; start one with start_llm.bat or
./start_llm.sh), it is chosen by default, so medical records never leave this computer. Otherwise an OpenRouter
key in ``.env`` (``OPENROUTER_API_KEY=...``) is used. With neither, answers come from the case and the policy
wording, and the sample cases and gen-data-style PDFs are read without a model.

Privacy: uploaded documents, chats and dry-run filings are kept only while ClaimClear runs. They are deleted
when the page closes (and at start-up, should a previous run have been killed). ``--keep-data`` keeps them.

    python start.py --ui1             open UI1 (the earlier web UI) instead of the chat
    python start.py --port 8001       the chat on another port (default 80; also CLAIMCLEAR_CHAT_PORT)
    python start.py --setup-only      build the environments and data, then exit (used by the Docker image)
    python start.py --console         the terminal console instead of a UI
    python start.py --no-browser      don't open the browser (open the printed address yourself)
    python start.py --auto SET-01     no questions asked: run one case, approve, exit (a self-check)
    python start.py --servers-only    just keep the servers running (Ctrl+C stops them)
    python start.py --reinstall       rebuild the environments from scratch
    python start.py --no-local-llm    don't switch to a running local LLM (use the saved setting)
    python start.py --set-openrouter-key   paste your OpenRouter key at a hidden prompt; checked, then saved to .env
    python start.py --check-openrouter     is the saved key accepted, and how much credit is left?
    python start.py --memory-user ID  long-term memory for this local user (verified claims, grievances and the topics
                                      of earlier conversations), only after: python -m claimclear_memory consent ID

Start it with ANY Python (3.8 or newer, including 3.15 and later). The packages ClaimClear depends on are
published for Python 3.12-3.14 only, so the environments are always built with one of those: your Python if
it is one of them, else another one found on this machine, else a private copy of Python 3.13 that is
downloaded into this folder automatically (with ``uv``; nothing is installed system-wide).

    python start.py --download-python   always use the private downloaded Python
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
WIN = os.name == "nt"
PORTS = {"settlement-engine": 8101, "case-records": 8102, "policy-kb": 8103, "insurer-portal": 8104,
         "document-reader": 8105}
SERVER_PACKAGES = ["servers/settlement_engine", "servers/case_records", "servers/policy_kb", "servers/insurer_portal",
                   "servers/document_reader", "contracts", "memory"]
WORDING = "development/dev_data/wordings/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf"


def say(text: str) -> None:
    print(f"[start] {text}", flush=True)


def venv_python(name: str) -> Path:
    return REPO / name / ("Scripts/python.exe" if WIN else "bin/python")


def run(cmd: list, cwd: Path = REPO, quiet: bool = True, env: dict = None) -> None:
    """Run a set-up command; on failure show its output and stop."""
    res = subprocess.run([str(c) for c in cmd], cwd=cwd, text=True, encoding="utf-8", errors="replace", env=env,
                         stdout=subprocess.PIPE if quiet else None, stderr=subprocess.STDOUT if quiet else None)
    if res.returncode != 0:
        sys.exit(f"[start] FAILED: {' '.join(str(c) for c in cmd)}\n{(res.stdout or '')[-3000:]}")


def stamp(files: list[str]) -> str:
    """Changes when a requirements or package file changes, so the install is redone only then."""
    h = hashlib.sha256()
    for f in files:
        h.update((REPO / f).read_bytes())
    return h.hexdigest()


SUPPORTED = ((3, 13), (3, 12), (3, 14))        # what the dependencies publish wheels for, best first
DOWNLOAD_VERSION = "3.13"
FORCE_DOWNLOAD = False


def version_of(cmd: list) -> tuple:
    """(major, minor) of a Python command, or () when it can't be run."""
    try:
        out = subprocess.run([str(c) for c in cmd] + ["-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                             capture_output=True, text=True, timeout=30)
        major, minor = out.stdout.split()
        return int(major), int(minor)
    except Exception:
        return ()


def find_python() -> list:
    """A supported Python already on this machine (the one running this script first), or [] if none."""
    if FORCE_DOWNLOAD:
        return []
    if sys.version_info[:2] in SUPPORTED:
        return [sys.executable]
    for major, minor in SUPPORTED:
        tag = f"{major}.{minor}"
        candidates = [["py", f"-{tag}"]] if WIN else []
        candidates.append([f"python{tag}"])
        for cmd in candidates:
            if shutil.which(cmd[0]) and version_of(cmd) == (major, minor):
                return cmd
    return []


def uv_command() -> list:
    """``uv`` (a single-file tool that can download Python), installed into a small private environment."""
    boot = REPO / ".venv-bootstrap"
    uv = boot / ("Scripts/uv.exe" if WIN else "bin/uv")
    if not uv.exists():
        why = "--download-python" if FORCE_DOWNLOAD else (
            f"this Python ({sys.version_info[0]}.{sys.version_info[1]}) is not supported by the dependencies and no "
            "Python 3.12-3.14 was found")
        say(f"{why}: downloading a private Python {DOWNLOAD_VERSION} into .python ...")
        run([sys.executable, "-m", "venv", boot])
        run([venv_python(".venv-bootstrap"), "-m", "pip", "install", "-q", "--disable-pip-version-check", "uv"])
    return [uv]


def make_venv(path: Path) -> None:
    base = find_python()
    if base:
        run([*base, "-m", "venv", path])
    else:
        # the downloaded Python lives in this folder (.python), never system-wide; with --download-python
        # uv must use it even if it could find another Python on the machine
        env = {**os.environ, "UV_PYTHON_INSTALL_DIR": str(REPO / ".python")}
        if FORCE_DOWNLOAD:
            env["UV_PYTHON_PREFERENCE"] = "only-managed"
        run([*uv_command(), "venv", "--python", DOWNLOAD_VERSION, "--seed", path], env=env)


def ensure_env(name: str, label: str, installs: list[list[str]], watched: list[str], reinstall: bool) -> Path:
    py, marker = venv_python(name), REPO / name / ".claimclear_installed"
    want = stamp(watched)
    stale = py.exists() and version_of([py]) not in SUPPORTED     # e.g. built earlier with Python 3.15
    if (reinstall or stale or (FORCE_DOWNLOAD and not marker.exists())) and (REPO / name).exists():
        shutil.rmtree(REPO / name)
    if py.exists() and marker.exists() and marker.read_text() == want:
        return py
    say(f"installing {label} into {name} (first run only; takes a few minutes) ...")
    if not py.exists():
        make_venv(REPO / name)
    for args in installs:
        run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", *args])
    marker.write_text(want)
    return py


def tesseract_installed_on_windows() -> bool:
    """The UB-Mannheim installer doesn't add Tesseract to PATH; the document reader finds it in these folders."""
    if not WIN:
        return False
    roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
    local = os.environ.get("LOCALAPPDATA")
    folders = [Path(r) / "Tesseract-OCR" for r in roots if r] + ([Path(local) / "Programs" / "Tesseract-OCR"] if local else [])
    return any((f / "tesseract.exe").exists() for f in folders)


def ensure_tesseract() -> None:
    """Best effort: OCR reads scanned bills. Without it scanned pages are reported unreadable (safe, not fatal)."""
    if shutil.which("tesseract") or tesseract_installed_on_windows():
        return
    attempts = []
    if WIN and shutil.which("winget"):
        attempts = [["winget", "install", "--id", "UB-Mannheim.TesseractOCR", "-e", "--silent",
                     "--accept-package-agreements", "--accept-source-agreements"]]
    elif sys.platform == "darwin" and shutil.which("brew"):
        attempts = [["brew", "install", "tesseract"]]
    elif shutil.which("apt-get"):
        sudo = [] if os.geteuid() == 0 else (["sudo", "-n"] if shutil.which("sudo") else None)
        if sudo is not None:
            attempts = [[*sudo, "apt-get", "install", "-y", "-q", "tesseract-ocr", "tesseract-ocr-eng"]]
    for cmd in attempts:
        say("installing Tesseract OCR ...")
        if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return
    say("note: Tesseract OCR not found and could not be installed automatically. Everything works except "
        "scanned documents (cases such as SET-32); install it later and run this again.")


def ensure_data(server_py: Path) -> None:
    if not (REPO / "var" / "case_store").exists() or not (REPO / "var" / "dataset_map.json").exists():
        say("loading the development cases ...")
        run([server_py, "-m", "case_records.register_dataset", "--split", "dev"], cwd=REPO / "servers" / "case_records")
    if not (REPO / "var" / "policy_kb" / "index.json").exists():
        say("building the policy wording index ...")
        run([server_py, "-m", "policy_kb", "build", "--wording", REPO / WORDING], cwd=REPO / "servers" / "policy_kb")


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_servers(server_py: Path, env: dict):
    """Start the five servers (or reuse running ones). Returns the launcher process, or None when reused."""
    if all(port_open(p) for p in PORTS.values()):
        say("servers already running: using them")
        return None
    busy = [f"{n} :{p}" for n, p in PORTS.items() if port_open(p)]
    if busy:
        sys.exit(f"[start] ports in use by something else: {', '.join(busy)}. Close it and run again.")
    log = REPO / "var" / "logs" / "servers.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    say("starting the five MCP servers ...")
    proc = subprocess.Popen([str(server_py), str(REPO / "scripts" / "dev_servers.py")], cwd=REPO, env=env,
                            stdout=open(log, "w", encoding="utf-8"), stderr=subprocess.STDOUT)
    deadline = time.time() + 90
    while time.time() < deadline and not all(port_open(p) for p in PORTS.values()):
        if proc.poll() is not None:
            sys.exit(f"[start] the servers stopped during start-up. Last lines of {log}:\n"
                     + "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]))
        time.sleep(0.3)
    if not all(port_open(p) for p in PORTS.values()):
        proc.terminate()
        sys.exit(f"[start] the servers did not answer within 90 s; see {log}")
    say("servers up: " + ", ".join(f"{n} :{p}" for n, p in PORTS.items()))
    return proc


def load_dotenv() -> None:
    """``KEY=value`` lines from ``.env`` (API keys etc.) into the environment, without overriding real variables."""
    path = REPO / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def choose_local_llm(enabled: bool) -> None:
    """Use a running local LLM by default; otherwise OpenRouter (if a key is saved) or no model."""
    from start_llm import find_local_llm
    base, key = os.environ.get("CLAIMCLEAR_LLM_BASE_URL"), os.environ.get("OPENROUTER_API_KEY")
    found = find_local_llm(base, os.environ.get("CLAIMCLEAR_LOCAL_MODEL")) if enabled else None
    if found:
        os.environ["CLAIMCLEAR_LLM_BASE_URL"], os.environ["CLAIMCLEAR_LOCAL_MODEL"] = found["base"], found["model"]
        say(f"local LLM found: {found['model']} ({found['engine']}); the chat uses it, records stay on this computer")
        return
    if base and enabled:                            # saved, but not running now
        os.environ.pop("CLAIMCLEAR_LLM_BASE_URL")
        say(f"the local LLM at {base} is not running ({'using OpenRouter' if key else 'no model'}). "
            "Start it with start_llm.bat or ./start_llm.sh.")
    elif key and not base:
        say("chat model: OpenRouter (no local LLM is running)")


def purge_user_data(server_py: Path) -> None:
    """Delete uploaded cases, their files, the text cache and dry-run filings (scripts/upload_case.py --purge)."""
    res = subprocess.run([str(server_py), str(REPO / "scripts" / "upload_case.py"), "--purge"], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        done = json.loads(res.stdout)
    except ValueError:
        say("note: could not clear previous data: " + (res.stdout + res.stderr)[-300:])
        return
    if done.get("cases_deleted") or done.get("filings_deleted"):
        say(f"cleared previous data: {done['cases_deleted']} uploaded case(s), {done['files_deleted']} file(s), "
            f"{done['filings_deleted']} dry-run filing(s)")


def free_port(start: int = 8000) -> int:
    for port in range(start, start + 50):
        if not port_open(port):
            return port
    sys.exit("[start] no free port for the web UI between 8000 and 8049")


UI_HOST = os.environ.get("CLAIMCLEAR_UI_HOST", "127.0.0.1")     # 0.0.0.0 inside Docker
DEFAULT_CHAT_PORT, FALLBACK_CHAT_PORT = 80, 8001


def chat_port(asked: "int | None") -> int:
    """The chat's port: --port, else CLAIMCLEAR_CHAT_PORT, else 80; port 80 falls back to 8001 only when it was not
    asked for and is taken or not allowed (Linux and macOS ports below 1024 need root on some systems)."""
    if asked:
        return asked
    if os.environ.get("CLAIMCLEAR_CHAT_PORT"):
        return int(os.environ["CLAIMCLEAR_CHAT_PORT"])
    no_root = sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() != 0
    if port_open(DEFAULT_CHAT_PORT) or no_root:
        say(f"port {DEFAULT_CHAT_PORT} is {'in use' if port_open(DEFAULT_CHAT_PORT) else 'not allowed without root'}: "
            f"the chat uses {FALLBACK_CHAT_PORT}")
        return FALLBACK_CHAT_PORT
    return DEFAULT_CHAT_PORT


def run_chat(agents_py: Path, env: dict, open_browser: bool, port: int) -> int:
    """UI2, the Chainlit chat (the default): runs until Ctrl+C."""
    if port_open(port):
        sys.exit(f"[start] port {port} is in use (another chat running?); choose one with --port")
    url = "http://localhost/" if port == 80 else f"http://localhost:{port}/"
    chat = subprocess.Popen([str(agents_py), "-m", "chainlit", "run", "app.py", "--host", UI_HOST,
                             "--port", str(port), "-h"], cwd=REPO / "ui_chainlit", env=env)
    try:
        for _ in range(240):                         # first start compiles the UI: give it up to two minutes
            if chat.poll() is not None or port_open(port):
                break
            time.sleep(0.5)
        if chat.poll() is None:
            say(f"ClaimClear is ready at {url} (the chat). Press Ctrl+C here to stop everything.")
            if open_browser:
                import webbrowser
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
        return chat.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if chat.poll() is None:
            chat.terminate()
            try:
                chat.wait(timeout=10)
            except subprocess.TimeoutExpired:
                chat.kill()


def run_web(agents_py: Path, env: dict, open_browser: bool) -> int:
    """Start the web UI and wait until the user closes the page (the UI then exits by itself)."""
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    web = subprocess.Popen([str(agents_py), "-m", "claimclear_graph.webapp", "--host", UI_HOST, "--port", str(port)],
                           cwd=REPO, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    try:
        for line in web.stdout:
            line = line.rstrip()
            if line.startswith("CLAIMCLEAR_UI_READY"):
                say(f"ClaimClear is ready at {url}")
                if open_browser:
                    import webbrowser
                    try:
                        webbrowser.open(url)
                    except Exception:
                        pass
                say("open that address in your browser if it didn't open by itself. Everything keeps running until "
                    "you close the ClaimClear page (or press Ctrl+C here).")
            elif line:
                print(f"  {line}", flush=True)
        return web.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if web.poll() is None:
            web.terminate()
            try:
                web.wait(timeout=10)
            except subprocess.TimeoutExpired:
                web.kill()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--auto", metavar="CASE", help="run one case without prompts (approve at the gate) and exit")
    ap.add_argument("--servers-only", action="store_true", help="start the servers and keep them running")
    ap.add_argument("--console", action="store_true", help="the terminal console instead of the web UI")
    ap.add_argument("--ui1", action="store_true", help="open UI1 (the earlier web UI) instead of the chat (UI2)")
    ap.add_argument("--port", type=int, help="the chat's port (default 80, else CLAIMCLEAR_CHAT_PORT; falls back to "
                                             "8001 when 80 is taken)")
    ap.add_argument("--setup-only", action="store_true", help="build the environments and data, then exit")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    ap.add_argument("--keep-data", action="store_true",
                    help="keep uploaded documents, chats and filings after closing (default: deleted)")
    ap.add_argument("--reinstall", action="store_true", help="rebuild both environments")
    ap.add_argument("--no-local-llm", action="store_true", help="don't switch to a running local LLM by itself")
    ap.add_argument("--set-openrouter-key", action="store_true",
                    help="paste an OpenRouter API key (hidden prompt or piped input); checked, saved to .env, then exit")
    ap.add_argument("--check-openrouter", action="store_true",
                    help="check the saved OpenRouter key (accepted? credit left?) and exit")
    ap.add_argument("--memory-user", metavar="ID",
                    help="turn on long-term memory for this local user ID (needs: python -m claimclear_memory consent ID)")
    ap.add_argument("--download-python", action="store_true",
                    help=f"build the environments with a private downloaded Python {DOWNLOAD_VERSION}")
    args = ap.parse_args()
    if args.set_openrouter_key or args.check_openrouter:
        import openrouter_key
        if args.set_openrouter_key:
            return openrouter_key.set_key(REPO / ".env")
        return openrouter_key.check_saved(REPO / ".env")
    global FORCE_DOWNLOAD
    FORCE_DOWNLOAD = args.download_python
    load_dotenv()
    choose_local_llm(not args.no_local_llm and os.environ.get("CLAIMCLEAR_AUTO_LOCAL") != "0")
    if args.memory_user:
        os.environ["CLAIMCLEAR_MEMORY_USER"] = args.memory_user
        say(f"long-term memory for user {args.memory_user!r} (used only with that user's consent: "
            f"python -m claimclear_memory consent {args.memory_user})")

    server_py = ensure_env(".venv", "the servers",
                           [["-r", "requirements-servers.txt"], [x for p in SERVER_PACKAGES for x in ("-e", p)]],
                           ["requirements-servers.txt", *[f"{p}/pyproject.toml" for p in SERVER_PACKAGES]], args.reinstall)
    agents_py = ensure_env(".venv-agents", "the agents", [["-r", "requirements-agents.txt"], ["-r", "requirements-ui.txt"]],
                           ["requirements-agents.txt", "requirements-ui.txt", "agents/toolkit/pyproject.toml",
                            "agents/orchestration/pyproject.toml"], args.reinstall)
    ensure_tesseract()
    ensure_data(server_py)
    if args.setup_only:
        say("setup done (environments and data); start ClaimClear with: python start.py")
        return 0
    keep = args.keep_data or os.environ.get("CLAIMCLEAR_KEEP_DATA") == "1"
    if not keep:
        purge_user_data(server_py)                  # leftovers of a run that was killed

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "CLAIMCLEAR_MCP_MODE": "http",
           "CLAIMCLEAR_SERVER_PYTHON": str(server_py), "CLAIMCLEAR_REPO": str(REPO)}
    servers = start_servers(server_py, env)
    try:
        if args.servers_only:
            say("servers are running. Press Ctrl+C to stop them.")
            while servers is None or servers.poll() is None:
                time.sleep(1)
            return 1
        if args.console or args.auto:
            cmd = [str(agents_py), str(REPO / "agents" / "orchestration" / "examples" / "console.py")]
            return subprocess.call(cmd + (["--auto", args.auto] if args.auto else []), cwd=REPO, env=env)
        code = (run_web(agents_py, env, open_browser=not args.no_browser) if args.ui1 else
                run_chat(agents_py, env, open_browser=not args.no_browser, port=chat_port(args.port)))
        if not keep:
            purge_user_data(server_py)
            say("your uploaded documents, chats and filings were deleted (use --keep-data to keep them)")
        return code
    except KeyboardInterrupt:
        return 0
    finally:
        if servers is not None and servers.poll() is None:
            servers.terminate()                     # dev_servers.py stops its five children on exit
            try:
                servers.wait(timeout=15)
            except subprocess.TimeoutExpired:
                servers.kill()
            say("servers stopped")


if __name__ == "__main__":
    sys.exit(main())
