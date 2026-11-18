"""Grievance agent, approval gate and portal submission: drafting, the gate's decisions, and every filing guard."""

from __future__ import annotations

import copy
import hashlib

import pytest
from claimclear_contracts.handoffs import GrievanceDraft
from claimclear_memory import MemoryStore

from claimclear_graph.agents.grievance import basis
from claimclear_graph.gateway import issue_token
from claimclear_graph.testing import tool_error

from conftest import Case, node_fn, run, states_before


@pytest.fixture(scope="module")
def st():
    return states_before("SET-01")


# --------------------------------------------------------------------------- drafting


def test_draft_covers_only_disputable_rows_with_a_valid_hash(st):
    fn, _ = node_fn("grievance_agent")
    out = run(fn(st["grievance_agent"]))
    g = GrievanceDraft.model_validate(out["grievance"])                # the contract re-checks the SHA-256
    assert g.row_ids == ["R3"] and out["route"] == "awaiting_approval" and out["human_approved"] is False
    listed = g.text.split("do not match my policy:")[1].split("The amount payable")[0]
    assert listed.strip().startswith("1. Proportionate deduction") and "\n2. " not in listed
    assert "Room rent above eligible limit" not in listed and "GST on room rent" not in listed   # R1, R2 match
    assert "₹8,522.86 may be disputable" in g.text and "Policyholder, policy AS-2025-100478" in g.text


def test_the_basis_names_the_charges_the_policy_excludes(st):
    fn, _ = node_fn("grievance_agent")
    text = run(fn(st["grievance_agent"]))["grievance"]["text"]
    for line in ("Laboratory investigations", "MRCP", "Pharmacy - inpatient medicines", "Laparoscopic clips"):
        assert line in text
    for line in ("Surgeon fee", "Anaesthetist fee", "Operation theatre"):          # those the cut may apply to
        assert line not in text.split("does not allow this deduction on:")[1]


def test_basis_falls_back_to_the_engines_reasoning_without_a_matching_method():
    row = {"method": "unknown", "matches": [], "explanation": "The engine's reasoning."}
    assert basis(row, {}, {}) == "The engine's reasoning."


def test_basis_without_policy_lines_lists_no_charges():
    row = {"method": "m1", "rule_ref": "r", "matches": [{"hypothesis_id": "m1", "title": "Some method", "line_ids": ["L1"]}]}
    assert basis(row, {"deductions": []}, {"lines": []}) == "How the insurer reached its figure: some method."


def test_no_disputable_row_means_no_grievance(st):
    la = copy.deepcopy(st["grievance_agent"]["letter_audit"])
    for r in la["rows"]:
        r["verdict"] = "matches_policy"
    fn, _ = node_fn("grievance_agent")
    out = run(fn({**st["grievance_agent"], "letter_audit": la}))
    assert out["outcome"] == "no_grievance" and "grievance" not in out


def test_a_draft_that_fails_the_checks_is_never_shown(st):
    la = copy.deepcopy(st["grievance_agent"]["letter_audit"])
    for r in la["rows"]:
        if r["row_id"] == "R3":
            r["particulars"] += " - you will get this back"            # insurer text containing a forbidden phrase
    fn, _ = node_fn("grievance_agent")
    out = run(fn({**st["grievance_agent"], "letter_audit": la}))
    assert out["outcome"] == "critic_blocked" and "grievance" not in out


def test_claim_id_falls_back_to_the_case_id(st):
    state = {**st["grievance_agent"], "claim": {**st["grievance_agent"]["claim"], "claim_id": ""}}
    fn, _ = node_fn("grievance_agent")
    assert run(fn(state))["grievance"]["claim_id"] == state["case_id"]


