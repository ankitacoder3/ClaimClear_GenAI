"""Episodic memory in the chat and the web UI: conversations saved as topics, recalled by meaning, never a source of
figures; the optional model summary is scrubbed and falls back to the questions; memory problems never break a reply."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from starlette.testclient import TestClient

from claimclear_graph import chat, episodic
from claimclear_graph.testing import ReplayToolkit
from claimclear_graph.webapp import server
from claimclear_memory import MemoryStore, NoMemory, UnsafeSummary
from claimclear_memory.store import MemoryStoreError

from conftest import load, run, states_before

EARLIER = [("Why was R3 deducted with the proportionate cut? I think ₹77,777 is wrong", "R3 ..."),
           ("Is the co-pay right?", "COPAY ...")]


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.db")


@pytest.fixture
def mem(store):
    m = store.for_user("u_local")
    m.grant_consent("test:settings")
    return m


@pytest.fixture(scope="module")
def st():
    return states_before("SET-01")["approval_gate"]


def tk():
    hit = {"clause_id": "C.3", "title": "Cataract", "text": "Cataract is covered up to Rs.40,000 per eye.", "citation": "C.3"}
    return ReplayToolkit(load("SET-01")["calls"], overrides={"search_clauses": lambda *a, **k: {"hits": [hit]}})


def collect(agen):
    async def go():
        return [e async for e in agen]
    return run(go())


def streamed(events):
    text = ""
    for e in events:
        if e["type"] == "retract":
            text = ""
        elif e["type"] == "delta":
            text += e["text"]
    return text


class Summariser:
    """A chat model for ``llm_summariser``: records the prompt, replies with ``reply`` (or raises)."""

    def __init__(self, reply="", fail=False):
        self.reply, self.fail, self.prompts = reply, fail, []
        self.max_tokens = 1500

    def model_copy(self, update):
        self.max_tokens = update["max_tokens"]
        return self

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise ConnectionError("model down")
        return AIMessage(content=self.reply)


# --------------------------------------------------------------------------- saving


def test_a_conversation_is_saved_from_the_questions(mem):
    e = run(episodic.save_conversation(mem, EARLIER, case_id="case_a", claim_id="CL-1"))
    assert e.case_id == "case_a" and e.claim_id == "CL-1" and e.source == "chat" and e.turns == 2
    assert "77,777" not in e.summary and "[amount]" in e.summary and "R3" in e.topics


def test_the_model_summary_sees_only_questions_and_is_scrubbed(mem):
    llm = Summariser("The user asked why R3 (₹77,777) was cut and about the co-pay; phone 9876543210.")
    e = run(episodic.save_conversation(mem, EARLIER, case_id="case_a", summariser=episodic.llm_summariser(llm)))
    assert e.source == "chat:llm" and "77,777" not in e.summary and "9876543210" not in e.summary
    assert "R3 ..." not in llm.prompts[0] and "COPAY ..." not in llm.prompts[0]   # answers are never sent
    assert llm.max_tokens == episodic.SUMMARY_MAX_TOKENS


def test_a_failing_model_falls_back_to_the_questions(mem):
    e = run(episodic.save_conversation(mem, EARLIER, summariser=episodic.llm_summariser(Summariser(fail=True))))
    assert e.source == "chat" and e.summary.startswith("Asked about:")


def test_an_unsafe_model_summary_falls_back_to_the_questions(mem, monkeypatch):
    real = mem.remember_conversation

    def picky(turns, **kw):
        if kw.get("summary"):
            raise UnsafeSummary("an amount survived")
        return real(turns, **kw)
    monkeypatch.setattr(mem, "remember_conversation", picky)
    e = run(episodic.save_conversation(mem, EARLIER, summariser=episodic.llm_summariser(Summariser("x"))))
    assert e is not None and e.source == "chat"


def test_nothing_is_saved_without_memory_or_consent(store):
    assert run(episodic.save_conversation(None, EARLIER)) is None
    assert run(episodic.save_conversation(NoMemory("u"), EARLIER)) is None
    assert run(episodic.save_conversation(store.session_memory("u_no_consent"), EARLIER)) is None
    assert run(episodic.save_conversation(store.for_user("u_raw"), EARLIER)) is None          # refused, not raised
    assert store.for_user("u_raw").episodes() == []


# --------------------------------------------------------------------------- recall in the chat


def test_the_model_gets_earlier_conversations_as_background(st, mem):
    run(episodic.save_conversation(mem, EARLIER, case_id="case_a"))
    seen = {}

    class Spy:
        async def astream(self, messages):
            seen["system"] = messages[0].content
            yield AIMessageChunk(content="Last time you asked about R3.")
    events = collect(chat.stream_answer("What did I ask about R3 and the proportionate cut?", st, tk(), Spy(),
                                        memory=mem))
    assert "<earlier_conversations>" in seen["system"] and "Asked about: Why was R3 deducted" in seen["system"]
    assert "77,777" not in seen["system"]
    assert streamed(events) == "Last time you asked about R3." and "earlier conversations" in events[-1]["sources"]


def test_a_figure_from_an_earlier_conversation_is_never_allowed(st, mem):
    run(episodic.save_conversation(mem, EARLIER, case_id="case_a"))

    class Invents:
        async def astream(self, messages):
            yield AIMessageChunk(content="Last time you said ₹77,777 was wrong.")
    events = collect(chat.stream_answer("What did I say about R3 last time?", st, tk(), Invents(), memory=mem))
    assert any(e["type"] == "retract" for e in events) and "77,777" not in streamed(events)


def test_without_a_model_past_questions_are_answered_from_memory(st, mem):
    run(episodic.save_conversation(mem, EARLIER, case_id="case_a", claim_id="CL-1"))
    events = collect(chat.stream_answer("What did I ask last time about the proportionate deduction?", st, tk(),
                                        memory=mem))
    text = streamed(events)
    assert text.startswith("From our earlier conversations") and "claim CL-1" in text and "R3" in text
    assert events[-1]["sources"] == ["earlier conversations"]


def test_a_question_about_the_past_without_a_topic_gets_the_latest_conversations(st, mem):
    run(episodic.save_conversation(mem, EARLIER, case_id="case_a"))          # found live: search matched nothing
    assert mem.recall("What did I ask about last time?") == []
    found = run(episodic.recall(mem, "What did I ask about last time?"))
    assert len(found) == 1 and "R3" in found[0].summary
    text = streamed(collect(chat.stream_answer("What did I ask about last time?", st, tk(), memory=mem)))
    assert text.startswith("From our earlier conversations") and "R3" in text
    assert run(episodic.recall(mem, "what is the weather today")) == []      # other questions: no fallback


def test_other_questions_are_unchanged_by_memory(st, mem):
    run(episodic.save_conversation(mem, EARLIER, case_id="case_a"))
    with_memory = streamed(collect(chat.stream_answer("Why was R3 deducted?", st, tk(), memory=mem)))
    without = streamed(collect(chat.stream_answer("Why was R3 deducted?", st, tk())))
    assert with_memory == without


def test_a_broken_memory_never_breaks_a_reply(st):
    class Broken:
        enabled = True

        def recall(self, *a, **k):
            raise MemoryStoreError("DB", "database is locked")
    text = streamed(collect(chat.stream_answer("Why was R3 deducted?", st, tk(), memory=Broken())))
    assert "R3" in text


# --------------------------------------------------------------------------- the web UI


@pytest.fixture
def web(tmp_path, monkeypatch):
    for k in server.MODEL_KEYS + ("CLAIMCLEAR_CHECKPOINTS",):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(server, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("CLAIMCLEAR_MEMORY_USER", "u_local")
    path = tmp_path / "memory.db"
    app = server.create_app(toolkit_factory=tk, grace=30, memory_store_factory=lambda: MemoryStore(path))
    return app, path


def wait_for(check, timeout=10.0):
    """Saving runs in the background: poll until ``check()`` is true."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def episodes_of(path):
    return MemoryStore(path).for_user("u_local").episodes()


