"""Start a local LLM for ClaimClear and choose its model, so medical records never leave this computer.

    Windows (CMD):    start_llm.bat
    macOS / Linux:    ./start_llm.sh
    any system:       python start_llm.py

It finds Ollama (and offers to install it if it is missing), starts it in the background, shows the models you
have and a few recommended ones, downloads the one you choose, loads it into memory and saves the choice in
.env. ClaimClear (start.bat / ./start.sh) then uses it automatically. The model keeps running after this
window closes; Ollama unloads it from memory by itself when it has been idle for a while.

    python start_llm.py                       choose from a menu
    python start_llm.py --model qwen2.5:7b    use this model (downloaded if needed), no questions
    python start_llm.py --list                show installed and recommended models, change nothing
    python start_llm.py --start               then start ClaimClear too (any further options go to start.py)

Already running LM Studio, llama.cpp or another OpenAI-compatible server? It is found too (ports 1234 and
8080), and you choose among the models it has loaded.

Standard library only: runs on any Python 3.8 or newer, before anything else is installed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent
WIN = os.name == "nt"
OLLAMA_URL = "http://127.0.0.1:11434/v1"
SERVERS = [("Ollama", OLLAMA_URL), ("LM Studio", "http://127.0.0.1:1234/v1"),
           ("llama.cpp server", "http://127.0.0.1:8080/v1")]
RECOMMENDED = [  # Ollama name, what it is, download size
    ("llama3.1:8b", "Meta Llama 3.1 8B: a good all-rounder (needs about 8 GB of RAM)", "4.9 GB"),
    ("qwen2.5:7b", "Qwen 2.5 7B: strong with tables and figures (about 8 GB of RAM)", "4.7 GB"),
    ("mistral:7b", "Mistral 7B: fast, plain English (about 8 GB of RAM)", "4.1 GB"),
    ("gemma2:9b", "Gemma 2 9B: careful answers, a little slower (about 10 GB of RAM)", "5.4 GB"),
    ("llama3.2:3b", "Llama 3.2 3B: small and quick for older computers (about 4 GB of RAM)", "2.0 GB"),
]
NOT_CHAT = ("embed", "bge", "rerank", "whisper", "clip")
# localhost must never go through a proxy
_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def say(text: str) -> None:
    print(f"[llm] {text}", flush=True)


def http_json(url: str, body: dict = None, timeout: float = 1.5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with _HTTP.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def chat_models(base: str):
    """Names of the chat models a server offers, or ``None`` if nothing answers at ``base``."""
    try:
        listed = http_json(base.rstrip("/") + "/models").get("data") or []
    except Exception:
        return None
    names = [m.get("id", "") for m in listed if isinstance(m, dict)]
    return [n for n in names if n and not any(w in n.lower() for w in NOT_CHAT)]


def same_model(a: str, b: str) -> bool:
    """``llama3.1`` and ``llama3.1:latest`` are the same Ollama model."""
    def norm(x):
        return x if ":" in x else x + ":latest"
    return bool(a and b) and norm(a.strip().lower()) == norm(b.strip().lower())


def find_local_llm(base: str = None, model: str = None):
    """The first running local server that has a chat model: ``{"engine", "base", "model", "models"}`` or ``None``.

    ``base`` (an address saved in .env) is tried first; ``model`` is used if that server has it, else its first
    chat model."""
    known = dict((url.rstrip("/"), name) for name, url in SERVERS)
    saved = [(known.get(base.rstrip("/"), "your saved server"), base)] if base else []
    servers = saved + [s for s in SERVERS if s[1] != base]
    for engine, url in servers:
        models = chat_models(url)
        if models:
            pick = next((m for m in models if same_model(m, model or "")), models[0])
            return {"engine": engine, "base": url, "model": pick, "models": models}
    return None


# --------------------------------------------------------------------------- Ollama


def find_ollama():
    exe = shutil.which("ollama")
    if exe:
        return exe
    places = []
    if WIN:
        places.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
    elif sys.platform == "darwin":
        places += [Path("/Applications/Ollama.app/Contents/Resources/ollama"), Path("/opt/homebrew/bin/ollama")]
    places.append(Path("/usr/local/bin/ollama"))
    return next((str(p) for p in places if p.is_file()), None)


def ask(question: str, default: str = "") -> str:
    if not sys.stdin.isatty():
        return default
    try:
        answer = input(question).strip()
    except EOFError:
        return default
    return answer or default


def install_ollama():
    """Offer to install Ollama with the system's package manager; return its path, or ``None``."""
    say("Ollama (the program that runs local models) is not installed.")
    if WIN and shutil.which("winget"):
        cmd = ["winget", "install", "--id", "Ollama.Ollama", "-e", "--accept-source-agreements",
               "--accept-package-agreements"]
    elif sys.platform == "darwin" and shutil.which("brew"):
        cmd = ["brew", "install", "ollama"]
    else:
        say("Install it from https://ollama.com/download"
            + ("  (or run: curl -fsSL https://ollama.com/install.sh | sh)" if sys.platform.startswith("linux") else "")
            + ", then run this again.")
        return None
    if ask(f"Install it now with: {' '.join(cmd[:4])}? [Y/n] ", "y").lower() not in ("y", "yes"):
        say("Install it from https://ollama.com/download, then run this again.")
        return None
    if subprocess.call(cmd) != 0:
        say("the installation did not finish. Install it from https://ollama.com/download, then run this again.")
        return None
    return find_ollama()


