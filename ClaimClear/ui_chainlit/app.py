"""ClaimClear in Chainlit: the chat UI (see additional_resources/member4_ui_security_deployment/ui_options.md).

Run (with the five MCP servers already up, e.g. `python start.py --servers-only`):

    cd ui_chainlit
    ../.venv-agents/Scripts/chainlit run app.py --port 8001 -h      (Windows)

One brain: Member 3's orchestration. This file only handles uploads and shows what his code does:
* uploaded files  -> Member 2's case store (store_docs), with the user's file names; each new file is identified
                    (type, summary, policy number; identify.py) and a policy wording is indexed
* once a bill, a settlement letter and the policy number are there -> Member 3's review graph runs on the chat's case
                    (steps, verdict table, questions, approve or don't file)
* every question  -> Member 3's answerer (claimclear_graph.chat.stream_answer), with the review's state when it has
                    run and a list of the uploads (what is there, what is still missing)
* sample cases    -> the same review graph on a sample case; questions then go to that case
Log: var/logs/chat.log (CLAIMCLEAR_CHAT_LOG), one line per event per chat: uploads, identification, each review
step, the review waiting for the user, its outcome, each question and what answered it, and errors with tracebacks.

Tests (about 3 s; no servers, model or browser):  ../.venv-agents/Scripts/python -m pytest tests
End to end with the servers and the model:        CLAIMCLEAR_LIVE=1 ../.venv-agents/Scripts/python -m pytest tests -m live
"""
from __future__ import annotations

import functools
import json
import logging
import logging.handlers
import os
import sys
import uuid
from pathlib import Path

import chainlit as cl
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from claimclear_graph import chat
from claimclear_graph.extraction import llm_extractor
from claimclear_graph.gateway import HumanApprovalGateway, issue_token, text_sha256
from claimclear_graph.graph import build_claimclear_graph, initial_state
from claimclear_graph.services import Services
from claimclear_graph.webapp.server import REPO, SAMPLES, upload_case
from claimclear_tools import ClaimClearToolError, ClaimClearToolkit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # ClaimClear/security
import security  # noqa: E402
from security import consistency_check  # noqa: E402

import findings
import store_docs
from case_status import documents_block, review_readiness
from identify import identify_documents
from store_docs import store_files

SAMPLE_DIR = REPO / "development" / "dev_data" / "dataset" / "dev" / "cases"
APP: dict = {}  # shared by every chat: toolkit, model, graph, gate (built once)
LOG = logging.getLogger("claimclear.chat")
LOG_PATH = Path(os.environ.get("CLAIMCLEAR_CHAT_LOG") or REPO / "var" / "logs" / "chat.log")


def setup_log() -> None:
    """One file for the chat and Member 3's graph (the "claimclear" loggers), kept to 3 x 2 MB."""
    parent = logging.getLogger("claimclear")
    if not any(getattr(h, "baseFilename", None) == str(LOG_PATH) for h in parent.handlers):
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        parent.addHandler(handler)
        parent.setLevel(logging.INFO)


def log(event: str, **details) -> None:
    """One line: the chat's session (first 8 characters), the event, and its details as JSON."""
    try:
        session = cl.context.session.id[:8]
    except Exception:
        session = "-"
    LOG.info("%s %s %s", session, event, json.dumps(details, ensure_ascii=False, default=str)[:3000])


def logged(handler):
    """Log any error with its traceback, and tell the user instead of leaving the chat hanging."""
    @functools.wraps(handler)
    async def run(*args, **kwargs):
        try:
            return await handler(*args, **kwargs)
        except Exception as exc:
            LOG.exception("%s error in %s", getattr(getattr(cl.context, "session", None), "id", "-")[:8],
                          handler.__name__)
            await cl.Message(content=f"Something went wrong ({type(exc).__name__}: {str(exc)[:200]}). "
                                     f"The details are in {LOG_PATH.name}.").send()
    return run