def slow_summariser(monkeypatch, seconds):
    async def summarise(turns):
        await asyncio.sleep(seconds)
        return "The user asked about cataract cover."
    monkeypatch.setattr(episodic, "llm_summariser", lambda llm: summarise)


def ws_ask(ws, text):
    ws.send_text(json.dumps({"type": "ask", "text": text, "id": "q"}))
    out = ""
    while True:
        m = json.loads(ws.receive_text())
        if m["type"] == "answer_delta":
            out += m["text"]
        if m["type"] == "answer_end":
            return out, m


def test_web_conversations_are_remembered_with_consent(web):
    app, path = web
    MemoryStore(path).for_user("u_local").grant_consent("test:settings")
    with TestClient(app) as c:
        assert c.get("/api/status").json()["memory"] == {"on": True, "consent": True, "episodes": 0}
        with c.websocket_connect("/ws") as ws:
            ws_ask(ws, "Is cataract surgery covered for my eye?")
        assert wait_for(lambda: c.get("/api/status").json()["memory"]["episodes"] == 1)   # saved after disconnect
        with c.websocket_connect("/ws") as ws:
            text, end = ws_ask(ws, "What did I ask last time about cataract?")
    assert "cataract" in text.lower() and end["sources"] == ["earlier conversations"]


def test_web_reset_saves_the_conversation(web):
    app, path = web
    MemoryStore(path).for_user("u_local").grant_consent("test:settings")
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws_ask(ws, "Is cataract surgery covered?")
        ws.send_text(json.dumps({"type": "reset"}))
        assert json.loads(ws.receive_text())["type"] == "session"
        assert wait_for(lambda: len(episodes_of(path)) == 1)


