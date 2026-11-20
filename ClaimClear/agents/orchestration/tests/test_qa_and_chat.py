"""The chat assistant and its rule-based answerer: every question type, every fallback, and streaming properties."""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings, strategies as hs
from langchain_core.messages import AIMessageChunk

from claimclear_graph import chat, qa
from claimclear_graph.services import ScopedToolkit
from claimclear_graph.testing import ReplayToolkit, tool_error

from conftest import Case, load, run, states_before


@pytest.fixture(scope="module")
def st():
    return states_before("SET-01")["approval_gate"]                    # audited, explained, grievance drafted


@pytest.fixture(scope="module")
def filed():
    c = Case("SET-01")
    run(c.start())
    return run(c.gate.approve_and_resume(c.cfg))


HIT = {"clause_id": "C.3", "title": "Cataract Treatment", "text": "Cataract treatment is covered up to 25% of Sum Insured "
       "or Rs.40,000 per eye.", "citation": "Policy wording, clause C.3"}


def tk(search_hits=(HIT,), clause=None, fail_clause=False):
    def search(*a, **k):
        return {"hits": list(search_hits)}

    def get_clause(cid, **k):
        if fail_clause:
            raise tool_error("get_clause", "INDEX_UNAVAILABLE")
        return clause or {"found": False, "clause_id": cid}
    return ReplayToolkit(load("SET-01")["calls"], overrides={"search_clauses": search, "get_clause": get_clause})


def ask(q, state, toolkit=None):
    return run(qa.rule_answer(q, state, ScopedToolkit(toolkit or tk(), qa.QA_AGENT)))


# --------------------------------------------------------------------------- rule-based answers


def test_clause_by_number():
    out = ask("What does clause C.3 say?", {}, tk(clause={**HIT, "found": True}))
    assert out["text"].startswith("Clause C.3 (Cataract Treatment)") and out["sources"] == ["Policy wording, clause C.3"]


def test_a_clause_that_does_not_exist_or_cannot_be_read():
    assert "no clause C.9" in ask("what about clause C.9", {}, tk())["text"]
    assert "no clause C.1" in ask("clause C.1 please", {}, tk(fail_clause=True))["text"]


@pytest.mark.parametrize("q,row", [("Why was R3 deducted?", "R3"), ("tell me about r1", "R1"),
                                   ("what about the co-pay?", "COPAY"), ("room rent cut?", "R1"),
                                   ("why GST?", "R2"), ("proportionate deduction?", "R3")])
def test_questions_about_a_row(st, q, row):
    out = ask(q, st)
    assert out["text"].startswith(f"{row},") and "Verdict:" in out["text"]


def test_at_most_two_rows_are_answered(st):
    assert ask("room gst proportionate", st)["text"].count("Verdict:") == 2          # three topics, two answers


def test_an_explicit_row_id_wins_over_topic_words(st):
    assert ask("room gst proportionate copay", st)["text"].startswith("COPAY,")


def test_dispute_with_a_drafted_grievance(st):
    text = ask("how much can I dispute?", st)["text"]
    assert text.startswith("₹8,522.86 may be disputable") and "drafted for you to approve" in text
    assert "can't promise the outcome" in text


def test_dispute_after_filing_and_the_status(filed):
    assert "A grievance was filed: reference DRYRUN-" in ask("can I appeal?", filed)["text"]
    status = ask("what is the status of my grievance?", filed)["text"]
    assert status.startswith("Your grievance was filed with reference DRYRUN-") and "dry run" in status


def test_nothing_to_dispute(st):
    s = copy.deepcopy(st)
    for r in s["letter_audit"]["rows"]:
        r["verdict"] = "matches_policy"
    s["letter_audit"]["disputable_amount"] = 0.0
    assert ask("is anything wrong?", s)["text"].startswith("Nothing on this letter can be shown")
    s["letter_audit"]["disputable_amount"] = 0.5
    assert "Overall the gap is ₹0.50" in ask("complaint?", s)["text"]


def test_totals_with_unverified_amounts(st):
    s = copy.deepcopy(st)
    s["letter_audit"]["unverified_amount"] = 300.0
    text = ask("how much is payable in total?", s)["text"]
    assert "₹87,094.64" in text and "₹95,617.50" in text and "₹300 can't be checked" in text


