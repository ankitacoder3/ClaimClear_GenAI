import pytest

from policy_kb.ingest import ingest_text
from policy_kb.models import WordingInfo
from policy_kb.text import stem, tokens

INFO = WordingInfo("Test Insurer", "Arogya Sanjeevani Policy", "TEST", synthetic=True)


# --- text -------------------------------------------------------------------------------


@pytest.mark.parametrize("a, b", [("charges", "charge"), ("charged", "charge"), ("deductions", "deduction"),
                                  ("medicines", "medicine"), ("gloves", "glove"), ("diagnostics", "diagnostic"),
                                  ("days", "day"), ("policies", "policy")])
def test_stemming_matches_word_forms(a, b):
    assert stem(a) == stem(b)


def test_tokens_drop_stop_words_and_keep_numbers():
    assert tokens("The limit is Rs. 5,000 per day, i.e. 2% of the sum insured") == \
        ["limit", "rs", "5000", "per", "day", "i.e", "2", "sum", "insur"]


# --- the sample wording -------------------------------------------------------------------


def test_sample_wording_clauses(ingested):
    ids = [c.clause_id for c in ingested.clauses]
    assert ids[:4] == ["1", "2", "3", "3.1"] and ids[-1] == "Annexure I"
    assert len(ids) == len(set(ids)) == 39
    assert {"4.3", "5.2", "7.5", "9.4", "10.2"} <= set(ids)


def test_titles_sections_and_parents(ingested):
    by_id = {c.clause_id: c for c in ingested.clauses}
    assert by_id["3.8"].title == "Room rent"                      # from "Room rent means ..."
    assert by_id["5.2"].title == "Items not reduced" and by_id["5.2"].section == "PROPORTIONATE DEDUCTION"
    assert by_id["5.2"].parent_id == "5" and by_id["5"].parent_id is None
    assert by_id["5"].text == "" and by_id["6"].text.startswith("Each admissible claim")
    assert by_id["7.1"].codes == ("Excl01",) and by_id["7.3"].codes == ("Excl03",)


def test_list_items_stay_inside_their_clause(ingested):
    text = {c.clause_id: c for c in ingested.clauses}["4.1"].text
    assert "Rs. 5,000 per day" in text and "Rs. 10,000 per day" in text
    assert text.count("\n") >= 3                                   # list items on their own lines


def test_preamble_is_reported(ingested):
    assert any("before the first clause" in w for w in ingested.warnings)


# --- numbering rules ----------------------------------------------------------------------


def test_lines_starting_with_numbers_are_not_clauses():
    text = "\n".join([
        "1. DEFINITIONS",
        "1.1 Waiting period means the time before cover starts.",
        "24 hours of admission is the minimum stay.",
        "30 days after inception the cover begins.",
        "2. COVERAGE",
        "2.1 Room rent",
        "Up to 2% of the sum insured.",
        "5 Rupees per day is not a clause.",
    ])
    ids = [c.clause_id for c in ingest_text(text, INFO).clauses]
    assert ids == ["1", "1.1", "2", "2.1"]


def test_sub_clauses_and_trailing_dots():
    text = "1. COVER\n1.1. Hospital\nText one.\n1.1.1 ICU\nText two.\n1.2 Day care\nText three."
    clauses = {c.clause_id: c for c in ingest_text(text, INFO).clauses}
    assert set(clauses) == {"1", "1.1", "1.1.1", "1.2"}
    assert clauses["1.1.1"].parent_id == "1.1" and clauses["1.1.1"].section == "COVER"


def test_pages_and_running_headers_from_form_feeds():
    page = "Insurer Ltd - Arogya Sanjeevani\n{body}\nPage {n} of 3"
    text = "\f".join([
        page.format(body="1. COVERAGE\n1.1 Room rent\nUp to 2% of sum insured,", n=1),
        page.format(body="subject to Rs. 5,000 per day.\n1.2 ICU\nUp to 5%.", n=2),
        page.format(body="2. CLAIMS\n2.1 Notice\nWithin 24 hours.", n=3),
    ])
    clauses = {c.clause_id: c for c in ingest_text(text, INFO).clauses}
    assert clauses["1.1"].page_start == 1 and clauses["1.1"].page_end == 2
    assert "Insurer Ltd" not in clauses["1.1"].text and "Page" not in clauses["1.1"].text
    assert clauses["1.1"].text == "Up to 2% of sum insured, subject to Rs. 5,000 per day."
    assert clauses["2.1"].page_start == 3


def test_pdf_ingestion(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from policy_kb.ingest import ingest_pdf
    doc = pymupdf.open()
    for body in ("1. COVERAGE\n1.1 Room rent\nUp to 2% of the sum insured.", "2. CLAIMS\n2.1 Notice\nWithin 24 hours."):
        page = doc.new_page()
        page.insert_text((72, 72), body, fontsize=11)
    path = tmp_path / "w.pdf"
    doc.save(path)
    clauses = {c.clause_id: c for c in ingest_pdf(path, INFO).clauses}
    assert set(clauses) == {"1", "1.1", "2", "2.1"} and clauses["2.1"].page_start == 2