def start_ollama(exe: str) -> bool:
    """Run ``ollama serve`` in the background (it keeps running after this window closes)."""
    log = REPO / "var" / "ollama.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    say("starting Ollama in the background ...")
    kw = {"creationflags": 0x00000008 | 0x00000200} if WIN else {"start_new_session": True}   # detached
    with open(log, "ab") as out:
        subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=out, stderr=out, **kw)
    for _ in range(60):
        if chat_models(OLLAMA_URL) is not None:
            return True
        time.sleep(0.5)
    say(f"Ollama did not start within 30 s; see {log}")
    return False


# --------------------------------------------------------------------------- choosing


def show_menu(installed: list, current: str, can_download: bool) -> list:
    """Print the numbered choices and return them in order."""
    choices = list(installed)
    print()
    if installed:
        print("  Installed models:")
        for i, name in enumerate(installed, 1):
            print(f"   {i:>2}. {name}{'   (current)' if same_model(name, current) else ''}")
    if can_download:
        extra = [r for r in RECOMMENDED if not any(same_model(r[0], n) for n in installed)]
        if extra:
            print("  Recommended to download:")
        for name, about, size in extra:
            choices.append(name)
            print(f"   {len(choices):>2}. {name:<13} {about}, {size}")
    print()
    return choices


def choose(installed: list, current: str, can_download: bool) -> str:
    default = next((m for m in installed if same_model(m, current)), None) or (installed[0] if installed
                                                                              else RECOMMENDED[0][0])
    choices = show_menu(installed, current, can_download)
    if not sys.stdin.isatty():
        say(f"no keyboard here: using {default}")
        return default
    hint = "a number" + (", or any model name from ollama.com/library" if can_download else "")
    while True:
        answer = ask(f"Which model? Type {hint} [Enter = {default}]: ", default)
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        if not answer.isdigit() and (can_download or any(same_model(answer, m) for m in installed)):
            return answer
        print("  Please type one of the numbers shown.")


def pull(exe: str, model: str) -> bool:
    say(f"downloading {model} (only the first time; this can take several minutes) ...")
    return subprocess.call([exe, "pull", model]) == 0


def warm_up(base: str, model: str) -> bool:
    """Load the model into memory now, so ClaimClear's first answer is not slow."""
    say(f"loading {model} into memory (up to a few minutes the first time) ...")
    try:
        http_json(base + "/chat/completions", {"model": model, "max_tokens": 1,
                                               "messages": [{"role": "user", "content": "Reply OK."}]}, timeout=600)
        return True
    except Exception as exc:
        say(f"the model did not answer: {exc}")
        return False


def save(base: str, model: str) -> None:
    """Write the choice to .env (git-ignored); start.py and the web UI read it. Other lines are kept."""
    path = REPO / ".env"
    values = {"CLAIMCLEAR_LLM_BASE_URL": base, "CLAIMCLEAR_LOCAL_MODEL": model}
    drop = set(values) | {"CLAIMCLEAR_AUTO_LOCAL"}          # choosing a local model turns automatic choice back on
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() not in drop]
    path.write_text("\n".join(lines + [f"{k}={v}" for k, v in values.items()]) + "\n", encoding="utf-8")


def saved_setting(name: str) -> str:
    path = REPO / ".env"
    if os.environ.get(name) or not path.exists():
        return os.environ.get(name, "")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", help="the model to use, e.g. llama3.1:8b (downloaded if needed)")
    ap.add_argument("--list", action="store_true", help="show installed and recommended models and exit")
    ap.add_argument("--start", action="store_true", help="then start ClaimClear (extra options go to start.py)")
    args, rest = ap.parse_known_args(argv)
    if rest and not args.start:
        ap.error("unrecognised arguments: " + " ".join(rest))
    current = args.model or saved_setting("CLAIMCLEAR_LOCAL_MODEL")

    exe = find_ollama()
    running = chat_models(OLLAMA_URL) is not None
    if not running and not exe:
        other = find_local_llm()                                     # LM Studio, llama.cpp ...
        if other:
            say(f"found {other['engine']} at {other['base']} (Ollama is not installed)")
            if args.list:
                show_menu(other["models"], current, False)
                return 0
            model = args.model or choose(other["models"], current, False)
            if not any(same_model(model, m) for m in other["models"]):
                say(f"{other['engine']} has no model {model}; load it there first.")
                return 1
            return finish(other["base"], model, args, rest)
        if args.list:
            show_menu([], current, True)
            say("Ollama is not installed: these can be downloaded once it is (https://ollama.com/download).")
            return 0
        exe = install_ollama()
        if not exe:
            return 1
    if not running and not (chat_models(OLLAMA_URL) is not None or start_ollama(exe)):
        return 1

    installed = chat_models(OLLAMA_URL) or []
    if args.list:
        show_menu(installed, current, True)
        return 0
    model = args.model or choose(installed, current, True)
    if not any(same_model(model, m) for m in installed):
        if not exe:
            say("Ollama is running but its program was not found, so models can't be downloaded from here. "
                f"Run: ollama pull {model}")
            return 1
        if not pull(exe, model):
            say(f"could not download {model}. Check the name at https://ollama.com/library and your connection.")
            return 1
        installed = chat_models(OLLAMA_URL) or [model]
        model = next((m for m in installed if same_model(m, model)), model)
    return finish(OLLAMA_URL, model, args, rest)


def finish(base: str, model: str, args, rest: list) -> int:
    if not warm_up(base, model):
        return 1
    save(base, model)
    say(f"ready: {model} at {base}. Saved to .env, so ClaimClear uses it automatically.")
    if args.start:
        return subprocess.call([sys.executable, str(REPO / "start.py"), *rest], cwd=REPO)
    say("now start ClaimClear: start.bat (Windows) or ./start.sh (macOS / Linux).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