def load_dotenv() -> None:
    """Model settings from ClaimClear/.env (same rule as start.py: real environment variables win)."""
    path = REPO / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def ready() -> dict:
    if not APP:
        load_dotenv()
        setup_log()
        cm = ClaimClearToolkit()
        tk = await cm.__aenter__()          # kept open for the life of the process
        llm = chat.chat_model_from_env()
        graph = build_claimclear_graph(Services(toolkit=tk, extractor=llm_extractor(llm) if llm else None),
                                       checkpointer=MemorySaver())
        APP.update(cm=cm, toolkit=tk, llm=llm, graph=graph, gate=HumanApprovalGateway(graph), access=None)
        if llm is not None:                                   # which models the key may use (one tiny call each)
            from security import model_access
            local = "openrouter.ai" not in str(getattr(llm, "openai_api_base", "") or "openrouter.ai")
            APP["access"] = await model_access.check(getattr(llm, "model_name", ""), local)
            if APP["access"]["guard_fallback"]:
                security.checks.UNAVAILABLE.add("safeguard")
            log("model_access", **APP["access"])
    return APP


def cfg() -> dict:
    return {"configurable": {"thread_id": cl.user_session.get("thread_id")}}


# --------------------------------------------------------------------------- start of a chat

@cl.on_chat_start
@logged
async def start() -> None:
    app = await ready()
    log("chat_start", model=chat.describe_model(app["llm"]) if app["llm"] else None)
    # this chat: its case in the store, and the review thread once the review has run on that case
    cl.user_session.set("chat", {"case_id": "", "review_case": "", "security_flags": []})
    cl.user_session.set("history", [])                  # (question, answer) pairs for the answerer
    model = chat.describe_model(app["llm"]) if app["llm"] else "no model configured"
    access, model_id = app.get("access") or {}, getattr(app["llm"], "model_name", "")
    if access and not access.get("main_ok", True):           # the key can't use the main model: nothing works
        from security import model_access
        await cl.Message(content=model_access.main_model_message(model_id, access)).send()
        return
    actions = [cl.Action(name="sample", payload={"name": n}, label=label)
               for n, label in SAMPLES if (SAMPLE_DIR / n).is_dir()]
    note = ""
    if access.get("guard_fallback"):
        from security import model_access
        note = "\n\n" + model_access.guard_message(model_id, access)
    await cl.Message(
        content="**ClaimClear** checks your health-insurance claim settlement.\n\n"
                "Upload your hospital bill, the insurer's settlement letter, your policy schedule and policy wording "
                "with the 📎, and ask me anything about them. Or run a sample review below."
                f"\n\n_Model: {model}_" + note,
        actions=actions).send()


@cl.action_callback("sample")
@logged
async def on_sample(action: cl.Action) -> None:
    folder = SAMPLE_DIR / action.payload["name"]
    log("sample", name=action.payload["name"])
    await cl.Message(content=f"Running the sample: **{action.label}**").send()
    result = await upload_case([(p, "") for p in sorted(folder.iterdir()) if p.is_file()])
    if result.get("case_id"):                                  # questions in this chat now go to the sample's case
        meta = cl.user_session.get("chat")
        meta["case_id"] = meta["review_case"] = result["case_id"]
    await run_case(result)


# --------------------------------------------------------------------------- messages: files and questions

@cl.on_message
@logged
async def on_message(msg: cl.Message) -> None:
    access = (await ready()).get("access") or {}
    if access and not access.get("main_ok", True):           # the key can't use the main model: say so, do nothing
        from security import model_access
        await cl.Message(content=model_access.main_model_message(getattr(APP["llm"], "model_name", ""), access)).send()
        return
    files = [(Path(e.path), e.name) for e in (msg.elements or []) if getattr(e, "path", None)]
    if files:
        await take_uploads(files)
    question = msg.content.strip() or ("What have I uploaded, and what else do you need?" if files else "")
    if question:
        await ask(question)


