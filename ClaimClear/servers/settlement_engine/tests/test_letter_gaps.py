"""Settlement letters SET-06 to SET-35 that the first version of the engine got wrong or could not run.

Expected figures are the dataset's hand-checked answer key (Member 1), never the engine's own output.
"""

from decimal import Decimal

from engine import Verdict, audit_letter, compute_settlement
from engine.dataset import answer_key, load_case, load_letter
from factories import claim, letter, line, policy, row


def audit(doc_id, dataset_dir):
    case = load_case(doc_id, dataset_dir)
    return audit_letter(load_letter(doc_id, dataset_dir), case.claim, case.policy, case.rules, case.history)


def rows_of(a):
    return {r.row_id: r for r in a.rows}


def disputable_as_key(doc_id, dataset_dir):
    return Decimal(str(answer_key(doc_id, dataset_dir)["disputable_amount"])).quantize(Decimal("0.01"))


# --------------------------------------------------------------------------- non-payable items (SET-16)


def test_unmarked_bill_lines_follow_the_non_payable_list(dataset_dir):
    """A bill can only mark a line non-payable; an unmarked line is decided by the policy's list."""
    case = load_case("SET-16", dataset_dir)
    flags = {v.description: v.non_payable for v in compute_settlement(case.claim, case.policy, case.rules).lines}
    assert flags["Patient care kit"] and flags["Sterile gloves"] and flags["N95 masks"]
    assert not flags["Operation theatre charges"] and not flags["Surgeon fee - laparoscopic appendectomy"]


def test_rows_that_split_the_non_payable_items_each_match(dataset_dir):
    a = audit("SET-16", dataset_dir)
    r = rows_of(a)
    assert r["R3"].verdict == Verdict.MATCHES_POLICY and r["R3"].policy_amount == Decimal("32220.00")
    assert r["R4"].verdict == Verdict.MATCHES_POLICY and r["R4"].method == "non_payable_named_items"
    assert a.disputable_amount == disputable_as_key("SET-16", dataset_dir)


def test_named_items_only_counts_the_items_the_row_names(rules):
    c = claim([line("L01", "Surgeon fee", 20000), line("L02", "Sterile gloves", 500),
               line("L03", "Admission kit", 1200)])
    lt = letter([row("R1", "Non-payable: sterile gloves", 500), row("R2", "Admission kit", 1200, reason="Listed as non-payable under the policy")],
                claimed=21700, paid=19000)
    r = rows_of(audit_letter(lt, c, policy(si=500000), rules))
    assert r["R1"].verdict == Verdict.MATCHES_POLICY and r["R1"].policy_amount == Decimal("500.00")
    assert r["R2"].verdict == Verdict.MATCHES_POLICY and r["R2"].policy_amount == Decimal("1200.00")


# --------------------------------------------------------------------------- charges billed twice (SET-16, SET-35)


def dated(line_id, description, amount, day, qty=1):
    from dataclasses import replace
    from engine.money import to_date
    return replace(line(line_id, description, amount, qty=qty), date=to_date(day))


def test_the_same_service_twice_on_the_same_day_is_paid_once(rules):
    c = claim([line("L01", "Surgeon fee - laparoscopic appendectomy", 48000),
               line("L02", "Surgeon charges - lap appendectomy", 48000),
               line("L03", "Physician visits", 9000, qty=6), line("L04", "Physician rounds", 9000, qty=6)])
    r = compute_settlement(c, policy(si=500000), rules)
    dups = [d for d in r.deductions if d.kind.value == "duplicate_line"]
    assert [d.line_ids for d in dups] == [("L02",), ("L04",)]
    assert {d.rule_ref for d in dups} == {"expenses_actually_incurred"}


def test_a_daily_charge_on_another_day_is_not_a_duplicate(rules):
    c = claim([dated("L01", "Oxygen therapy", 950, "2026-01-19"), dated("L02", "Oxygen therapy", 950, "2026-01-20"),
               dated("L03", "Oxygen therapy", 900, "2026-01-20"), dated("L04", "Nebulisation", 950, "2026-01-19")])
    r = compute_settlement(c, policy(si=500000), rules)
    assert not [d for d in r.deductions if d.kind.value == "duplicate_line"]


