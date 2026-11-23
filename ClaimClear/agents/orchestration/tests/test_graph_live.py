"""Live: the graph against the real MCP servers over stdio (settlement-engine, case-records, policy-kb,
insurer-portal), through ``claimclear_tools.ClaimClearToolkit``. Nothing is stubbed.

Needs the servers' environment at ``<repo>/.venv`` (or ``$CLAIMCLEAR_SERVER_PYTHON``); skipped otherwise.
SET-32 needs Tesseract (its bill is a scan) and is skipped without it.

DEVELOPMENT STAND-INS (labelled): case IDs come from a scratch store's dataset map, and the claim/letter
from the engine's ``--case-payload``, in place of the app's upload and the LLM extraction.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

pytest.importorskip("langchain_mcp_adapters")

from claimclear_memory import MemoryStore  # noqa: E402
from claimclear_tools import ClaimClearToolkit  # noqa: E402
from claimclear_tools.config import find_repo, server_python  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.graph import START, MessagesState, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402

from claimclear_graph import (AuditLog, HumanApprovalGateway, Services, build_claimclear_graph,  # noqa: E402
                              initial_state, permission_hook)
from claimclear_tools.results import tool_error  # noqa: E402

from conftest import run  # noqa: E402

try:
    REPO = find_repo()
    SERVER_PY = server_python(REPO)
except FileNotFoundError as exc:  # pragma: no cover
    pytest.skip(str(exc), allow_module_level=True)

GATE_SECRET = "live-test-gate-secret"


@pytest.fixture(scope="module", autouse=True)
def servers_env(tmp_path_factory):
    """A scratch case store with the dataset, a policy-kb index of the real wording, a gate secret."""
    work = tmp_path_factory.mktemp("live")
    store = work / "case_store"
    subprocess.run([SERVER_PY, "-m", "case_records.register_dataset", "--store", str(store)],
                   cwd=REPO / "servers" / "case_records", check=True, capture_output=True)
    index = work / "policy_kb.json"
    subprocess.run([SERVER_PY, "-m", "policy_kb", "--index", str(index), "build", "--wording",
                    str(REPO / "development" / "dev_data" / "wordings" / "policy-wordings-arogya-sanjeevani-policy-go-digit.pdf")],
                   cwd=REPO / "servers" / "policy_kb", check=True, capture_output=True)
    mp = pytest.MonkeyPatch()
    mp.setenv("CLAIMCLEAR_CASE_STORE", str(store))
    mp.setenv("CLAIMCLEAR_POLICY_KB_INDEX", str(index))
    mp.setenv("CLAIMCLEAR_PORTAL_STORE", str(work / "portal.json"))
    mp.setenv("CLAIMCLEAR_GATE_SECRET", GATE_SECRET)               # the portal server checks HMAC tokens
    mp.setenv("CLAIMCLEAR_MCP_MODE", "stdio")
    yield json.loads((work / "dataset_map.json").read_text(encoding="utf-8"))
    mp.undo()


def payload(dataset_id: str) -> dict:
    out = subprocess.run([SERVER_PY, "-m", "mcp_server", "--case-payload", dataset_id],
                         cwd=REPO / "servers" / "settlement_engine", capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return json.loads(out.stdout)


async def drive(mapping, dataset_id, *, decide=None, answers=None, memory_store=None, user_id=None, log=None):
    """Run one case live; ``decide(gate, cfg)`` acts at the approval gate."""
    async with ClaimClearToolkit(tool_interceptors=[log] if log else None) as tk:
        graph = build_claimclear_graph(Services(toolkit=tk, memory_store=memory_store))
        gate = HumanApprovalGateway(graph, gate_secret=GATE_SECRET)
        cfg = {"configurable": {"thread_id": dataset_id}}
        ex = payload(dataset_id)
        state = await graph.ainvoke(initial_state(mapping[dataset_id]["case_id"], claim=ex["claim"],
                                                  letter=ex["letter"], user_id=user_id), cfg)
        if answers and await gate.pending_questions(cfg):
            state = await gate.answer_questions(cfg, answers)
        paused = await gate.is_paused_for_approval(cfg)
        if paused and decide:
            state = await decide(gate, cfg)
        return state, paused


def test_set01_live_dispute_approved_and_filed_with_hmac_token(servers_env):
    log = AuditLog()
    state, paused = run(drive(servers_env, "SET-01", decide=lambda g, c: g.approve_and_resume(c), log=log))
    assert paused and state["outcome"] == "grievance_filed"
    assert state["letter_audit"]["policy_payable"] == 95617.5 and state["letter_audit"]["insurer_paid"] == 87094.64
    assert state["letter_audit"]["disputable_amount"] == 8522.86
    assert state["row_audits"]["R3"]["method"] == "prop_on_all_lines"
    assert state["submission"]["reference"].startswith("DRYRUN-") and state["submission"]["dry_run"]
    assert state["grievance_status"]["status"] == "dry_run"
    servers = {r["server"] for r in log.records}
    assert servers == {"case-records", "policy-kb", "settlement-engine", "insurer-portal"}
    assert not any(r["error"] for r in log.records)


def test_wrong_token_is_refused_by_the_real_portal(servers_env):
    async def wrong_secret(gate, cfg):
        gate.gate_secret = "not-the-server-secret"
        return await gate.approve_and_resume(cfg)
    with pytest.raises(PermissionError, match="APPROVAL_REQUIRED"):
        run(drive(servers_env, "SET-03", decide=wrong_secret))


def test_set02_live_clean_settlement(servers_env):
    state, paused = run(drive(servers_env, "SET-02"))
    assert not paused and state["outcome"] == "no_grievance" and state["critic"]["passed"]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="SET-32's bill is a scan: needs Tesseract")
def test_set32_live_question_answered(servers_env):
    state, _ = run(drive(servers_env, "SET-32", answers={"Q-CONDITION-TYPE": "illness"}))
    assert state["answers"] == {"Q-CONDITION-TYPE": "illness"} and state["outcome"] == "no_grievance"


def test_set09_live_impossible_dates_confirm_the_rejection(servers_env):
    # SET-09's bill discharges the patient before admitting them; the insurer rejected it as not genuine. The engine
    # reports the impossible dates (engine/integrity.py) and confirms the rejection, without asking for "real" dates.
    state, _ = run(drive(servers_env, "SET-09"))
    whole = state["row_audits"]["REJECTION"]
    assert state["outcome"] == "no_grievance" and state.get("answers") in (None, {})
    assert whole["verdict"] == "matches_policy" and whole["method"] == "not_genuine_documents"
    assert "discharge date" in whole["explanation"] and state["letter_audit"]["disputable_amount"] == 0


def test_set21_live_lookalike_policy_number(servers_env):
    state, _ = run(drive(servers_env, "SET-21"))
    assert any("lookalike" in f for f in state["security_flags"]) and state["outcome"] == "no_grievance"


def test_memory_live_round_trip(servers_env, tmp_path):
    store = MemoryStore(str(tmp_path / "memory.db"))
    store.for_user("u_live").grant_consent("test")
    state, _ = run(drive(servers_env, "SET-27", decide=lambda g, c: g.approve_and_resume(c),
                         memory_store=store, user_id="u_live"))
    g = store.for_user("u_live").grievance(state["memory_grievance_id"])
    assert g.status == "filed" and g.reference_no == state["submission"]["reference"]


def test_hook1_on_real_mcp_tools(servers_env):
    async def go():
        async with ClaimClearToolkit() as tk:
            g = StateGraph(MessagesState)
            g.add_node("tools", ToolNode(tk.for_agent("single_agent") + [tk.tool("file_grievance")],
                                         awrap_tool_call=permission_hook("explainer")))
            g.add_edge(START, "tools")
            call = AIMessage(content="", tool_calls=[{"name": "list_hypotheses", "args": {}, "id": "1"}])
            return (await g.compile().ainvoke({"messages": [call]}))["messages"][-1]
    msg = run(go())
    assert tool_error(msg).code == "NOT_ALLOWED"                      # explainer may not list hypotheses


def test_web_ui_process_serves_streams_and_exits_when_the_page_closes(servers_env, tmp_path):
    """``python -m claimclear_graph.webapp`` for real: starts the MCP servers over stdio, serves the page and the
    chat over HTTP and WebSocket, and exits by itself once the last page has been closed."""
    import os
    import socket
    import sys
    import time
    import urllib.request

    import websockets

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "CLAIMCLEAR_MCP_MODE": "stdio", "CLAIMCLEAR_UI_GRACE": "1", "PYTHONUNBUFFERED": "1"}
    for k in ("OPENROUTER_API_KEY", "CLAIMCLEAR_LLM_BASE_URL"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, "-m", "claimclear_graph.webapp", "--port", str(port)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 90
        line = ""
        while time.time() < deadline and "CLAIMCLEAR_UI_READY" not in line:
            line = proc.stdout.readline()
        assert "CLAIMCLEAR_UI_READY" in line
        status = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status").read())
        assert status["chat_model"] is False and len(status["boot"]) == 12

        async def chat_once():
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                await ws.send(json.dumps({"type": "ask", "text": "Is cataract surgery covered?", "id": "x"}))
                text = ""
                while True:
                    m = json.loads(await ws.recv())
                    text += m.get("text", "") if m["type"] == "answer_delta" else ""
                    if m["type"] == "answer_end":
                        return text
        answer = run(chat_once())
        assert "policy wording" in answer.lower() and "Clause" in answer      # answered from the real policy-kb
        assert proc.wait(timeout=30) == 0                                       # the page closed: it exits
    finally:
        if proc.poll() is None:
            proc.kill()
