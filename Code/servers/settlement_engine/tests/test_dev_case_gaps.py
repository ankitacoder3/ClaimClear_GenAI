"""The gaps the gen-data development cases showed, each on a hand-worked case.

Expected figures are worked out by hand from the Arogya Sanjeevani wording (room 2% of sum insured up
to ₹5,000 a day, ICU 5% up to ₹10,000, cataract 25% up to ₹40,000 per eye, road ambulance ₹2,000 per
hospitalisation, 30 days before and 60 days after the stay, co-pay 5%), never from the engine's output.
"""

from decimal import Decimal

import pytest

from engine import (
    ConditionType,
    DeductionKind,
    RowKind,
    Status,
    Verdict,
    audit_letter,
    classify_row,
    compute_settlement,
)
from engine.categories import annexure_list, categorise, looks_non_payable
from engine.hypotheses import HYPOTHESES, CaseContext
from factories import claim, letter, line, past, policy, row


def rows_of(audit):
    return {r.row_id: r for r in audit.rows}


# --------------------------------------------------------------------------- 1. Annexure A item lists


@pytest.mark.parametrize("description, listed_in", [
    ("Gauze and cotton", "List III"),
    ("Eye kit and drape", "List III"),
    ("Urine bag", "List IV"),
    ("Registration charges", "List IV"),
    ("Mineral water", "List I"),
    ("Crepe bandage", "List I"),
    ("Nebuliser kit", "List I"),
    ("File opening charges", "List II"),
    ("Documentation charges", "List II"),
    ("Discharge procedure charges", "List II"),
    ("Admission kit", "List II"),
])
def test_annexure_items_are_not_paid_as_separate_lines(description, listed_in):
    assert annexure_list(description) == listed_in
    assert looks_non_payable(description, categorise(description)[0])


@pytest.mark.parametrize("description", [
    "Surgical consumables", "Consumables", "Pharmacy", "Platelet transfusion (SDP)", "Road ambulance",
    "Operation theatre charges", "Oxygen therapy",
])
def test_payable_lines_stay_payable(description):
    assert not looks_non_payable(description, categorise(description)[0])


def test_a_listed_item_no_longer_blocks_the_proportionate_deduction(rules):
    # SI 1,50,000: room cap 3,000. Room 3 days at 4,000. Mineral water used to be an unknown line, so the
    # engine asked whether the hospital prices it by room type instead of working the claim out.
    c = claim([line("L01", "Private room", 12000, qty=3, rate=4000),
               line("L02", "Surgeon fee", 20000),
               line("L03", "Mineral water", 160)])
    r = compute_settlement(c, policy(si=150000), rules)
    assert r.status == Status.COMPUTED and not r.questions
    assert r.deduction(DeductionKind.NON_PAYABLE).amount == Decimal("160.00")
    assert r.deduction(DeductionKind.ROOM_RENT_EXCESS).amount == Decimal("3000.00")    # 3 x (4,000 - 3,000)
    assert r.deduction(DeductionKind.PROPORTIONATE).amount == Decimal("5000.00")       # 20,000 x 3,000 / 12,000
    assert r.payable_amount == Decimal("22800.00")                                     # (32,160 - 8,160) x 95%
    assert "Annexure A List I" in r.deduction(DeductionKind.NON_PAYABLE).description
    assert not any("not recognised" in w for w in r.warnings)


# --------------------------------------------------------------------------- 2. calling out unexplained deductions


def test_a_deduction_the_policy_does_not_allow_is_called_out_even_without_the_insurers_method(rules):
    # SI 2,50,000: room cap 5,000. Twin sharing at 4,800 is under it, so no proportionate deduction is due.
    c = claim([line("L01", "Deluxe twin sharing - room rent", 9600, qty=2, rate=4800),
               line("L02", "Surgeon fee", 33750),
               line("L03", "OT charges", 16150)])
    lt = letter([row("R1", "Proportionate deduction (room category above eligibility)", 13417)],
                claimed=59500, paid=43783)
    r = rows_of(audit_letter(lt, c, policy(si=250000), rules))["R1"]
    assert r.verdict == Verdict.DOES_NOT_MATCH_POLICY and r.method is None
    assert r.policy_amount == Decimal("0.00") and r.difference == Decimal("13417.00")
    assert r.questions[0].question_id == "Q-BREAKDOWN-R1"