def test_double_billed_visits_are_removed_as_the_answer_key_says(dataset_dir):
    a = audit("SET-35", dataset_dir)
    key = answer_key("SET-35", dataset_dir)
    assert rows_of(a)["R1"].verdict == Verdict.MATCHES_POLICY
    assert a.policy_payable == Decimal(str(key["expected_payable"])).quantize(Decimal("0.01"))
    assert a.disputable_amount == disputable_as_key("SET-35", dataset_dir)


def test_the_duplicate_surgeon_fee_row_matches(dataset_dir):
    r = rows_of(audit("SET-16", dataset_dir))["R1"]
    assert r.kind.value == "duplicate" and r.verdict == Verdict.MATCHES_POLICY
    assert r.policy_amount == Decimal("48000.00")


# --------------------------------------------------------------------------- daily charges treated as duplicates (SET-24)


def test_daily_charges_removed_as_duplicates_do_not_match(dataset_dir):
    a = audit("SET-24", dataset_dir)
    r = rows_of(a)
    for row_id, amount in (("R1", "2850.00"), ("R2", "6600.00")):
        assert r[row_id].kind.value == "duplicate" and r[row_id].verdict == Verdict.DOES_NOT_MATCH_POLICY
        assert r[row_id].method == "duplicate_daily_repeats" and r[row_id].policy_amount == Decimal("0.00")
        assert r[row_id].insurer_amount == Decimal(amount)
    assert a.disputable_amount == disputable_as_key("SET-24", dataset_dir)


def test_daily_repeats_only_count_the_service_the_row_names(rules):
    c = claim([dated("L01", "Oxygen therapy", 950, "2026-01-19"), dated("L02", "Oxygen therapy", 950, "2026-01-20"),
               dated("L03", "Physician round", 1100, "2026-01-19"), dated("L04", "Physician round", 1100, "2026-01-20")])
    lt = letter([row("R1", "Duplicate entries: oxygen therapy", 950)], claimed=4100, paid=3000)
    r = rows_of(audit_letter(lt, c, policy(si=500000), rules))["R1"]
    assert r.verdict == Verdict.DOES_NOT_MATCH_POLICY and r.method == "duplicate_daily_repeats"


# --------------------------------------------------------------------------- bills with no admission date (SET-06, SET-22, SET-25)


def test_a_bill_without_an_admission_date_asks_for_it(rules):
    from dataclasses import replace
    c = replace(claim([line("L01", "Pharmacy - oral medicines", 1100)]), admission=None, discharge=None)
    r = compute_settlement(c, policy(si=500000), rules)
    assert r.status.value == "needs_information" and r.payable_amount is None
    assert [q.question_id for q in r.questions] == ["Q-ADMISSION"]


def test_pharmacy_and_post_hospitalisation_letters_no_longer_crash(dataset_dir):
    for doc_id in ("SET-06", "SET-22", "SET-25"):
        a = audit(doc_id, dataset_dir)
        assert a.settlement.status.value == "needs_information", doc_id
        assert "Q-ADMISSION" in {q.question_id for q in a.questions}, doc_id
        assert all(r.verdict == Verdict.NOT_VERIFIABLE for r in a.rows), doc_id


def test_the_mcp_tool_accepts_a_claim_without_dates(dataset_dir):
    import asyncio
    from mcp import Client
    from mcp_server import create_server
    from mcp_server.convert import case_payload
    payload = case_payload(load_case("SET-06", dataset_dir))
    assert payload["claim"]["admission"] is None

    async def go():
        async with Client(create_server()) as client:
            return await client.call_tool("expected_settlement", {"case": payload})
    out = asyncio.run(go()).structured_content
    assert out["status"] == "needs_information" and out["questions"][0]["question_id"] == "Q-ADMISSION"


# --------------------------------------------------------------------------- look-alike policy numbers (SET-21)


