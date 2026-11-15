"""The ClaimClear web UI: upload documents, watch the agents work live, answer, approve, and chat.

    python -m claimclear_graph.webapp [--port 8000]      (start.py runs it after starting the MCP servers)

* ``GET /``                the page (``static/index.html``)
* ``GET /api/status``      MCP servers up?, chat model on?, sample cases
* ``POST /api/upload``     multipart ``files`` (+ optional ``roles``): stores a new case (``scripts/upload_case.py``)
* ``POST /api/sample``     ``{"name": "syn-dev-005"}``: the same, with a development case's documents
* ``POST /api/shutdown``   the page's Close button: stop the UI (start.py then stops the servers)
* ``GET/POST /api/model``  the model settings dialog: which model is used; save a new one after a live test
* ``POST /api/clear``      the Clear my data button: delete uploads, filings and every chat now
* ``WS /ws``               one live session per browser tab:

  ==========================================  ================================================================
  page -> server                              server -> page
  ==========================================  ================================================================
  ``{"type": "analyse", "upload": {...}}``     ``step`` (each agent step as it finishes), ``questions``,
  ``{"type": "answers", "answers": {...}}``    ``explanation`` (sentences, rows, totals), ``grievance`` (text),
  ``{"type": "decision", "decision", "text"}`` ``outcome``, ``answer`` (chat reply), ``busy``, ``error``,
  ``{"type": "ask", "text"}``                  ``session`` (thread id, for resuming after a page reload)
  ``{"type": "resume", "thread_id"}``
  ==========================================  ================================================================

**Lifetime.** The UI stays up as long as at least one page is open. When the last page disconnects and no page
reconnects within ``CLAIMCLEAR_UI_GRACE`` seconds (default 15, enough for a reload), the UI stops, and
``start.py`` then stops the MCP servers. Before the first page connects it waits indefinitely.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from claimclear_tools import ClaimClearToolkit
from claimclear_tools.config import find_repo, server_python
from langgraph.types import Command
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .. import chat
from ..extraction import llm_extractor
from ..gateway import HumanApprovalGateway, issue_token, text_sha256
from ..graph import build_claimclear_graph, initial_state
from ..services import Services
from ..checkpoints import open_checkpointer
from ..checks import inr
from claimclear_contracts.verdicts import wording_for

REPO = find_repo()
STATIC = Path(__file__).resolve().parent / "static"
PORTS = {"settlement-engine": 8101, "case-records": 8102, "policy-kb": 8103, "insurer-portal": 8104,
         "document-reader": 8105}
SAMPLES = [("syn-dev-005", "Gall-bladder surgery: a disputable deduction (SET-01)"),
           ("syn-dev-019", "Appendicitis: a clean settlement (SET-02)"),
           ("syn-dev-017", "The engine asks you a question (SET-32)"),
           ("gen-dev-147e01", "Another insurer's letter, read from the PDF tables")]
GRACE = float(os.environ.get("CLAIMCLEAR_UI_GRACE", "15"))
ENV_FILE = REPO / ".env"                      # where model settings are saved (tests point it elsewhere)
AGENT_OF = {"Supervisor": "supervisor", "DocumentReader": "document_reader", "PolicyAnalyst": "policy_analyst",
            "SettlementAuditor": "settlement_auditor", "AskUser": "ask_user", "Critic": "critic",
            "Explainer": "explainer", "GrievanceAgent": "grievance_agent", "ApprovalGate": "approval_gate",
            "PortalSubmit": "portal_submit"}


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


async def upload_case(paths: list[tuple[Path, str]]) -> dict:
    """Run the upload helper with the servers' Python (it writes the case store, the servers read it)."""
    args = [f"{p}={role}" if role else str(p) for p, role in paths]
    proc = await asyncio.create_subprocess_exec(server_python(REPO), str(REPO / "scripts" / "upload_case.py"), *args,
                                                cwd=str(REPO), stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    try:
        return json.loads(out.decode("utf-8"))
    except json.JSONDecodeError:
        return {"error": (err.decode("utf-8", "replace") or "upload failed")[-600:]}


# --------------------------------------------------------------------------- one browser tab


LOCAL_KEYS = ("CLAIMCLEAR_LLM_BASE_URL", "CLAIMCLEAR_LOCAL_MODEL")
OPENROUTER_KEYS = ("OPENROUTER_API_KEY", "CLAIMCLEAR_CHAT_MODEL")
AUTO_LOCAL = "CLAIMCLEAR_AUTO_LOCAL"    # "0": start.py doesn't switch to a running local model by itself
MODEL_KEYS = LOCAL_KEYS + OPENROUTER_KEYS + (AUTO_LOCAL,)
PROVIDERS = {  # provider -> (key variable or None, model variable, default model, default base URL)
    "local": (None, "CLAIMCLEAR_LOCAL_MODEL", chat.LOCAL_DEFAULT_MODEL, "http://127.0.0.1:11434/v1"),
    "openrouter": ("OPENROUTER_API_KEY", "CLAIMCLEAR_CHAT_MODEL", chat.OPENROUTER_DEFAULT_MODEL, None),
}


def current_provider() -> str:
    """The provider ``chat.chat_model_from_env`` uses: a local model first, then OpenRouter."""
    if os.environ.get("CLAIMCLEAR_LLM_BASE_URL"):
        return "local"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    return "none"


def write_env(values: dict[str, str], remove: tuple = ()) -> None:
    """Set ``values`` and delete ``remove`` in ``.env`` (kept on this computer, git-ignored); other lines stay."""
    path = ENV_FILE
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    drop = set(values) | set(remove)
    lines = [ln for ln in lines if ln.split("=", 1)[0].strip() not in drop]
    lines += [f"{k}={v}" for k, v in values.items() if v]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def same_origin(request: Request) -> bool:
    """Refuse state-changing requests from other web sites (the UI only serves this computer)."""
    origin = request.headers.get("origin")
    return origin is None or origin.split("://", 1)[-1] == request.headers.get("host")


class Session:
    def __init__(self, app, ws: WebSocket):
        self.app, self.ws = app, ws
        self.thread_id: str | None = None
        self.lock = asyncio.Lock()               # one graph advance at a time; chat answers run alongside
        self.sent: set[str] = set()              # what this page has already been shown for the thread
        self.history: list[tuple[str, str]] = []  # (question, answer) turns of this conversation
        self.records: dict[str, chat.RecordIndex] = {}
        self.replying: asyncio.Task | None = None

    @property
    def cfg(self) -> dict:
        return {"configurable": {"thread_id": self.thread_id}}

    async def send(self, type_: str, **data) -> None:
        try:
            await self.ws.send_text(json.dumps({"type": type_, **data}, ensure_ascii=False, default=str))
        except Exception:
            pass                                  # the page went away; the watchdog handles shutdown

    async def advance(self, inp) -> None:
        """Run the graph until it ends or pauses, sending each agent's step the moment it finishes."""
        await self.send("busy", value=True)
        try:
            async for update in self.app.state.graph.astream(inp, self.cfg, stream_mode="updates"):
                for node, change in update.items():
                    if not isinstance(change, dict):
                        continue
                    for line in change.get("trace", []):
                        who, _, text = line.partition(":")
                        await self.send("step", agent=AGENT_OF.get(who.strip(), node), label=who.strip(), text=text.strip())
            await self.report()
        except PermissionError as exc:
            await self.send("error", text=f"Not filed: {exc}")
        except Exception as exc:
            await self.send("error", text=f"{type(exc).__name__}: {exc}")
        finally:
            await self.send("busy", value=False)

    async def report(self) -> None:
        """Send whatever the user should now see: questions, the explanation, the grievance, the outcome."""
        graph, gate = self.app.state.graph, self.app.state.gate
        snap = await graph.aget_state(self.cfg)
        st = snap.values
        questions = await gate.pending_questions(self.cfg)
        if questions:
            await self.send("questions", questions=questions)
            return
        if st.get("explanation") and st.get("critic_stage") == "draft_passed" and "explanation" not in self.sent:
            self.sent.add("explanation")
            audit = st.get("letter_audit") or {}
            clauses = {c.get("clause_id"): c for c in (st.get("clauses") or {}).values()}
            rows = []
            for r in audit.get("rows", []):
                sentence = next((s for s in (st.get("draft") or {}).get("sentences", []) if s.get("row_ids") == [r["row_id"]]), {})
                cid = (sentence.get("clause_ids") or [None])[0]
                rows.append({"row_id": r["row_id"], "particulars": r.get("particulars"), "insurer": inr(r.get("insurer_amount")),
                             "policy": inr(r.get("policy_amount")), "verdict": r.get("verdict"), "wording": wording_for(r),
                             "clause": cid, "citation": (clauses.get(cid) or {}).get("citation")})
            await self.send("explanation", text=st["explanation"], rows=rows,
                            totals={"paid": inr(audit.get("insurer_paid")), "payable": inr(audit.get("policy_payable")),
                                    "disputable": inr(audit.get("disputable_amount")) if audit.get("disputable_amount") else None})
        if await gate.is_paused_for_approval(self.cfg):
            g = st.get("grievance") or {}
            await self.send("grievance", text=g.get("text"), sha=g.get("text_sha256"), rows=g.get("row_ids"))
            return
        if st.get("outcome") and f"outcome:{st['outcome']}" not in self.sent:
            self.sent.add(f"outcome:{st['outcome']}")
            await self.send("outcome", outcome=st["outcome"], submission=st.get("submission"),
                            status=st.get("grievance_status"), questions=st.get("questions") if st["outcome"] in
                            ("missing_document", "ask_user_for_policy") else None,
                            security_flags=st.get("security_flags", []))

    async def reply(self, question: str, reply_id: str) -> None:
        """Stream one chat answer (``answer_start`` / ``answer_delta`` / ``answer_retract`` / ``answer_end``)."""
        app = self.app
        state = (await app.state.graph.aget_state(self.cfg)).values if self.thread_id else {}
        records = None
        case_id = state.get("case_id")
        if case_id:
            if case_id not in self.records:
                try:
                    self.records[case_id] = await chat.load_records(app.state.toolkit, case_id)
                except Exception:
                    self.records[case_id] = None
            records = self.records[case_id]
        await self.send("answer_start", id=reply_id)
        text = ""
        try:
            async for ev in chat.stream_answer(question, state, app.state.toolkit, app.state.llm, records, self.history):
                if ev["type"] == "delta":
                    text += ev["text"]
                    await self.send("answer_delta", id=reply_id, text=ev["text"])
                elif ev["type"] == "retract":
                    text = ""
                    await self.send("answer_retract", id=reply_id, reason=ev["reason"])
                elif ev["type"] == "end":
                    await self.send("answer_end", id=reply_id, sources=ev["sources"], how=ev["how"])
        except asyncio.CancelledError:
            await self.send("answer_end", id=reply_id, sources=[], how="stopped")
            text += " [stopped]"
        except Exception as exc:
            await self.send("answer_end", id=reply_id, sources=[], how=f"error: {type(exc).__name__}: {exc}")
        self.history = (self.history + [(question, text)])[-10:]

    # ---- messages from the page ----
    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "ask":
            if self.replying and not self.replying.done():
                self.replying.cancel()
            self.replying = asyncio.current_task()
            await self.reply(msg.get("text", ""), msg.get("id") or uuid.uuid4().hex[:8])
            return
        if kind == "stop":
            if self.replying and not self.replying.done():
                self.replying.cancel()
            return
        if kind == "reset":
            self.thread_id, self.sent, self.history = None, set(), []
            await self.send("session", thread_id=None, resumed=False)
            return
        if kind == "resume":
            tid = msg.get("thread_id")
            if msg.get("boot") != self.app.state.boot_id:      # a previous launch: never show its data
                await self.send("session", thread_id=None, resumed=False)
                return
            if tid and (await self.app.state.graph.aget_state({"configurable": {"thread_id": tid}})).values:
                self.thread_id = tid
                await self.send("session", thread_id=tid, resumed=True)
                await self.report()
            return
        async with self.lock:
            if kind == "analyse":
                up = msg.get("upload") or {}
                self.thread_id, self.sent, self.history = f"web-{uuid.uuid4().hex[:12]}", set(), []
                await self.send("session", thread_id=self.thread_id, resumed=False)
                ex = up.get("extraction") or {}
                if not ex and self.app.state.llm is None:
                    await self.send("error", text="These documents couldn't be read automatically here. Add an API key "
                                                  "(OPENROUTER_API_KEY in .env) so the document reader's LLM can read them, "
                                                  "or try one of the sample cases.")
                    return
                await self.advance(initial_state(up["case_id"], claim=ex.get("claim"), letter=ex.get("letter")))
            elif kind == "answers" and self.thread_id:
                answers = {k: (v if v not in ("", None) else None) for k, v in (msg.get("answers") or {}).items()}
                if "Q-ROOM-PRICING" in answers and isinstance(answers["Q-ROOM-PRICING"], str):
                    answers["Q-ROOM-PRICING"] = answers["Q-ROOM-PRICING"].lower() in ("yes", "y", "true", "1")
                await self.advance(Command(resume=answers))
            elif kind == "decision" and self.thread_id:
                if msg.get("decision") == "reject":
                    decision = {"decision": "reject", "reason": msg.get("reason") or "declined in the web UI"}
                else:
                    g = (await self.app.state.graph.aget_state(self.cfg)).values.get("grievance") or {}
                    text = msg.get("text") if msg.get("text") else g.get("text", "")
                    decision = {"decision": "approve", "approval_token": issue_token(text_sha256(text),
                                                                                   self.app.state.gate.gate_secret)}
                    if text != g.get("text"):
                        decision["edited_text"] = text
                await self.advance(Command(resume=decision))


# --------------------------------------------------------------------------- HTTP and WebSocket routes


async def index(request: Request):
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


async def status(request: Request):
    return JSONResponse({"boot": request.app.state.boot_id, "servers": {n: port_open(p) for n, p in PORTS.items()},
                         "chat_model": request.app.state.llm is not None,
                         "model": chat.describe_model(request.app.state.llm),
                         "samples": [{"name": n, "label": label} for n, label in SAMPLES
                                     if (REPO / "data" / "dataset" / "dev" / "cases" / n).is_dir()]})


def safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name or "file").name)[:80]
    return name or "file"


