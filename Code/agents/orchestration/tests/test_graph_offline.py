"""The whole graph, offline, on recorded real tool outputs (``tests/fixtures``, see examples/record_fixtures.py).

Covers every route and safety property of the orchestration: the dispute path and the approval gate
(approve, edit, reject, tamper, no approval, HMAC token), the clean path, the ask-the-user pause, the
critic's retry -> replan -> loop guard, the draft fallback and block, early exits, least privilege,
memory, thread isolation and time travel.
"""

from __future__ import annotations

import copy
import hashlib

import pytest
from claimclear_memory import MemoryStore

from claimclear_graph.gateway import issue_token
from claimclear_graph.testing import tool_error

from conftest import Case, load, run

SET01_DISPUTABLE = 8522.86


# --------------------------------------------------------------------------- dispute path + approval gate


def test_set01_pauses_at_the_gate_with_a_grievance_for_r3_only():
    c = Case("SET-01")
    state = run(c.start())
    assert run(c.gate.is_paused_for_approval(c.cfg))
    assert state["letter_audit"]["disputable_amount"] == SET01_DISPUTABLE
    assert state["critic"]["passed"] and state["critic_stage"] == "draft_passed"
    g = state["grievance"]
    assert g["row_ids"] == ["R3"]
    assert g["text_sha256"] == hashlib.sha256(g["text"].encode()).hexdigest()
    assert "₹8,522.86 may be disputable" in g["text"]
    # plain words, not the engine's formula: the method, and the charges the cut may not apply to
    assert "proportionate cut applied to every non-room line" in g["text"]
    assert "Laboratory investigations, MRCP, Pharmacy - inpatient medicines, Laparoscopic clips" in g["text"]
    assert " x (" not in g["text"]
    assert "file_grievance" not in c.tk.log                        # nothing filed before approval
    assert not state.get("outcome")


def test_explanation_quotes_engine_figures_and_allowed_wording():
    state = run(Case("SET-01").start())
    text = state["explanation"]
    assert "₹95,617.50" in text and "₹87,094.64" in text and "₹8,522.86" in text
    assert "R3" in text and "may be disputable" in text and "matches your policy" in text
    assert "| R3 |" in state["audit_table_markdown"]
    for s in state["draft"]["sentences"]:
        for cid in s["clause_ids"]:
            assert cid in state["clauses"]                          # every cited clause came from policy-kb


def test_approve_files_once_through_the_portal():
    c = Case("SET-01")
    run(c.start())
    text, sha = run(c.gate.get_pending_grievance(c.cfg))
    final = run(c.gate.approve_and_resume(c.cfg))
    assert final["outcome"] == "grievance_filed"
    assert final["submission"]["reference"].startswith("DRYRUN-") and final["submission"]["text_sha256"] == sha
    assert final["grievance_status"]["status"] == "dry_run"
    assert c.tk.log.count("file_grievance") == 1
    assert any(t.startswith("PortalSubmit: filed as DRYRUN-") for t in final["trace"])


def test_edit_rebinds_hash_and_token_before_filing():
    c = Case("SET-01", gate_secret="s3cret-gate-key")
    run(c.start())
    text, old_sha = run(c.gate.get_pending_grievance(c.cfg))
    edited = text + "\nI am happy to share any further documents."
    final = run(c.gate.approve_and_resume(c.cfg, edited_text=edited))
    assert final["outcome"] == "grievance_filed"
    new_sha = hashlib.sha256(edited.encode()).hexdigest()
    assert final["grievance"]["text_sha256"] == new_sha != old_sha
    assert final["approval_token"] == issue_token(new_sha, "s3cret-gate-key")
    assert next(iter(c.tk.filed.values()))["text"] == edited


def test_reject_ends_without_filing():
    c = Case("SET-01")
    run(c.start())
    final = run(c.gate.reject(c.cfg, "Not now."))
    assert final["outcome"] == "grievance_declined" and not final["human_approved"]
    assert "file_grievance" not in c.tk.log
    assert not run(c.gate.is_paused_for_approval(c.cfg))


def test_text_changed_after_approval_is_blocked():
    c = Case("SET-01")
    run(c.start())
    g = copy.deepcopy(run(c.values())["grievance"])
    g["text"] += " (changed behind the gate's back)"               # hash no longer matches the text
    run(c.graph.aupdate_state(c.cfg, {"grievance": g}))
    with pytest.raises(PermissionError, match="SHA-256"):
        run(c.gate.approve_and_resume(c.cfg))
    assert "file_grievance" not in c.tk.log