def test_a_deduction_below_the_policy_figure_is_still_not_verifiable(rules):
    # SI 1,50,000: room cap 3,000; 3 days at 4,000 -> 3,000 above the cap. ₹1,000 is no known method.
    c = claim([line("L01", "Private room", 12000, qty=3, rate=4000), line("L02", "Surgeon fee", 20000)])
    lt = letter([row("R1", "Room rent above limit", 1000)], claimed=32000, paid=29450)
    assert rows_of(audit_letter(lt, c, policy(si=150000), rules))["R1"].verdict == Verdict.NOT_VERIFIABLE


# --------------------------------------------------------------------------- 3. missing rules


def test_road_ambulance_is_paid_up_to_its_limit(rules):
    c = claim([line("L01", "Road ambulance", 2800), line("L02", "Surgeon fee", 10000)])
    r = compute_settlement(c, policy(), rules)
    assert r.deduction(DeductionKind.AMBULANCE_LIMIT).amount == Decimal("800.00")      # 2,800 - 2,000
    lt = letter([row("R1", "Ambulance charges above limit", 800)], claimed=12800, paid=11400)
    assert rows_of(audit_letter(lt, c, policy(), rules))["R1"].verdict == Verdict.MATCHES_POLICY
    under = compute_settlement(claim([line("L01", "Road ambulance", 1500)]), policy(), rules)
    assert under.deduction(DeductionKind.AMBULANCE_LIMIT) is None


def test_bills_outside_the_pre_and_post_hospitalisation_days(rules):
    # Admitted 19 Jan 2026, discharged 22 Jan 2026: cover runs from 20 Dec 2025 to 23 Mar 2026.
    c = claim([line("L01", "Surgeon fee", 10000),
               line("L02", "Ultrasound abdomen", 1800, date="2025-12-19"),     # 31 days before: outside
               line("L03", "Fever panel", 900, date="2025-12-20"),             # 30 days before: inside
               line("L04", "Follow-up blood count", 650, date="2026-03-23"),   # 60 days after: inside
               line("L05", "Multivitamin tonic", 480, date="2026-04-07")])     # 75 days after: outside
    r = compute_settlement(c, policy(), rules)
    outside = {d.line_ids[0]: (d.amount, d.rule_ref) for d in r.deductions
               if d.kind == DeductionKind.OUTSIDE_COVER_WINDOW}
    assert outside == {"L02": (Decimal("1800.00"), "pre_hospitalisation"),
                       "L05": (Decimal("480.00"), "post_hospitalisation")}
    lt = letter([row("R1", "Multivitamin tonic - outside post-hospitalisation period (75 days)", 480)],
                claimed=13830, paid=12682)
    assert rows_of(audit_letter(lt, c, policy(), rules))["R1"].verdict == Verdict.MATCHES_POLICY


# --------------------------------------------------------------------------- 4. matching rows to the right lines


def test_each_row_is_measured_against_the_lines_it_names(rules):
    c = claim([line("L01", "Pharmacy", 6950), line("L02", "Crepe bandage", 500),
               line("L03", "Registration charges", 520), line("L04", "Platelet transfusion (SDP)", 10100)])
    lt = letter([row("R1", "Crepe bandage - List I (not payable)", 500),
                 row("R2", "Registration charges - List IV (part of cost of treatment)", 520),
                 row("R3", "Platelet transfusion (SDP) - Blood products not payable", 10100),
                 row("R4", "Pharmacy items not payable as per annexure", 4300)],
                claimed=18070, paid=2650)
    r = rows_of(audit_letter(lt, c, policy(), rules))
    assert r["R1"].verdict == Verdict.MATCHES_POLICY and r["R1"].policy_amount == Decimal("500.00")
    assert r["R2"].verdict == Verdict.MATCHES_POLICY and r["R2"].policy_amount == Decimal("520.00")
    # Blood is payable (wording 4.1(iv)) and on no Annexure A list: the row is measured against its own line
    assert r["R3"].verdict == Verdict.DOES_NOT_MATCH_POLICY and r["R3"].policy_amount == Decimal("0.00")
    assert r["R3"].method == "nonpay_payable_item_listed"
    # part of a line that groups many items: the insurer's item list is needed first
    assert r["R4"].verdict == Verdict.NOT_VERIFIABLE and r["R4"].questions[0].question_id == "Q-ITEMS-R4"


