"""The checked document reader (``claimclear_graph.checked_extraction``): the four fixes, on readings shaped like the
ones gpt-4.1-mini produced for the development cases (product path, 26 Nov 2026), with a scripted model."""

from __future__ import annotations

from claimclear_contracts.tools import tool_schemas
from claimclear_graph import checked_extraction as ce
from claimclear_graph.extraction import letter_issues, llm_extractor

from conftest import run

DEFS = next(t for t in tool_schemas()["settlement-engine"] if t["name"] == "reproduce_deduction")["input_schema"]["$defs"]


def schema(model: str) -> dict:
    return {**DEFS[model], "$defs": DEFS}


class TK:
    def schema(self, name):
        return schema(name)


class Scripted:
    """Answers scripted per schema (popped in order, the last one repeated); records every prompt."""

    def __init__(self, claims, letters):
        self.answers = {"ClaimIn": list(claims), "LetterIn": list(letters)}
        self.prompts = []

    def model_copy(self, update):
        return self

    def with_structured_output(self, sch):
        outer = self

        class Runnable:
            async def ainvoke(self, prompt):
                outer.prompts.append(prompt)
                queue = outer.answers[sch["title"]]
                return queue.pop(0) if len(queue) > 1 else queue[0]
        return Runnable()


def bill(lines, total, **extra):
    return {"claim_id": "AGI/1", "policy_no": "P-1", "printed_total": total, **extra,
            "lines": [{"line_id": str(i), "description": d, "amount": a, **({"non_payable": True} if np else {}),
                       "category": "pharmacy"} for i, (d, a, np) in enumerate(lines, 1)]}


# gen-dev-147e01 as the model read it: the co-pay both in copay_amount and as a third row
LETTER_147 = {"letter_id": "L", "letter_type": "settlement", "claimed_amount": "73100", "paid_amount": "24625",
              "copay_amount": "375",
              "rows": [{"row_id": "R1", "particulars": "Eye drops (non-payable)", "amount": "900", "kind": "non_payable"},
                       {"row_id": "R2", "particulars": "Excess over cataract limit", "amount": "47200"},
                       {"row_id": "R3", "particulars": "Co-payment 5% Clause 9.3", "amount": "375", "kind": "copay"}]}

DOCS = [{"document_id": "b1", "role": "bill"}, {"document_id": "b2", "role": "other_bills"},
        {"document_id": "l1", "role": "settlement_letter"}]
PAGES = {d: {"pages": [{"page": 1, "text": f"text of {d}"}]} for d in ("b1", "b2", "l1")}


def test_a_repeated_copay_row_is_removed_and_the_letter_adds_up():
    assert letter_issues(LETTER_147)                               # as read: claimed - rows - co-pay != paid
    folded = ce.fold_copay(LETTER_147)
    assert [r["row_id"] for r in folded["rows"]] == ["R1", "R2"] and folded["copay_amount"] == "375"
    assert letter_issues(folded) == []


def test_a_lone_copay_row_moves_into_copay_amount_and_rows_are_counted_again():
    # gen-dev-b4331d: the letter prints the co-pay between two deductions, without row numbers
    letter = {"letter_type": "settlement", "claimed_amount": "100", "paid_amount": "80", "copay_amount": None,
              "rows": [{"row_id": "R1", "particulars": "Nebuliser kit", "amount": "5"},
                       {"row_id": "R2", "particulars": "Less: Co-payment 5%", "amount": "5"},
                       {"row_id": "R3", "particulars": "Pharmacy items not payable", "amount": "10"}]}
    folded = ce.fold_copay(letter)
    assert folded["copay_amount"] == "5"
    assert [(r["row_id"], r["particulars"]) for r in folded["rows"]] == [("R1", "Nebuliser kit"),
                                                                        ("R2", "Pharmacy items not payable")]
    assert letter_issues(folded) == []


def test_printed_labels_out_of_order_are_kept_and_a_different_copay_is_left_alone():
    letter = {**LETTER_147, "rows": [{**r, "row_id": f"R{n}"} for r, n in zip(LETTER_147["rows"], (2, 5, 7))]}
    assert [r["row_id"] for r in ce.fold_copay(letter)["rows"]] == ["R2", "R5"]
    other = {**LETTER_147, "copay_amount": "999"}
    assert ce.fold_copay(other) is other


def test_the_engine_decides_what_is_payable():
    claim, letter = ce.engine_decides(bill([("Platelet transfusion (SDP)", "10100", True)], "10100"), LETTER_147)
    assert "non_payable" not in claim["lines"][0] and "category" not in claim["lines"][0]
    assert claim["lines"][0]["description"] == "Platelet transfusion (SDP)" and claim["lines"][0]["amount"] == "10100"
    assert all("kind" not in r for r in letter["rows"])


def test_a_bill_that_stays_short_is_read_file_by_file():
    # gen-dev-3ce156: the three lines of other_bills.pdf missed, in the first read and in the second ask
    short = bill([("Room", "80000", False)], "82930")
    main_file = bill([("Room", "80000", False)], "80000")
    other_file = bill([("Fever panel", "1800", False), ("Blood count", "650", False), ("Tonic", "480", False)], "2930")
    llm = Scripted([short, short, short, short, main_file, other_file], [{**LETTER_147}])
    out = run(ce.checked_extractor(llm)(TK(), "c", DOCS, PAGES))
    assert [x["description"] for x in out["claim"]["lines"]] == ["Room", "Fever panel", "Blood count", "Tonic"]
    assert out["checks"]["bill"]["per_file"] and out["checks"]["bill"]["left"] == []
    one_file = [p for p in llm.prompts if "ONE of the hospital's bills" in p]
    assert len(one_file) == 2 and "text of b2" in one_file[1] and "text of l1" not in one_file[1]


def test_two_bill_readings_keep_the_one_that_adds_up(monkeypatch):
    monkeypatch.setenv(ce.VOTES_ENV, "2")
    good = bill([("Room", "80000", False), ("Fever panel", "2930", False)], "82930")
    short = bill([("Room", "80000", False)], "82930")
    llm = Scripted([short, good, good], [{**LETTER_147}])          # vote 1 short (its second ask fixes it), vote 2 good
    out = run(ce.checked_extractor(llm)(TK(), "c", DOCS, PAGES))
    assert len(out["claim"]["lines"]) == 2 and out["checks"]["bill"]["votes"] == 2
    assert out["checks"]["letter"]["copay_folded"] and out["checks"]["letter"]["found"] == []   # no wasted second ask
    assert [r["row_id"] for r in out["letter"]["rows"]] == ["R1", "R2"]


def test_classic_reader_on_request(monkeypatch):
    llm = Scripted([bill([("Room", "1", False)], "1")], [{**LETTER_147}])
    monkeypatch.setenv(ce.READER_ENV, "classic")
    assert ce.make_extractor(llm).__qualname__ == llm_extractor(llm).__qualname__
    monkeypatch.delenv(ce.READER_ENV)
    assert ce.make_extractor(llm).__qualname__.startswith("checked_extractor")
    assert ce.make_extractor(None) is None
