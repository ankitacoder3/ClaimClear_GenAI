"""The orchestration layer: topology, determinism, concurrency, gateway, services, checkpoints, hooks, language."""

from __future__ import annotations

import asyncio
import sys

import pytest
from claimclear_tools.agents import AGENT_TOOLS, TOOL_SERVER
from claimclear_tools.results import ClaimClearToolError

from claimclear_graph import HumanApprovalGateway, ScopedToolkit, Services, build_claimclear_graph, initial_state
from claimclear_graph import checkpoints, language, plan
from claimclear_graph.gateway import issue_token
from claimclear_graph.hooks import AuditLog, is_error_message, permission_hook
from claimclear_graph.testing import ReplayToolkit, tool_error

from conftest import Case, load, run


# --------------------------------------------------------------------------- topology


def test_graph_has_exactly_the_documented_nodes_and_edges():
    g = build_claimclear_graph(Services(toolkit=ReplayToolkit([]))).get_graph()
    assert set(g.nodes) - {"__start__", "__end__"} == {
        "supervisor", "document_reader", "policy_analyst", "settlement_auditor", "ask_user", "critic", "explainer",
        "grievance_agent", "approval_gate", "portal_submit"}
    edges = {(e.source, e.target) for e in g.edges}
    for must in [("__start__", "supervisor"), ("ask_user", "settlement_auditor"), ("explainer", "critic"),
                 ("grievance_agent", "approval_gate"), ("approval_gate", "portal_submit"), ("portal_submit", "__end__")]:
        assert must in edges
    assert ("grievance_agent", "portal_submit") not in edges            # filing only through the gate
    assert not any(t == "portal_submit" and s != "approval_gate" for s, t in edges)


def test_same_input_same_result():
    a, b = Case("SET-01"), Case("SET-01")
    sa, sb = run(a.start()), run(b.start())
    keys = ("letter_audit", "row_audits", "explanation", "audit_table_markdown", "grievance", "trace")
    assert all(sa[k] == sb[k] for k in keys)


def test_the_trace_follows_the_plan_order():
    trace = run(Case("SET-01").start())["trace"]
    order = [t.split(":")[0] for t in trace]
    assert order == ["Supervisor", "DocumentReader", "PolicyAnalyst", "SettlementAuditor", "Critic", "Explainer",
                     "Critic", "GrievanceAgent"]


def test_many_cases_run_concurrently_on_one_graph_without_mixing():
    fx = {d: load(d) for d in ("SET-01", "SET-02")}
    calls = fx["SET-01"]["calls"] + fx["SET-02"]["calls"]
    graph = build_claimclear_graph(Services(toolkit=ReplayToolkit(calls)))

    async def one(i):
        d = "SET-01" if i % 2 else "SET-02"
        cfg = {"configurable": {"thread_id": f"t{i}"}}
        st = await graph.ainvoke(initial_state(fx[d]["case_id"], claim=fx[d]["claim"], letter=fx[d]["letter"]), cfg)
        return d, st

    async def go():
        return await asyncio.gather(*(one(i) for i in range(24)))
    for d, st in run(go()):
        if d == "SET-01":
            assert st["letter_audit"]["disputable_amount"] == 8522.86 and st["grievance"]["row_ids"] == ["R3"]
        else:
            assert st["outcome"] == "no_grievance" and "grievance" not in st


@pytest.mark.parametrize("outcome,setup", [
    ("missing_document", {"get_document_text": "unreadable"}),
    ("ask_user_for_policy", {"get_policy": "POLICY_NOT_FOUND"}),
    ("invalid_extraction", {"expected_settlement": "INVALID_ARGUMENTS"}),
    ("tool_error", {"audit_settlement_letter": "CASE_NOT_FOUND"}),
])
def test_every_early_outcome_is_reachable_through_the_graph(outcome, setup):
    fx = load("SET-01")
    method, code = next(iter(setup.items()))
    if code == "unreadable":
        from conftest import call

        def fn(case_id, document_id, pages=None):
            t = call(fx, "get_document_text", document_id)
            t["pages"][0]["ocr_status"] = "failed"
            return t
    else:
        def fn(*a, **k):
            raise tool_error(method, code)
    c = Case("SET-01", overrides={method: fn})
    assert run(c.start())["outcome"] == outcome
    assert not run(c.gate.is_paused_for_approval(c.cfg))


# --------------------------------------------------------------------------- gateway on threads that never started


def test_gateway_on_an_unknown_thread():
    g = HumanApprovalGateway(build_claimclear_graph(Services(toolkit=ReplayToolkit([]))))
    cfg = {"configurable": {"thread_id": "never-started"}}
    assert run(g.is_paused_for_approval(cfg)) is False and run(g.pending_questions(cfg)) == []
    assert run(g.get_pending_grievance(cfg)) == (None, None)
    for action in (g.approve_and_resume(cfg), g.reject(cfg)):
        with pytest.raises(RuntimeError):
            run(action)


def test_issue_token_uses_the_environment_secret(monkeypatch):
    sha = "a" * 64
    monkeypatch.setenv("CLAIMCLEAR_GATE_SECRET", "env-secret")
    assert issue_token(sha) == issue_token(sha, "env-secret") != issue_token(sha, "")
    monkeypatch.delenv("CLAIMCLEAR_GATE_SECRET")
    assert issue_token(sha).startswith("dev-approval-")


# --------------------------------------------------------------------------- services: least privilege for every agent


PAIRS = [(agent, tool) for agent in AGENT_TOOLS for tool in TOOL_SERVER]