async def upload(request: Request):
    if not same_origin(request):
        return JSONResponse({"error": "refused"}, status_code=403)
    form = await request.form()
    files, roles = form.getlist("files"), form.getlist("roles")
    if not files:
        return JSONResponse({"error": "no files"}, status_code=400)
    tmp = Path(tempfile.mkdtemp(prefix="claimclear_upload_"))
    try:
        paths = []
        for i, f in enumerate(files):
            data = await f.read()
            if len(data) > 25 * 1024 * 1024:
                return JSONResponse({"error": f"{f.filename}: larger than 25 MB"}, status_code=400)
            path = tmp / f"{i:02d}_{safe_name(f.filename)}"
            path.write_bytes(data)
            role = roles[i] if i < len(roles) else ""
            paths.append((path, role))
        result = await upload_case(paths)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if "documents" in result:                    # show the user's own file names
        for d, f in zip(result["documents"], files):
            d["name"] = f.filename
    return JSONResponse(result, status_code=400 if "error" in result else 200)


async def sample(request: Request):
    name = (await request.json()).get("name", "")
    if name not in {n for n, _ in SAMPLES}:
        return JSONResponse({"error": "unknown sample"}, status_code=400)
    folder = REPO / "data" / "dataset" / "dev" / "cases" / name
    result = await upload_case([(p, "") for p in sorted(folder.iterdir()) if p.is_file()])
    return JSONResponse(result, status_code=400 if "error" in result else 200)


