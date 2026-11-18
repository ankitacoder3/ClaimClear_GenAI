"""The settlement-engine MCP server: one test per tool, errors, schema contract, stdio.

Needs the ``mcp`` package (project virtual environment). Skipped without it, so
the engine tests still run on a bare Python.
"""

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters  # noqa: E402

from engine import Verdict, default_rules  # noqa: E402
from engine.dataset import answer_key, load_case, load_letter  # noqa: E402
from factories import claim, line, policy, worked_example_lines  # noqa: E402
from mcp_server import create_server  # noqa: E402
from mcp_server.__main__ import tool_schemas  # noqa: E402
from mcp_server.convert import case_payload, claim_payload, letter_payload, policy_payload, to_case, to_letter  # noqa: E402
from mcp_server.schemas import CaseIn, LetterIn  # noqa: E402

ENGINE_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "settlement_engine_tools.json"
TOOLS = {"expected_settlement", "reproduce_deduction", "audit_settlement_letter", "list_hypotheses"}
LETTERS = ["SET-01", "SET-02", "SET-03", "SET-04", "SET-05"]


def call(tool, args, server=None):
    async def go():
        async with Client(server or create_server(default_rules())) as client:
            return await client.call_tool(tool, args)
    return asyncio.run(go())


def error_of(result):
    assert result.is_error
    text = result.content[0].text
    return json.loads(text[text.index("{"):])


def dataset_args(doc_id, dataset_dir):
    return {"case": case_payload(load_case(doc_id, dataset_dir)),
            "letter": letter_payload(load_letter(doc_id, dataset_dir))}


# --------------------------------------------------------------------------- listing and contract


def test_tools_are_listed_read_only():
    tools = asyncio.run(create_server(default_rules()).list_tools())
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False
        assert t.meta == {"access": "read"}
        assert t.output_schema and t.description


def test_tool_schemas_match_the_snapshot():
    """A schema change on either side must be deliberate: regenerate the snapshot and review the diff.

        python -m mcp_server --dump-schemas > tests/snapshots/settlement_engine_tools.json
    """
    current = json.loads(json.dumps(asyncio.run(tool_schemas()), sort_keys=True))
    assert current == json.loads(SNAPSHOT.read_text(encoding="utf-8")), "tool schemas changed; see the docstring"


# --------------------------------------------------------------------------- expected_settlement


def test_expected_settlement(dataset_dir):
    r = call("expected_settlement", {"case": case_payload(load_case("SET-01", dataset_dir))})
    s = r.structured_content
    assert not r.is_error and s["status"] == "computed"
    assert s["payable_amount"] == 95617.5
    assert {d["kind"] for d in s["deductions"]} == {"room_rent_excess", "room_gst_excess", "proportionate_deduction"}
    assert any(f["fact_id"] == "F-PAYABLE" for f in s["facts"])


def test_expected_settlement_asks_instead_of_guessing():
    c = claim(worked_example_lines() + [line("L11", "Platelet transfusion", 8500)])
    r = call("expected_settlement", {"case": {"claim": claim_payload(c), "policy": policy_payload(policy())}})
    s = r.structured_content
    assert s["status"] == "needs_information" and s["payable_amount"] is None
    assert s["questions"][0]["question_id"] == "Q-ROOM-PRICING"


# --------------------------------------------------------------------------- reproduce_deduction


def test_reproduce_deduction(dataset_dir):
    r = call("reproduce_deduction", {**dataset_args("SET-01", dataset_dir), "row_id": "R3"})
    s = r.structured_content
    assert s["verdict"] == Verdict.DOES_NOT_MATCH_POLICY.value and s["method"] == "prop_on_all_lines"
    assert s["difference"] == 8971.43 and s["policy_fact_ids"] == ["F-D-PROPORTIONATE"]


def test_reproduce_deduction_partial_test_then_replan(dataset_dir):
    args = {**dataset_args("SET-01", dataset_dir), "row_id": "R3"}
    first = call("reproduce_deduction", {**args, "hypothesis_ids": ["prop_incl_pharmacy"]}).structured_content
    assert first["verdict"] == "not_verifiable" and first["exhaustive"] is False
    second = call("reproduce_deduction", args).structured_content
    assert second["method"] == "prop_on_all_lines" and second["exhaustive"] is True


def test_reproduce_deduction_copay_and_rejection_rows(dataset_dir):
    copay = call("reproduce_deduction", {**dataset_args("SET-03", dataset_dir), "row_id": "COPAY"}).structured_content
    assert copay["verdict"] == "method_matches"
    rej = call("reproduce_deduction", {**dataset_args("SET-05", dataset_dir), "row_id": "REJECTION"}).structured_content
    assert rej["method"] == "waiting_from_renewal"


# --------------------------------------------------------------------------- audit_settlement_letter


@pytest.mark.parametrize("doc_id", LETTERS)
def test_audit_settlement_letter(doc_id, dataset_dir):
    s = call("audit_settlement_letter", dataset_args(doc_id, dataset_dir)).structured_content
    key = answer_key(doc_id, dataset_dir)
    assert s["policy_payable"] == key["expected_payable"]
    assert s["disputable_amount"] == key["disputable_amount"]
    assert s["unverified_amount"] == key["unverified_amount"]
    for i, row in enumerate(key["insurer_deductions"], start=1):
        assert next(r for r in s["rows"] if r["row_id"] == f"R{i}")["verdict"] == row["expected_verdict"]