@pytest.mark.parametrize("particulars, kind", [
    ("File opening charges - List II (part of room charges)", RowKind.NON_PAYABLE),
    ("Urine bag - List IV (part of cost of treatment)", RowKind.NON_PAYABLE),
    ("Room / ICU rent above eligible limit", RowKind.ROOM_AND_ICU),
    ("Multivitamin tonic - outside post-hospitalisation period (75 days)", RowKind.COVER_WINDOW),
    ("Ambulance charges above limit", RowKind.AMBULANCE),
    ("Date of admission falls outside the policy period", RowKind.POLICY_PERIOD),
    ("This hospitalisation was already settled under claim CLM-1. The same expenses cannot be paid twice.",
     RowKind.ALREADY_PAID),
    ("Amount not supported by the itemised charges", RowKind.UNITEMISED),
])
def test_row_kinds(particulars, kind):
    assert classify_row(particulars) == kind


def test_a_room_and_icu_row_counts_both_caps(rules):
    # SI 2,50,000: room cap 5,000 (2%), ICU cap 10,000 (5% is 12,500). Room 3 days at 6,500, ICU 1 day at 12,000.
    c = claim([line("L01", "Surgical ICU - room rent", 12000, qty=1, rate=12000),
               line("L02", "Single private AC - room rent", 19500, qty=3, rate=6500),
               line("L03", "Surgeon fee", 36800)], admission="2026-01-18", discharge="2026-01-22")
    lt = letter([row("R1", "Room / ICU rent above eligible limit", 6500)], claimed=68300, paid=58710)
    r = rows_of(audit_letter(lt, c, policy(si=250000), rules))["R1"]
    assert r.verdict == Verdict.MATCHES_POLICY and r.policy_amount == Decimal("6500.00")   # 3 x 1,500 + 2,000


# --------------------------------------------------------------------------- 5. whole-claim checks


def test_a_hospitalisation_already_settled_is_not_paid_again(rules):
    history = [past("CLM-1", "2026-01-19", 80123, diagnosis="Acute appendicitis")]
    c = claim([line("L01", "Surgeon fee", 25000)], diagnosis="Acute appendicitis")
    r = compute_settlement(c, policy(), rules, history)
    assert r.status == Status.NOT_ADMISSIBLE
    assert r.deduction(DeductionKind.ALREADY_SETTLED).amount == Decimal("25000.00")
    lt = letter([], claimed=25000, paid=0, letter_type="rejection",
                rejection_reason="This hospitalisation was already settled under claim CLM-1. "
                                 "The same expenses cannot be paid twice.")
    assert rows_of(audit_letter(lt, c, policy(), rules, history))["REJECTION"].verdict == Verdict.MATCHES_POLICY
    # without the earlier claim on record the engine can't disprove the rejection: it is not called wrong
    assert rows_of(audit_letter(lt, c, policy(), rules))["REJECTION"].verdict == Verdict.NOT_VERIFIABLE
    # another stay, or a pharmacy bill for the same stay, is a separate expense
    assert compute_settlement(claim([line("L01", "Surgeon fee", 25000)], admission="2026-03-02",
                                    discharge="2026-03-04"), policy(), rules, history).status == Status.COMPUTED
    pharmacy = claim([line("L01", "Medicines", 900)], discharge=None, diagnosis="Acute appendicitis")
    assert compute_settlement(pharmacy, policy(), rules, history).deduction(DeductionKind.ALREADY_SETTLED) is None


def test_a_rejection_for_an_admission_inside_the_policy_period_does_not_match(rules):
    c = claim([line("L01", "Surgeon fee", 25000)])               # admitted 19 Jan 2026; policy to 14 Jul 2026
    lt = letter([], claimed=25000, paid=0, letter_type="rejection",
                rejection_reason="Date of admission falls outside the policy period")
    r = rows_of(audit_letter(lt, c, policy(), rules))["REJECTION"]
    assert r.verdict == Verdict.DOES_NOT_MATCH_POLICY and r.policy_amount == Decimal("0.00")