async def take_uploads(files: list[tuple[Path, str]]) -> None:
    """Store, identify, and start the review once everything it needs is there."""
    app, meta = await ready(), cl.user_session.get("chat")
    if not meta.get("reference_key"):              # demo data: which dataset case, from the files as uploaded
        meta["reference_key"] = store_docs.dataset_reference_key([store_docs.file_document_id(p) for p, _ in files])
    if security.enabled():                         # T1: checked and cleaned before anything is stored
        async with cl.Step(name="Security check", type="tool") as step:
            guards = security.build(app["llm"])
            checks = await security.check_files(app["toolkit"], guards, files)
            if any(g.errors for g in guards):                 # a guard that can't run finds nothing: say so
                log("security_guard_errors", errors={g.name: [len(g.errors), g.errors[0]] for g in guards if g.errors})
                await cl.Message(content=security.guard_problems(guards)).send()
            step.output = "\n".join(
                f"{c.name}: " + ("not used" if c.blocked else "cleaned" if c.findings else "clean")
                + (f", {len(c.findings)} finding(s)" if c.findings else "")
                + (f" ({c.error})" if c.error else "") for c in checks)
            found = [f.line() for c in checks for f in c.findings]
            meta["security_flags"] += [f for f in found if f not in meta["security_flags"]]
            log("security_files", files=[{"name": c.name, "findings": [f.line() for f in c.findings],
                                          "removed": len(c.removed), "blocked": c.blocked,
                                          "error": c.error or None} for c in checks])
        if found:
            await cl.Message(content=await security.files_message(app["llm"], checks)).send()
        files = [(c.path, c.name) for c in checks if not c.blocked]
        if not files:
            return
    async with cl.Step(name="Storing your documents", type="tool") as step:
        result = await store_files(meta["case_id"], files)
        log("upload", case_id=result.get("case_id") or meta["case_id"], files=[n for _, n in files],
            error=result.get("error"))
        if result.get("error"):
            step.output = f"failed: {result['error']}"
            return
        meta["case_id"] = result["case_id"]
        step.output = "\n".join(name for _, name in files)
    if app["llm"]:
        async with cl.Step(name="Reading your documents", type="tool") as step:
            found = await identify_documents(app["llm"], app["toolkit"], meta["case_id"],
                                             [d["document_id"] for d in result["documents"]])
            step.output = "\n".join(f"{d['name']}: " + (f"couldn't read it ({d['error']})" if d.get("error") else
                                    f"{d['type'].replace('_', ' ')}: {d['summary']}"
                                    + (f" ({d['note']})" if d.get("note") else "")) for d in found)
            log("identified", documents=[{k: d.get(k) for k in ("name", "type", "policy_no", "note", "error")}
                                         for d in found])
        docs = meta.setdefault("facts", {})                   # every document's fact sheet, for the checks below
        docs.update({d["document_id"]: d for d in found if not d.get("error")})
        await settle_letters(meta)
    case = await app["toolkit"].list_case_documents(meta["case_id"])
    readiness = review_readiness(case)
    log("readiness", case_id=meta["case_id"], **readiness)
    if meta["review_case"] != meta["case_id"] and readiness["ready"]:
        await start_review(case)


async def settle_letters(meta: dict) -> None:
    """With more than one settlement letter, check the current one and keep the others as earlier claims (bug #3);
    with the defences on, check that the documents agree (consistency_check)."""
    docs = list(meta.get("facts", {}).values())
    pick = consistency_check.pick_current_letter(docs)
    if pick["earlier"]:
        by_id = {d["document_id"]: d for d in docs}
        if pick["ambiguous"]:                                  # code can't tell: ask, with one button per letter
            ans = await cl.AskActionMessage(
                content="You uploaded more than one settlement letter. Which claim should I check?",
                actions=[cl.Action(name="letter", payload={"id": i}, label=by_id[i]["name"])
                         for i in [pick["current"], *pick["earlier"]]], timeout=300).send()
            chosen = (ans or {}).get("payload", {}).get("id") or pick["current"]
            pick = {**pick, "current": chosen, "reason": "you chose it",
                    "earlier": [i for i in [pick["current"], *pick["earlier"]] if i != chosen]}
        for i in pick["earlier"]:
            await store_docs.describe_document(meta["case_id"], i, "other", consistency_check.earlier_summary(by_id[i]))
            by_id[i]["type"] = "earlier_settlement_letter"
        log("letters", current=pick["current"], earlier=pick["earlier"], reason=pick["reason"])
        await cl.Message(content=f"I'm checking **{by_id[pick['current']]['name']}** ({pick['reason']}); "
                                 + ", ".join(by_id[i]["name"] for i in pick["earlier"])
                                 + " I've kept as earlier claims.").send()
    if security.enabled():
        found = consistency_check.check(docs, pick["current"])
        new = [f.line() for f in found if f.line() not in meta["security_flags"]]
        if new:
            meta["security_flags"] += new
            log("consistency", findings=new)
            await cl.Message(content=consistency_check.message(found)).send()


