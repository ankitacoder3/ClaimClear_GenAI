"""Record the offline test fixtures from a live run against the real MCP servers.

    .venv-agents/bin/python agents/orchestration/examples/record_fixtures.py

For each case below the whole graph runs live (servers over stdio, through ``claimclear_tools``),
every typed tool call is recorded, and ``tests/fixtures/<case>.json`` is written. The offline tests
replay these, so they exercise the graph on the engine's real outputs. Re-run after a server change.

DEVELOPMENT STAND-INS (labelled, never used in evaluation): the case ID comes from the dataset map
of a scratch case store, and the claim/letter come from the engine's ``--case-payload`` instead of the
document reader's LLM extraction. Needs Tesseract for SET-32 (its bill is a scan).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from claimclear_tools import ClaimClearToolkit
from claimclear_tools.config import find_repo, server_python

from claimclear_graph import HumanApprovalGateway, Services, build_claimclear_graph, initial_state
from claimclear_graph.testing import RecordingToolkit

REPO = find_repo()
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CASES = {"SET-01": None, "SET-02": None, "SET-32": {"Q-CONDITION-TYPE": "illness"}}


def prepare(work: Path) -> dict:
    """DEV STAND-IN for the app's upload step: register the dataset, build the policy index."""
    py = server_python(REPO)
    store = work / "case_store"
    subprocess.run([py, "-m", "case_records.register_dataset", "--store", str(store)],
                   cwd=REPO / "servers" / "case_records", check=True, capture_output=True)
    index = work / "policy_kb.json"
    subprocess.run([py, "-m", "policy_kb", "--index", str(index), "build", "--wording",
                    str(REPO / "dev_data" / "wordings" / "policy-wordings-arogya-sanjeevani-policy-go-digit.pdf")],
                   cwd=REPO / "servers" / "policy_kb", check=True, capture_output=True)
    os.environ.update(CLAIMCLEAR_CASE_STORE=str(store), CLAIMCLEAR_POLICY_KB_INDEX=str(index),
                      CLAIMCLEAR_PORTAL_STORE=str(work / "portal.json"), CLAIMCLEAR_MCP_MODE="stdio")
    return json.loads((work / "dataset_map.json").read_text(encoding="utf-8"))


def payload(dataset_id: str) -> dict:
    """DEV STAND-IN for the document reader's extraction."""
    out = subprocess.run([server_python(REPO), "-m", "mcp_server", "--case-payload", dataset_id],
                         cwd=REPO / "servers" / "settlement_engine", capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return json.loads(out.stdout)


async def record(mapping: dict) -> None:
    async with ClaimClearToolkit() as live:
        for dataset_id, answers in CASES.items():
            tk = RecordingToolkit(live)
            graph = build_claimclear_graph(Services(toolkit=tk))
            cfg = {"configurable": {"thread_id": dataset_id}}
            extracted = payload(dataset_id)
            case_id = mapping[dataset_id]["case_id"]
            state = await graph.ainvoke(initial_state(case_id, claim=extracted["claim"], letter=extracted["letter"]), cfg)
            gate = HumanApprovalGateway(graph, gate_secret="")
            if answers:
                state = await gate.answer_questions(cfg, answers)
            reads = [c for c in tk.calls if not c["key"].startswith(('["file_grievance"', '["grievance_status"'))]
            fixture = {"dataset_id": dataset_id, "case_id": case_id, "claim": extracted["claim"],
                       "letter": extracted["letter"], "answers": answers, "live_outcome": state.get("outcome"),
                       "live_paused_for_approval": await gate.is_paused_for_approval(cfg), "calls": reads}
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{dataset_id}.json").write_text(json.dumps(fixture, indent=1, ensure_ascii=False, default=str),
                                                     encoding="utf-8")
            print(f"{dataset_id}: {len(reads)} calls, outcome {fixture['live_outcome']}, "
                  f"paused for approval {fixture['live_paused_for_approval']}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        mapping = prepare(Path(tmp))
        asyncio.run(record(mapping))
    return 0


if __name__ == "__main__":
    sys.exit(main())
