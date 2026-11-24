"""The Chainlit handlers in app.py, run inside a real Chainlit chat context with a recording emitter.

One brain: questions go to Member 3's answerer (claimclear_graph.chat.stream_answer), uploads are stored and
identified here, and the review graph starts once a bill, a settlement letter and the policy number are there.
What is checked is what the browser would receive and what the answerer was given.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app
from conftest import BILL, LETTER, FakeToolkit, ScriptedModel, in_chat, say

SCHEDULE = ["POLICY SCHEDULE\nPolicy No. AS/2025/658678/79"]


@pytest.fixture
def ui(monkeypatch):
    """app.py with a scripted model and a fake toolkit in place of the real ones (``ready()`` returns them)."""
    def setup(script=(), identities=(), toolkit=None):
        model = ScriptedModel(script=list(script), identities=list(identities))
        tk = toolkit or FakeToolkit({"DOC-1": BILL, "DOC-2": LETTER}, names={"DOC-1": "bill.pdf", "DOC-2": "letter.pdf"})
        monkeypatch.setattr(app, "APP", {"llm": model, "toolkit": tk})
        return model, tk
    return setup


def system_prompt(model) -> str:
    return model.seen[-1][0].content


def in_case(case_id="CASE-T1"):
    async def scenario_start(rec):
        await app.start()
        app.cl.user_session.get("chat")["case_id"] = case_id
    return scenario_start


def upload(tmp_path, monkeypatch, names):
    """Stand in for the case store: the uploads become DOC-1, DOC-2... of CASE-NEW."""
    async def fake_store(case_id, files):
        return {"case_id": "CASE-NEW", "documents": [{"path": str(p), "document_id": f"DOC-{i}"}
                                                     for i, (p, _) in enumerate(files, 1)]}
    monkeypatch.setattr(app, "store_files", fake_store)
    elements = []
    for n in names:
        (tmp_path / n).write_bytes(b"%PDF-")
        elements.append(SimpleNamespace(path=str(tmp_path / n), name=n))
    return elements


def test_welcome_message_names_the_model_and_asks_for_the_documents(ui):
    ui()
    rec = in_chat(lambda rec: app.start())
    (welcome,) = rec.messages()
    assert "Upload your hospital bill, the insurer's settlement letter" in welcome
    assert "_Model: scripted-test-model_" in welcome


def test_before_any_upload_the_answerer_is_told_nothing_is_there(ui):
    model, _ = ui([say("Please upload your documents first.")])

    async def scenario(rec):
        await app.start()
        await app.ask("Was my claim settled right?")
    rec = in_chat(scenario)
    assert "Nothing uploaded yet: ask the user to upload the hospital bill" in system_prompt(model)
    assert rec.messages()[-1] == "Please upload your documents first."
    assert len(rec.tokens) > 1                                                     # streamed, not sent at once


def test_partial_uploads_say_what_is_missing(ui):
    model, tk = ui([say("I have your bill. Please upload the settlement letter.")])
    tk.meta["DOC-1"].update(role="bill", summary="City Eye Hospital final bill")

    async def scenario(rec):
        await in_case()(rec)
        await app.ask("Can you check my claim?")
    rec = in_chat(scenario)
    prompt = system_prompt(model)
    assert "bill.pdf: bill, 2 page(s): City Eye Hospital final bill" in prompt
    assert ("Still needed for a settlement check: the insurer's settlement letter (what was paid and deducted); "
            "the policy number (upload the policy schedule).") in prompt
    assert ("search_clauses", "Can you check my claim?", "GODHLIP24179V022324", "CASE-T1") in tk.calls  # case's wording
    assert ("get_document_text", "CASE-T1", "DOC-1", []) in tk.calls              # his records index read the bill
    assert rec.messages()[-1] == "I have your bill. Please upload the settlement letter."


def test_uploads_are_stored_identified_and_the_review_starts_when_ready(ui, monkeypatch, tmp_path):
    started = []
    model, tk = ui([say("Here is what I found.")], identities=[
        {"type": "bill", "summary": "City Eye Hospital final bill"},
        {"type": "settlement_letter", "summary": "Claim settlement advice"},
        {"type": "policy_schedule", "summary": "Policy schedule", "policy_no": "AS/2025/658678/79"}],
        toolkit=FakeToolkit({"DOC-1": BILL, "DOC-2": LETTER, "DOC-3": SCHEDULE},
                            names={"DOC-1": "a.pdf", "DOC-2": "b.pdf", "DOC-3": "c.pdf"}))

    class Graph:
        async def aget_state(self, cfg):
            return SimpleNamespace(values={"case_id": "CASE-NEW"})
    app.APP["graph"] = Graph()

    async def fake_review(case):
        started.append(case["policy_no"])
        app.cl.user_session.get("chat")["review_case"] = app.cl.user_session.get("chat")["case_id"]
    monkeypatch.setattr(app, "start_review", fake_review)
    files = upload(tmp_path, monkeypatch, ["a.pdf", "b.pdf", "c.pdf"])

    async def scenario(rec):
        await app.start()
        await app.on_message(SimpleNamespace(content="", elements=files))
    rec = in_chat(scenario)
    (store_step,) = [s for s in rec.tool_steps() if s["name"] == "Storing your documents"]
    assert store_step["output"] == "a.pdf\nb.pdf\nc.pdf"
    (read,) = [s for s in rec.tool_steps() if s["name"] == "Reading your documents"]
    assert read["output"].splitlines()[1] == "b.pdf: settlement letter: Claim settlement advice"
    assert started == ["AS/2025/658678/79"]                                        # from the schedule
    assert rec.messages()[-1] == "Here is what I found."                           # then the implicit question


def test_no_review_until_the_letter_is_there(ui, monkeypatch, tmp_path):
    started = []
    ui([say("Please upload the settlement letter.")], identities=[{"type": "bill", "summary": "A bill"}],
       toolkit=FakeToolkit({"DOC-1": BILL}, names={"DOC-1": "a.pdf"}))
    monkeypatch.setattr(app, "start_review", lambda case: started.append(case))
    files = upload(tmp_path, monkeypatch, ["a.pdf"])

    async def scenario(rec):
        await app.start()
        await app.on_message(SimpleNamespace(content="", elements=files))
    in_chat(scenario)
    assert started == []


def test_start_review_runs_the_graph_on_the_chats_case(ui, monkeypatch):
    ui()
    runs = []

    async def fake_advance(inp):
        runs.append(inp)
    monkeypatch.setattr(app, "advance", fake_advance)

    async def scenario(rec):
        await in_case("CASE-NEW")(rec)
        await app.start_review({"policy_no": "AS/1", "documents": [{"document_id": "DOC-1"}]})
        assert app.cl.user_session.get("chat")["review_case"] == "CASE-NEW"
    rec = in_chat(scenario)
    assert runs == [{"case_id": "CASE-NEW"}]
    assert rec.messages()[-1].startswith("I have your bill, settlement letter and policy")


def test_after_the_review_questions_use_its_state(ui, monkeypatch):
    model, _ = ui([say("The proportionate deduction may be disputable.")])
    audit = {"insurer_paid": "79451", "policy_payable": "92197", "rows": []}

    class Graph:
        async def aget_state(self, cfg):
            return SimpleNamespace(values={"case_id": "CASE-T1", "letter_audit": audit})
    app.APP["graph"] = Graph()

    async def scenario(rec):
        await in_case()(rec)
        app.cl.user_session.get("chat")["review_case"] = "CASE-T1"
        await app.ask("Is the proportionate deduction right?")
    rec = in_chat(scenario)
    prompt = system_prompt(model)
    assert '"insurer_paid": "79451"' in prompt and '"policy_payable": "92197"' in prompt
    assert "The settlement check has run" in prompt
    assert rec.messages()[-1] == "The proportionate deduction may be disputable."


def test_an_invented_amount_is_withdrawn(ui):
    ui([say("You will get ₹12,345 back.")])

    async def scenario(rec):
        await in_case()(rec)
        await app.ask("How much will I get back?")
    rec = in_chat(scenario)
    assert "12,345" not in rec.messages()[-1]                     # his figure check replaced the answer


def test_follow_up_questions_get_the_history(ui):
    model, _ = ui([say("Two documents."), say("Yes, the letter.")])

    async def scenario(rec):
        await in_case()(rec)
        await app.ask("What did I upload?")
        await app.ask("Is one of them a letter?")
    in_chat(scenario)
    texts = [m.content for m in model.seen[-1]]
    assert "What did I upload?" in texts and "Two documents." in texts


def test_failed_store_is_shown_and_nothing_is_kept(ui, monkeypatch, tmp_path):
    ui([say("Nothing is uploaded yet.")])

    async def failing_store(case_id, paths):
        return {"error": "file type not allowed"}
    monkeypatch.setattr(app, "store_files", failing_store)
    f = tmp_path / "x"
    f.write_bytes(b"MZ")

    async def scenario(rec):
        await app.start()
        await app.on_message(SimpleNamespace(content="", elements=[SimpleNamespace(path=str(f), name="tool.exe")]))
        assert app.cl.user_session.get("chat") == {"case_id": "", "review_case": "", "security_flags": [], "reference_key": ""}
    rec = in_chat(scenario)
    (store_step,) = [s for s in rec.tool_steps() if s["name"] == "Storing your documents"]
    assert store_step["output"] == "failed: file type not allowed"


def test_the_chat_log_has_one_line_per_event(ui, monkeypatch, tmp_path, caplog):
    started = []
    ui([say("Please upload the settlement letter.")], identities=[{"type": "bill", "summary": "A bill"}],
       toolkit=FakeToolkit({"DOC-1": BILL}, names={"DOC-1": "a.pdf"}))
    monkeypatch.setattr(app, "start_review", lambda case: started.append(case))
    files = upload(tmp_path, monkeypatch, ["a.pdf"])

    async def scenario(rec):
        await app.start()
        await app.on_message(SimpleNamespace(content="", elements=files))
    with caplog.at_level("INFO", logger="claimclear.chat"):
        in_chat(scenario)
    events = [r.getMessage().split(" ")[1] for r in caplog.records if r.name == "claimclear.chat"]
    assert events == ["chat_start", "upload", "identified", "readiness", "question", "answer"]
    readiness = next(r.getMessage() for r in caplog.records if " readiness " in r.getMessage())
    assert '"ready": false' in readiness and "settlement letter" in readiness


def test_an_error_is_logged_and_shown_not_left_hanging(ui, monkeypatch, caplog):
    ui()

    async def broken(question):
        raise RuntimeError("servers are down")
    monkeypatch.setattr(app, "ask", broken)

    async def scenario(rec):
        await app.start()
        await app.on_message(SimpleNamespace(content="Hello?", elements=[]))
    with caplog.at_level("INFO", logger="claimclear.chat"):
        rec = in_chat(scenario)
    assert rec.messages()[-1].startswith("Something went wrong (RuntimeError: servers are down).")
    assert any(r.levelname == "ERROR" and r.exc_info for r in caplog.records)
