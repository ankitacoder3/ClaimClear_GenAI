"""Live E1: C0, C1 and C2 against the real MCP servers (the same toolkit, the same case), nothing recorded.

The model's reading is the labelled development stand-in (the engine's ``--case-payload``) for C0 and C2; C1's
model is scripted, but every tool it calls goes through the real toolkit's ``call(name, args)`` to the servers.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langchain_mcp_adapters")

from claimclear_tools import ClaimClearToolkit, signals  # noqa: E402
from claimclear_tools.case import build_case  # noqa: E402

import e1_architectures as arch  # noqa: E402
from conftest import run  # noqa: E402
from test_architectures import ScriptedChat  # noqa: E402
from test_graph_live import payload, servers_env  # noqa: E402,F401  (Member 3's live setup, imported as it is)

TEXT = "R3 was cut by ₹30,371.43; your policy allows ₹21,400. In total ₹8,522.86 may be disputable."


def test_all_three_configurations_agree_on_the_real_servers(servers_env):     # noqa: F811
    ex = payload("SET-01")
    case_id = servers_env["SET-01"]["case_id"]

    async def reader(toolkit, cid, documents, pages):
        return {"claim": ex["claim"], "letter": ex["letter"]}

    async def go():
        async with ClaimClearToolkit() as tk:
            c0 = await arch.run_review("c0", tk, None, case_id, extractor=reader)
            c2 = await arch.run_review("c2", tk, None, case_id, extractor=reader)
            case = build_case(ex["claim"], await tk.get_policy(case_id), await tk.get_claim_history(case_id))
            script = [[("list_case_documents", {"case_id": case_id})],
                      [("get_policy", {"case_id": case_id}), ("get_claim_history", {"case_id": case_id})],
                      [("expected_settlement", {"case": case})],
                      [("reproduce_deduction", {"case": case, "letter": ex["letter"], "row_id": r})
                       for r in signals.rows_to_audit(ex["letter"])],
                      [("audit_settlement_letter", {"case": case, "letter": ex["letter"]})],
                      [("submit_review", {"explanation": TEXT, "overall_verdict": "disputable"})]]
            llm = ScriptedChat(script=script)
            c1 = await arch.run_review("c1", tk, llm, case_id)
            return c0, c1, c2, llm
    c0, c1, c2, llm = run(go())
    for st in (c0, c1, c2):
        assert st["letter_audit"]["disputable_amount"] == 8522.86, st["architecture"]
        assert {k: v["verdict"] for k, v in st["row_audits"].items()} == \
               {k: v["verdict"] for k, v in c2["row_audits"].items()}
        assert st["policy_violations"] == [] and st["usage"]["tool_calls"] > 0
    assert len(llm.seen[-1]) == 14                    # the 13 live read tools + submit_review, with their schemas
    assert c1["usage"]["tools"]["reproduce_deduction"] == len(signals.rows_to_audit(ex["letter"]))