def test_web_saving_never_delays_a_reset(web, monkeypatch):
    app, path = web
    MemoryStore(path).for_user("u_local").grant_consent("test:settings")
    slow_summariser(monkeypatch, 1.5)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws_ask(ws, "Is cataract surgery covered?")
        app.state.llm = object()                         # a model is configured: the slow summary is used
        t0 = time.monotonic()
        ws.send_text(json.dumps({"type": "reset"}))
        assert json.loads(ws.receive_text())["type"] == "session"
        assert time.monotonic() - t0 < 1.0               # the reset did not wait for the 1.5 s summary
        assert episodes_of(path) == []                   # ... which is still running in the background
        assert wait_for(lambda: len(episodes_of(path)) == 1)
    assert episodes_of(path)[0].source == "chat:llm"


def test_web_shutdown_finishes_pending_saves(web, monkeypatch):
    app, path = web
    MemoryStore(path).for_user("u_local").grant_consent("test:settings")
    slow_summariser(monkeypatch, 0.8)
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            ws_ask(ws, "Is cataract surgery covered?")
            app.state.llm = object()
    assert len(episodes_of(path)) == 1                   # closing the app waited for the background write
    assert not app.state.background


def test_background_task_errors_are_logged_not_raised(caplog):

    async def boom():
        raise RuntimeError("disk full")

    async def go():
        st = SimpleNamespace(background=set())
        task = server.spawn_background(st, boom())
        await asyncio.wait([task])
        await asyncio.sleep(0)
        return st
    with caplog.at_level("WARNING", logger="claimclear.webapp"):
        st = run(go())
    assert not st.background and "disk full" in caplog.text


def test_drain_cancels_what_does_not_finish_in_time():

    async def go():
        st = SimpleNamespace(background=set())
        server.spawn_background(st, asyncio.sleep(5))
        return await server.drain_background(st, timeout=0.1)
    assert run(go()) == 1


def test_web_case_is_remembered_by_the_graph(web):
    app, path = web
    MemoryStore(path).for_user("u_local").grant_consent("test:settings")
    fx = load("SET-01")
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "analyse", "upload": {"case_id": fx["case_id"],
                                                               "extraction": {"claim": fx["claim"], "letter": fx["letter"]}}}))
        while json.loads(ws.receive_text())["type"] != "grievance":
            pass
    claims = MemoryStore(path).for_user("u_local").claims()
    assert [c.claim_id for c in claims] == [fx["claim"]["claim_id"]]


def test_web_without_consent_stores_nothing(web):
    app, path = web
    with TestClient(app) as c:
        assert c.get("/api/status").json()["memory"] == {"on": True, "consent": False, "episodes": 0}
        with c.websocket_connect("/ws") as ws:
            ws_ask(ws, "Is cataract surgery covered?")
    assert MemoryStore(path).for_user("u_local").export()["episodes"] == []


def test_web_without_a_memory_user_has_memory_off(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAIMCLEAR_MEMORY_USER", raising=False)
    for k in server.MODEL_KEYS:
        monkeypatch.delenv(k, raising=False)
    app = server.create_app(toolkit_factory=tk, grace=30)
    with TestClient(app) as c:
        assert c.get("/api/status").json()["memory"] == {"on": False, "consent": False, "episodes": 0}