def test_portal_submit_refuses_without_approval_even_if_routed_there():
    c = Case("SET-01")
    run(c.start())
    # Pretend a bug routed past the gate without a decision: the node itself still refuses.
    run(c.graph.aupdate_state(c.cfg, {"route": "approved", "human_approved": False}, as_node="approval_gate"))
    with pytest.raises(PermissionError, match="not approved"):
        run(c.graph.ainvoke(None, c.cfg))
    assert "file_grievance" not in c.tk.log


def test_the_gate_is_a_step_of_its_own_in_the_history():
    c = Case("SET-01")
    run(c.start())
    snap = run(c.graph.aget_state(c.cfg))
    assert snap.next == ("approval_gate",)
    final = run(c.gate.reject(c.cfg, "Not now."))
    assert final["trace"][-1].startswith("ApprovalGate: rejected")


def test_wrong_hmac_token_is_refused_by_the_portal():
    c = Case("SET-01", gate_secret="server-secret")
    run(c.start())
    c.gate.gate_secret = "a-different-secret"                      # the gate and the portal disagree
    with pytest.raises(PermissionError, match="APPROVAL_REQUIRED"):
        run(c.gate.approve_and_resume(c.cfg))


def test_approve_when_not_paused_raises():
    c = Case("SET-02")
    run(c.start())
    with pytest.raises(RuntimeError):
        run(c.gate.approve_and_resume(c.cfg))


# --------------------------------------------------------------------------- clean path and questions


def test_clean_case_ends_with_no_grievance():
    c = Case("SET-02")
    state = run(c.start())
    assert state["outcome"] == "no_grievance"
    assert "grievance" not in state and not run(c.gate.is_paused_for_approval(c.cfg))
    assert "Nothing on this letter looks disputable" in state["explanation"]
    assert all(r["verdict"] == "matches_policy" for r in state["row_audits"].values())


def test_engine_question_pauses_and_answer_resumes():
    c = Case("SET-32")
    state = run(c.start())
    qs = run(c.gate.pending_questions(c.cfg))
    assert [q["question_id"] for q in qs] == ["Q-CONDITION-TYPE"]
    assert "row_audits" not in state                               # nothing audited before the answer
    final = run(c.gate.answer_questions(c.cfg, {"Q-CONDITION-TYPE": "illness"}))
    assert final["claim"]["condition_type"] == "illness"
    assert final["answers"] == {"Q-CONDITION-TYPE": "illness"}
    assert final["outcome"] == "no_grievance"


# --------------------------------------------------------------------------- critic loops and guards


def _disagreeing_audit(fx):
    """The critic's independent audit disagrees with the auditor on R3 (never happens with one engine)."""
    real = next(c["result"] for c in fx["calls"] if c["key"].startswith('["audit_settlement_letter"'))

    def audit(case, letter, hypothesis_ids=None):
        out = copy.deepcopy(real)
        for r in out["rows"]:
            if r["row_id"] == "R3":
                r["verdict"], r["policy_amount"], r["difference"] = "matches_policy", r["insurer_amount"], 0.0
        out["disputable_amount"] = 0.0
        return out
    return audit


def test_critic_retries_then_replans_then_guard_stops_the_loop():
    fx = load("SET-01")
    c = Case("SET-01", overrides={"audit_settlement_letter": _disagreeing_audit(fx)})
    state = run(c.start())
    trace = "\n".join(state["trace"])
    assert "audit review #1 FAILED -> auditor retry" in trace
    assert "audit review #2 FAILED -> replan" in trace
    assert "Supervisor: replan v2" in trace and state["plan"]["version"] == 2 and state["plan"]["replan_reason"]
    assert state["revision_count"] >= state["max_revisions"]          # the loop guard took over
    assert trace.count("SettlementAuditor: policy payable") == 3       # first run, retry, after replan
    assert "audit review #3 FAILED" in trace and state["revision_count"] == 3
    assert "Explainer:" in trace                                       # explains the critic's own audit
    assert run(c.gate.is_paused_for_approval(c.cfg)) is False          # R3 matches in the critic's audit
    assert state["outcome"] == "no_grievance"


def _forbidden_particulars(fx, phrase="you will get"):
    real = next(c["result"] for c in fx["calls"] if c["key"].startswith('["audit_settlement_letter"'))

    def audit(case, letter, hypothesis_ids=None):
        out = copy.deepcopy(real)
        out["rows"][0]["particulars"] += f" ({phrase} this back)"     # insurer text the explainer quotes
        return out
    return audit


