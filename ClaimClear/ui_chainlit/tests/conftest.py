"""Shared fakes for the chat UI tests: a scripted chat model, a fake case-records toolkit, and a Chainlit chat.

* ``ScriptedModel``: a LangChain chat model that replies with the next ``AIMessage`` from its script (tool calls or
  an answer), streamed token by token like a real model, so the ReAct agent and LangGraph's streaming run for real.
* ``FakeToolkit``: ``list_case_documents`` / ``get_document_text`` with the same shapes and errors as case-records.
* ``in_chat(scenario)``: runs ``scenario(rec)`` inside a Chainlit chat context (Chainlit's own ``HTTPSession`` and
  ``ChainlitContext``), with an emitter that records everything the app would send to the browser:
  messages, steps, step updates and streamed tokens. No server, no browser, no network.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

UI = Path(__file__).resolve().parents[1]
os.environ.setdefault("CHAINLIT_APP_ROOT", str(UI))     # Chainlit writes .chainlit/ under its app root on import
sys.path.insert(0, str(UI))

import pytest  # noqa: E402
from chainlit.context import ChainlitContext, context_var  # noqa: E402
from chainlit.emitter import BaseChainlitEmitter  # noqa: E402
from chainlit.session import HTTPSession  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult  # noqa: E402

from claimclear_graph.testing import tool_error  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs the five MCP servers and a model key (CLAIMCLEAR_LIVE=1)")


# --------------------------------------------------------------------------- the model

def call(name: str, **args) -> AIMessage:
    """A scripted reply that calls one tool."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}])


def say(text: str) -> AIMessage:
    """A scripted final answer."""
    return AIMessage(content=text)


class ScriptedModel(BaseChatModel):
    script: list = []                 # AIMessages, used in order
    seen: list = []                   # the messages the model was given on each turn
    bound_tools: list = []
    model_name: str = "scripted-test-model"

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        return self

    identities: list = []             # replies to with_structured_output (identify.py), used in order
    prompts: list = []

    def with_structured_output(self, schema, **kwargs):
        model = self

        class Structured:
            async def ainvoke(self, prompt):
                model.prompts.append(prompt)
                return schema.model_validate(model.identities.pop(0) if model.identities else
                                             {"type": "other", "summary": "a document"})
        return Structured()

    def _next(self, messages) -> AIMessage:
        self.seen.append(list(messages))
        if not self.script:
            raise AssertionError("the model was called more times than the script allows")
        return self.script.pop(0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self._next(messages)
        if msg.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(msg.tool_calls)]))
            return
        for piece in re.findall(r"\S+\s*", msg.content):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))


# --------------------------------------------------------------------------- case-records

class FakeToolkit:
    """``docs``: document_id -> page texts. ``hidden``: {(document_id, page)} pages carrying hidden text.
    ``names``: document_id -> the user's file name. The newest FakeToolkit also stands in for the case store's
    writes (``store_docs.describe_document`` etc., patched in ``fake_store_writes``)."""
    current: "FakeToolkit"

    def __init__(self, docs: dict[str, list[str]], hidden: Optional[set] = None, case_wording: Optional[str] = None,
                 names: Optional[dict] = None):
        self.docs, self.hidden, self.calls = docs, hidden or set(), []
        self.case_wording = case_wording         # what CaseStore.set_wording put on the case
        self.meta = {d: {"role": "other", "name": (names or {}).get(d, ""), "summary": ""} for d in docs}
        self.policy = ("unknown", "")
        FakeToolkit.current = self

    # case-records get_policy_wording, policy-kb search_clauses and register_uploaded_wording
    async def get_policy_wording(self, case_id: str) -> dict:
        self.calls.append(("get_policy_wording", case_id))
        if self.case_wording:
            return {"wording_uin": self.case_wording, "wording_source": "uploaded", "status": "uploaded"}
        return {"wording_uin": "GODHLIP24179V022324", "wording_source": "catalogue", "status": "not_printed"}

    async def search_clauses(self, query: str, k: int = 5, wording_uin=None, case_id=None) -> dict:
        self.calls.append(("search_clauses", query, wording_uin, case_id))
        own = (wording_uin or "").startswith("upload:")
        return {"query": query, "wording": {"insurer": "Narmada Health" if own else "Go Digit General Insurance Limited",
                                            "source": "uploaded" if own else "catalogue"},
                "hits": [{"clause_id": "Annexure A List I", "title": "Items for which coverage is not available",
                          "text": "1. ATTENDANT CHARGES", "page_start": 39, "page_end": 39}]}

    async def register_uploaded_wording(self, case_id: str, document_id: str, pages: list[dict]) -> dict:
        self.calls.append(("register_uploaded_wording", case_id, document_id, [p["page"] for p in pages]))
        return {"wording_uin": f"upload:{document_id}", "structure": "clauses", "clause_count": 120, "in_scope": True}

    async def list_case_documents(self, case_id: str) -> dict:
        self.calls.append(("list_case_documents", case_id))
        return {"case_id": case_id, "policy_no": self.policy[0], "documents": [
            {"document_id": d, "media_type": "application/pdf", "size_bytes": 2048 * len(pages),
             "page_count": len(pages), **self.meta[d]} for d, pages in self.docs.items()]}

    async def get_document_text(self, case_id: str, document_id: str, pages: Optional[list[int]] = None) -> dict:
        self.calls.append(("get_document_text", case_id, document_id, list(pages or [])))
        texts = self.docs[document_id]
        bad = [p for p in pages or [] if not 1 <= p <= len(texts)]
        if bad:
            raise tool_error("get_document_text", "PAGE_OUT_OF_RANGE", f"pages {bad} outside 1..{len(texts)}")
        return {"page_count": len(texts), "pages": [
            {"page": p, "text": texts[p - 1],
             "spans": [{"hidden_reasons": ["white_text"]}] if (document_id, p) in self.hidden else []}
            for p in pages or range(1, len(texts) + 1)]}


