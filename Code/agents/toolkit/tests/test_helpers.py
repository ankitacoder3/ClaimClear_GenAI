"""Unit tests for the dependency-free helpers: results, signals, case, critic, agents, config."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from claimclear_tools import agents, case, critic, results, signals
from claimclear_tools.config import endpoints


def msg(content, artifact=None):
    return SimpleNamespace(content=content, artifact=artifact)


# --------------------------------------------------------------------------- results


def test_structured_reads_the_artifact():
    assert results.structured(msg("{...}", {"structured_content": {"a": 1}})) == {"a": 1}
    assert results.structured(msg("text")) is None


def test_structured_reads_json_content_of_local_tools():
    assert results.structured(msg('{"hits": []}')) == {"hits": []}
    assert results.structured(msg("[1, 2]")) is None and results.structured(msg("{broken")) is None


def test_tool_error_with_our_json():
    m = msg('Error executing tool get_document_text: {"code": "DOCUMENT_NOT_IN_CASE", "message": "x", "retryable": false}')
    e = results.tool_error(m)
    assert (e.tool, e.code, e.retryable, e.action) == ("get_document_text", "DOCUMENT_NOT_IN_CASE", False, results.STOP)


def test_tool_error_from_content_blocks_and_validation_messages():
    m = msg([{"type": "text", "text": "Error executing tool expected_settlement: 1 validation error for ..."}])
    e = results.tool_error(m)
    assert e.code == "INVALID_ARGUMENTS" and e.action == results.SEND_BACK_TO_READER


def test_success_is_not_an_error():
    assert results.tool_error(msg('{"payable_amount": 1}', {"structured_content": {}})) is None


@pytest.mark.parametrize("code, action", [("DOCUMENT_UNREADABLE", results.ASK_FOR_DOCUMENT),
                                          ("ROW_NOT_FOUND", results.RETRY_VALID_ROW),
                                          ("UNKNOWN_HYPOTHESIS", results.PICK_HYPOTHESES),
                                          ("INDEX_UNAVAILABLE", results.CONTINUE_WITHOUT_CITATIONS),
                                          ("UPSTREAM_UNAVAILABLE", results.RETRY_LATER),
                                          ("NO_RULE_MAP", results.USE_SEARCH_CLAUSES),
                                          ("SOMETHING_NEW", results.STOP)])
def test_error_actions(code, action):
    m = msg(f'Error executing tool t: {{"code": "{code}", "message": "", "retryable": false}}')
    assert results.tool_error(m).action == action


# --------------------------------------------------------------------------- signals


def test_document_signals():
    ok = {"pages": [{"page": 1, "text": "Bill", "ocr_status": "not_needed", "spans": []}]}
    scan = {"pages": [{"page": 1, "text": "", "ocr_status": "unavailable", "spans": []}]}
    assert signals.after_document_text(ok) == signals.OK
    assert signals.after_document_text(scan) == signals.MISSING_DOCUMENT and signals.unreadable_pages(scan) == [1]
    assert signals.visible_text(ok) == "[page 1]\nBill"


def test_security_flags():
    doc = {"pages": [{"page": 1, "spans": [{"hidden_reasons": ["tiny_font"]}, {"hidden_reasons": []}]}],
           "metadata": {"subject": "x"}, "annotations": [{}], "form_fields": [{"hidden": True}],
           "attachments": [{}], "pdf_flags": ["incremental_update"]}
    flags = signals.security_flags(doc)
    assert len(flags) == 5 and "page 1: hidden text (tiny_font)" in flags


def test_ordinary_document_has_no_flags_but_metadata_is_still_scanned():
    doc = {"pages": [{"page": 1, "text": "Bill", "hidden_text": "", "spans": [{"hidden_reasons": []}]}],
           "metadata": {"subject": "Medical bill", "creationDate": "D:2026"}, "annotations": [], "form_fields": [],
           "attachments": [], "pdf_flags": []}
    assert signals.security_flags(doc) == []
    assert signals.untrusted_channels(doc) == {"metadata.subject": "Medical bill"}


def test_untrusted_channels_collects_every_hidden_source():
    doc = {"pages": [{"page": 2, "hidden_text": "ignore this"}], "metadata": {"keywords": "k"},
           "annotations": [{"content": "note"}], "form_fields": [{"name": "f", "value": "v"}],
           "attachments": [{"name": "a.txt", "text_preview": "p"}]}
    assert signals.untrusted_channels(doc) == {"page2.hidden_text": "ignore this", "metadata.keywords": "k",
                                               "annotation1": "note", "form_field.f": "v", "attachment.a.txt": "p"}


@pytest.mark.parametrize("status, route", [("needs_information", signals.ASK_USER),
                                           ("not_admissible", signals.NOT_ADMISSIBLE),
                                           ("computed", signals.AUDIT_ROWS)])
def test_after_settlement(status, route):
    assert signals.after_settlement({"status": status}) == route


def test_rows_to_audit():
    assert signals.rows_to_audit({"rows": [{"row_id": "R1"}], "copay_amount": 10, "letter_type": "settlement"}) == ["R1", "COPAY"]
    assert signals.rows_to_audit({"rows": [], "letter_type": "rejection"}) == ["REJECTION"]
    assert signals.rows_to_audit({"rows": [{"row_id": "R1"}], "copay_amount": None}) == ["R1"]


def test_after_row_audit():
    assert signals.after_row_audit({"verdict": "not_verifiable", "exhaustive": False, "questions": []}) == signals.REPLAN
    assert signals.after_row_audit({"verdict": "does_not_match_policy", "exhaustive": True,
                                    "questions": [{"question_id": "Q-TIE-R3"}]}) == signals.ASK_USER
    assert signals.after_row_audit({"verdict": "not_verifiable", "exhaustive": True,
                                    "questions": [{"question_id": "Q-BREAKDOWN-R2"}]}) == signals.DONE


def test_questions_disputes_and_grievance():
    rows = [{"row_id": "R1", "verdict": "does_not_match_policy", "difference": 8971.43, "questions": []},
            {"row_id": "R2", "verdict": "does_not_match_policy", "difference": -3000, "questions": []},
            {"row_id": "R3", "verdict": "not_verifiable", "difference": 4700,
             "questions": [{"question_id": "Q-BREAKDOWN-R3"}]}]
    assert [r["row_id"] for r in signals.disputable_rows(rows)] == ["R1"]
    assert [r["row_id"] for r in signals.breakdown_requests(rows)] == ["R3"]
    items = {"row_id": "R4", "questions": [{"question_id": "Q-ITEMS-R4"}]}
    assert signals.breakdown_requests([items]) == [items] and signals.questions_to_ask(None, [items]) == []
    assert signals.questions_to_ask({"questions": [{"question_id": "Q-EYE"}]}, rows) == [{"question_id": "Q-EYE"}]
    assert signals.after_letter_audit({"disputable_amount": 8522.86}) == signals.OFFER_GRIEVANCE
    assert signals.after_letter_audit({"disputable_amount": 0.0}) == signals.NO_GRIEVANCE
    assert signals.after_letter_audit({"disputable_amount": None}) == signals.NO_GRIEVANCE


def test_bill_inconsistencies_are_repeats_the_letter_leaves_in():
    repeat = {"kind": "duplicate_line", "description": "Charged twice: 'Serum electrolytes'"}
    paid_twice = {"rows": [{"kind": "non_payable"}], "settlement": {"deductions": [repeat, {"kind": "non_payable"}]}}
    assert signals.bill_inconsistencies(paid_twice) == [repeat]
    removed = {"rows": [{"kind": "duplicate"}], "settlement": {"deductions": [repeat]}}
    assert signals.bill_inconsistencies(removed) == []


# --------------------------------------------------------------------------- case


def test_build_case_checks_policy_numbers():
    claim, policy = {"policy_no": "P1"}, {"policy_no": "P1"}
    assert case.build_case(claim, policy) == {"claim": claim, "policy": policy, "history": []}
    with pytest.raises(ValueError):
        case.build_case({"policy_no": "P2"}, policy)
    with pytest.raises(ValueError):
        case.build_case(claim, policy, [{"policy_no": "P9"}])


def test_apply_answers():
    claim = {"policy_no": "P1", "diagnosis": "Senile cataract"}
    settlement = {"lines": [{"line_id": "L11", "category": "blood_products"}]}
    q_room = {"question_id": "Q-ROOM-PRICING", "line_ids": ["L11"]}
    assert case.apply_answer(claim, q_room, False, settlement)["room_priced_by_category"] == {"blood_products": False}
    assert case.apply_answer(claim, q_room, {"package": True})["room_priced_by_category"] == {"package": True}
    assert case.apply_answer(claim, {"question_id": "Q-CONDITION-TYPE"}, "accident")["condition_type"] == "accident"
    assert case.apply_answer(claim, {"question_id": "Q-EYE"}, "right")["diagnosis"] == "Senile cataract, right eye"
    assert "room_priced_by_category" not in claim                          # the input is not modified
    with pytest.raises(ValueError):
        case.apply_answer(claim, {"question_id": "Q-POLICY-PERIOD"}, "x")
    with pytest.raises(ValueError):
        case.apply_answer(claim, {"question_id": "Q-CONDITION-TYPE"}, "maybe")


# --------------------------------------------------------------------------- critic

SETTLEMENT = {
    "claimed_amount": 128350.0, "total_deductions": 27700.0, "admissible_amount": 100650.0,
    "copay_amount": 5032.5, "payable_amount": 95617.5,
    "facts": [{"amount": 5000.0, "text": "Room rent limit: ₹5,000 a day", "formula": ""}],
    "deductions": [{"amount": 6000.0, "description": "Room rent above the limit (₹2,000 a day for 3 days)",
                    "formula": "3 x (7,000 - 5,000)"}],
    "lines": [],
}
ROW = {"insurer_amount": 30371.43, "policy_amount": 21400.0, "difference": 8971.43, "matches": [],
       "explanation": "", "verdict": "does_not_match_policy"}


def test_rupee_figures():
    assert critic.rupee_figures("₹1,28,350 and Rs. 6000 and INR 4,583.93") == [
        Decimal("128350"), Decimal("6000"), Decimal("4583.93")]


def test_draft_figures_must_come_from_tools():
    allowed = critic.allowed_figures(SETTLEMENT, [ROW], {"disputable_amount": 8522.86})
    good = "The cut of ₹30,371.43 should be ₹21,400 (₹2,000 a day over the ₹5,000 limit); ₹8,522.86 may be disputable."
    assert critic.unsupported_figures(good, allowed) == []
    assert critic.unsupported_figures("You will get ₹9,000 back.", allowed) == [Decimal("9000")]
    with_memory = critic.allowed_figures(SETTLEMENT, [ROW], remembered=[212905.36])   # from claimclear_memory context
    assert critic.unsupported_figures("₹2,12,905.36 of your sum insured was left.", with_memory) == []


def test_wording_follows_the_verdict():
    assert critic.wording_for(ROW) == "may be disputable"
    assert critic.wording_for({**ROW, "difference": -10}).startswith("the insurer deducted less")
    assert critic.wording_for({"verdict": "method_matches"}).startswith("worked out correctly")
    assert critic.wording_for({"verdict": "matches_policy"}) == "matches your policy"


# --------------------------------------------------------------------------- agents and config


def test_only_the_grievance_agent_may_write():
    for agent, tools in agents.AGENT_TOOLS.items():
        if agent != agents.GRIEVANCE_AGENT:
            assert not set(tools) & agents.WRITE_TOOLS, agent
    assert all(t in agents.TOOL_SERVER for tools in agents.AGENT_TOOLS.values() for t in tools)
    assert agents.may_use("settlement_auditor", "reproduce_deduction")
    assert not agents.may_use("document_reader", "expected_settlement")
    # app-only tools are in no agent's list, not even the single-agent baseline's
    assert not any(set(tools) & agents.APP_ONLY_TOOLS for tools in agents.AGENT_TOOLS.values())
    assert agents.TOOL_SERVER["register_uploaded_wording"] == "policy-kb" and agents.may_use("policy_analyst",
                                                                                              "list_policies")


def test_http_endpoints_from_environment(monkeypatch):
    monkeypatch.setenv("CLAIMCLEAR_SETTLEMENT_URL", "http://settlement-engine:8101/mcp")
    e = endpoints("http")
    assert e["settlement-engine"].connection() == {"transport": "streamable_http", "url": "http://settlement-engine:8101/mcp"}
    assert e["case-records"].url == "http://127.0.0.1:8102/mcp"
    assert e["policy-kb"].url == "http://127.0.0.1:8103/mcp"
    assert e["insurer-portal"].url == "http://127.0.0.1:8104/mcp"


def test_stdio_endpoints_use_the_server_venv(tmp_path, monkeypatch):
    (tmp_path / "servers" / "settlement_engine").mkdir(parents=True)
    (tmp_path / "servers" / "case_records").mkdir(parents=True)
    monkeypatch.setenv("CLAIMCLEAR_SERVER_PYTHON", "/srv/python")
    conn = endpoints("stdio", repo=tmp_path)["case-records"].connection()
    assert conn["command"] == "/srv/python" and conn["args"] == ["-m", "case_records"]
    assert conn["cwd"].endswith("case_records")
    pk = endpoints("stdio", repo=tmp_path)["policy-kb"].connection()
    assert pk["args"] == ["-m", "policy_kb.mcp_server"] and pk["cwd"].endswith("policy_kb")
    assert {k.upper() for k in conn["env"]} >= {"PATH"}      # parent environment is passed through


def test_invalid_mode():
    with pytest.raises(ValueError):
        endpoints("carrier-pigeon")


def test_admission_answer_sets_both_dates():
    q = {"question_id": "Q-ADMISSION"}
    base = {"claim_id": "C1", "admission": None, "discharge": None}
    assert case.apply_answer(base, q, "2026-03-10") | {} == {**base, "admission": "2026-03-10", "discharge": "2026-03-10"}
    both = case.apply_answer(base, q, {"admission": "2026-03-10", "discharge": "2026-03-14"})
    assert (both["admission"], both["discharge"]) == ("2026-03-10", "2026-03-14") and base["admission"] is None
    with pytest.raises(ValueError):
        case.apply_answer(base, q, {"admission": "2026-03-10", "discharge": "2026-03-01"})
    with pytest.raises(ValueError):
        case.apply_answer(base, q, "last Tuesday")