def test_summary_returns_the_explanation(st):
    assert ask("give me a summary", st)["text"] == st["explanation"]


def test_anything_else_is_answered_from_the_policy_wording(st):
    out = ask("is dialysis covered?", st)
    assert out["text"].startswith("Here is what your policy wording says:") and "Clause C.3" in out["text"]
    before_case = ask("is cataract covered?", {})
    assert "Upload your bill" in before_case["text"]


def test_nothing_found_anywhere():
    assert ask("blorp?", {}, tk(search_hits=()))["text"].startswith("I couldn't find that")


def test_search_outage_falls_through_gracefully():
    toolkit = ReplayToolkit([], overrides={"search_clauses": lambda *a, **k: (_ for _ in ()).throw(
        tool_error("search_clauses", "INDEX_UNAVAILABLE"))})
    assert ask("anything", {}, toolkit)["text"].startswith("I couldn't find that")


# --------------------------------------------------------------------------- the streaming chat


def collect(gen):
    async def go():
        return [e async for e in gen]
    return run(go())


def streamed(events):
    return "".join(e["text"] for e in events if e["type"] == "delta")


@pytest.mark.parametrize("q,expect", [
    ("what was my diagnosis?", "Cholelithiasis"), ("which surgery did I have?", "Laparoscopic cholecystectomy"),
    ("when was I admitted?", "2026-01-19"), ("list my bill items", "L01"), ("who treated me at the hospital?", "page"),
])
def test_medical_record_questions(st, q, expect):
    records = run(chat.load_records(tk(), st["case_id"]))
    assert expect in chat.record_answer(q, st, records)["text"]


def test_record_questions_without_a_case_return_nothing():
    assert chat.record_answer("what was my diagnosis?", {}, None) is None


def test_empty_question_and_no_model(st):
    events = collect(chat.stream_answer("   ", st, tk()))
    assert streamed(events) == "Please type a question." and events[-1]["how"] == "rules"


def test_model_failing_mid_stream_is_replaced(st):
    class Broken:
        async def astream(self, messages):
            yield AIMessageChunk(content="Your R3 ")
            raise ConnectionError("dropped")
    events = collect(chat.stream_answer("Why R3?", st, tk(), Broken()))
    kinds = [e["type"] for e in events]
    assert "retract" in kinds and events[-1]["how"].startswith("rules (model answer withdrawn: the model could not be reached")


def test_only_the_last_six_turns_are_sent(st):
    seen = {}

    class Spy:
        async def astream(self, messages):
            seen["n"] = len(messages)
            yield AIMessageChunk(content="ok")
    history = [(f"q{i}", f"a{i}") for i in range(10)]
    collect(chat.stream_answer("next?", st, tk(), Spy(), None, history))
    assert seen["n"] == 1 + 2 * 6 + 1                                   # system + 6 turns + the question


def test_a_figure_the_user_typed_may_be_quoted_back(st):
    class Echo:
        async def astream(self, messages):
            yield AIMessageChunk(content="₹1,234 is not on your letter.")
    events = collect(chat.stream_answer("Is ₹1,234 right?", st, tk(), Echo()))
    assert streamed(events) == "₹1,234 is not on your letter." and events[-1]["how"] == "llm"


def test_content_block_chunks_are_streamed(st):
    class Blocks:
        async def astream(self, messages):
            yield AIMessageChunk(content=[{"type": "text", "text": "Hello "}, {"type": "text", "text": "there"}])
    assert streamed(collect(chat.stream_answer("hi", st, tk(), Blocks()))) == "Hello there"


