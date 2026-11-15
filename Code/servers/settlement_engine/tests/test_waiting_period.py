from datetime import date
from decimal import Decimal

from engine import ConditionType, DeductionKind, Status, compute_settlement
from engine import calculators as calc
from factories import claim, line, policy


def wp(rules, inception, admission, condition=None, listed=False):
    return calc.waiting_period(rules, date.fromisoformat(inception), date.fromisoformat(admission), condition, listed)


# --- initial 30 days -----------------------------------------------------------------


def test_inside_initial_period_not_admissible(rules):
    # DS-04 / MAL-04: first inception 1 Feb 2026, true admission 12 Feb 2026
    p = policy(si=1000000, start="2026-02-01", end="2027-01-31", inception="2026-02-01")
    c = claim([line("L01", "Surgeon fee", 30000)], admission="2026-02-12", discharge="2026-02-15",
              condition_type=ConditionType.ILLNESS)
    r = compute_settlement(c, p, rules)
    assert r.status == Status.NOT_ADMISSIBLE
    assert r.payable_amount == Decimal("0")
    assert r.deduction(DeductionKind.WAITING_PERIOD).amount == r.claimed_amount


def test_day_30_is_outside_the_initial_period(rules):
    assert wp(rules, "2026-02-01", "2026-03-03", ConditionType.ILLNESS).served is True   # 30 days
    assert wp(rules, "2026-02-01", "2026-03-02", ConditionType.ILLNESS).served is False  # 29 days


def test_accident_has_no_waiting_period(rules):
    assert wp(rules, "2026-02-01", "2026-02-05", ConditionType.ACCIDENT).served is True


def test_unknown_condition_inside_initial_period_asks_about_accident(rules):
    p = policy(si=500000, start="2026-02-01", end="2027-01-31", inception="2026-02-01")
    r = compute_settlement(claim([line("L01", "Surgeon fee", 30000)], admission="2026-02-10"), p, rules)
    assert r.status == Status.NEEDS_INFORMATION
    assert "accident" in r.questions[0].text


# --- listed illnesses and pre-existing disease --------------------------------------


def test_listed_illness_by_keyword_short_cover_not_served(rules):
    assert wp(rules, "2024-07-01", "2026-03-01", listed=True).served is False   # 20 months < 24


def test_listed_illness_by_keyword_between_tiers_asks(rules):
    assert wp(rules, "2023-07-01", "2026-01-01", listed=True).served is None    # 30 months: 24 or 36?


def test_listed_illness_by_keyword_long_cover_served(rules):
    assert wp(rules, "2022-07-01", "2026-01-01", listed=True).served is True    # 42 months


def test_explicit_tier(rules):
    assert wp(rules, "2023-07-01", "2026-01-01", ConditionType.LISTED_ILLNESS_SHORT).served is True   # 30 >= 24
    assert wp(rules, "2023-07-01", "2026-01-01", ConditionType.LISTED_ILLNESS_LONG).served is False   # 30 < 36


def test_pre_existing_needs_full_months(rules):
    assert wp(rules, "2023-03-01", "2026-02-28", ConditionType.PRE_EXISTING).served is False   # 35 months
    assert wp(rules, "2023-03-01", "2026-03-01", ConditionType.PRE_EXISTING).served is True    # exactly 36


def test_ordinary_illness_under_36_months_is_not_asked_about(rules):
    # SET-02: appendicitis, 31 months of cover, no listed illness, no pre-existing disease stated
    res = wp(rules, "2023-04-01", "2025-11-12", None, listed=False)
    assert res.served is True


def test_counted_from_first_inception_not_renewal(rules):
    # SET-05: renewed 1 Feb 2026, first inception 1 Feb 2022, knee condition (listed)
    p = policy(si=500000, start="2026-02-01", end="2027-01-31", inception="2022-02-01")
    c = claim([line("L01", "Surgeon fee - knee arthroscopy", 29000)], admission="2026-03-25", discharge="2026-03-27",
              diagnosis="Medial meniscus tear, left knee", condition_type=ConditionType.LISTED_ILLNESS_SHORT)
    r = compute_settlement(c, p, rules)
    assert r.status == Status.COMPUTED
    assert r.deduction(DeductionKind.WAITING_PERIOD) is None
    assert r.fact("F-WAITING").inputs["months_since_inception"] == 49


def test_listed_keyword_detects_dataset_diagnoses():
    assert calc.looks_listed_illness("Senile cataract, right eye")
    assert calc.looks_listed_illness("Cholelithiasis with cholecystitis")
    assert calc.looks_listed_illness("Medial meniscus tear, left knee")
    assert not calc.looks_listed_illness("Acute appendicitis")
    assert not calc.looks_listed_illness("Dengue fever with thrombocytopenia")
