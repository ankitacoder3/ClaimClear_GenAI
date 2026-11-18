"""Each hypothesis on a hand-worked case. Expected figures are worked out by hand."""

from decimal import Decimal

import pytest

from engine import HYPOTHESES, CaseContext, ConditionType, RowKind, compute_settlement, list_hypotheses
from factories import claim, letter, line, past, policy, row, worked_example_lines


def ctx_for(c, p, rules, history=(), lt=None):
    history = list(history)
    return CaseContext(c, p, rules, history, compute_settlement(c, p, rules, history), lt)


def amounts(hid, ctx):
    return [c.amount for c in HYPOTHESES[hid].run(ctx)]


# --- the registry ----------------------------------------------------------------------


def test_one_correct_hypothesis_per_kind():
    """One policy-correct method for the whole row; a kind may add one for the items a row names, and the two
    rejection-evidence hypotheses (engine/integrity.py) confirm a whole-claim rejection. ``not_genuine`` rows have no
    policy figure of their own: only the evidence can confirm them."""
    from engine.hypotheses import REJECTION_EVIDENCE
    for kind in RowKind:
        correct = [h.hypothesis_id for h in list_hypotheses(kind) if h.correct]
        whole = [i for i in correct if i == f"{kind.value}_policy"]
        assert len(whole) == (0 if kind in (RowKind.UNSPECIFIED, RowKind.NOT_GENUINE) else 1), kind
        assert all(i.endswith("_named_items") or i in REJECTION_EVIDENCE for i in set(correct) - set(whole)), kind


def test_every_hypothesis_is_documented():
    for h in HYPOTHESES.values():
        assert h.title and h.description and h.hypothesis_id == h.hypothesis_id.lower()


def test_list_hypotheses_filters_by_kind():
    assert {h.kind for h in list_hypotheses(RowKind.PROPORTIONATE)} == {RowKind.PROPORTIONATE}
    assert list_hypotheses(RowKind.PROPORTIONATE)[0].correct


def test_only_copay_on_insurer_base_is_method_only():
    assert [h.hypothesis_id for h in HYPOTHESES.values() if h.method_only] == ["copay_on_insurer_base"]


# --- room and ICU ----------------------------------------------------------------------


def test_room_cap_pct_only(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(si=300000), rules)
    assert amounts("room_cap_pct_only", ctx) == [Decimal("3000.00")]   # 3 x (7,000 - 6,000)


def test_room_cap_max_only(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(si=200000), rules)
    assert amounts("room_rent_policy", ctx) == [Decimal("9000.00")]    # cap 4,000
    assert amounts("room_cap_max_only", ctx) == [Decimal("6000.00")]   # cap 5,000