BILL = ["CITY EYE HOSPITAL\nFinal bill\nCataract surgery (right eye) Rs. 48,000.00\nEye kit and drape Rs. 900.00",
        "Total claimed Rs. 55,600.00"]
LETTER = ["Claim settlement advice\nAmount paid INR 7,125.00\nCo-payment 5% INR 375.00"]


NAMES = {"DOC-1": "bill.pdf", "DOC-2": "letter.pdf"}


@pytest.fixture
def toolkit():
    return FakeToolkit({"DOC-1": BILL, "DOC-2": LETTER}, names=NAMES)


CHAT = {"case_id": "CASE-T1"}


@pytest.fixture(autouse=True)
def defences_off_by_default(monkeypatch, request):
    """The chat tests' fake toolkit has no document reader, so the security checks are off unless a test turns them
    on (``test_security_chat.py``). Live tests use the real setting."""
    if not request.node.get_closest_marker("live"):
        monkeypatch.setenv("CLAIMCLEAR_DEFENCES", "off")


@pytest.fixture(autouse=True)
def fake_store_writes(monkeypatch, request):
    """The case store's writes (store_docs, which runs the servers' Python) land in the newest FakeToolkit.
    Not for live tests, which write to the real store."""
    import store_docs
    writes = []
    if request.node.get_closest_marker("live"):
        return writes

    async def describe(case_id, document_id, role, summary):
        writes.append(("describe", case_id, document_id, role, summary))
        FakeToolkit.current.meta[document_id].update(role=role, summary=summary)
        return {"ok": True}

    async def policy(case_id, policy_no, reference_key=""):
        writes.append(("policy", case_id, policy_no, reference_key))
        FakeToolkit.current.policy = (policy_no, reference_key)
        return {"ok": True}

    async def wording(case_id, uin):
        writes.append(("wording", case_id, uin))
        FakeToolkit.current.case_wording = uin
        return {"ok": True}
    monkeypatch.setattr(store_docs, "describe_document", describe)
    monkeypatch.setattr(store_docs, "set_policy", policy)
    monkeypatch.setattr(store_docs, "set_case_wording", wording)
    return writes


# --------------------------------------------------------------------------- Chainlit

class RecordingEmitter(BaseChainlitEmitter):
    """Keeps what the app sends to the browser. ``steps``: step id -> its latest state (messages are steps too)."""

    def __init__(self, session):
        super().__init__(session)
        self.steps: dict[str, dict] = {}
        self.tokens: list[tuple[str, str]] = []

    def _keep(self, d: dict) -> None:
        self.steps[d["id"]] = {**self.steps.get(d["id"], {}), **d}

    async def send_step(self, step_dict):
        self._keep(dict(step_dict))

    async def update_step(self, step_dict):
        self._keep(dict(step_dict))

    async def stream_start(self, step_dict):
        self._keep(dict(step_dict))

    async def send_token(self, id: str, token: str, is_sequence=False, is_input=False):
        self.tokens.append((id, token))

    # what a viewer sees
    def messages(self) -> list[str]:
        return [s.get("output", "") for s in self.steps.values() if s.get("type") == "assistant_message"]

    def tool_steps(self) -> list[dict]:
        return [s for s in self.steps.values() if s.get("type") == "tool"]


def in_chat(scenario) -> RecordingEmitter:
    """Run ``await scenario(rec)`` inside one Chainlit chat and return the recording."""
    async def main():
        session = HTTPSession(id=str(uuid.uuid4()), thread_id=str(uuid.uuid4()), client_type="webapp")
        rec = RecordingEmitter(session)
        context_var.set(ChainlitContext(session, rec))
        await scenario(rec)
        return rec
    return asyncio.run(main())


def run(coro) -> Any:
    return asyncio.run(coro)
