"""The lettered-section layout (as in Go Digit's wording), on a synthetic text; and checks on the real wording
that run only when it has been downloaded into development/dev_data/wordings/ (it is git-ignored)."""

from pathlib import Path

import pytest

from policy_kb import PolicyKB
from policy_kb.ingest import ingest_file, ingest_text
from policy_kb.kb import _normalise_id
from policy_kb.models import WordingInfo

# (Project restructuring #1)

INFO = WordingInfo("Test Insurer", "Arogya Sanjeevani Policy", "TEST", synthetic=True)

LETTERED = """Test Insurer Policy Wording
A. PREAMBLE
This policy is a contract.
B. DEFINITIONS
I.
STANDARD DEFINITIONS
1. Accident means a sudden event.
2. Migrationmeans a transfer of credits.
3. An AYUSH Hospital is a healthcare facility.
4. Emergency Care: management of a sudden illness.
36 months prior to the date of commencement of the policy.
C. BENEFITS COVERED UNDER THE POLICY
I.
COVERAGE
1.
Hospitalization
Room rent up to 2% of the sum insured.
1.1 Other expenses
Note:
1. Hospitalization must last 24 hours.
2. In case of admission to a room at rates exceeding the limits, other expenses are reduced in proportion.
3. Proportionate deductions will not apply where billing is not differential.
2.
AYUSH Treatment
Ayurveda and homeopathy are covered.
D. EXCLUSIONS
1.
Pre-Existing Diseases (Code- Excl01)
Excluded for 36 months.
2.
Specific Waiting Period
(Code- Excl02) The following listed conditions:
1. Hernia
2. Hydrocele
3. Cataract
4. Mastoidectomy
5. Tympanoplasty
3.
First Thirty Days Waiting Period (Code- Excl03)
Excluded for 30 days.
4. Breach of law: (Code- Excl10)
Expenses from a breach of law.
5. Treatment for alcoholism or substance abuse and consequences thereof.
ANNEXURE A
List I – Optional Items
1.
GLOVES (Not Payable)
List II – Items subsumed into Room Charges
1.
TOILETRIES
ANNEXURE - B
Ombudsman offices
"""


@pytest.fixture(scope="module")
def lettered():
    return {c.clause_id: c for c in ingest_text(LETTERED, INFO).clauses}


def test_sections_clauses_and_annexures(lettered):
    assert list(lettered) == ["A", "B", "B.1", "B.2", "B.3", "B.4", "C", "C.1", "C.1.1", "C.2", "D", "D.1", "D.2",
                              "D.3", "D.4", "D.5", "Annexure A", "Annexure A List I", "Annexure A List II", "Annexure B"]


def test_titles(lettered):
    assert lettered["B.1"].title == "Accident"
    assert lettered["B.2"].title == "Migration"                     # "Migrationmeans" in the PDF
    assert lettered["B.3"].title == "An AYUSH Hospital"
    assert lettered["B.4"].title == "Emergency Care"
    assert lettered["C.1"].title == "Hospitalization"               # bare "1." then the title line
    assert lettered["D.4"].title == "Breach of law" and lettered["D.4"].codes == ("Excl10",)
    assert lettered["C"].title == "BENEFITS COVERED UNDER THE POLICY" and lettered["C.1"].section == lettered["C"].title


def test_numbered_lists_stay_inside_their_clause(lettered):
    assert "4. Mastoidectomy" in lettered["D.2"].text                # not clause D.4: a bare "4." isn't next... the real D.4 is inline
    assert "2. In case of admission" in lettered["C.1.1"].text      # the real C.2 comes later as a bare "2."
    assert "36 months prior" in lettered["B.4"].text                # not a clause
    assert lettered["D.2"].codes == ("Excl02",)


def test_roman_group_labels_are_dropped(lettered):
    assert "STANDARD DEFINITIONS" not in lettered["B"].text and "COVERAGE" not in lettered["C"].text


def test_annexure_lists(lettered):
    assert lettered["Annexure A List I"].title == "Optional Items" and "GLOVES" in lettered["Annexure A List I"].text
    assert lettered["Annexure A List II"].parent_id == "Annexure A"
    assert lettered["Annexure B"].text.startswith("Ombudsman")


@pytest.mark.parametrize("raw, norm", [("c.1.1", "C.1.1"), ("Clause D.3", "D.3"), ("annexure a list i", "Annexure A List I"),
                                       ("ANNEXURE - B", "Annexure B")])
def test_lettered_id_normalisation(raw, norm):
    assert _normalise_id(raw) == norm


def test_long_clauses_are_split_at_an_internal_numbered_list():
    body = "\n".join(["1. COVERAGE", "1.1 Claim Procedure", "Intro line."] +
                     [f"{n}. Step {n} heading:\n" + ("detail text " * 120) for n in (1, 2, 3)])
    clauses = {c.clause_id: c for c in ingest_text(body, INFO).clauses}
    assert {"1.1", "1.1.1", "1.1.2", "1.1.3"} <= set(clauses)
    assert clauses["1.1.2"].title == "Step 2 heading" and clauses["1.1"].text == "Intro line."


def test_short_clauses_are_not_split(lettered):
    assert not any(cid.startswith("D.2.") for cid in lettered)


# --- the real Go Digit wording (skipped unless downloaded) -----------------------------------------

GODIGIT = Path(__file__).resolve().parents[3] / "development"/"dev_data" / "wordings" / "policy-wordings-arogya-sanjeevani-policy-go-digit.pdf"


@pytest.fixture(scope="module")
def godigit():
    pytest.importorskip("pymupdf")
    if not GODIGIT.exists():
        pytest.skip("Go Digit wording not downloaded (python -m policy_kb.fetch ...)")
    info = WordingInfo("Go Digit General Insurance Limited", "Arogya Sanjeevani Policy", "GODHLIP24179V022324")
    return PolicyKB.build(ingest_file(GODIGIT, info))


def test_godigit_structure(godigit):
    ids = [c.clause_id for c in godigit.clauses]
    assert ids[:3] == ["A", "B", "B.1"] and "B.53" in ids and "C.7" in ids and "D.23" in ids and "E.28" in ids
    assert {"Annexure A List I", "Annexure A List V", "Annexure B"} <= set(ids)
    assert len(ids) == len(set(ids))
    assert godigit.get_clause("D.1").codes == ("Excl01",) and godigit.get_clause("D.3").codes == ("Excl02",)
    assert godigit.get_clause("C.3").title == "Cataract Treatment"


def test_godigit_key_figures_are_in_the_right_clauses(godigit):
    assert "maximum of Rs.5000" in godigit.get_clause("C.1").text
    assert "same proportion" in godigit.get_clause("C.1.1").text
    assert "Rs.40,000" in godigit.get_clause("C.3").text
    assert "Co-payment of 5%" in godigit.get_clause("E.28.3").text


def test_godigit_rule_map_is_complete(godigit):
    assert godigit.check_rule_map() == []
    assert [c.clause_id for c in godigit.clauses_for_rule("copay")] == ["E.28.3", "B.10"]
    assert godigit.rule_map()["rules"]["proportionate_deduction"]["differs_from_engine"]


def test_godigit_search(godigit):
    assert "C.1.1" in [h.clause_id for h in godigit.search("why did they cut my medicine bill", k=5)]
    assert godigit.search("cataract limit per eye", k=1)[0].clause_id == "C.3"
