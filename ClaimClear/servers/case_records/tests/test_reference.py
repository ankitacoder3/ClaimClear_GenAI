import json

import pytest

from case_records.reference import CLAIM_FIELDS, POLICY_FIELDS, ReferenceData
from case_records.register_dataset import register
from case_records.store import CaseStore, StoreError

# The settlement-engine tools' PolicyIn and PastClaimIn take exactly these fields.
SETTLEMENT_POLICY_IN = {"policy_no", "sum_insured", "period_start", "period_end", "first_inception",
                        "holder", "insurer", "product"}
SETTLEMENT_PAST_CLAIM_IN = {"claim_id", "policy_no", "admission", "status", "settled_amount", "diagnosis", "procedure"}


@pytest.fixture
def ref(dataset_dir, tmp_path):
    """Both splits' synthetic reference records in one place (the tests below use policies from each)."""
    for name in ("policies.json", "claim_history.json"):
        merged = [r for split in ("dev", "heldout")
                  for r in json.loads((dataset_dir / split / "reference" / name).read_text(encoding="utf-8"))]
        (tmp_path / name).write_text(json.dumps(merged), encoding="utf-8")
    return ReferenceData(tmp_path)


def test_policy_shape_matches_the_settlement_engine(ref):
    p = ref.policy("AS-2025-100478")
    assert set(p) == set(POLICY_FIELDS) == SETTLEMENT_POLICY_IN
    assert p["sum_insured"] == 300000 and p["first_inception"] == "2022-07-15"


def test_unknown_policy(ref):
    with pytest.raises(StoreError) as e:
        ref.policy("AS-0000-000000")
    assert e.value.code == "POLICY_NOT_FOUND"


def test_claim_history_shape_and_scope(ref):
    claims = ref.claim_history("AS-2025-102254")
    assert len(claims) == 1 and set(claims[0]) == set(CLAIM_FIELDS) == SETTLEMENT_PAST_CLAIM_IN
    assert "line_items" not in claims[0]


def test_claim_history_current_period_excludes_other_years(ref):
    # CLM-2025-00811 (AS-2025-101122) was admitted on 18 Aug 2025, inside 1 Jun 2025 - 31 May 2026
    assert [c["claim_id"] for c in ref.claim_history("AS-2025-101122")] == ["CLM-2025-00811"]
    # a policy with no history
    assert ref.claim_history("AS-2025-100478") == [] and ref.claim_history("AS-2025-100478", "all") == []


def test_claim_history_never_returns_other_policies(ref):
    for policy_no in ("AS-2026-100764", "AS-2025-101209"):
        assert {c["policy_no"] for c in ref.claim_history(policy_no, "all")} == {policy_no}


def test_invalid_scope(ref):
    with pytest.raises(StoreError) as e:
        ref.claim_history("AS-2025-100478", "everything")
    assert e.value.code == "INVALID_SCOPE"


# --- records shared by several cases ---------------------------------------------------------


def test_a_reused_policy_number_gives_each_case_its_own_record(dataset_dir):
    # gen-data's D2 variants reuse AS/2025/658678/79 with a sum insured of 1,50,000 or 1,00,000
    ref = ReferenceData(dataset_dir / "dev" / "reference")
    assert ref.policy("AS/2025/658678/79", "gen-dev-147e01")["sum_insured"] == 150000
    assert ref.policy("AS/2025/658678/79", "gen-dev-acf2ec")["sum_insured"] == 100000
    assert len(ref.claim_history("AS/2025/658678/79", "all", "gen-dev-acf2ec")) == 2
    assert len(ref.claim_history("AS/2025/658678/79", "all", "gen-dev-147e01")) == 1
    with pytest.raises(StoreError) as e:                 # an upload without the key can't pick one
        ref.policy("AS/2025/658678/79")
    assert e.value.code == "POLICY_NOT_FOUND"


# --- dataset registration ----------------------------------------------------------------


def _cases(dataset_dir, split):
    return json.loads((dataset_dir / split / "cases.json").read_text(encoding="utf-8"))["cases"]


def test_register_dataset_makes_one_case_per_folder(tmp_path, dataset_dir):
    store = CaseStore(tmp_path / "case_store")
    mapping = register(store, dataset_dir)                # the dev split
    cases = _cases(dataset_dir, "dev")
    assert len(mapping) == sum(len(c["documents"]) for c in cases)
    assert len({m["case_id"] for m in mapping.values()}) == len(cases) == 42
    set01 = mapping["SET-01"]["case_id"]
    assert mapping["GEN-02"]["case_id"] == mapping["DS-02"]["case_id"] == mapping["SCH-GEN-02"]["case_id"] == set01
    assert len(store.case(set01).document_ids) == 4
    assert store.role(set01, mapping["SCH-GEN-02"]["document_id"]) == "policy_schedule"
    assert store.case(set01).policy_no == "AS-2025-100478"
    gen = mapping["gen-dev-147e01/bill.pdf"]["case_id"]
    assert store.role(gen, mapping["gen-dev-147e01/earlier_settlement_1.pdf"]["document_id"]) == "other"
    assert store.case(gen).reference_key == "gen-dev-147e01" and store.case(set01).reference_key == ""
    index = (tmp_path / "case_store" / "index.json").read_text(encoding="utf-8")
    assert not any(label in index for label in ("GEN-", "MAL-", "ADV-", "POI-", "SET-", "adversarial", "genuine"))


def test_register_dataset_is_repeatable(tmp_path, dataset_dir):
    first = register(CaseStore(tmp_path / "case_store"), dataset_dir)
    second = register(CaseStore(tmp_path / "case_store"), dataset_dir)
    assert first == second


def test_register_dataset_by_split(tmp_path, dataset_dir):
    dev = register(CaseStore(tmp_path / "dev"), dataset_dir, split="dev")
    heldout = register(CaseStore(tmp_path / "heldout"), dataset_dir, split="heldout")
    dev_cases = {m["case_id"] for m in dev.values()}
    heldout_cases = {m["case_id"] for m in heldout.values()}
    assert (len(dev_cases), len(heldout_cases)) == (42, 53)
    assert not dev_cases & heldout_cases and not set(dev) & set(heldout)
    assert "SET-01" in dev and "GEN-02" in dev                  # the plan's worked example is a development case
    held_store = (tmp_path / "heldout" / "index.json").read_text(encoding="utf-8")
    shared = {m["document_id"] for m in heldout.values()}       # identical files (the gen-data wording) share an ID
    assert not any(m["document_id"] in held_store for m in dev.values() if m["document_id"] not in shared)
