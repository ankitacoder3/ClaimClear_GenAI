"""Reference flow: verify one settlement through the MCP servers, no LLM (the C0 fixed-workflow shape).

    python examples/verify_settlement_demo.py SET-01

Run in the **agents'** environment with ``claimclear_tools`` installed, after
``python -m case_records.register_dataset`` has filled ``var/case_store``.

Two development stand-ins are used and labelled below; replace them in the real graph:

* the **case ID** comes from ``var/dataset_map.json`` (evaluation-only file; the app supplies it in real use);
* the **extracted claim and letter** come from ``python -m mcp_server --case-payload`` instead of the
  document reader's LLM extraction.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys

from claimclear_tools import ClaimClearToolkit, build_case, signals
from claimclear_tools.config import find_repo, server_python
from claimclear_tools.critic import allowed_figures, unsupported_figures, wording_for


def dev_case_id(repo, dataset_id: str) -> str:
    """DEV STAND-IN for the app's upload step."""
    return json.loads((repo / "var" / "dataset_map.json").read_text(encoding="utf-8"))[dataset_id]["case_id"]


def dev_extraction(repo, dataset_id: str) -> dict:
    """DEV STAND-IN for the document reader's extraction (LLM in the real graph)."""
    out = subprocess.run([server_python(repo), "-m", "mcp_server", "--case-payload", dataset_id],
                         cwd=repo / "servers" / "settlement_engine", capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return json.loads(out.stdout)


async def verify(dataset_id: str) -> dict:
    repo = find_repo()
    case_id = dev_case_id(repo, dataset_id)

    async with ClaimClearToolkit() as tk:
        # 1. read the case (document reader + policy analyst's case-records part)
        records = await tk.read_case(case_id)
        for doc_id, text in records["documents"].items():
            if signals.after_document_text(text) == signals.MISSING_DOCUMENT:
                return {"route": "missing_document", "document_id": doc_id,
                        "pages": signals.unreadable_pages(text)}
            flags = signals.security_flags(text)
            if flags:
                print(f"  guardrail flags for {doc_id}: {flags}")
        extracted = dev_extraction(repo, dataset_id)
        case = build_case(extracted["claim"], records["policy"], records["history"])
        letter = extracted["letter"]

        # 2. what the policy requires
        settlement = await tk.expected_settlement(case)
        route = signals.after_settlement(settlement)
        if route == signals.ASK_USER:
            return {"route": route, "questions": signals.questions_to_ask(settlement)}

        # 3. each row of the letter (an agent would pick hypothesis_ids first, then replan)
        rows = {}
        for row_id in signals.rows_to_audit(letter):
            row = await tk.reproduce_deduction(case, letter, row_id)
            if signals.after_row_audit(row) == signals.REPLAN:
                row = await tk.reproduce_deduction(case, letter, row_id)
            rows[row_id] = row

        # 4. critic: one call re-runs everything; check a draft's figures and wording
        audit = await tk.audit_settlement_letter(case, letter)
        draft = " ".join(f"{r['particulars']}: ₹{r['insurer_amount']:,} {wording_for(r)}." for r in rows.values())
        draft += f" May be disputable: ₹{audit['disputable_amount']:,}."
        problems = unsupported_figures(draft, allowed_figures(settlement, rows.values(), audit))

        return {
            "route": signals.after_letter_audit(audit),
            "payable_under_policy": audit["policy_payable"],
            "insurer_paid": audit["insurer_paid"],
            "disputable": audit["disputable_amount"],
            "unverified": audit["unverified_amount"],
            "rows": {k: (v["verdict"], v["method"]) for k, v in rows.items()},
            "grievance_rows": [r["row_id"] for r in signals.disputable_rows(rows.values())],
            "critic_unsupported_figures": [str(p) for p in problems],
        }


if __name__ == "__main__":
    result = asyncio.run(verify(sys.argv[1] if len(sys.argv) > 1 else "SET-01"))
    print(json.dumps(result, indent=2, ensure_ascii=False))
