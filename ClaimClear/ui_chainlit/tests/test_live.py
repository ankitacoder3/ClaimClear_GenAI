"""End to end through the Chainlit handlers with the real services: the five MCP servers, Member 2's case store,
Member 3's review graph and answerer, and the configured model (OpenRouter key in ClaimClear/.env). Off by default:

    CLAIMCLEAR_LIVE=1 ../.venv-agents/Scripts/python -m pytest tests -m live -s       (servers up first)

Uploads four documents of the dev case gen-dev-147e01 under neutral names (nothing in a name gives away what a
document is). They are identified from their content, the review runs by itself, and then the user asks two
questions. The model's wording varies, so the checks are on what must hold.
"""
from __future__ import annotations

import os
import shutil
from types import SimpleNamespace

import pytest

import app
from conftest import UI, in_chat

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("CLAIMCLEAR_LIVE") != "1", reason="set CLAIMCLEAR_LIVE=1 (servers up)")]

UPLOADS = UI.parent / "var" / "test_upload"          # bill, letter and schedule of gen-dev-147e01, and a wording
FILES = ["doc_a.pdf", "doc_b.pdf", "doc_c.pdf", "doc_d.pdf"]
QUESTIONS = ["How much did the insurer pay, and is any deduction disputable?", "Are attendant charges covered?"]


def test_upload_review_and_ask(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "APP", {})                              # build the real toolkit, model and graph
    uploads = []
    for name in FILES:
        shutil.copy(UPLOADS / name, tmp_path / name)
        uploads.append(SimpleNamespace(path=str(tmp_path / name), name=name))

    async def scenario(rec):
        try:
            await app.start()
            await app.on_message(SimpleNamespace(content="", elements=uploads))
            for q in QUESTIONS:
                await app.on_message(SimpleNamespace(content=q, elements=[]))
            rec.chat = dict(app.cl.user_session.get("chat"))
        finally:
            if app.APP.get("cm"):
                await app.APP["cm"].__aexit__(None, None, None)
    rec = in_chat(scenario)

    for s in rec.steps.values():                                     # shown with -s
        if s.get("type") != "assistant_message":
            print(f"[{s.get('name')}] {str(s.get('output'))[:300]}")
    for m in rec.messages():
        print("MESSAGE:", m[:700].replace("\n", " | "))

    read = next(s for s in rec.tool_steps() if s["name"] == "Reading your documents")
    lines = dict(line.split(": ", 1) for line in read["output"].splitlines())   # neutral names: typed from content
    assert [lines[n].split(":")[0] for n in FILES] == ["bill", "settlement letter", "policy schedule", "policy wording"]
    assert rec.chat["review_case"] == rec.chat["case_id"]           # the review ran on the chat's own case
    assert any(m.startswith("### What I found") for m in rec.messages())   # the verdict table
    answers = rec.messages()[-2:]
    assert "7,125" in answers[0]                                     # paid, as printed in the letter
    assert "attendant" in answers[1].lower()