@pytest.mark.parametrize("env,expected,url", [
    ({"OPENROUTER_API_KEY": "k"}, "openai/gpt-4.1-mini", "openrouter.ai"),
    ({"OPENROUTER_API_KEY": "k", "CLAIMCLEAR_CHAT_MODEL": "anthropic/claude-x"}, "anthropic/claude-x", "openrouter.ai"),
    ({"CLAIMCLEAR_LLM_BASE_URL": "http://h/v1"}, "llama3.1", "http://h/v1"),
    ({"CLAIMCLEAR_LLM_BASE_URL": "http://h/v1", "CLAIMCLEAR_LOCAL_MODEL": "qwen2.5:7b"}, "qwen2.5:7b", "http://h/v1"),
    # both set: the local model wins, and the OpenRouter model name and key are never sent to it
    ({"CLAIMCLEAR_LLM_BASE_URL": "http://h/v1", "OPENROUTER_API_KEY": "sk-or", "CLAIMCLEAR_CHAT_MODEL": "openai/x"},
     "llama3.1", "http://h/v1"),
    # Anthropic and OpenAI keys are not used any more
    ({"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k"}, None, None),
])
def test_model_selection(monkeypatch, env, expected, url):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "CLAIMCLEAR_LLM_BASE_URL",
              "CLAIMCLEAR_CHAT_MODEL", "CLAIMCLEAR_LOCAL_MODEL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    llm = chat.chat_model_from_env()
    if expected is None:
        assert llm is None and chat.describe_model(llm).startswith("no model")
        return
    assert chat.describe_model(llm) == expected and url in str(llm.openai_api_base)
    if "local" in url or url.startswith("http://h"):
        assert llm.openai_api_key.get_secret_value() == "local"


def test_guard_holds_back_partial_currency_prefixes():
    g = chat.StreamGuard({Decimal("5")})
    assert g.feed("cost R") == "cost "                                 # could be "Rs 5": held
    assert g.feed("s 5 only") == "Rs 5 only" and not g.failed


# --------------------------------------------------------------------------- properties of the streaming guard

ALLOWED_TEXT = ("R3 was cut by ₹30,371.43, but your policy allows ₹21,400 (clause C.1.1). In total ₹8,522.86 "
                "may be disputable; Rs. 6,000 for room rent matches. INR 300 is GST.")
ALLOWED = {Decimal(x) for x in ("30371.43", "21400", "8522.86", "6000", "300")}


def chunked(text, cuts):
    cuts = sorted({c % (len(text) + 1) for c in cuts})
    pieces, last = [], 0
    for c in cuts + [len(text)]:
        pieces.append(text[last:c])
        last = c
    return pieces


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(hs.lists(hs.integers(min_value=0, max_value=10_000), max_size=40))
def test_property_allowed_text_streams_through_unchanged_for_any_chunking(cuts):
    g = chat.StreamGuard(ALLOWED)
    out = "".join(g.feed(p) for p in chunked(ALLOWED_TEXT, cuts)) + g.finish()
    assert out == ALLOWED_TEXT and not g.failed


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(hs.lists(hs.integers(min_value=0, max_value=10_000), max_size=40),
       hs.integers(min_value=1, max_value=9_999_999).filter(lambda n: Decimal(n) not in ALLOWED),
       hs.sampled_from(["₹", "Rs. ", "INR "]))
def test_property_an_invented_amount_never_reaches_the_user(cuts, amount, sign):
    text = f"Good news: you are owed {sign}{amount:,} for R3. " + ALLOWED_TEXT
    g = chat.StreamGuard(ALLOWED)
    out = ""
    for p in chunked(text, cuts):
        out += g.feed(p)
        if g.failed:
            break
    else:
        out += g.finish()
    assert g.failed and f"{amount:,}" not in out and str(amount) not in out.replace(",", "")


def test_uploaded_documents_go_into_the_prompt(st):
    class Spy:
        seen = None

        async def astream(self, messages):
            Spy.seen = messages[0].content
            yield AIMessageChunk(content="Please upload the settlement letter.")
    docs = "bill.pdf: bill: City Eye Hospital, total ₹55,600.00\nStill needed for a settlement check: the settlement letter"
    text = streamed(collect(chat.stream_answer("What else do you need?", st, tk(), Spy(), documents=docs)))
    assert "<uploaded_documents>\nbill.pdf: bill: City Eye Hospital" in Spy.seen
    assert "Still needed for a settlement check: the settlement letter" in Spy.seen
    assert text == "Please upload the settlement letter."
    collect(chat.stream_answer("And now?", st, tk(), Spy()))
    assert "<uploaded_documents>\n(not given)\n</uploaded_documents>" in Spy.seen       # old callers unchanged