@pytest.mark.parametrize("agent,name", PAIRS, ids=[f"{a}-{t}" for a, t in PAIRS])
def test_scoped_toolkit_enforces_the_table_for_every_agent_and_tool(agent, name):
    called = []
    target = name

    class TK:
        tools = {target: object()}

        async def call(self, n, args):
            called.append(n)
            return {}

        def tool(self, n):
            return self.tools[n]

    async def method(*a, **k):
        called.append(target)
        return {}
    tk = TK()
    setattr(tk, name, method)
    scoped = ScopedToolkit(tk, agent)
    if name in AGENT_TOOLS[agent]:
        run(getattr(scoped, name)())
        run(scoped.call(name, {}))
        assert called == [name, name] and name in scoped.tools and scoped.tool(name) is tk.tools[name]
    else:
        with pytest.raises(ClaimClearToolError) as e:
            run(getattr(scoped, name)())
        assert e.value.info.code == "NOT_ALLOWED"
        with pytest.raises(ClaimClearToolError):
            run(scoped.call(name, {}))
        with pytest.raises(ClaimClearToolError):
            scoped.tool(name)
        assert called == [] and name not in scoped.tools


def test_retries_back_off_exponentially(monkeypatch):
    delays, attempts = [], []

    async def fake_sleep(d):
        delays.append(d)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class TK:
        async def get_clause(self, *a):
            attempts.append(1)
            raise tool_error("get_clause", "UPSTREAM_UNAVAILABLE")
    scoped = ScopedToolkit(TK(), "explainer", retry_attempts=3, retry_backoff=0.5)
    with pytest.raises(ClaimClearToolError):
        run(scoped.get_clause("C.1"))
    assert len(attempts) == 4 and delays == [0.5, 1.0, 2.0] and scoped.retries == 3


def test_no_retry_when_disabled():
    attempts = []

    class TK:
        async def get_clause(self, *a):
            attempts.append(1)
            raise tool_error("get_clause", "UPSTREAM_UNAVAILABLE")
    with pytest.raises(ClaimClearToolError):
        run(ScopedToolkit(TK(), "explainer", retry_attempts=0).get_clause("C.1"))
    assert attempts == [1]


def test_non_tool_attributes_pass_through():
    class TK:
        def schema(self, name):
            return {"title": name}
    assert ScopedToolkit(TK(), "document_reader").schema("ClaimIn") == {"title": "ClaimIn"}


def test_memory_for_without_store_or_user():
    s = Services(toolkit=None)
    assert s.memory_for("u1") is None
    assert Services(toolkit=None, memory_store=object()).memory_for(None) is None


# --------------------------------------------------------------------------- plan, checkpoints, hooks, language


def test_replan_from_an_empty_previous_plan():
    p = plan.replan({}, "why", [])
    assert p["version"] == 2 and "every row" in p["steps"][0]["goal"]


@pytest.mark.parametrize("url", ["", "memory"])
def test_in_memory_checkpointer(url):
    async def go():
        async with checkpoints.open_checkpointer(url) as saver:
            return type(saver).__name__
    assert run(go()) == "InMemorySaver" or run(go()) == "MemorySaver"


@pytest.mark.parametrize("form", ["sqlite:///{p}/a/b/c.db", "{p}/x.sqlite", "{p}/y.db"])
def test_sqlite_checkpointer_url_forms(tmp_path, form):
    url = form.format(p=tmp_path)

    async def go():
        async with checkpoints.open_checkpointer(url) as saver:
            return type(saver).__name__
    assert run(go()) == "AsyncSqliteSaver"


def test_checkpointer_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMCLEAR_CHECKPOINTS", f"sqlite:///{tmp_path}/env.db")

    async def go():
        async with checkpoints.open_checkpointer() as saver:
            return type(saver).__name__
    assert run(go()) == "AsyncSqliteSaver" and (tmp_path / "env.db").exists()


def test_postgres_without_the_package_says_how_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres.aio", None)

    async def go():
        async with checkpoints.open_checkpointer("postgresql://u:p@localhost/db"):
            pass
    with pytest.raises(RuntimeError, match="langgraph-checkpoint-postgres"):
        run(go())


@pytest.mark.parametrize("url", ["redis://x", "mysql://y", "/tmp/notadb.txt"])
def test_unknown_checkpoint_urls_are_refused(url):
    async def go():
        async with checkpoints.open_checkpointer(url):
            pass
    with pytest.raises(ValueError):
        run(go())


def test_permission_hook_accepts_dict_requests_and_missing_ids():
    hook = permission_hook("explainer")

    async def execute(req):
        return "ran"
    refused = run(hook({"name": "file_grievance", "args": {}}, execute))
    assert refused.status == "error" and refused.tool_call_id == "call"
    assert run(hook({"name": "get_clause", "args": {}, "id": "x"}, execute)) == "ran"


def test_audit_log_sink_receives_every_record():
    seen = []
    log = AuditLog(sink=seen.append)

    class Req:
        server_name, name = "policy-kb", "get_clause"

    async def handler(_):
        from langchain_core.messages import ToolMessage
        return ToolMessage(content="x", tool_call_id="1", status="error")
    run(log(Req(), handler))
    assert seen == log.records and seen[0]["error"] is True
    assert is_error_message("plain string") is False


def test_llm_rewriter_handles_text_and_content_blocks():
    class LLM:
        def __init__(self, content):
            self.content, self.prompts = content, []

        async def ainvoke(self, prompt):
            self.prompts.append(prompt)
            return type("M", (), {"content": self.content})()
    plain = LLM("  simple text ")
    assert run(language.llm_rewriter(plain)("x", "hi")) == "simple text" and "simple Hindi" in plain.prompts[0]
    blocks = LLM([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
    assert run(language.llm_rewriter(blocks)("x", "xx")) == "ab" and "xx" in blocks.prompts[0]   # unknown code passes through