async def start_review(case: dict) -> None:
    """Member 3's review graph on the chat's own case (the documents are typed, the policy number is set)."""
    meta = cl.user_session.get("chat")
    schedule = next((d.get("facts") or {} for d in meta.get("facts", {}).values() if d.get("type") == "policy_schedule"),
                    {})
    key = (meta.get("reference_key") or store_docs.dataset_reference_key([d["document_id"] for d in case.get("documents", [])])
           or store_docs.reference_key_by_policy(case.get("policy_no") or "", schedule))
    if key:                                                    # demo data only (see store_docs.dataset_reference_key)
        await store_docs.set_policy(meta["case_id"], case["policy_no"], key)
    meta["review_case"] = meta["case_id"]
    log("review_start", case_id=meta["case_id"], policy_no=case.get("policy_no"), reference_key=key or None)
    await cl.Message(content="I have your bill, settlement letter and policy, so I'm checking the settlement now.\n\n"
                             + store_docs.policy_source_note(case.get("policy_no") or "", schedule or None)).send()
    cl.user_session.set("thread_id", f"cl-{uuid.uuid4().hex[:12]}")
    cl.user_session.set("shown", False)
    cl.user_session.set("outcome", None)
    state = initial_state(meta["case_id"])
    if meta.get("security_flags"):                           # the guard's findings travel with the review (T1)
        state["security_flags"] = list(meta["security_flags"])
    await advance(state)


async def ask(question: str) -> None:
    """Member 3's answerer, with the review's state when it has run on this case, and the list of uploads."""
    app, meta = await ready(), cl.user_session.get("chat")
    case = await app["toolkit"].list_case_documents(meta["case_id"]) if meta["case_id"] else {}
    reviewed = bool(meta["case_id"]) and meta["review_case"] == meta["case_id"]
    if reviewed:
        state = (await app["graph"].aget_state(cfg())).values
    else:
        state = {"case_id": meta["case_id"]} if meta["case_id"] else {}
        if meta["case_id"]:                                   # search the case's own wording (uploaded, else standard)
            try:
                state["policy"] = {"wording_uin": (await app["toolkit"].get_policy_wording(meta["case_id"]))["wording_uin"]}
            except ClaimClearToolError:
                pass
    history = cl.user_session.get("history") or []
    log("question", case_id=meta["case_id"], reviewed=reviewed, question=question)
    if security.enabled():                                    # T2: the answerer never sees an injected message
        guards = security.build(app["llm"])
        found = await security.check_chat(guards, question)
        if any(g.errors for g in guards) and not cl.user_session.get("guard_warned"):   # once per chat
            cl.user_session.set("guard_warned", True)
            log("security_guard_errors", errors={g.name: [len(g.errors), g.errors[0]] for g in guards if g.errors})
            await cl.Message(content=security.guard_problems(guards)).send()
        if found:
            meta["security_flags"] = meta.get("security_flags", []) + [f.line() for f in found]
            log("security_chat", findings=[f.line() for f in found])
            reply = await security.chat_reply(app["llm"], question, found)
            await cl.Message(content=reply).send()
            cl.user_session.set("history", (history + [(question, reply)])[-12:])
            return
    out, text = cl.Message(content=""), ""
    async for ev in chat.stream_answer(question, state, app["toolkit"], app["llm"], await records(meta["case_id"], case),
                                       history, documents=documents_block(case, reviewed, meta.get("security_flags") or [])):
        if ev["type"] == "delta":
            text += ev["text"]
            await out.stream_token(ev["text"])
        elif ev["type"] == "retract":                         # his figure check withdrew the answer; a safe one follows
            log("answer_withdrawn", reason=ev.get("reason"))
            text, out.content = "", ""
            await out.update()
        elif ev["type"] == "end":
            log("answer", how=ev.get("how"), sources=ev.get("sources"), chars=len(text))
            if ev.get("sources"):
                async with cl.Step(name="Where this comes from", type="tool") as step:
                    step.output = "\n".join(ev["sources"]) + f"\n(answered by: {ev.get('how')})"
    await out.send()
    cl.user_session.set("history", (history + [(question, text)])[-12:])


async def records(case_id: str, case: dict):
    """The answerer's searchable copy of the case's documents (visible text), rebuilt when the uploads change."""
    if not case_id:
        return None
    key = (case_id, len(case.get("documents", [])))
    cached = cl.user_session.get("records")
    if not cached or cached[0] != key:
        cached = (key, await chat.load_records((await ready())["toolkit"], case_id))
        cl.user_session.set("records", cached)
    return cached[1]


# --------------------------------------------------------------------------- showing the review

