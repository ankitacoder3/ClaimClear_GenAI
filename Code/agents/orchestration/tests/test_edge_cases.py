"""Remaining edge cases: web server error paths, memory refusals, recorder, guard internals, optional PostgreSQL."""

from __future__ import annotations

import json
import os

import pytest
from starlette.testclient import TestClient

from claimclear_graph import chat, checks, checkpoints, router
from claimclear_graph.testing import RecordingToolkit, ReplayToolkit, tool_error
from claimclear_graph.webapp import server

from conftest import load, node_fn, run, states_before
from test_webapp import env, fixture_upload, replay, until   # noqa: F401  (shared fixtures)


# --------------------------------------------------------------------------- web server error paths


@pytest.fixture
def app(env):                                                          # noqa: F811
    return server.create_app(stop=lambda r: None, toolkit_factory=replay, grace=30)


@pytest.mark.parametrize("var,provider", [("CLAIMCLEAR_LLM_BASE_URL", "local"), ("OPENROUTER_API_KEY", "openrouter"),
                                          ("ANTHROPIC_API_KEY", "none"), ("OPENAI_API_KEY", "none")])
def test_settings_report_the_configured_provider(app, monkeypatch, var, provider):
    monkeypatch.setattr(chat, "chat_model_from_env", lambda: None)
    monkeypatch.setenv(var, "x" * 20)
    with TestClient(app) as c:
        m = c.get("/api/model").json()
    assert m["provider"] == provider
    if provider == "openrouter":
        assert m["key_saved"][provider] is True and "x" * 20 not in json.dumps(m)   # never returned


def test_a_crashing_graph_is_reported_not_fatal(app):
    with TestClient(app) as c:
        def boom(*a, **k):
            raise RuntimeError("engine exploded")
        c.app.state.toolkit.overrides["expected_settlement"] = boom
        with c.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "analyse", "upload": fixture_upload("SET-01")}))
            err, _ = until(ws, "error")
            assert "RuntimeError: engine exploded" in err["text"]
            ws.send_text(json.dumps({"type": "ask", "text": "still there?", "id": "z"}))
            end, _ = until(ws, "answer_end")                            # the session survives
    assert end["type"] == "answer_end"


def test_records_that_cannot_be_loaded_do_not_break_the_chat(app):
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "analyse", "upload": fixture_upload("SET-02")}))
            until(ws, "outcome")

            def fail(*a, **k):
                raise tool_error("list_case_documents", "CASE_NOT_FOUND")
            c.app.state.toolkit.overrides["list_case_documents"] = fail
            ws.send_text(json.dumps({"type": "ask", "text": "what was my diagnosis?", "id": "d"}))
            end, seen = until(ws, "answer_end")
    assert "Acute appendicitis" in "".join(m.get("text", "") for m in seen if m["type"] == "answer_delta")


def test_room_pricing_answers_arrive_as_text_and_become_booleans(app):
    captured = {}
    with TestClient(app) as c:
        st = c.app.state
        with c.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "analyse", "upload": fixture_upload("SET-32")}))
            until(ws, "questions")
            original = st.graph.astream

            def spy(inp, cfg, **k):
                captured["resume"] = getattr(inp, "resume", None)
                return original(inp, cfg, **k)
            st.graph.astream = spy
            ws.send_text(json.dumps({"type": "answers", "answers": {"Q-ROOM-PRICING": "Yes", "Q-CONDITION-TYPE": ""}}))
            until(ws, "busy")
    assert captured["resume"] == {"Q-ROOM-PRICING": True, "Q-CONDITION-TYPE": None}


def test_a_broken_upload_helper_is_reported(app, monkeypatch):
    class Proc:
        async def communicate(self):
            return b"not json", b"Traceback: something broke"

    async def fake_exec(*a, **k):
        return Proc()
    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", fake_exec)
    with TestClient(app) as c:
        r = c.post("/api/sample", json={"name": "syn-dev-005"})
        assert r.status_code == 400 and "something broke" in r.json()["error"]
        assert c.post("/api/clear").json() == {"ok": True}                # clear survives a broken helper too


# --------------------------------------------------------------------------- agents and helpers