def test_the_waiting_period_list_comes_from_the_condition(rules):
    # 29 full months of cover (1 Mar 2024 to 20 Aug 2026): past the 24-month list, inside the 36-month one
    p = policy(si=500000, start="2026-03-01", end="2027-02-28", inception="2024-03-01")
    hernia = claim([line("L01", "Surgeon fee", 33750)], admission="2026-08-20", discharge="2026-08-22",
                   diagnosis="Right inguinal hernia", procedure="Laparoscopic TEP hernioplasty with mesh")
    r = compute_settlement(hernia, p, rules)
    assert r.status == Status.COMPUTED and r.deduction(DeductionKind.WAITING_PERIOD) is None
    assert r.fact("F-WAITING").inputs["condition_type"] == ConditionType.LISTED_ILLNESS_SHORT.value
    knee = claim([line("L01", "Surgeon fee", 150000)], admission="2026-08-20", discharge="2026-08-25",
                 diagnosis="Age-related osteoarthritis, right knee", procedure="Total knee replacement")
    assert compute_settlement(knee, p, rules).status == Status.NOT_ADMISSIBLE


def test_an_amount_no_bill_line_supports_matches_when_taken_out(rules):
    c = claim([line("L01", "Surgeon fee", 10000)], printed_total=40000)
    lt = letter([row("R1", "Amount not supported by the itemised charges", 30000)], claimed=40000, paid=9500)
    r = rows_of(audit_letter(lt, c, policy(), rules))["R1"]
    assert r.verdict == Verdict.MATCHES_POLICY and r.policy_amount == Decimal("30000.00")


# --------------------------------------------------------------------------- an insurer method: cataract


def test_cataract_limit_shared_between_eyes(rules):
    # SI 1,50,000: 37,500 per eye. Left eye earlier this year: 28,500 paid (30,000 admitted before co-pay).
    # Right eye now: 54,700. The policy takes 54,700 - 37,500 = 17,200; an insurer that nets the left eye
    # against the right eye's limit takes 54,700 - (37,500 - 30,000) = 47,200.
    p = policy(si=150000, start="2025-10-01", end="2026-09-30", inception="2023-10-01")
    history = [past("CLM-0", "2026-02-12", 28500, diagnosis="Senile cataract, left eye")]
    c = claim([line("L01", "Cataract surgery - right eye", 54700)], admission="2026-06-10", discharge="2026-06-10",
              diagnosis="Senile cataract, right eye")
    r = compute_settlement(c, p, rules, history)
    assert r.deduction(DeductionKind.CATARACT_LIMIT).amount == Decimal("17200.00")
    lt = letter([row("R1", "Cataract limit (right eye), balance available INR 7,500.00", 47200)],
                claimed=54700, paid=7125, copay=375)
    called_out = rows_of(audit_letter(lt, c, p, rules, history))["R1"]
    assert called_out.verdict == Verdict.DOES_NOT_MATCH_POLICY and called_out.method == "cataract_shared_between_eyes"
    # with no claim history the engine can't tell whether earlier claims explain the figure
    no_history = rows_of(audit_letter(lt, c, p, rules))["R1"]
    assert no_history.verdict == Verdict.NOT_VERIFIABLE and no_history.questions[0].question_id == "Q-HISTORY-R1"
    ctx = CaseContext(c, p, rules, history, r)
    assert [x.amount for x in HYPOTHESES["cataract_shared_between_eyes"].run(ctx)] == [Decimal("45700.00"),
                                                                                      Decimal("47200.00")]


# --------------------------------------------------------------------------- every rule has a clause to cite


def test_every_rule_ref_is_in_the_go_digit_rule_map():
    """policy-kb's clauses_for_rule fails on a rule_ref its map doesn't know, so a new rule needs a clause."""
    import json
    from pathlib import Path

    from engine import RULE_REFS

    path = Path(__file__).resolve().parents[2] / "policy_kb" / "policy_kb" / "rule_maps" / "GODHLIP24179V022324.json"
    assert set(RULE_REFS) == set(json.loads(path.read_text(encoding="utf-8"))["rules"])
