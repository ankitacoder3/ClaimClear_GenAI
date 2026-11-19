"""The web UI server: every HTTP endpoint and WebSocket message, its guards, model settings, data clearing, lifetime.

Runs the real Starlette app on recorded tool results (``ReplayToolkit``); uploads and data clearing run the real
``scripts/upload_case.py`` against a temporary case store, never the project's own ``var/``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from claimclear_graph import chat
from claimclear_graph.testing import ReplayToolkit
from claimclear_graph.webapp import server

from conftest import condition_question_open, load

REPO = Path(server.REPO)
CASES = REPO / "dev_data" / "dataset" / "dev" / "cases"
pytestmark = pytest.mark.skipif(not (REPO / ".venv").exists(), reason="needs the servers' environment for uploads")


def replay():
    calls = load("SET-01")["calls"] + load("SET-02")["calls"] + load("SET-32")["calls"]
    hit = {"clause_id": "C.3", "title": "Cataract", "text": "Cataract is covered up to Rs.40,000 per eye.", "citation": "C.3"}
    return ReplayToolkit(calls, overrides={"search_clauses": lambda *a, **k: {"hits": [hit]},
                                           "reproduce_deduction": condition_question_open(calls)})


@pytest.fixture
def env(fresh_var, tmp_path, monkeypatch):
    """A temporary var/ and case store with the dev dataset registered, and a temporary .env."""
    var = fresh_var
    for k in server.MODEL_KEYS + ("CLAIMCLEAR_CHECKPOINTS",):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CLAIMCLEAR_VAR", str(var))
    monkeypatch.setenv("CLAIMCLEAR_CASE_STORE", str(var / "case_store"))
    monkeypatch.setenv("CLAIMCLEAR_PORTAL_STORE", str(var / "insurer_portal" / "dry_run.json"))
    monkeypatch.setattr(server, "ENV_FILE", tmp_path / ".env")
    import os
    saved = {k: os.environ.get(k) for k in server.MODEL_KEYS}
    yield tmp_path
    for k, v in saved.items():                     # the settings endpoint changes the process environment by design
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def app(env):
    stops = []
    application = server.create_app(stop=stops.append, toolkit_factory=replay, grace=0.3)
    application.state.stops = stops
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def fixture_upload(dataset_id):
    fx = load(dataset_id)
    return {"case_id": fx["case_id"], "extraction": {"claim": fx["claim"], "letter": fx["letter"]}}


def until(ws, *kinds, limit=400):
    seen = []
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        seen.append(m)
        if m["type"] in kinds:
            return m, seen
        if m == {"type": "busy", "value": False} and {"type": "busy", "value": True} in seen and set(kinds) & {"questions", "explanation", "grievance", "outcome",
                                                                   "error", "step"}:
            # the graph finished its run without sending it: fail now instead of waiting forever for a message
            raise AssertionError(f"the run ended without {kinds}: {[x['type'] for x in seen]} "
                                 f"{[x.get('text') for x in seen if x['type'] == 'error']}")
    raise AssertionError(f"never got {kinds}: {[m['type'] for m in seen]}")


def ask(ws, text):
    ws.send_text(json.dumps({"type": "ask", "text": text, "id": "q1"}))
    end, seen = until(ws, "answer_end")
    return "".join(m["text"] for m in seen if m["type"] == "answer_delta"), end


# --------------------------------------------------------------------------- HTTP


def test_index_is_served_uncached(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>ClaimClear</title>" in r.text and r.headers["cache-control"] == "no-store"


def test_status(client):
    s = client.get("/api/status").json()
    assert set(s["servers"]) == {"settlement-engine", "case-records", "policy-kb", "insurer-portal", "document-reader"}
    assert len(s["boot"]) == 12 and s["chat_model"] is False and s["model"].startswith("no model")
    assert [x["name"] for x in s["samples"]] == ["syn-dev-005", "syn-dev-019", "gen-dev-0fa297", "gen-dev-147e01"]


def test_upload_creates_a_case_with_the_users_file_names(client):
    folder = CASES / "syn-dev-005"
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted(folder.iterdir())]
    r = client.post("/api/upload", files=files, data={"roles": ["bill", "discharge_summary", "policy_schedule",
                                                               "settlement_letter"]})
    body = r.json()
    assert r.status_code == 200 and body["case_id"].startswith("case_") and body["policy_no"] == "AS-2025-100478"
    assert [d["name"] for d in body["documents"]] == sorted(p.name for p in folder.iterdir())
    assert body["extraction"]["letter"]["rows"] and "SET-01" in body["how"]


def test_upload_needs_files_and_a_letter(client):
    assert client.post("/api/upload", data={"x": "1"}).status_code == 400
    bill = (CASES / "syn-dev-005" / "bill.pdf").read_bytes()
    r = client.post("/api/upload", files=[("files", ("bill.pdf", bill, "application/pdf"))])
    assert r.status_code == 400 and "settlement letter" in r.json()["error"]


def test_upload_rejects_files_over_25_mb(client):
    big = b"%PDF-1.4\n" + b"0" * (25 * 1024 * 1024 + 1)
    r = client.post("/api/upload", files=[("files", ("settlement_letter.pdf", big, "application/pdf"))])
    assert r.status_code == 400 and "25 MB" in r.json()["error"]


def test_unsupported_files_are_skipped_with_a_warning(client):
    folder = CASES / "syn-dev-005"
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted(folder.iterdir())]
    files.append(("files", ("notes.txt", b"hello", "text/plain")))
    body = client.post("/api/upload", files=files).json()
    assert any("notes.txt" in w for w in body["warnings"]) and len(body["documents"]) == 4


def test_unsafe_file_names_are_neutralised(client):
    folder = CASES / "syn-dev-005"
    files = [("files", ("../../../etc/" + p.name, p.read_bytes(), "application/pdf")) for p in sorted(folder.iterdir())]
    r = client.post("/api/upload", files=files)
    assert r.status_code == 200                                      # stored under neutral IDs, never at that path


def test_samples(client):
    assert client.post("/api/sample", json={"name": "../../etc"}).status_code == 400
    body = client.post("/api/sample", json={"name": "gen-dev-147e01"}).json()
    assert body["how"] == "parsed from the PDF tables" and body["extraction"]["letter"]["paid_amount"]


@pytest.mark.parametrize("path,kwargs", [("/api/shutdown", {}), ("/api/clear", {}),
                                         ("/api/model", {"json": {"provider": "none"}}),
                                         ("/api/upload", {"files": [("files", ("a.pdf", b"x", "application/pdf"))]})])
def test_other_websites_cannot_change_anything(client, app, path, kwargs):
    r = client.post(path, headers={"Origin": "https://evil.example"}, **kwargs)
    assert r.status_code == 403 and app.state.stops == []


def test_close_button_stops_the_ui(client, app):
    assert client.post("/api/shutdown").json() == {"ok": True} and app.state.stops == ["the Close button"]


# --------------------------------------------------------------------------- model settings


class GoodModel:
    model = "test-model"

    async def ainvoke(self, prompt):
        return "OK"

    async def astream(self, messages):
        from langchain_core.messages import AIMessageChunk
        for w in ["R3 ", "is ", "disputable."]:
            yield AIMessageChunk(content=w)


class BadModel:
    async def ainvoke(self, prompt):
        raise PermissionError("invalid x-api-key sk-secret-12345678")


def test_model_settings_report_no_model(client):
    m = client.get("/api/model").json()
    assert m["provider"] == "none" and m["configured"] is False and m["key_saved"] == {"openrouter": False}
    assert set(m["defaults"]) == {"local", "openrouter"} and m["defaults"]["openrouter"]["model"] == "openai/gpt-4.1-mini"
    assert m["defaults"]["local"]["base_url"] == "http://127.0.0.1:11434/v1"


@pytest.mark.parametrize("provider", ["anthropic", "openai", "ollama", "skynet"])
def test_only_local_and_openrouter_are_offered(client, provider):
    assert client.post("/api/model", json={"provider": provider, "api_key": "k"}).status_code == 400


def test_a_key_is_required_for_hosted_models(client):
    r = client.post("/api/model", json={"provider": "openrouter"})
    assert r.status_code == 400 and "API key" in r.json()["error"]


def test_a_failing_model_is_not_saved_and_the_key_not_echoed(client, env, monkeypatch):
    monkeypatch.setattr(chat, "chat_model_from_env", lambda: BadModel())
    r = client.post("/api/model", json={"provider": "openrouter", "api_key": "sk-secret-12345678"}).json()
    assert r["ok"] is False and "invalid x-api-key" in r["error"] and "sk-secret-12345678" not in r["error"]
    assert not (env / ".env").exists()
    import os
    assert "OPENROUTER_API_KEY" not in os.environ                    # restored to the previous settings


def test_local_failure_explains_how_to_start_it(client, monkeypatch):
    monkeypatch.setattr(chat, "chat_model_from_env", lambda: BadModel())
    r = client.post("/api/model", json={"provider": "local", "model": "qwen2.5:7b"}).json()
    assert "start_llm.bat" in r["error"] and "ollama pull qwen2.5:7b" in r["error"]


def test_a_working_model_is_saved_and_used_live(client, env, monkeypatch):
    monkeypatch.setattr(chat, "chat_model_from_env", lambda: GoodModel())
    (env / ".env").write_text("OTHER_SETTING=1\nOPENROUTER_API_KEY=kept\nCLAIMCLEAR_AUTO_LOCAL=0\n", encoding="utf-8")
    r = client.post("/api/model", json={"provider": "local", "base_url": "http://127.0.0.1:11434/v1", "model": "llama3.1"}).json()
    assert r == {"ok": True, "model": "test-model", "configured": True}
    saved = (env / ".env").read_text(encoding="utf-8")
    assert "OTHER_SETTING=1" in saved and "OPENROUTER_API_KEY=kept" in saved     # OpenRouter kept as the fallback
    assert "CLAIMCLEAR_LLM_BASE_URL=http://127.0.0.1:11434/v1" in saved and "CLAIMCLEAR_LOCAL_MODEL=llama3.1" in saved
    assert "CLAIMCLEAR_AUTO_LOCAL" not in saved                                 # automatic choice back on
    assert client.get("/api/status").json()["chat_model"] is True
    with client.websocket_connect("/ws") as ws:
        text, end = ask(ws, "Why R3?")
        assert text == "R3 is disputable." and end["how"] == "llm"


def test_choosing_openrouter_clears_the_local_model_and_sticks(client, env, monkeypatch):
    monkeypatch.setattr(chat, "chat_model_from_env", lambda: GoodModel())
    (env / ".env").write_text("CLAIMCLEAR_LLM_BASE_URL=http://127.0.0.1:11434/v1\nCLAIMCLEAR_LOCAL_MODEL=x\n", encoding="utf-8")
    assert client.post("/api/model", json={"provider": "openrouter", "api_key": "sk-or-123456789"}).json()["ok"]
    saved = (env / ".env").read_text(encoding="utf-8")
    assert "CLAIMCLEAR_LLM_BASE_URL" not in saved and "CLAIMCLEAR_LOCAL_MODEL" not in saved
    assert "OPENROUTER_API_KEY=sk-or-123456789" in saved and "CLAIMCLEAR_CHAT_MODEL=openai/gpt-4.1-mini" in saved
    assert "CLAIMCLEAR_AUTO_LOCAL=0" in saved                                   # start.py won't switch by itself


def test_switching_back_to_no_model(client, monkeypatch, env):
    monkeypatch.setattr(chat, "chat_model_from_env", lambda: None)
    r = client.post("/api/model", json={"provider": "none"}).json()
    assert r == {"ok": True, "model": chat.describe_model(None), "configured": False}


# --------------------------------------------------------------------------- the live session


def test_ask_before_any_case_answers_from_the_policy(client):
    with client.websocket_connect("/ws") as ws:
        text, end = ask(ws, "Is cataract covered?")
    assert "Clause C.3" in text and "Upload your bill" in text and end["how"] == "rules"


def test_full_case_steps_explanation_grievance_and_filing(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "analyse", "upload": fixture_upload("SET-01")}))
        g, seen = until(ws, "grievance")
        steps = [m["label"] for m in seen if m["type"] == "step"]
        assert steps[:4] == ["Supervisor", "DocumentReader", "PolicyAnalyst", "SettlementAuditor"]
        exp = next(m for m in seen if m["type"] == "explanation")
        assert exp["totals"]["disputable"] == "₹8,522.86" and [r["row_id"] for r in exp["rows"]] == ["R1", "R2", "R3", "COPAY"]
        assert g["rows"] == ["R3"]
        text, _ = ask(ws, "What was my diagnosis?")                     # chat works while the gate waits
        assert "Cholelithiasis" in text
        ws.send_text(json.dumps({"type": "decision", "decision": "approve", "text": g["text"] + "\nThanks."}))
        out, _ = until(ws, "outcome")
        assert out["outcome"] == "grievance_filed" and out["submission"]["reference"].startswith("DRYRUN-")
        text, _ = ask(ws, "what is the status of my grievance?")
        assert "DRYRUN-" in text


def test_reject_at_the_gate(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "analyse", "upload": fixture_upload("SET-01")}))
        until(ws, "grievance")
        ws.send_text(json.dumps({"type": "decision", "decision": "reject"}))
        out, _ = until(ws, "outcome")
    assert out["outcome"] == "grievance_declined" and out["submission"] is None


def test_questions_are_asked_and_answered(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "analyse", "upload": fixture_upload("SET-32")}))
        q, _ = until(ws, "questions")
        assert q["questions"][0]["question_id"] == "Q-CONDITION-TYPE"
        ws.send_text(json.dumps({"type": "answers", "answers": {"Q-CONDITION-TYPE": "illness"}}))
        out, _ = until(ws, "outcome")
    assert out["outcome"] == "no_grievance"


def test_documents_that_cannot_be_read_without_a_model(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "analyse", "upload": {"case_id": load("SET-01")["case_id"], "extraction": None}}))
        err, _ = until(ws, "error")
    assert "API key" in err["text"]


def test_decisions_and_answers_without_a_case_are_ignored(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "decision", "decision": "approve"}))
        ws.send_text(json.dumps({"type": "answers", "answers": {}}))
        ws.send_text(json.dumps({"type": "something-else"}))
        text, _ = ask(ws, "still alive?")
    assert text


def test_resume_within_the_same_launch_only(client):
    boot = client.get("/api/status").json()["boot"]
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "analyse", "upload": fixture_upload("SET-01")}))
        s, _ = until(ws, "session")
        until(ws, "grievance")
    with client.websocket_connect("/ws") as ws:                         # a reload in the same launch
        ws.send_text(json.dumps({"type": "resume", "thread_id": s["thread_id"], "boot": boot}))
        r, _ = until(ws, "session")
        g, _ = until(ws, "grievance")
        assert r["resumed"] is True and g["rows"] == ["R3"]
    with client.websocket_connect("/ws") as ws:                         # a page from a previous launch
        ws.send_text(json.dumps({"type": "resume", "thread_id": s["thread_id"], "boot": "previous-run"}))
        r, _ = until(ws, "session")
        assert r == {"type": "session", "thread_id": None, "resumed": False}


def test_new_chat_resets_the_session(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "analyse", "upload": fixture_upload("SET-02")}))
        until(ws, "outcome")
        ws.send_text(json.dumps({"type": "reset"}))
        r, _ = until(ws, "session")
        assert r["thread_id"] is None
        text, _ = ask(ws, "how much can I dispute?")
    assert text.startswith("Here is what your policy wording says:")    # no case any more: answered from the policy


def test_stop_ends_a_reply(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "ask", "text": "Is cataract covered?", "id": "a"}))
        ws.send_text(json.dumps({"type": "stop"}))
        end, _ = until(ws, "answer_end")
    assert end["how"] in ("stopped", "rules")


def test_malformed_messages_close_only_that_connection(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("not json")
    assert client.get("/api/status").status_code == 200


def test_clear_my_data_deletes_uploads_and_resets_pages(client, env):
    folder = CASES / "syn-dev-005"
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted(folder.iterdir())]
    files.append(("files", ("extra_report.pdf", (folder / "bill.pdf").read_bytes() + b"\n%unique", "application/pdf")))
    case_id = client.post("/api/upload", files=files).json()["case_id"]
    index = json.loads((env / "var" / "case_store" / "index.json").read_text())
    assert any(c["case_id"] == case_id for c in index["cases"])
    with client.websocket_connect("/ws") as ws:
        r = client.post("/api/clear").json()
        cleared, _ = until(ws, "cleared")
    assert r["ok"] and r["cases_deleted"] == 1 and r["files_deleted"] == 1
    index = json.loads((env / "var" / "case_store" / "index.json").read_text())
    assert not any(c["case_id"] == case_id for c in index["cases"])


# --------------------------------------------------------------------------- lifetime


def test_the_ui_stops_after_the_last_page_closes(app):
    with TestClient(app) as c:
        with c.websocket_connect("/ws"):
            pass
        deadline = time.time() + 5
        while not app.state.stops and time.time() < deadline:
            time.sleep(0.1)
    assert app.state.stops and "last ClaimClear page was closed" in app.state.stops[0]


def test_the_ui_waits_for_the_first_page(app):
    with TestClient(app) as c:
        time.sleep(1.0)
        assert c.get("/api/status").status_code == 200
    assert app.state.stops == []