def test_memory_refusing_an_audit_does_not_fail_the_critic():
    st = states_before("SET-01")["critic"]

    class Refusing:
        def remember_claim(self, *a, **k):
            from claimclear_memory.store import MemoryStoreError
            raise MemoryStoreError("NO_CONSENT", "refused")

    class Store:
        def session_memory(self, user_id):
            return Refusing()
    fn, _ = node_fn("critic", memory_store=Store())
    assert run(fn({**st, "user_id": "u1"}))["critic_stage"] == "audit_passed"


def test_review_audit_when_the_independent_audit_lacks_a_row():
    rows = {"R9": {"row_id": "R9", "verdict": "matches_policy", "policy_amount": 1.0}}
    fails = checks.review_audit(rows, {"rows": []})
    assert fails[0]["detail"].startswith("R9: audited by the auditor but absent")


def test_confidence_when_nothing_was_deducted():
    assert checks.confidence({"rows": [{"insurer_amount": 0}], "unverified_amount": 5}) == 1.0


def test_unknown_critic_stage_ends_the_run():
    from langgraph.graph import END
    assert router.route_after_critic({"critic_stage": "something-new"}) == END


def test_record_index_text_and_empty_answers():
    idx = chat.RecordIndex([chat.Chunk("d1", "bill", 1, "Room rent 7000", chat.RecordIndex.tokens("Room rent 7000"))])
    assert idx.text() == "Room rent 7000" and idx.search("unrelated words") == []
    assert chat.record_answer("what was my diagnosis?", {"claim": {"lines": []}}, idx) is None


def test_recording_toolkit_records_results_and_errors():
    class Live:
        async def get_policy(self, case_id):
            return {"policy_no": "P1"}

        async def get_clause(self, cid):
            raise tool_error("get_clause", "UNKNOWN_WORDING")

        def schema(self, name):
            return {"title": name}
    rec = RecordingToolkit(Live())
    assert run(rec.get_policy("c1")) == {"policy_no": "P1"} and rec.schema("ClaimIn") == {"title": "ClaimIn"}
    with pytest.raises(Exception):
        run(rec.get_clause("C.1"))
    assert [("result" in c, "error" in c) for c in rec.calls] == [(True, False), (False, True)]
    replayed = ReplayToolkit(rec.calls)
    assert run(replayed.get_policy("c1")) == {"policy_no": "P1"}
    with pytest.raises(Exception) as e:
        run(replayed.get_clause("C.1"))
    assert "UNKNOWN_WORDING" in str(e.value)
    with pytest.raises(AttributeError):
        replayed.not_a_tool


def test_replay_reports_an_unrecorded_call_clearly():
    with pytest.raises(KeyError, match="re-record the fixture"):
        run(ReplayToolkit([]).get_policy("nope"))
    with pytest.raises(Exception, match="GRIEVANCE_NOT_FOUND"):
        run(ReplayToolkit([]).grievance_status("DRYRUN-000000000000"))


@pytest.mark.skipif(not os.environ.get("CLAIMCLEAR_TEST_POSTGRES"), reason="set CLAIMCLEAR_TEST_POSTGRES to run")
def test_postgres_checkpointer_survives_a_restart():
    pytest.importorskip("langgraph.checkpoint.postgres")
    fx = load("SET-01")
    url, cfg = os.environ["CLAIMCLEAR_TEST_POSTGRES"], {"configurable": {"thread_id": f"pg-{os.getpid()}"}}
    from claimclear_graph import HumanApprovalGateway, Services, build_claimclear_graph, initial_state

    async def go():
        async with checkpoints.open_checkpointer(url) as saver:
            g = build_claimclear_graph(Services(toolkit=ReplayToolkit(fx["calls"])), checkpointer=saver)
            await g.ainvoke(initial_state(fx["case_id"], claim=fx["claim"], letter=fx["letter"]), cfg)
        async with checkpoints.open_checkpointer(url) as saver:
            g = build_claimclear_graph(Services(toolkit=ReplayToolkit(fx["calls"])), checkpointer=saver)
            return await HumanApprovalGateway(g).is_paused_for_approval(cfg)
    assert run(go())