async def model_get(request: Request):
    provider = current_provider()
    return JSONResponse({"provider": provider, "model": chat.describe_model(request.app.state.llm),
                         "configured": request.app.state.llm is not None,
                         "key_saved": {p: bool(os.environ.get(k)) for p, (k, _, _, _) in PROVIDERS.items() if k},
                         "base_url": os.environ.get("CLAIMCLEAR_LLM_BASE_URL", ""),
                         "defaults": {p: {"model": m, "base_url": b} for p, (_, _, m, b) in PROVIDERS.items()}})


async def model_set(request: Request):
    """Try the chosen model with a tiny live request; only if it answers, save it to .env and switch to it."""
    if not same_origin(request):
        return JSONResponse({"ok": False, "error": "refused"}, status_code=403)
    body = await request.json()
    provider = body.get("provider", "none")
    values: dict[str, str] = {}
    if provider != "none":
        if provider not in PROVIDERS:
            return JSONResponse({"ok": False, "error": "unknown provider"}, status_code=400)
        key_var, model_var, default_model, default_base = PROVIDERS[provider]
        if key_var:
            key = (body.get("api_key") or "").strip() or os.environ.get(key_var, "")
            if not key:
                return JSONResponse({"ok": False, "error": "Please paste your API key."}, status_code=400)
            values[key_var] = key
        else:
            values["CLAIMCLEAR_LLM_BASE_URL"] = (body.get("base_url") or "").strip() or default_base
        values[model_var] = (body.get("model") or "").strip() or default_model
    saved = {k: os.environ.pop(k) for k in MODEL_KEYS if k in os.environ}
    os.environ.update(values)
    llm = None
    try:
        llm = chat.chat_model_from_env()
        if llm is not None:
            # a tiny reply limit: the test costs almost nothing and fits any credit limit
            await asyncio.wait_for(chat.with_max_tokens(llm, 16).ainvoke("Reply with the single word OK."), timeout=45)
    except Exception as exc:
        for k in MODEL_KEYS:                             # failed: back to the previous settings, nothing saved
            os.environ.pop(k, None)
        os.environ.update(saved)
        msg = str(exc).splitlines()[0][:260] if str(exc) else type(exc).__name__
        for k, v in values.items():                      # never echo a key back
            if k.endswith("_KEY") and v:
                msg = msg.replace(v, "***")
        hint = (" Is the local model running? Start it with start_llm.bat (Windows) or ./start_llm.sh, or run: "
                "ollama pull " + values.get("CLAIMCLEAR_LOCAL_MODEL", "")) if provider == "local" else ""
        if "402" in msg or "credits" in msg.lower():
            hint += (" Your account has too little credit for this model. Add credit with the provider, raise the "
                     "key's credit limit, or choose a cheaper model.")
        return JSONResponse({"ok": False, "error": f"The model didn't answer: {type(exc).__name__}: {msg}.{hint}"})
    if provider == "local":
        write_env(values, remove=(AUTO_LOCAL,))
    else:                                    # a choice made here is kept: no switching to a local model at start
        write_env({**values, AUTO_LOCAL: "0"}, remove=MODEL_KEYS)
    st = request.app.state
    st.llm = llm
    st.graph = build_claimclear_graph(Services(toolkit=st.toolkit, extractor=llm_extractor(llm) if llm else None),
                                      checkpointer=st.saver)
    st.gate = HumanApprovalGateway(st.graph)
    return JSONResponse({"ok": True, "model": chat.describe_model(llm), "configured": llm is not None})