def test_draft_failing_twice_is_blocked_and_never_shown():
    c = Case("SET-01", overrides={"audit_settlement_letter": _forbidden_particulars(load("SET-01"))})
    state = run(c.start())
    trace = "\n".join(state["trace"])
    assert "draft attempt 1 FAILED" in trace and "plain verdict table (fallback)" in trace
    assert "draft attempt 2 FAILED" in trace
    assert state["outcome"] == "critic_blocked" and "grievance" not in state
    assert {f["check"] for f in state["critic"]["failures"]} == {"forbidden_phrase"}


# --------------------------------------------------------------------------- early exits


def test_unreadable_page_takes_the_missing_document_edge():
    fx = load("SET-01")
    good = {c["key"]: c["result"] for c in fx["calls"] if c["key"].startswith('["get_document_text"')}

    def unreadable(case_id, document_id, pages=None):
        doc = copy.deepcopy(next(v for k, v in good.items() if document_id in k))
        doc["pages"][0]["ocr_status"] = "unavailable"
        return doc
    state = run(Case("SET-01", overrides={"get_document_text": unreadable}).start())
    assert state["outcome"] == "missing_document" and state["questions"][0]["question_id"] == "Q-DOCUMENT"
    assert "settlement" not in state


def test_missing_policy_asks_the_user():
    def no_policy(case_id):
        raise tool_error("get_policy", "POLICY_NOT_FOUND", "no schedule on record")
    state = run(Case("SET-01", overrides={"get_policy": no_policy}).start())
    assert state["outcome"] == "ask_user_for_policy" and state["route"] == "ask_user_to_confirm_policy"


def test_impossible_claim_goes_back_to_the_reader():
    def invalid(case):
        raise tool_error("expected_settlement", "INVALID_ARGUMENTS", "discharge is before admission")
    state = run(Case("SET-01", overrides={"expected_settlement": invalid}).start())
    assert state["outcome"] == "invalid_extraction" and state["route"] == "send_back_to_document_reader"


def test_lookalike_policy_number_is_replaced_and_flagged():
    c = Case("SET-01")
    c.fx["claim"] = {**c.fx["claim"], "policy_no": "АЅ-2025-100478"}  # Cyrillic А and Ѕ
    state = run(c.start())
    assert state["claim"]["policy_no"] == "AS-2025-100478"
    assert any("lookalike" in f for f in state["security_flags"])
    assert run(c.gate.is_paused_for_approval(c.cfg))


def test_no_extraction_and_no_extractor_stops():
    c = Case("SET-01")
    c.fx["claim"] = None
    state = run(c.start())
    assert state["outcome"] == "extraction_needed"


# --------------------------------------------------------------------------- memory, threads, time travel


def test_memory_remembers_the_audit_and_the_filed_grievance(tmp_path):
    store = MemoryStore(str(tmp_path / "memory.db"))
    store.for_user("u_test").grant_consent("test")
    c = Case("SET-01", memory_store=store, user_id="u_test")
    run(c.start())
    final = run(c.gate.approve_and_resume(c.cfg))
    mem = store.for_user("u_test")
    claim = mem.claim("AGI/HC/2526/004512")
    assert claim is not None and float(claim.disputable_amount) == SET01_DISPUTABLE
    g = mem.grievance(final["memory_grievance_id"])
    assert g.status == "filed" and g.reference_no == final["submission"]["reference"]
    assert g.text_sha256 == final["grievance"]["text_sha256"]
    again = Case("SET-02", memory_store=store, user_id="u_test")      # next session: memory is loaded
    state = run(again.start())
    assert state["memory"] and "memory:" in state["trace"][0]


def test_memory_stays_empty_without_consent(tmp_path):
    store = MemoryStore(str(tmp_path / "memory.db"))
    c = Case("SET-01", memory_store=store, user_id="u_noconsent")
    run(c.start())
    assert store.for_user("u_noconsent").claims() == []


def test_threads_are_isolated():
    c1, c2 = Case("SET-01"), Case("SET-02")
    run(c1.start())
    run(c2.start())
    assert run(c1.gate.is_paused_for_approval(c1.cfg)) and not run(c2.gate.is_paused_for_approval(c2.cfg))
    assert run(c1.values())["claim"]["claim_id"] != run(c2.values())["claim"]["claim_id"]


def test_time_travel_replays_from_a_checkpoint():
    c = Case("SET-02")
    run(c.start())

    async def history():
        return [h async for h in c.graph.aget_state_history(c.cfg)]
    snapshots = run(history())
    assert len(snapshots) > 6
    before_critic = next(h for h in snapshots if h.next == ("critic",))
    forked = run(c.graph.ainvoke(None, before_critic.config))         # re-run from that checkpoint
    assert forked["outcome"] == "no_grievance"
