"""Live tests: the toolkit against the real servers over stdio.

Needs ``langchain-mcp-adapters`` (agents' environment) and the servers' venv at
``<repo>/.venv``. Skipped otherwise.
"""

import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("langchain_mcp_adapters")

from claimclear_tools import ClaimClearToolError, ClaimClearToolkit, apply_answer, build_case, results, signals  # noqa: E402
from claimclear_tools.config import find_repo, server_python  # noqa: E402

try:
    REPO = find_repo()
    SERVER_PY = server_python(REPO)
except FileNotFoundError as exc:  # pragma: no cover
    pytest.skip(str(exc), allow_module_level=True)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    """A case store with the dataset registered, and the evaluation map."""
    root = tmp_path_factory.mktemp("cr") / "case_store"
    subprocess.run([SERVER_PY, "-m", "case_records.register_dataset", "--store", str(root)],
                   cwd=REPO / "servers" / "case_records", check=True, capture_output=True)
    return root, json.loads((root.parent / "dataset_map.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def policy_index(tmp_path_factory):
    """A policy-kb index of the synthetic test wording (so the tests don't depend on var/)."""
    path = tmp_path_factory.mktemp("pk") / "index.json"
    subprocess.run([SERVER_PY, "-m", "policy_kb", "--index", str(path), "build", "--wording",
                    "tests/fixtures/sample_wording.txt", "--insurer", "Aarohan General Insurance Ltd.",
                    "--uin", "SYNHLIP00000V000000", "--synthetic"],
                   cwd=REPO / "servers" / "policy_kb", check=True, capture_output=True)
    return path


@pytest.fixture(scope="module", autouse=True)
def env(store, policy_index, tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("CLAIMCLEAR_CASE_STORE", str(store[0]))
    mp.setenv("CLAIMCLEAR_POLICY_KB_INDEX", str(policy_index))
    mp.delenv("CLAIMCLEAR_POLICY_CATALOGUE", raising=False)
    mp.setenv("CLAIMCLEAR_PORTAL_STORE", str(tmp_path_factory.mktemp("portal") / "dry_run.json"))
    mp.setenv("CLAIMCLEAR_MCP_MODE", "stdio")
    yield
    mp.undo()


def payload(doc_id):
    out = subprocess.run([SERVER_PY, "-m", "mcp_server", "--case-payload", doc_id],
                         cwd=REPO / "servers" / "settlement_engine", capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return json.loads(out.stdout)


def test_toolkit_connects_and_scopes_tools():
    async def go():
        async with ClaimClearToolkit() as tk:
            return (sorted(tk.tools), [t.name for t in tk.for_agent("settlement_auditor")],
                    [t.name for t in tk.for_agent("policy_analyst")], tk.schema("ClaimIn"))
    names, auditor, analyst, claim_schema = run(go())
    assert names == ["audit_settlement_letter", "clauses_for_rule", "expected_settlement", "file_grievance",
                     "get_claim_history", "get_clause", "get_document_text", "get_policy", "get_policy_wording",
                     "grievance_status",
                     "list_case_documents", "list_hypotheses", "list_policies", "register_uploaded_wording",
                     "reproduce_deduction", "search_clauses"]
    assert auditor == ["expected_settlement", "list_hypotheses", "reproduce_deduction"]
    assert analyst == ["get_policy", "get_policy_wording", "get_claim_history", "list_policies", "search_clauses", "get_clause",
                       "clauses_for_rule"]
    assert {"claim_id", "lines", "policy_no"} <= set(claim_schema["properties"]) and "$defs" in claim_schema


def test_set01_end_to_end(store):
    ids = store[1]["SET-01"]
    extracted = payload("SET-01")

    async def go():
        async with ClaimClearToolkit() as tk:
            records = await tk.read_case(ids["case_id"])
            case = build_case(extracted["claim"], records["policy"], records["history"])
            settlement = await tk.expected_settlement(case)
            partial = await tk.reproduce_deduction(case, extracted["letter"], "R3", ["prop_incl_pharmacy"])
            full = await tk.reproduce_deduction(case, extracted["letter"], "R3")
            audit = await tk.audit_settlement_letter(case, extracted["letter"])
            return records, settlement, partial, full, audit

    records, settlement, partial, full, audit = run(go())
    assert len(records["documents"]) == 4          # bill, discharge summary, settlement letter, policy schedule
    assert all(signals.after_document_text(d) == signals.OK for d in records["documents"].values())
    assert signals.after_settlement(settlement) == signals.AUDIT_ROWS and settlement["payable_amount"] == 95617.5
    assert signals.after_row_audit(partial) == signals.REPLAN
    assert signals.after_row_audit(full) == signals.DONE and full["method"] == "prop_on_all_lines"
    assert audit["disputable_amount"] == 8522.86 and signals.after_letter_audit(audit) == signals.OFFER_GRIEVANCE


def test_policy_kb_over_mcp():
    async def go():
        async with ClaimClearToolkit() as tk:
            found = await tk.search_clauses("why did they cut my medicine bill", k=2)
            clause = await tk.get_clause(found["hits"][0]["clause_id"])
            missing = await tk.get_clause("99.9")
            assert "stub" not in found and tk.tool("get_clause") is tk.tools["get_clause"]   # the live tool
            try:
                await tk.clauses_for_rule("copay")
            except ClaimClearToolError as exc:
                return found, clause, missing, exc.info
    found, clause, missing, err = run(go())
    assert found["hits"][0]["clause_id"] == "5.2" and found["synthetic"] is True
    assert clause["found"] and clause["title"] == "Items not reduced" and missing["found"] is False
    assert err.code == "NO_RULE_MAP" and err.action == results.USE_SEARCH_CLAUSES   # no rule map for a test wording


def test_memory_round_trip_through_the_engine(store, tmp_path):
    """Remember SET-01 after its audit; a later claim on the same policy then has ₹87,094.64 less sum insured."""
    memory = pytest.importorskip("claimclear_memory")
    ids = store[1]["SET-01"]
    extracted = payload("SET-01")
    store = memory.MemoryStore(tmp_path / "memory.db")
    store.for_user("u_test").grant_consent("test:settings")      # in the app: the user's own choice
    mem = store.session_memory("u_test")
    later = copy.deepcopy(extracted["claim"])
    later.update(claim_id="LATER-1", admission="2026-03-02", discharge="2026-03-04")

    async def go():
        async with ClaimClearToolkit() as tk:
            policy = await tk.get_policy(ids["case_id"])
            server_history = await tk.get_claim_history(ids["case_id"])
            case = build_case(extracted["claim"], policy, server_history)
            audit = await tk.audit_settlement_letter(case, extracted["letter"])
            mem.remember_claim(case, audit, case_id=ids["case_id"], letter=extracted["letter"])
            history = memory.merge_history(server_history, mem.claim_history(policy["policy_no"]))
            return await tk.expected_settlement(build_case(later, policy, history))
    settlement = run(go())
    facts = {f["fact_id"]: f["amount"] for f in settlement["facts"]}
    assert facts["F-SI-REMAINING"] == 212905.36                 # 3,00,000 - 87,094.64, worked out by the engine
    assert mem.context()["recent_claims"][0]["disputable_amount"] == 8522.86


def test_uploaded_policy_flow(store):
    """App path B: the user's own policy document is read through case-records and indexed for the case."""
    ids = store[1]["SET-01"]

    async def go():
        async with ClaimClearToolkit() as tk:
            reg = await tk.ingest_uploaded_policy(ids["case_id"], ids["document_id"])     # any text PDF works here
            found = await tk.search_clauses("co-pay", k=2, wording_uin=reg["wording_uin"], case_id=ids["case_id"])
            listed = await tk.list_policies(case_id=ids["case_id"])
            return reg, found, listed
    reg, found, listed = run(go())
    assert reg["wording_uin"].startswith("upload:doc_") and reg["reviewed"] is False
    assert found["wording"]["source"] == "uploaded"
    assert reg["wording_uin"] in {p["wording_uin"] for p in listed["policies"]}


def test_file_grievance_dry_run():
    import hashlib
    text = "To the Grievance Officer: please review the proportionate deduction on claim AGI/HC/2526/004512."
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def go():
        async with ClaimClearToolkit() as tk:
            filed = await tk.file_grievance("case_0123456789abcdef", "AGI/HC/2526/004512", ["R3"], text, sha,
                                            "token-from-the-approval-gate")
            status = await tk.grievance_status(filed["reference"])
            try:
                await tk.file_grievance("case_0123456789abcdef", "AGI/HC/2526/004512", ["R3"], text + " edited",
                                        sha, "token-from-the-approval-gate")
            except ClaimClearToolError as exc:
                return filed, status, exc.info
    filed, status, err = run(go())
    assert filed["status"] == status["status"] == "dry_run"
    assert err.code == "TEXT_HASH_MISMATCH" and err.action == results.BACK_TO_APPROVAL


def test_errors_raise_with_an_action(store):
    case_id = store[1]["SET-01"]["case_id"]

    async def go():
        async with ClaimClearToolkit() as tk:
            await tk.get_document_text(case_id, store[1]["ADV-02"]["document_id"])
    with pytest.raises(ClaimClearToolError) as e:
        run(go())
    assert e.value.info.code == "DOCUMENT_NOT_IN_CASE" and e.value.info.action == results.STOP


def test_ask_answer_rerun_loop(store):
    """A platelet line with the room over the cap: the engine asks, the answer is applied, the engine computes."""
    extracted = payload("SET-01")
    claim = extracted["claim"]
    claim["lines"].append({"line_id": "L99", "description": "Platelet transfusion", "amount": "8500"})

    async def go():
        async with ClaimClearToolkit() as tk:
            ids = store[1]["SET-01"]
            case = build_case(claim, await tk.get_policy(ids["case_id"]), [])
            first = await tk.expected_settlement(case)
            q = signals.questions_to_ask(first)[0]
            answered = apply_answer(claim, q, False, first)
            second = await tk.expected_settlement(build_case(answered, case["policy"], []))
            return first, q, second
    first, q, second = run(go())
    assert signals.after_settlement(first) == signals.ASK_USER and q["question_id"] == "Q-ROOM-PRICING"
    assert second["status"] == "computed"


def test_reference_demo_runs(store, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    import verify_settlement_demo as demo
    monkeypatch.setattr(demo, "dev_case_id", lambda repo, d: store[1][d]["case_id"])
    out = run(demo.verify("SET-01"))
    assert out["disputable"] == 8522.86 and out["grievance_rows"] == ["R3"]
    assert out["rows"]["R3"] == ("does_not_match_policy", "prop_on_all_lines")
    assert out["critic_unsupported_figures"] == []


def test_local_tools_replace_the_policy_kb_stubs():
    """policy_kb tools passed as local_tools stand in for the policy-kb server, with the same results and errors."""
    pk = REPO / "servers" / "policy_kb"
    if not (pk / "policy_kb").is_dir():
        pytest.skip("policy_kb not found")
    sys.path.insert(0, str(pk))
    sys.path.insert(0, str(pk / "tests"))
    from conftest import INFO, SAMPLE
    from policy_kb import PolicyKB
    from policy_kb.tools import make_tools
    kb = PolicyKB.from_file(SAMPLE, INFO)

    async def go():
        async with ClaimClearToolkit(servers={}, local_tools=make_tools(kb)) as tk:
            tools = {t.name: t for t in tk.for_agent("policy_analyst")}
            typed = await tk.get_clause("4.3")                          # typed helper on a local tool
            try:
                await tk.clauses_for_rule("copay")
            except ClaimClearToolError as exc:
                err = exc.info
            return tools, tools["search_clauses"].invoke({"query": "why did they cut my medicine bill", "k": 1}),                 typed, err
    tools, found, typed, err = run(go())
    assert set(tools) == {"search_clauses", "get_clause", "clauses_for_rule", "list_policies"}   # all in-process
    assert found["hits"][0]["clause_id"] == "5.2" and found["synthetic"] is True
    assert typed["title"] == "Cataract treatment" and err.code == "NO_RULE_MAP"


# --------------------------------------------------------------------------- where hooks attach


def test_mcp_interceptors_run_around_every_call_and_can_refuse():
    """Hook point 2: interceptors at the MCP client (tool_interceptors), around every tool call."""
    from langchain_core.messages import ToolMessage
    seen = []

    async def log_hook(request, handler):                  # post-tool style: observe, then pass through
        result = await handler(request)
        seen.append((request.server_name, request.name))
        return result

    async def deny_hook(request, handler):                 # pre-tool style: refuse without calling the server
        if request.name == "list_hypotheses":
            return ToolMessage(content='{"code": "NOT_ALLOWED", "message": "refused by hook", "retryable": false}',
                               tool_call_id="refused", status="error")
        return await handler(request)

    async def go():
        async with ClaimClearToolkit(tool_interceptors=[log_hook, deny_hook]) as tk:
            refused = await tk.tool("list_hypotheses").ainvoke(
                {"type": "tool_call", "id": "c1", "name": "list_hypotheses", "args": {}})
            ok = await tk.call("get_clause", {"clause_id": "5.2"})
            return refused, ok
    refused, ok = run(go())
    assert "refused by hook" in results.message_text(refused) and ok["found"] is True
    assert ("policy-kb", "get_clause") in seen and ("settlement-engine", "list_hypotheses") in seen


def test_tool_node_wrapper_checks_the_calling_agent():
    """Hook point 1: LangGraph's ToolNode(awrap_tool_call=...), which knows the agent and the graph state."""
    from langchain_core.messages import AIMessage, ToolMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode
    from claimclear_tools.agents import may_use

    def permission_hook(agent):
        async def wrapper(request, execute):
            name = request.tool_call["name"]
            if not may_use(agent, name):
                return ToolMessage(content=f'{{"code": "NOT_ALLOWED", "message": "{agent} may not call {name}"}}',
                                   tool_call_id=request.tool_call["id"], status="error")
            return await execute(request)
        return wrapper

    async def go():
        async with ClaimClearToolkit() as tk:
            node = ToolNode(tk.for_agent("explainer") + [tk.tool("list_hypotheses")],
                            awrap_tool_call=permission_hook("explainer"))
            calls = [{"name": "get_clause", "args": {"clause_id": "5.2"}, "id": "a", "type": "tool_call"},
                     {"name": "list_hypotheses", "args": {}, "id": "b", "type": "tool_call"}]
            graph = StateGraph(MessagesState)
            graph.add_node("explainer_tools", node)
            graph.add_edge(START, "explainer_tools")
            graph.add_edge("explainer_tools", END)
            out = await graph.compile().ainvoke({"messages": [AIMessage(content="", tool_calls=calls)]})
            return {m.tool_call_id: m for m in out["messages"] if isinstance(m, ToolMessage)}
    msgs = run(go())
    assert msgs["a"].status != "error" and results.structured(msgs["a"])["found"] is True
    assert msgs["b"].status == "error" and "explainer may not call list_hypotheses" in results.message_text(msgs["b"])
