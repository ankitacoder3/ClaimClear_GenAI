"""The LLM extraction's format normaliser, on the engine's exported schemas and the outputs a real model produced in
the live run of 17 Nov 2026 (gpt-4.1-mini via OpenRouter): printed amounts, Indian dates, nulls. Format only:
nothing is computed, and anything unreadable is left for the engine to refuse."""

from __future__ import annotations

import pytest

from claimclear_contracts.tools import tool_schemas
from claimclear_graph.extraction import _date, _number, llm_extractor, normalise

from conftest import run

DEFS = next(t for t in tool_schemas()["settlement-engine"] if t["name"] == "reproduce_deduction")["input_schema"]["$defs"]


def schema(model: str) -> dict:
    """As ``ClaimClearToolkit.schema`` builds it from the live tool listing."""
    return {**DEFS[model], "$defs": DEFS}


LIVE_CLAIM = {          # what the model returned for SET-01 (syn-dev-005) before the fix
    "claim_id": "AGI/HC/2526/004512", "policy_no": "AS-2025-100478", "admission": "19/01/2026",
    "discharge": "22/01/2026", "discount": None, "printed_total": "₹1,28,350.00", "condition_type": None,
    "diagnosis": "Cholelithiasis with cholecystitis", "procedure": "Laparoscopic cholecystectomy",
    "room_priced_by_category": {}, "lines": [
        {"line_id": "1", "description": "Private room", "amount": "21,000.00", "gst_pct": "5", "rate": "7,000.00",
         "date": None, "qty": "3", "non_payable": None, "category": "Room"},
        {"line_id": "2", "description": "Gloves", "amount": "Rs. 450/-", "gst_pct": "12%", "rate": None,
         "date": "08-Jan-2026", "qty": "1", "non_payable": "yes", "category": None}]}
LIVE_LETTER = {"letter_id": "L1", "letter_type": "settlement", "claimed_amount": "₹1,28,350.00",
               "paid_amount": "₹87,094.64", "copay_amount": None,
               "rows": [{"row_id": "R3", "particulars": "Proportionate deduction", "amount": "-₹30,371.43",
                         "reason": "room above eligibility", "kind": None}]}


def test_printed_amounts_dates_and_nulls_are_put_in_the_engines_format():
    c = normalise(LIVE_CLAIM, schema("ClaimIn"))
    assert c["admission"] == "2026-01-19" and c["discharge"] == "2026-01-22"
    assert c["printed_total"] == "128350.00" and "discount" not in c and "condition_type" not in c
    first, second = c["lines"]
    assert first == {"line_id": "1", "description": "Private room", "amount": "21000.00", "gst_pct": "5",
                     "rate": "7000.00", "qty": "3", "category": "room"}
    assert second["amount"] == "450" and second["gst_pct"] == "12" and second["date"] == "2026-01-08"
    assert second["non_payable"] is True and "rate" not in second and "category" not in second


def test_a_deduction_printed_with_a_minus_sign_is_the_deduction():
    letter = normalise(LIVE_LETTER, schema("LetterIn"))
    assert letter["rows"][0]["amount"] == "30371.43"                     # amount can't be negative in the schema
    assert letter["paid_amount"] == "87094.64" and letter["claimed_amount"] == "128350.00"
    assert "copay_amount" not in letter and "kind" not in letter["rows"][0]


def test_text_and_ids_are_never_changed():
    c = normalise(LIVE_CLAIM, schema("ClaimIn"))
    assert c["claim_id"] == "AGI/HC/2526/004512" and c["policy_no"] == "AS-2025-100478"
    assert c["diagnosis"] == LIVE_CLAIM["diagnosis"] and c["lines"][1]["description"] == "Gloves"


def test_what_cannot_be_read_is_left_for_the_engine_to_refuse():
    c = normalise({"claim_id": "X", "admission": "the 19th", "lines": [{"line_id": "1", "description": "Room",
                                                                        "amount": "twenty thousand"}]},
                  schema("ClaimIn"))
    assert c["admission"] == "the 19th" and c["lines"][0]["amount"] == "twenty thousand"


def test_unknown_keys_from_the_model_are_dropped():
    c = normalise({"claim_id": "X", "notes": "the model added this", "lines": []}, schema("ClaimIn"))
    assert c == {"claim_id": "X", "lines": []}


def test_an_unknown_category_is_left_for_the_engine_to_work_out():
    c = normalise({"claim_id": "X", "lines": [{"line_id": "9", "description": "Syringes", "amount": "120",
                                                "category": "Pharmacy & consumables"}]}, schema("ClaimIn"))
    assert "category" not in c["lines"][0]                               # seen live: refused by the engine before


def test_printed_placeholders_in_optional_fields_take_the_default():
    c = normalise({"claim_id": "X", "discount": "Nil", "lines": [{"line_id": "1", "description": "Room",
                                                                  "amount": "7,000", "gst_pct": "-", "qty": "NA"}]},
                  schema("ClaimIn"))
    assert "discount" not in c and c["lines"][0] == {"line_id": "1", "description": "Room", "amount": "7000"}
    assert normalise({"claim_id": "-", "lines": []}, schema("ClaimIn"))["claim_id"] == "-"   # required: kept


@pytest.mark.parametrize("text,iso", [("19/01/2026", "2026-01-19"), ("08-Jan-2026", "2026-01-08"),
                                       ("8 January 2026", "2026-01-08"), ("2026-01-19T00:00:00", "2026-01-19"),
                                       ("19.01.2026", "2026-01-19"), ("Jan 8, 2026", "2026-01-08")])