def test_memory_opens_a_draft_grievance_with_consent(st, tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    mem = store.for_user("u1")
    mem.grant_consent("test")
    from claimclear_graph.state import engine_case
    mem.remember_claim(engine_case(st["grievance_agent"]), st["grievance_agent"]["letter_audit"],
                       case_id=st["grievance_agent"]["case_id"], letter=st["grievance_agent"]["letter"])
    fn, _ = node_fn("grievance_agent", memory_store=store)
    out = run(fn({**st["grievance_agent"], "user_id": "u1"}))
    assert mem.grievance(out["memory_grievance_id"]).status == "draft"


def test_memory_refusal_does_not_block_the_draft(st, tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    store.for_user("u1").grant_consent("test")                          # no remembered claim: memory refuses
    fn, _ = node_fn("grievance_agent", memory_store=store)
    out = run(fn({**st["grievance_agent"], "user_id": "u1"}))
    assert out["grievance"] and out.get("memory_grievance_id") is None


# --------------------------------------------------------------------------- the approval gate (through the graph)


def test_an_empty_decision_is_a_rejection():
    c = Case("SET-01")
    run(c.start())
    from langgraph.types import Command
    final = run(c.graph.ainvoke(Command(resume={"decision": "maybe"}), c.cfg))
    assert final["outcome"] == "grievance_declined" and "file_grievance" not in c.tk.log


def test_reject_reason_is_recorded():
    c = Case("SET-01")
    run(c.start())
    final = run(c.gate.reject(c.cfg, "I'll call the insurer first."))
    assert final["trace"][-1] == "ApprovalGate: rejected: I'll call the insurer first."


def test_an_edit_identical_to_the_draft_is_not_a_new_version():
    c = Case("SET-01")
    run(c.start())
    text, sha = run(c.gate.get_pending_grievance(c.cfg))
    final = run(c.gate.approve_and_resume(c.cfg, edited_text=text))
    assert final["grievance"]["text_sha256"] == sha and "unchanged" in "\n".join(final["trace"])


def test_approving_twice_is_refused():
    c = Case("SET-01")
    run(c.start())
    run(c.gate.approve_and_resume(c.cfg))
    with pytest.raises(RuntimeError):
        run(c.gate.approve_and_resume(c.cfg))
    assert c.tk.log.count("file_grievance") == 1


# --------------------------------------------------------------------------- portal submission (the only write)


@pytest.fixture
def approved(st):
    g = run(node_fn("grievance_agent")[0](st["grievance_agent"]))["grievance"]
    return {**st["grievance_agent"], "grievance": g, "human_approved": True,
            "approval_token": issue_token(g["text_sha256"], "")}


def test_files_and_reads_back_the_status(approved):
    fn, tk = node_fn("portal_submit")
    out = run(fn(approved))
    assert out["outcome"] == "grievance_filed" and out["submission"]["reference"].startswith("DRYRUN-")
    assert out["grievance_status"]["status"] == "dry_run" and tk.log == ["file_grievance", "grievance_status"]


@pytest.mark.parametrize("change,message", [
    (lambda s: s.pop("grievance"), "no grievance draft"),
    (lambda s: s.update(human_approved=False), "has not approved"),
    (lambda s: s.update(approval_token=None), "no approval token"),
    (lambda s: s["grievance"].update(text=s["grievance"]["text"] + "!"), "SHA-256 differs"),
])
def test_every_guard_refuses_before_anything_is_sent(approved, change, message):
    state = copy.deepcopy(approved)
    change(state)
    fn, tk = node_fn("portal_submit")
    with pytest.raises((PermissionError, ValueError), match=message):
        run(fn(state))
    assert tk.log == []


def test_the_portal_checks_the_hmac_token(approved):
    fn, _ = node_fn("portal_submit", gate_secret="server-secret")       # the token was issued without a secret
    with pytest.raises(PermissionError, match="APPROVAL_REQUIRED"):
        run(fn(approved))
    good = {**approved, "approval_token": issue_token(approved["grievance"]["text_sha256"], "server-secret")}
    assert run(fn(good))["outcome"] == "grievance_filed"


def test_portal_outage_is_reported_as_not_filed(approved):
    def down(*a, **k):
        raise tool_error("file_grievance", "UPSTREAM_UNAVAILABLE")
    fn, _ = node_fn("portal_submit", overrides={"file_grievance": down}, retry_attempts=0)
    with pytest.raises(PermissionError, match="UPSTREAM_UNAVAILABLE"):
        run(fn(approved))


def test_filing_the_same_text_twice_returns_the_first_reference(approved):
    fn, tk = node_fn("portal_submit")
    first = run(fn(approved))
    second = run(fn(approved))
    assert first["submission"]["reference"] == second["submission"]["reference"] and second["submission"]["duplicate"]


def test_memory_moves_the_grievance_to_filed(approved, tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    mem = store.for_user("u1")
    mem.grant_consent("test")
    from claimclear_graph.state import engine_case
    mem.remember_claim(engine_case(approved), approved["letter_audit"], case_id=approved["case_id"], letter=approved["letter"])
    gid = mem.open_grievance(approved["grievance"]["claim_id"], ["R3"]).grievance_id
    fn, _ = node_fn("portal_submit", memory_store=store)
    out = run(fn({**approved, "user_id": "u1", "memory_grievance_id": gid}))
    g = mem.grievance(gid)
    assert g.status == "filed" and g.reference_no == out["submission"]["reference"]
    assert g.text_sha256 == hashlib.sha256(approved["grievance"]["text"].encode()).hexdigest()


def test_memory_errors_do_not_undo_a_filing(approved, tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    store.for_user("u1").grant_consent("test")
    fn, _ = node_fn("portal_submit", memory_store=store)
    out = run(fn({**approved, "user_id": "u1", "memory_grievance_id": "grv_does_not_exist"}))
    assert out["outcome"] == "grievance_filed"
