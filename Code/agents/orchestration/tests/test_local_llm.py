"""The local LLM: start_llm.py (start a model, choose it, save it) and start.py choosing it by default."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load(name):
    sys.path.insert(0, str(REPO))                        # start.py imports start_llm from its own folder
    try:
        spec = importlib.util.spec_from_file_location(name, REPO / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules.setdefault(name, mod)
        return mod
    finally:
        sys.path.remove(str(REPO))


start_llm = _load("start_llm")
start = _load("start")


class FakeLLM:
    """An OpenAI-compatible server on a free port: ``/v1/models`` and ``/v1/chat/completions``."""

    def __init__(self, models):
        self.models, self.chats = models, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body):
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send({"data": [{"id": m} for m in outer.models]})

            def do_POST(self):
                outer.chats.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self._send({"choices": [{"message": {"content": "OK"}}]})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def dead_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}/v1"          # nothing listens here


@pytest.fixture
def llm():
    servers = []

    def make(models):
        servers.append(FakeLLM(models))
        return servers[-1]
    yield make
    for s in servers:
        s.close()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """start_llm writes .env (and its log) into a temporary folder; no real local server is ever probed."""
    monkeypatch.setattr(start_llm, "REPO", tmp_path)
    monkeypatch.setattr(start_llm, "SERVERS", [("Ollama", dead_url()), ("LM Studio", dead_url())])
    monkeypatch.setattr(start_llm, "OLLAMA_URL", start_llm.SERVERS[0][1])
    for k in ("CLAIMCLEAR_LLM_BASE_URL", "CLAIMCLEAR_LOCAL_MODEL", "OPENROUTER_API_KEY", "CLAIMCLEAR_AUTO_LOCAL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    return tmp_path


# --------------------------------------------------------------------------- finding a running server


def test_chat_models_lists_only_chat_models(llm):
    s = llm(["llama3.1:8b", "nomic-embed-text:latest", "bge-m3", "qwen2.5:7b"])
    assert start_llm.chat_models(s.base) == ["llama3.1:8b", "qwen2.5:7b"]
    assert start_llm.chat_models(dead_url()) is None


@pytest.mark.parametrize("a,b,same", [("llama3.1", "llama3.1:latest", True), ("Qwen2.5:7B", "qwen2.5:7b", True),
                                      ("llama3.1:8b", "llama3.1", False), ("", "x", False)])
def test_same_model(a, b, same):
    assert start_llm.same_model(a, b) is same


def test_find_prefers_the_saved_server_and_model(repo, llm, monkeypatch):
    lm = llm(["mistral:7b"])
    saved = llm(["llama3.1:8b", "qwen2.5:7b"])
    monkeypatch.setattr(start_llm, "SERVERS", [("LM Studio", lm.base)])
    found = start_llm.find_local_llm(saved.base, "qwen2.5:7b")
    assert found["base"] == saved.base and found["model"] == "qwen2.5:7b"
    assert start_llm.find_local_llm(saved.base, "gone:1b")["model"] == "llama3.1:8b"      # first chat model
    assert start_llm.find_local_llm(dead_url())["engine"] == "LM Studio"                   # saved one is down


def test_a_server_with_no_chat_model_is_skipped(repo, llm, monkeypatch):
    empty, good = llm(["nomic-embed-text"]), llm(["phi3"])
    monkeypatch.setattr(start_llm, "SERVERS", [("Ollama", empty.base), ("LM Studio", good.base)])
    assert start_llm.find_local_llm()["model"] == "phi3"
    monkeypatch.setattr(start_llm, "SERVERS", [("Ollama", empty.base)])
    assert start_llm.find_local_llm() is None


# --------------------------------------------------------------------------- start_llm.py


def test_save_keeps_other_lines_and_turns_automatic_choice_back_on(repo):
    (repo / ".env").write_text("OPENROUTER_API_KEY=sk\nCLAIMCLEAR_AUTO_LOCAL=0\nCLAIMCLEAR_LOCAL_MODEL=old\n")
    start_llm.save("http://127.0.0.1:11434/v1", "qwen2.5:7b")
    lines = (repo / ".env").read_text().splitlines()
    assert lines == ["OPENROUTER_API_KEY=sk", "CLAIMCLEAR_LLM_BASE_URL=http://127.0.0.1:11434/v1",
                     "CLAIMCLEAR_LOCAL_MODEL=qwen2.5:7b"]
    assert start_llm.saved_setting("CLAIMCLEAR_LOCAL_MODEL") == "qwen2.5:7b"


def test_menu_numbers_installed_then_recommended(capsys):
    choices = start_llm.show_menu(["llama3.1:8b"], "llama3.1:8b", True)
    out = capsys.readouterr().out
    assert choices[0] == "llama3.1:8b" and "(current)" in out
    assert "llama3.1:8b" not in choices[1:] and "qwen2.5:7b" in choices          # no installed model offered twice
    assert start_llm.show_menu(["a"], "", False) == ["a"]                        # nothing to download elsewhere


def test_choosing_by_number_name_or_enter(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    answers = iter(["9", "2"])
    monkeypatch.setattr("builtins.input", lambda q: next(answers))
    assert start_llm.choose(["a:1b", "b:2b"], "", False) == "b:2b"               # 9 is not shown: asked again
    monkeypatch.setattr("builtins.input", lambda q: "")
    assert start_llm.choose(["a:1b", "b:2b"], "b:2b", False) == "b:2b"           # Enter keeps the current one
    monkeypatch.setattr("builtins.input", lambda q: "phi3:mini")
    assert start_llm.choose([], "", True) == "phi3:mini"                         # any Ollama name
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert start_llm.choose([], "", True) == start_llm.RECOMMENDED[0][0]         # no keyboard: the default


def test_main_with_a_running_ollama_and_an_installed_model(repo, llm, monkeypatch):
    s = llm(["llama3.1:8b", "qwen2.5:7b"])
    monkeypatch.setattr(start_llm, "OLLAMA_URL", s.base)
    monkeypatch.setattr(start_llm, "find_ollama", lambda: "/usr/bin/ollama")
    assert start_llm.main(["--model", "qwen2.5:7b"]) == 0
    assert s.chats[0]["model"] == "qwen2.5:7b" and s.chats[0]["max_tokens"] == 1          # warmed up
    assert f"CLAIMCLEAR_LLM_BASE_URL={s.base}" in (repo / ".env").read_text()


def test_main_downloads_a_missing_model(repo, llm, monkeypatch):
    s = llm(["llama3.1:8b"])
    monkeypatch.setattr(start_llm, "OLLAMA_URL", s.base)
    monkeypatch.setattr(start_llm, "find_ollama", lambda: "/usr/bin/ollama")
    pulled = []

    def fake_pull(exe, model):
        pulled.append(model)
        s.models.append("mistral:7b")
        return True
    monkeypatch.setattr(start_llm, "pull", fake_pull)
    assert start_llm.main(["--model", "mistral:7b"]) == 0 and pulled == ["mistral:7b"]
    assert "CLAIMCLEAR_LOCAL_MODEL=mistral:7b" in (repo / ".env").read_text()
    monkeypatch.setattr(start_llm, "pull", lambda exe, model: False)
    assert start_llm.main(["--model", "nope:1b"]) == 1                            # a failed download saves nothing
    assert "nope" not in (repo / ".env").read_text()


def test_main_starts_ollama_when_it_is_installed_but_not_running(repo, llm, monkeypatch):
    s = llm(["llama3.1:8b"])
    started = []

    def fake_start(exe):
        started.append(exe)
        monkeypatch.setattr(start_llm, "OLLAMA_URL", s.base)                     # now it answers
        return True
    monkeypatch.setattr(start_llm, "find_ollama", lambda: "/usr/bin/ollama")
    monkeypatch.setattr(start_llm, "start_ollama", fake_start)
    assert start_llm.main([]) == 0 and started == ["/usr/bin/ollama"]


def test_main_uses_lm_studio_when_ollama_is_missing(repo, llm, monkeypatch):
    s = llm(["local-model-q4"])
    monkeypatch.setattr(start_llm, "SERVERS", [("Ollama", start_llm.OLLAMA_URL), ("LM Studio", s.base)])
    monkeypatch.setattr(start_llm, "find_ollama", lambda: None)
    assert start_llm.main([]) == 0 and "CLAIMCLEAR_LOCAL_MODEL=local-model-q4" in (repo / ".env").read_text()
    assert start_llm.main(["--model", "other"]) == 1                              # LM Studio can't download


def test_main_without_any_local_llm_offers_to_install(repo, monkeypatch, capsys):
    monkeypatch.setattr(start_llm, "find_ollama", lambda: None)
    monkeypatch.setattr(start_llm.shutil, "which", lambda name: None)             # no winget / brew
    assert start_llm.main([]) == 1
    assert "ollama.com/download" in capsys.readouterr().out and not (repo / ".env").exists()
    assert start_llm.main(["--list"]) == 0


def test_list_changes_nothing(repo, llm, monkeypatch, capsys):
    s = llm(["llama3.1:8b"])
    monkeypatch.setattr(start_llm, "OLLAMA_URL", s.base)
    monkeypatch.setattr(start_llm, "find_ollama", lambda: "/usr/bin/ollama")
    assert start_llm.main(["--list"]) == 0
    assert "llama3.1:8b" in capsys.readouterr().out and s.chats == [] and not (repo / ".env").exists()


def test_unknown_options_need_start(repo):
    with pytest.raises(SystemExit):
        start_llm.main(["--console"])


def test_start_passes_the_rest_to_start_py(repo, llm, monkeypatch):
    s = llm(["llama3.1:8b"])
    monkeypatch.setattr(start_llm, "OLLAMA_URL", s.base)
    monkeypatch.setattr(start_llm, "find_ollama", lambda: "/usr/bin/ollama")
    calls = []
    monkeypatch.setattr(start_llm.subprocess, "call", lambda cmd, **k: calls.append(cmd) or 0)
    assert start_llm.main(["--start", "--no-browser"]) == 0
    assert calls[0][-2:] == [str(repo / "start.py"), "--no-browser"]


# --------------------------------------------------------------------------- start.py chooses it by default


@pytest.fixture
def launcher(repo, monkeypatch):
    monkeypatch.setitem(sys.modules, "start_llm", start_llm)
    return monkeypatch


def test_start_uses_a_running_local_llm_by_default(launcher, llm, capsys):
    s = llm(["qwen2.5:7b"])
    launcher.setattr(start_llm, "SERVERS", [("Ollama", s.base)])
    launcher.setenv("OPENROUTER_API_KEY", "sk-or")
    start.choose_local_llm(True)
    import os
    assert os.environ["CLAIMCLEAR_LLM_BASE_URL"] == s.base and os.environ["CLAIMCLEAR_LOCAL_MODEL"] == "qwen2.5:7b"
    assert "local LLM found: qwen2.5:7b" in capsys.readouterr().out


def test_start_falls_back_to_openrouter_when_the_saved_local_llm_is_down(launcher, capsys):
    import os
    launcher.setenv("CLAIMCLEAR_LLM_BASE_URL", dead_url())
    launcher.setenv("OPENROUTER_API_KEY", "sk-or")
    start.choose_local_llm(True)
    assert "CLAIMCLEAR_LLM_BASE_URL" not in os.environ and "using OpenRouter" in capsys.readouterr().out


def test_start_with_openrouter_only(launcher, capsys):
    launcher.setenv("OPENROUTER_API_KEY", "sk-or")
    start.choose_local_llm(True)
    assert "chat model: OpenRouter" in capsys.readouterr().out


def test_start_does_not_switch_when_told_not_to(launcher, llm):
    import os
    s = llm(["qwen2.5:7b"])
    launcher.setattr(start_llm, "SERVERS", [("Ollama", s.base)])
    start.choose_local_llm(False)
    assert "CLAIMCLEAR_LLM_BASE_URL" not in os.environ