def test_indian_dates(text, iso):
    assert _date(text) == iso


@pytest.mark.parametrize("text,num", [("₹1,28,350.00", "128350.00"), ("Rs. 450/-", "450"), ("INR 6,000", "6000"),
                                       ("5%", "5"), ("-₹550.00", "-550.00"), ("abc", None), ("1.2.3", None)])
def test_numbers(text, num):
    assert _number(text) == num


def test_the_extractor_normalises_and_retries_once(monkeypatch):
    import claimclear_graph.extraction as ex
    monkeypatch.setattr(ex.asyncio, "sleep", lambda s: asyncio_noop())
    calls = {"n": 0}

    class Flaky:
        def model_copy(self, update):
            return self

        def with_structured_output(self, sch):
            class Runnable:
                async def ainvoke(self, prompt):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        raise ConnectionError("provider hiccup")
                    return LIVE_CLAIM if sch["title"] == "ClaimIn" else LIVE_LETTER
            return Runnable()

    class TK:
        def schema(self, name):
            return schema(name)
    docs = [{"document_id": "d1", "role": "bill"}, {"document_id": "d2", "role": "settlement_letter"}]
    pages = {"d1": {"pages": [{"page": 1, "text": "bill"}]}, "d2": {"pages": [{"page": 1, "text": "letter"}]}}
    out = run(llm_extractor(Flaky())(TK(), "case_x", docs, pages))
    # 1 failed call + bill + letter, then one second ask each: the sample reading doesn't add up (lines vs total,
    # rows vs paid) and the fake answers the same again, so the first readings are kept and the issues reported
    assert calls["n"] == 5 and out["claim"]["admission"] == "2026-01-19" and out["letter"]["paid_amount"] == "87094.64"
    assert out["checks"]["bill"]["found"] and out["checks"]["bill"]["left"] and out["checks"]["letter"]["left"]


async def asyncio_noop():
    return None


# --------------------------------------------------------------------------- arithmetic check and second ask

from claimclear_graph.extraction import bill_issues, letter_issues  # noqa: E402


def _bill(lines, total, discount=None):
    c = {"claim_id": "X", "printed_total": total, "lines": [{"line_id": str(i), "description": d, "amount": a,
                                                             "gst_pct": g} for i, (d, a, g) in enumerate(lines, 1)]}
    if discount is not None:
        c["discount"] = discount
    return c


def test_bill_arithmetic():
    assert bill_issues(_bill([("Room", "21000", "5"), ("Surgeon", "32000", "0")], "54050")) == []
    assert bill_issues(_bill([("Room", "21000", "5")], "54050"))                    # a line was missed
    assert bill_issues(_bill([("Room", "21000", "0")], "20000", discount="1000")) == []
    assert bill_issues({"claim_id": "X", "lines": []}) == []                        # nothing to check


def test_letter_arithmetic():
    ok_letter = {"letter_type": "settlement", "claimed_amount": "100", "paid_amount": "85.5",
                 "copay_amount": "4.5", "rows": [{"amount": "10"}]}
    assert letter_issues(ok_letter) == []
    assert letter_issues({**ok_letter, "rows": []})                                 # a row was missed
    assert letter_issues({"letter_type": "rejection", "claimed_amount": "100", "paid_amount": "0"}) == []
    assert letter_issues({"letter_type": "rejection", "claimed_amount": "100", "paid_amount": "100"})


class Scripted:
    """A model whose answers are scripted per schema; records every prompt."""

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
                return outer.answers[sch["title"]].pop(0)
        return Runnable()


class TK:
    def schema(self, name):
        return schema(name)


DOCS = [{"document_id": "d1", "role": "bill"}, {"document_id": "d2", "role": "settlement_letter"}]
PAGES = {"d1": {"pages": [{"page": 1, "text": "bill"}]}, "d2": {"pages": [{"page": 1, "text": "letter"}]}}
GOOD_LETTER = {"letter_id": "L", "letter_type": "settlement", "claimed_amount": "54050", "paid_amount": "54050",
               "rows": []}


def test_a_missed_line_is_fixed_by_the_second_ask():
    missed = _bill([("Room", "21,000.00", "5")], "₹54,050")
    full = _bill([("Room", "21,000.00", "5"), ("Surgeon fee", "32,000", "0")], "₹54,050")
    llm = Scripted([missed, full], [GOOD_LETTER])
    out = run(llm_extractor(llm)(TK(), "c", DOCS, PAGES))
    assert len(out["claim"]["lines"]) == 2 and out["checks"]["bill"]["found"] and out["checks"]["bill"]["left"] == []
    assert "does not add up" in llm.prompts[1] and "Never change an amount" in llm.prompts[1]
    assert len(llm.prompts) == 3                                                    # bill, bill again, letter


def test_a_worse_second_reading_is_not_kept():
    missed = _bill([("Room", "21000", "5")], "54050")
    worse = {**missed, "printed_total": "1"}                                       # still wrong: no better
    out = run(llm_extractor(Scripted([missed, worse], [GOOD_LETTER]))(TK(), "c", DOCS, PAGES))
    assert out["claim"]["printed_total"] == "54050" and out["checks"]["bill"]["left"]


def test_a_reading_that_adds_up_is_not_asked_again():
    good = _bill([("Room", "21000", "5"), ("Surgeon fee", "32000", "0")], "54050")
    llm = Scripted([good], [GOOD_LETTER])
    out = run(llm_extractor(llm)(TK(), "c", DOCS, PAGES))
    assert len(llm.prompts) == 2 and out["checks"]["bill"] == {"found": [], "left": []}
