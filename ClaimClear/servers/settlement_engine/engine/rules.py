"""Policy limits and rule references.

``load_rules`` reads ``dev_data/dataset/policy_rules.json``. That file
is a simplified summary of the public Arogya Sanjeevani wording. Before the
engine is used for evaluation, check every number against the wording Member 2
ingests, and fill in ``clause`` for every entry in ``RULE_REFS``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import PolicyRules
from .money import D

# Every deduction and fact carries one of these IDs as ``rule_ref``.
# ``clause`` is the clause ID in the ingested policy wording (policy-kb). It is
# empty until the wording is downloaded and chunked; the critic must treat an
# empty clause as "citation missing", not as "no clause needed".
RULE_REFS: dict[str, dict[str, str]] = {
    "room_rent_cap": {
        "summary": "Room rent per day is limited to a % of sum insured, up to a rupee maximum.",
        "clause": "",
    },
    "icu_cap": {
        "summary": "ICU charges per day are limited to a % of sum insured, up to a rupee maximum.",
        "clause": "",
    },
    "gst_follows_charge": {
        "summary": "GST on a disallowed part of a charge is disallowed with it.",
        "clause": "",
    },
    "proportionate_deduction": {
        "summary": (
            "If the room rent exceeds the limit, associated medical expenses are reduced in the "
            "same proportion. IRDAI/HLT/REG/CIR/151/06/2020 (11 Jun 2020) bars this for pharmacy, "
            "consumables, implants, medical devices, diagnostics, ICU charges, and any expense the "
            "hospital does not price differently by room category."
        ),
        "clause": "",
    },
    "non_payable_items": {
        "summary": "Items on the policy's list of non-payable items are not paid.",
        "clause": "",
    },
    "cataract_limit": {
        "summary": "Cataract treatment is limited per eye per policy period to the lower of a % of sum insured and a rupee maximum.",
        "clause": "",
    },
    "initial_waiting_period": {
        "summary": "Illness treated within the first days of first inception is excluded (accidents are not).",
        "clause": "",
    },
    "listed_illness_waiting_period": {
        "summary": "Listed illnesses are covered only after a waiting period counted from first inception.",
        "clause": "",
    },
    "pre_existing_waiting_period": {
        "summary": "Pre-existing diseases are covered only after a waiting period counted from first inception.",
        "clause": "",
    },
    "copay": {
        "summary": "The policyholder bears a fixed % of every admissible claim, applied after all other deductions.",
        "clause": "",
    },
    "sum_insured": {
        "summary": "Payments in one policy period cannot exceed the sum insured.",
        "clause": "",
    },
    "pre_hospitalisation": {
        "summary": "Expenses before admission are paid only for a fixed number of days before the admission.",
        "clause": "",
    },
    "post_hospitalisation": {
        "summary": "Expenses after discharge are paid only for a fixed number of days from the discharge.",
        "clause": "",
    },
    "ambulance_limit": {
        "summary": "Road ambulance is paid up to a rupee limit per hospitalisation.",
        "clause": "",
    },
    "policy_period": {
        "summary": "A claim is covered when the admission falls inside the policy period.",
        "clause": "",
    },
    "expenses_actually_incurred": {
        "summary": "Only expenses actually incurred are paid: a charge billed twice for the same day is paid once.",
        "clause": "",
    },
    "fraud": {
        "summary": ("A claim supported by false or fraudulent documents is not payable, and treatment must be in a "
                    "hospital as the policy defines it. The engine never decides fraud: it reports definite "
                    "inconsistencies on the bill, which can support an insurer's rejection."),
        "clause": "",
    },
}


def rules_from_dict(raw: dict) -> PolicyRules:
    """Build ``PolicyRules`` from the ``policy_rules.json`` structure."""
    listed = tuple(int(m) for m in raw["listed_illness_waiting_months"])
    if not listed:
        raise ValueError("listed_illness_waiting_months must not be empty")
    return PolicyRules(
        room_pct_of_si=D(raw["room_rent_per_day"]["pct_of_sum_insured"]),
        room_max_inr=D(raw["room_rent_per_day"]["max_inr"]),
        icu_pct_of_si=D(raw["icu_per_day"]["pct_of_sum_insured"]),
        icu_max_inr=D(raw["icu_per_day"]["max_inr"]),
        cataract_pct_of_si=D(raw["cataract_per_eye"]["pct_of_sum_insured"]),
        cataract_max_inr=D(raw["cataract_per_eye"]["max_inr"]),
        copay_pct=D(raw["copay_pct"]),
        initial_waiting_days=int(raw["initial_waiting_period_days"]),
        listed_illness_waiting_months=listed,
        pre_existing_waiting_months=int(raw["pre_existing_waiting_months"]),
        pre_hospitalisation_days=int(raw.get("pre_hospitalisation_days", 30)),
        post_hospitalisation_days=int(raw.get("post_hospitalisation_days", 60)),
        ambulance_max_inr=D(raw.get("ambulance_per_hospitalisation_max_inr", 2000)),
    )


def load_rules(path: str | Path) -> PolicyRules:
    """Read a ``policy_rules.json`` file."""
    with open(path, encoding="utf-8") as fh:
        return rules_from_dict(json.load(fh))


def default_rules() -> PolicyRules:
    """The Arogya Sanjeevani limits used in the capstone dataset, without reading a file."""
    return rules_from_dict(
        {
            "room_rent_per_day": {"pct_of_sum_insured": 2, "max_inr": 5000},
            "icu_per_day": {"pct_of_sum_insured": 5, "max_inr": 10000},
            "cataract_per_eye": {"pct_of_sum_insured": 25, "max_inr": 40000},
            "copay_pct": 5,
            "initial_waiting_period_days": 30,
            "listed_illness_waiting_months": [24, 36],
            "pre_existing_waiting_months": 36,
            "pre_hospitalisation_days": 30,
            "post_hospitalisation_days": 60,
            "ambulance_per_hospitalisation_max_inr": 2000,
        }
    )
