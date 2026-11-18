"""Episodic memory: earlier conversations as topics only, found again by meaning (``claimclear_memory.episodes``).

What must hold: no amount, number or contact ever reaches storage (even from a model's summary); only the user's
questions are summarised; recall is relevant, bounded and recency-aware; the usual controls (consent, expiry,
export, forget, user isolation) cover episodes too.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from claimclear_memory import (EpisodeRecord, HashingEmbedder, MemoryStore, MemoryStoreError, NoMemory, Retention,
                               UnsafeSummary, extractive_summary, render_episodes, scrub)
from claimclear_memory import episodes as ep

MONEY = re.compile(r"₹|\brs\.?\s*\d|\binr\s*\d|\d{3,}", re.I)


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t

    def advance(self, days):
        self.t += timedelta(days=days)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return MemoryStore(tmp_path / "memory.db", clock=clock)


@pytest.fixture
def mem(store):
    m = store.for_user("u_alice")
    m.grant_consent("test:settings")
    return m


R3 = [("Why was R3 deducted? The proportionate cut was ₹30,371.43", "R3 ... ₹21,400 ..."),
      ("Is the co-pay on my claim right?", "Co-pay ... ₹4,780.88")]
EYE = [("Is cataract surgery covered for my left eye?", "Clause C.3 ...")]
DATES = [("What was my diagnosis and when was I discharged?", "Diagnosis ...")]


# --------------------------------------------------------------------------- scrubbing


def test_scrub_removes_amounts_numbers_and_contacts():
    text = ("Why was Rs. 30,371.43 deducted on R3 under C.1.1 and E.28.3? Policy AS-2025-100478, claim "
            "AGI/HC/2526/004512, call +91 98765 43210, mail a.b@example.com, admitted 2026-03-02, 8522 extra, "
            "INR 500, 1200 rupees, ₹5,000 cap, see https://x.example/a")
    out = scrub(text)
    assert not MONEY.search(out), out
    for gone in ("30,371", "100478", "004512", "98765", "example.com", "2026", "8522", "5,000", "https"):
        assert gone not in out
    for kept in ("R3", "C.1.1", "E.28.3"):                       # what was discussed survives, without a figure
        assert kept in out
    assert "[amount]" in out and "[phone]" in out and "[email]" in out and "[id]" in out and "[date]" in out


def test_scrub_keeps_small_counts_and_limits_length():
    assert scrub("stayed 3 days in room 2") == "stayed 3 days in room 2"
    long = scrub("why " * 400)
    assert len(long) <= ep.SUMMARY_CHARS + 2 and long.endswith("…")


def test_scrub_refuses_what_it_cannot_clean(monkeypatch):
    monkeypatch.setattr(ep, "_RUPEE", re.compile(r"(?!x)x"))     # a broken pattern must not let money through
    monkeypatch.setattr(ep, "_NUMBER", re.compile(r"(?!x)x"))
    with pytest.raises(UnsafeSummary):
        scrub("deducted Rs 500")


def test_only_the_users_questions_are_summarised():
    s = extractive_summary(R3)
    assert s.startswith("Asked about: Why was R3 deducted?") and "Is the co-pay" in s
    assert "21,400" not in s and "4,780" not in s                # the assistant's answers are never used
    assert extractive_summary([("", "answer only")]) == ""


# --------------------------------------------------------------------------- remembering


def test_remember_a_conversation(mem):
    e = mem.remember_conversation(R3, case_id="case_a", claim_id="CL-1")
    assert isinstance(e, EpisodeRecord) and e.case_id == "case_a" and e.claim_id == "CL-1" and e.turns == 2
    assert "proportionate deduction" in e.topics and "co-pay" in e.topics and "R3" in e.topics
    assert not MONEY.search(e.summary) and "[amount]" in e.summary


def test_a_model_summary_is_scrubbed_too(mem):
    e = mem.remember_conversation(R3, case_id="case_a", source="chat:llm",
                                  summary="The user disputed ₹8,522.86 on R3 and gave phone 9876543210.")
    assert e.source == "chat:llm" and not MONEY.search(e.summary) and "R3" in e.summary


def test_nothing_is_stored_without_consent(store):
    m = store.for_user("u_bob")
    with pytest.raises(MemoryStoreError) as err:
        m.remember_conversation(R3)
    assert err.value.code == "NO_CONSENT"
    assert m.recall("proportionate") == []
    assert isinstance(store.session_memory("u_bob"), NoMemory)
    assert store.session_memory("u_bob").remember_conversation(R3) is None


def test_empty_conversations_are_not_stored(mem):
    assert mem.remember_conversation([]) is None
    assert mem.remember_conversation([("   ", "x")]) is None
    assert mem.episodes() == []


def test_a_repeated_conversation_is_merged(mem):
    first = mem.remember_conversation(R3, case_id="case_a")
    again = mem.remember_conversation(R3, case_id="case_a")
    assert again.episode_id == first.episode_id and again.turns == 4 and len(mem.episodes()) == 1
    other_case = mem.remember_conversation(R3, case_id="case_b")       # same words, another case: kept apart
    assert other_case.episode_id != first.episode_id and len(mem.episodes()) == 2


def test_episodes_are_capped(mem, monkeypatch):
    monkeypatch.setattr(ep, "MAX_EPISODES", 3)
    for i in range(5):
        mem.remember_conversation([(f"question about topic{'abcde'[i]} room rent", "")], case_id=f"case_{i}")
    kept = mem.episodes()
    assert len(kept) == 3 and {e.case_id for e in kept} == {"case_2", "case_3", "case_4"}


# --------------------------------------------------------------------------- recall


def test_recall_finds_the_relevant_conversation(mem):
    mem.remember_conversation(R3, case_id="case_a")
    mem.remember_conversation(EYE, case_id="case_b")
    mem.remember_conversation(DATES, case_id="case_c")
    assert mem.recall("what did I ask about the proportionate deduction?")[0].case_id == "case_a"
    assert mem.recall("cataract eye surgery")[0].case_id == "case_b"
    assert mem.recall("when was I discharged")[0].case_id == "case_c"
    hit = mem.recall("co-pay", k=1)
    assert len(hit) == 1 and hit[0].score and hit[0].score > 0


def test_unrelated_questions_recall_nothing(mem):
    mem.remember_conversation(R3, case_id="case_a")
    assert mem.recall("what is the weather like today") == []
    assert mem.recall("") == []


def test_recall_prefers_newer_conversations(mem, clock):
    mem.remember_conversation([("room rent limit question", "")], case_id="old")
    clock.advance(120)
    mem.remember_conversation([("room rent limit question again", "")], case_id="new")
    assert [e.case_id for e in mem.recall("room rent limit")][:1] == ["new"]


def test_recall_can_be_limited_to_one_case(mem):
    mem.remember_conversation(R3, case_id="case_a")
    mem.remember_conversation([("proportionate deduction again", "")], case_id="case_b")
    assert {e.case_id for e in mem.recall("proportionate", case_id="case_b")} == {"case_b"}


def test_recall_marks_episodes_as_used(mem):
    e = mem.remember_conversation(R3, case_id="case_a")
    mem.recall("proportionate")
    mem.recall("co-pay")
    assert mem.episode(e.episode_id).recall_count == 2


def test_another_embedder_is_used_consistently(mem):
    class Upper(HashingEmbedder):
        def __init__(self):
            super().__init__(dims=64)
            self.name = "upper-64"
    mem.remember_conversation(R3, case_id="case_a")                     # stored with the default embedder
    assert mem.recall("proportionate deduction", embedder=Upper())[0].case_id == "case_a"   # re-embedded


def test_users_never_recall_each_others_conversations(store):
    a, b = store.for_user("u_a"), store.for_user("u_b")
    a.grant_consent("t")
    b.grant_consent("t")
    a.remember_conversation(R3, case_id="case_a")
    assert b.recall("proportionate") == [] and b.episodes() == []


# --------------------------------------------------------------------------- controls


def test_episodes_expire(tmp_path, clock):
    store = MemoryStore(tmp_path / "short.db", clock=clock, retention=Retention(episode_days=10))
    m = store.for_user("u_alice")
    m.grant_consent("t")
    m.remember_conversation(R3, case_id="case_a")
    clock.advance(11)
    assert m.recall("proportionate") == [] and m.episodes() == []


def test_episodes_are_exported_and_forgotten(mem, store):
    mem.remember_conversation(R3, case_id="case_a")
    data = mem.export()
    assert len(data["episodes"]) == 1 and "vector" not in data["episodes"][0]
    json.dumps(data)
    assert mem.forget()["episodes"] == 1
    with sqlite3.connect(store.path) as con:
        assert con.execute("SELECT COUNT(*) FROM episodes WHERE user_id='u_alice'").fetchone()[0] == 0


def test_episodes_never_add_allowed_figures(mem):
    mem.remember_conversation(R3, case_id="case_a")
    assert mem.context()["figures"] == []                               # the critic's allow-list is untouched


def test_render_episodes_for_a_prompt(mem):
    mem.remember_conversation(R3, case_id="case_a", claim_id="CL-1")
    block = render_episodes(mem.recall("proportionate"))
    assert block.startswith(ep.NOTE) and "(claim CL-1)" in block and "R3" in block
    assert render_episodes([]) == ""
    assert len(render_episodes(mem.episodes(), max_chars=len(ep.NOTE) + 5)) == 0      # nothing fits: nothing shown


def test_upgrade_from_schema_2_adds_the_episodes_table(tmp_path):
    path = tmp_path / "v2.db"
    m = MemoryStore(path).for_user("u_old")
    m.grant_consent("t")
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE episodes")
        con.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    again = MemoryStore(path).for_user("u_old")
    assert again.remember_conversation(R3).turns == 2                    # the table is back and usable
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "3"
        assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='episodes'").fetchone()[0] == 1


def test_command_line_consent_episodes_recall_and_forget(tmp_path, capsys):
    from claimclear_memory.__main__ import main
    db = str(tmp_path / "cli.db")

    def cli(*args):
        code = main(["--db", db, *args])
        return code, capsys.readouterr()
    assert cli("consent", "u_cli")[0] == 0
    MemoryStore(db).for_user("u_cli").remember_conversation(R3, case_id="case_a")
    code, out = cli("status", "u_cli")
    assert code == 0 and json.loads(out.out)["episodes"] == 1
    assert json.loads(cli("recall", "u_cli", "proportionate")[1].out)[0]["case_id"] == "case_a"
    assert "Asked about" in cli("episodes", "u_cli")[1].out
    assert json.loads(cli("forget", "u_cli")[1].out)["episodes"] == 1
    code, out = cli("status", "bad user!")
    assert code == 2 and "INVALID_USER" in out.err