def test_lookalike_characters_map_to_the_filed_policy_number():
    from engine import canonical_policy_no, has_lookalikes, same_policy
    assert canonical_policy_no("АЅ-2026-101944") == "AS-2026-101944"          # Cyrillic A and S
    assert canonical_policy_no("ＡＳ–2026 – 101944") == "AS-2026-101944"       # full width, en dashes, spaces
    assert has_lookalikes("АЅ-2026-101944") and not has_lookalikes("AS-2026-101944")
    assert same_policy("as-2026-101944", "AS-2026-101944") and not same_policy("AS-2026-101945", "AS-2026-101944")


def test_a_bill_with_lookalike_policy_number_is_matched_and_flagged(dataset_dir):
    a = audit("SET-21", dataset_dir)
    key = answer_key("SET-21", dataset_dir)
    assert a.policy_payable == Decimal(str(key["expected_payable"])).quantize(Decimal("0.01"))
    assert a.disputable_amount == disputable_as_key("SET-21", dataset_dir)
    assert any("look-alike" in w for w in a.settlement.warnings)


def test_the_mcp_tool_takes_only_plain_policy_numbers(dataset_dir):
    """Over MCP the agent passes get_policy's number; a printed look-alike is refused by the schema."""
    import asyncio
    import json
    from mcp import Client
    from mcp_server import create_server
    from mcp_server.convert import case_payload
    payload = case_payload(load_case("SET-21", dataset_dir))

    async def go(p):
        async with Client(create_server()) as client:
            return await client.call_tool("expected_settlement", {"case": p})
    assert asyncio.run(go(payload)).is_error                      # 'АЅ-2026-101944' fails the ID pattern
    payload["claim"]["policy_no"] = payload["policy"]["policy_no"]
    assert not asyncio.run(go(payload)).is_error
    payload["claim"]["policy_no"] = "AS-2026-999999"
    out = asyncio.run(go(payload))
    text = out.content[0].text
    assert out.is_error and json.loads(text[text.index("{"):])["code"] == "POLICY_MISMATCH"


# --------------------------------------------------------------------------- one stay on two invoices (SET-20)


def test_a_stay_billed_on_two_invoices_is_one_claim(dataset_dir):
    """ADV-04 bills one knee replacement on two invoices (198,900 + 142,600). Both are the same stay (same IP
    number and dates), so the claim adds them up; the answer key's policy payable is 95% of 341,500 = 324,425."""
    case = load_case("SET-20", dataset_dir)
    assert len(case.claim.bill_numbers) == 2 and case.claim.printed_total == Decimal("341500")
    assert sum(line.amount for line in case.claim.lines) == Decimal("341500")
    s = compute_settlement(case.claim, case.policy, case.rules, case.history)
    assert s.payable_amount == Decimal(str(answer_key("SET-20", dataset_dir)["expected_payable"])) == Decimal("324425")
    assert any(f.inputs.get("code") == "split_invoices" for f in s.facts if f.kind == "integrity")
    a = audit("SET-20", dataset_dir)
    assert a.policy_payable == a.insurer_paid == Decimal("324425") and a.gap == 0 and a.disputable_amount == 0


def test_only_invoices_of_the_same_stay_are_added_up():
    from engine.dataset import claim_from_invoices

    def inv(no, ip, total, admission="2026-09-14"):
        return {"invoice_no": no, "ip_no": ip, "policy_no": "P-TEST", "admission": admission, "discharge": "2026-09-19",
                "printed_total": total, "line_items": [{"description": "Surgeon fee", "printed_amount": total}]}

    one = claim_from_invoices([inv("A-1", "IP/7", 1000)], "C")
    assert one.bill_numbers == ("A-1",) and len(one.lines) == 1
    two = claim_from_invoices([inv("A-1", "IP/7", 1000), inv("A-2", "ip/7 ", 500), inv("B-1", "IP/9", 900)], "C")
    assert two.bill_numbers == ("A-1", "A-2") and [l.line_id for l in two.lines] == ["L01", "L02"]
    assert two.printed_total == Decimal("1500")               # B-1 is another stay: a separate claim