# --------------------------------------------------------------------------- list_hypotheses


def test_list_hypotheses():
    everything = call("list_hypotheses", {}).structured_content["hypotheses"]
    assert len(everything) == 51                 # 49 + the two that confirm a rejection from the bill (18 Nov 2026)
    prop = call("list_hypotheses", {"kind": "proportionate"}).structured_content["hypotheses"]
    assert {h["kind"] for h in prop} == {"proportionate"} and prop[0]["correct"] is True


# --------------------------------------------------------------------------- errors


def test_policy_mismatch(dataset_dir):
    args = {"case": case_payload(load_case("SET-01", dataset_dir))}
    args["case"]["policy"]["policy_no"] = "AS-OTHER"
    assert error_of(call("expected_settlement", args))["code"] == "POLICY_MISMATCH"


def test_history_on_another_policy(dataset_dir):
    args = {"case": case_payload(load_case("SET-01", dataset_dir))}
    args["case"]["history"] = [{"claim_id": "H1", "policy_no": "AS-OTHER", "admission": "2025-09-01",
                                "status": "settled", "settled_amount": "1000"}]
    assert error_of(call("expected_settlement", args))["code"] == "HISTORY_POLICY_MISMATCH"


def test_row_not_found_lists_valid_rows(dataset_dir):
    err = error_of(call("reproduce_deduction", {**dataset_args("SET-01", dataset_dir), "row_id": "R9"}))
    assert err["code"] == "ROW_NOT_FOUND" and "COPAY" in err["message"] and err["retryable"] is False


def test_unknown_hypothesis(dataset_dir):
    args = {**dataset_args("SET-01", dataset_dir), "row_id": "R3", "hypothesis_ids": ["made_up"]}
    assert error_of(call("reproduce_deduction", args))["code"] == "UNKNOWN_HYPOTHESIS"


def test_a_discharge_before_the_admission_is_accepted_reported_and_asked_about(dataset_dir):
    # Since 18 Nov 2026 impossible dates are a finding about the bill (engine/integrity.py), not invalid input.
    args = {"case": case_payload(load_case("SET-01", dataset_dir))}
    args["case"]["claim"].update(discharge="2026-01-01")
    out = call("expected_settlement", args).structured_content
    assert out["status"] == "needs_information" and [q["question_id"] for q in out["questions"]] == ["Q-ADMISSION"]
    assert any(f["kind"] == "integrity" and f["inputs"]["code"] == "discharge_before_admission" for f in out["facts"])


@pytest.mark.parametrize("mutate", [
    lambda a: a["case"]["claim"]["lines"][0].update(amount="-5"),                   # negative amount
    lambda a: a["case"]["claim"]["lines"].append(dict(a["case"]["claim"]["lines"][0])),  # duplicate line_id
    lambda a: a["case"].update(rules={"copay_pct": 0}),                              # rules are not an input
    lambda a: a["case"]["claim"].update(lines=[]),                                   # no lines
    lambda a: a["case"]["claim"].update(claim_id="x" * 65),                          # over-long ID
])
def test_invalid_input_is_rejected(mutate, dataset_dir):
    args = {"case": case_payload(load_case("SET-01", dataset_dir))}
    mutate(args)
    assert call("expected_settlement", args).is_error


def test_reserved_row_ids_are_rejected(dataset_dir):
    args = {**dataset_args("SET-01", dataset_dir), "row_id": "R1"}
    args["letter"]["rows"][0]["row_id"] = "COPAY"
    assert call("reproduce_deduction", args).is_error


# --------------------------------------------------------------------------- configuration and conversion


def test_policy_rules_come_from_the_server(dataset_dir):
    rules = default_rules()
    ten_pct = type(rules)(**{**rules.__dict__, "copay_pct": Decimal(10)})
    s = call("expected_settlement", {"case": case_payload(load_case("SET-01", dataset_dir))},
             server=create_server(ten_pct)).structured_content
    assert s["copay_amount"] == 10065.0                                            # 10% of 1,00,650


@pytest.mark.parametrize("doc_id", LETTERS)
def test_payload_round_trip(doc_id, dataset_dir):
    case = load_case(doc_id, dataset_dir)
    c, p, h = to_case(CaseIn.model_validate(case_payload(case)))
    assert (c, p, tuple(h)) == (case.claim, case.policy, case.history)
    lt = load_letter(doc_id, dataset_dir)
    assert to_letter(LetterIn.model_validate(letter_payload(lt))) == lt


# --------------------------------------------------------------------------- real transport


def test_stdio_transport_lists_the_tools():
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"], cwd=str(ENGINE_DIR))

    async def go():
        async with Client(params, read_timeout_seconds=60) as client:
            return await client.list_tools()

    assert {t.name for t in asyncio.run(go()).tools} == TOOLS


# --------------------------------------------------------------------------- dev payload command


def test_case_payload_command(dataset_dir):
    from mcp_server.__main__ import case_payload_for
    letter = case_payload_for("SET-01")
    assert set(letter) == {"claim", "letter"}
    CaseIn.model_validate({"claim": letter["claim"], "policy": policy_payload(load_case("SET-01", dataset_dir).policy)})
    LetterIn.model_validate(letter["letter"])
    assert set(case_payload_for("GEN-02")) == {"claim"}          # a bill has no letter