def test_room_days_incl_discharge(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    assert amounts("room_days_incl_discharge", ctx) == [Decimal("8000.00")]


def test_room_gst_on_full_room(rules):
    ctx = ctx_for(claim([line("L01", "Private room", 21000, qty=3, rate=7000, gst=5)]), policy(), rules)
    assert amounts("room_gst_policy", ctx) == [Decimal("300.00")]
    assert amounts("room_gst_on_full_room", ctx) == [Decimal("1050.00")]


def test_icu_room_cap_used(rules):
    ctx = ctx_for(claim([line("L01", "ICU charges", 19000, qty=2, rate=9500)]), policy(si=400000), rules)
    assert amounts("icu_policy", ctx) == [Decimal("0")]
    assert amounts("icu_room_cap_used", ctx) == [Decimal("9000.00")]


# --- proportionate deduction ------------------------------------------------------------


@pytest.mark.parametrize("hid, expected", [
    ("proportionate_policy", "21400.00"),
    ("prop_on_all_lines", "30371.43"),       # 1,06,300 x 2/7
    ("prop_incl_pharmacy", "25085.71"),      # (74,900 + 12,900) x 2/7
    ("prop_incl_diagnostics", "25314.29"),   # (74,900 + 7,200 + 6,500) x 2/7
    ("prop_incl_implants", "22771.43"),      # (74,900 + 4,800) x 2/7
    ("prop_on_whole_bill", "36371.43"),      # 1,27,300 x 2/7
    ("prop_round_each_line", "21401.00"),    # 1,286 + 9,143 + 3,143 + 6,286 + 1,543
])
def test_proportionate_variants_on_worked_example(rules, hid, expected):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    assert amounts(hid, ctx) == [Decimal(expected)]


def test_proportionate_variants_silent_when_room_within_cap(rules):
    ctx = ctx_for(claim(worked_example_lines(room_rate=4500)), policy(), rules)
    assert amounts("prop_on_all_lines", ctx) == []


def test_prop_incl_non_payable(rules):
    lines = worked_example_lines() + [line("L11", "Consumables - gloves, masks", 3500, non_payable=True)]
    ctx = ctx_for(claim(lines), policy(), rules)
    assert amounts("prop_incl_non_payable", ctx) == [Decimal("31371.43")]   # (1,06,300 + 3,500) x 2/7


# --- non-payable ------------------------------------------------------------------------


def test_nonpay_payable_item_listed_tries_each_line(rules):
    c = claim([line("L01", "Surgeon fee", 20000), line("L02", "USG abdomen", 2400),
               line("L03", "Consumables - gloves, masks", 3360, non_payable=True)])
    ctx = ctx_for(c, policy(si=500000), rules)
    assert sorted(amounts("nonpay_payable_item_listed", ctx)) == [Decimal("5760.00"), Decimal("23360.00")]


# --- cataract ---------------------------------------------------------------------------


def _cat(amount, admission="2026-02-06"):
    return claim([line("L01", "Phacoemulsification package - right eye", amount)], admission=admission,
                 discharge=admission, diagnosis="Senile cataract, right eye")


CAT_POLICY = dict(start="2025-10-01", end="2026-09-30", inception="2021-10-01")


def test_cataract_15pct_si(rules):
    ctx = ctx_for(_cat(38500), policy(si=200000, **CAT_POLICY), rules)
    assert amounts("cataract_policy", ctx) == [Decimal("0")]
    assert amounts("cataract_15pct_si", ctx) == [Decimal("8500.00")]


def test_cataract_pct_and_max_only(rules):
    ctx = ctx_for(_cat(45000), policy(si=100000, **CAT_POLICY), rules)
    assert amounts("cataract_policy", ctx) == [Decimal("20000.00")]     # limit 25,000
    assert amounts("cataract_max_only", ctx) == [Decimal("5000.00")]    # limit 40,000
    assert amounts("cataract_pct_only", ctx) == [Decimal("20000.00")]   # same as the policy here


def test_cataract_mixes_policy_years(rules):
    history = [past("H1", "2025-03-01", 30000, diagnosis="Cataract, right eye")]   # previous policy year
    ctx = ctx_for(_cat(20000), policy(si=200000, **CAT_POLICY), rules, history)
    assert amounts("cataract_policy", ctx) == [Decimal("0")]
    assert amounts("cataract_mixes_policy_years", ctx) == [Decimal("10000.00")]


# --- co-pay -----------------------------------------------------------------------------


def test_copay_hypotheses_use_the_insurers_base(rules):
    c = claim(worked_example_lines())
    lt = letter([row("R1", "Room rent", 6000), row("R2", "Proportionate", 30371.43)], 127300, 86382.14, 4546.43)
    ctx = ctx_for(c, policy(), rules, lt=lt)
    assert amounts("copay_policy", ctx) == [Decimal("4995.00")]
    assert amounts("copay_on_insurer_base", ctx) == [Decimal("4546.43")]   # 5% of 90,928.57
    assert amounts("copay_on_claimed", ctx) == [Decimal("6365.00")]
    assert amounts("copay_twice", ctx) == [Decimal("8865.54")]             # 9.75% of 90,928.57 = 8,865.5356
    assert amounts("copay_double_rate", ctx) == [Decimal("9092.86")]


def test_copay_insurer_base_needs_a_letter(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    assert amounts("copay_on_insurer_base", ctx) == []


# --- waiting periods and sum insured ----------------------------------------------------


def test_waiting_from_renewal(rules):
    p = policy(si=500000, start="2026-02-01", end="2027-01-31", inception="2022-02-01")
    c = claim([line("L01", "Surgeon fee - knee arthroscopy", 29000)], admission="2026-03-25", discharge="2026-03-27",
              diagnosis="Medial meniscus tear, left knee")
    ctx = ctx_for(c, p, rules)
    assert amounts("waiting_period_policy", ctx) == [Decimal("0")]
    assert amounts("waiting_from_renewal", ctx) == [Decimal("29000.00")]


def test_waiting_from_renewal_silent_in_first_policy_year(rules):
    p = policy(si=500000, start="2026-02-01", end="2027-01-31", inception="2026-02-01")
    ctx = ctx_for(claim([line("L01", "Surgeon fee", 1000)], admission="2026-06-01"), p, rules)
    assert amounts("waiting_from_renewal", ctx) == []


def test_waiting_pre_existing_assumed(rules):
    p = policy(si=500000, start="2025-09-01", end="2026-08-31", inception="2024-09-01")   # 20 months of cover
    c = claim([line("L01", "Surgeon fee", 30000)], admission="2026-05-10", discharge="2026-05-12",
              condition_type=ConditionType.ILLNESS)
    ctx = ctx_for(c, p, rules)
    assert amounts("waiting_pre_existing_assumed", ctx) == [Decimal("30000.00")]


def test_si_mixes_policy_years(rules):
    history = [past("H1", "2025-03-01", 280000)]   # previous policy year
    ctx = ctx_for(claim([line("L01", "Surgeon fee", 50000)]), policy(si=300000), rules, history)
    assert amounts("sum_insured_policy", ctx) == [Decimal("0")]
    assert amounts("si_mixes_policy_years", ctx) == [Decimal("27500.00")]   # 47,500 - 20,000