async def run_case(result: dict) -> None:
    if not result or result.get("error"):
        await cl.Message(content=f"I couldn't take those documents: {result.get('error') if result else 'no reply'}").send()
        return
    docs = ", ".join(f"{d.get('name')} ({d.get('role')})" for d in result.get("documents", []))
    await cl.Message(content=f"Case for policy **{result.get('policy_no')}**: {docs}").send()
    cl.user_session.set("thread_id", f"cl-{uuid.uuid4().hex[:12]}")
    cl.user_session.set("shown", False)
    cl.user_session.set("outcome", None)
    ex = result.get("extraction") or {}
    await advance(initial_state(result["case_id"], claim=ex.get("claim"), letter=ex.get("letter")))


async def advance(inp) -> None:
    """Run the graph until it ends or pauses; show each agent's step as it finishes."""
    app, flags = await ready(), (cl.user_session.get("chat") or {}).get("security_flags") or []
    config = cfg() if not flags else {**cfg(), "tags": ["security_issue"],       # visible in traces when tracing is on
                                      "metadata": {"security_flags": len(flags)}}
    async with cl.Step(name="Agents at work", type="run") as run:
        async for update in app["graph"].astream(inp, config, stream_mode="updates"):
            for node, change in update.items():
                if isinstance(change, dict):
                    for line in change.get("trace", []):
                        log("review_step", node=node, line=line)
                        who, _, text = line.partition(":")
                        async with cl.Step(name=who.strip() or node, parent_id=run.id) as step:
                            step.output = text.strip()
    await report()


async def report() -> None:
    """Show what the user needs now: questions, the verdicts, the grievance draft, or the outcome."""
    app = await ready()
    graph, gate = app["graph"], app["gate"]
    st = (await graph.aget_state(cfg())).values

    questions = await gate.pending_questions(cfg())
    if questions:
        log("review_waiting", waiting_for="answers", questions=[q["question_id"] for q in questions])
        answers = {}
        for q in questions:
            reply = await cl.AskUserMessage(
                content=q.get("text", "Please answer:") + "\n\n_The review is paused: your next message is the answer "
                                                          "to this question._", timeout=600).send()
            text = (reply or {}).get("output", "").strip()
            log("review_answer", question=q["question_id"], answered=bool(reply), answer=text[:200])
            answers[q["question_id"]] = (text.lower() in ("yes", "y", "true", "1")
                                         if q["question_id"] == "Q-ROOM-PRICING" else (text or None))
        pending = {q["question_id"]: None for q in questions}
        await advance(Command(resume={**pending, **answers}))
        return

    if st.get("explanation") and st.get("critic_stage") == "draft_passed" and not cl.user_session.get("shown"):
        cl.user_session.set("shown", True)
        audit = st.get("letter_audit") or {}
        log("findings", insurer_paid=audit.get("insurer_paid"), policy_payable=audit.get("policy_payable"),
            disputable=audit.get("disputable_amount"), rows={r["row_id"]: r.get("verdict") for r in audit.get("rows", [])})
        message, rows = findings.render(st)
        await cl.Message(content=message).send()
        if rows:
            async with cl.Step(name="Row by row", type="tool") as step:
                step.output = "\n".join(f"- {r}" for r in rows)

    if await gate.is_paused_for_approval(cfg()):
        g = st.get("grievance") or {}
        log("review_waiting", waiting_for="approval", rows=g.get("row_ids"))
        res = await cl.AskActionMessage(
            content=f"### Grievance draft\nNothing is sent without your approval. _The review is paused until you "
                    f"choose below._\n\n```\n{g.get('text', '')}\n```",
            actions=[cl.Action(name="approve", payload={"d": "approve"}, label="Approve and file"),
                     cl.Action(name="reject", payload={"d": "reject"}, label="Don't file")],
            timeout=900).send()
        if res and res.get("payload", {}).get("d") == "approve":
            decision = {"decision": "approve", "approval_token": issue_token(text_sha256(g.get("text", "")),
                                                                            gate.gate_secret)}
        else:
            decision = {"decision": "reject", "reason": "declined in the chat" if res else "no answer in time"}
        log("review_decision", decision=decision["decision"], reason=decision.get("reason"))
        await advance(Command(resume=decision))
        return

    if st.get("outcome") and cl.user_session.get("outcome") != st["outcome"]:
        cl.user_session.set("outcome", st["outcome"])
        log("review_outcome", outcome=st["outcome"], reference=(st.get("submission") or {}).get("reference"))
        sub = st.get("submission") or {}
        extra = f" Reference: {sub.get('reference')}." if sub.get("reference") else ""
        await cl.Message(content=f"**Outcome:** {st['outcome'].replace('_', ' ')}.{extra}").send()