async def clear(request: Request):
    """Delete uploads, filings and every chat of this run now (start.py also does this on close)."""
    if not same_origin(request):
        return JSONResponse({"ok": False}, status_code=403)
    proc = await asyncio.create_subprocess_exec(server_python(REPO), str(REPO / "scripts" / "upload_case.py"), "--purge",
                                                cwd=str(REPO), stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    out, _ = await proc.communicate()
    st = request.app.state
    from langgraph.checkpoint.memory import MemorySaver
    if isinstance(st.saver, MemorySaver):                # forget every chat and audit of this run
        st.saver = MemorySaver()
        st.graph = build_claimclear_graph(Services(toolkit=st.toolkit, extractor=llm_extractor(st.llm) if st.llm else None),
                                          checkpointer=st.saver)
        st.gate = HumanApprovalGateway(st.graph)
    for session in list(st.sessions):
        session.thread_id, session.sent, session.history, session.records = None, set(), [], {}
        await session.send("cleared")
    try:
        result = json.loads(out.decode("utf-8"))
    except ValueError:
        result = {}
    return JSONResponse({"ok": True, **result})


async def shutdown(request: Request):
    if not same_origin(request):
        return JSONResponse({"ok": False}, status_code=403)
    request.app.state.stop("the Close button")
    return JSONResponse({"ok": True})


async def ws_endpoint(ws: WebSocket):
    app = ws.app
    await ws.accept()
    app.state.connections += 1
    app.state.ever_connected = True
    session = Session(app, ws)
    app.state.sessions.add(session)
    tasks: set[asyncio.Task] = set()
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            t = asyncio.create_task(session.handle(msg))           # chat answers don't wait for a running graph
            tasks.add(t)
            t.add_done_callback(tasks.discard)
    except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
        pass
    finally:
        app.state.connections -= 1
        app.state.sessions.discard(session)
        app.state.last_disconnect = time.monotonic()


# --------------------------------------------------------------------------- lifetime


async def watchdog(app) -> None:
    """Stop the UI once every page has been closed for ``GRACE`` seconds."""
    while True:
        await asyncio.sleep(1)
        st = app.state
        if st.ever_connected and st.connections == 0 and time.monotonic() - st.last_disconnect > st.grace:
            st.stop(f"the last ClaimClear page was closed {st.grace:.0f} s ago")
            return


@asynccontextmanager
async def lifespan(app):
    st = app.state
    st.connections, st.ever_connected, st.last_disconnect = 0, False, time.monotonic()
    st.grace = st.grace if st.grace is not None else GRACE
    st.boot_id, st.sessions = uuid.uuid4().hex[:12], set()
    st.llm = chat.chat_model_from_env()
    async with st.toolkit_factory() as tk, open_checkpointer() as saver:
        st.toolkit, st.saver = tk, saver
        st.graph = build_claimclear_graph(Services(toolkit=tk, extractor=llm_extractor(st.llm) if st.llm else None),
                                          checkpointer=saver)
        st.gate = HumanApprovalGateway(st.graph)
        dog = asyncio.create_task(watchdog(app))
        yield
        dog.cancel()


def create_app(stop=lambda reason: None, toolkit_factory=ClaimClearToolkit, grace: float | None = None) -> Starlette:
    """The web app. ``toolkit_factory`` returns an async context manager giving the toolkit (tests pass a replay);
    ``grace`` overrides ``CLAIMCLEAR_UI_GRACE``."""
    app = Starlette(routes=[Route("/", index), Route("/api/status", status), Route("/api/upload", upload, methods=["POST"]),
                            Route("/api/sample", sample, methods=["POST"]),
                            Route("/api/model", model_get), Route("/api/model", model_set, methods=["POST"]),
                            Route("/api/clear", clear, methods=["POST"]),
                            Route("/api/shutdown", shutdown, methods=["POST"]), WebSocketRoute("/ws", ws_endpoint)],
                    lifespan=lifespan)
    app.state.stop = stop
    app.state.toolkit_factory = toolkit_factory
    app.state.grace = grace
    return app
