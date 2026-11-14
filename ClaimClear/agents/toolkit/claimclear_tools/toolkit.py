"""``ClaimClearToolkit``: one object that connects the agents to every ClaimClear MCP server.

    async with ClaimClearToolkit() as tk:
        auditor_tools = tk.for_agent("settlement_auditor")     # LangChain tools for create_react_agent / ToolNode
        claim_schema = tk.schema("ClaimIn")                    # JSON schema for the document reader's extraction
        settlement = await tk.expected_settlement(case)        # typed call for deterministic code (critic, C0)

* Opens **one persistent session per server** (a fresh process per call is ~2 s;
  a session call is ~15 ms).
* ``for_agent`` hands each agent only its allowed tools (``agents.AGENT_TOOLS``),
  filling policy-kb tools with stubs if that server isn't connected.
* The typed helpers return the tool's structured result as a ``dict`` and raise
  ``ClaimClearToolError`` (with a suggested graph action) on an error.
"""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from .agents import AGENT_TOOLS, TOOL_SERVER
from .config import Mode, connections
from .results import ClaimClearToolError, structured, tool_error


class ClaimClearToolkit:
    def __init__(self, mode: Optional[Mode] = None, repo: Optional[Path] = None,
                 servers: Optional[dict[str, dict]] = None, use_stubs: bool = True,
                 local_tools: Optional[dict[str, Any]] = None, tool_interceptors: Optional[list[Any]] = None):
        """``servers`` overrides the connection dict (``{name: connection}``); by default it comes from ``config``.

        ``local_tools`` are in-process LangChain tools that take the place of a server's tools, e.g.
        ``policy_kb.tools.make_tools(kb)`` for the policy-kb tools without that server. A live MCP tool of the
        same name wins over a local one.

        ``tool_interceptors`` are ``langchain_mcp_adapters`` interceptors, ``async (request, handler)``, run around
        every MCP tool call (first is outermost): the place for Member 4's pre-tool and post-tool hooks at the
        MCP client. ``request.server_name`` names the server; return a ``ToolMessage`` instead of calling
        ``handler`` to refuse a call.
        """
        self._connections = servers if servers is not None else connections(mode, repo)
        self._interceptors = list(tool_interceptors or [])
        self._use_stubs = use_stubs
        self._local = dict(local_tools or {})
        self._stack: Optional[AsyncExitStack] = None
        self.tools: dict[str, Any] = {}

    # ------------------------------------------------------------------ lifecycle

    async def __aenter__(self) -> "ClaimClearToolkit":
        self._stack = AsyncExitStack()
        client = MultiServerMCPClient(self._connections)
        try:
            for name in self._connections:
                session = await self._stack.enter_async_context(client.session(name))
                for t in await load_mcp_tools(session, tool_interceptors=self._interceptors or None,
                                              server_name=name):
                    self.tools[t.name] = t
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self.tools = {}

    # ------------------------------------------------------------------ tools for agents

    def tool(self, name: str) -> Any:
        """One LangChain tool by name: live MCP tool, else a local tool, else a stub for a policy-kb tool."""
        if name in self.tools:
            return self.tools[name]
        if name in self._local:
            return self._local[name]
        if self._use_stubs and TOOL_SERVER.get(name) == "policy-kb":
            from .stubs import POLICY_KB_STUBS
            return POLICY_KB_STUBS[name]
        raise KeyError(f"tool {name!r} is not available (server not connected?)")

    def for_agent(self, agent: str) -> list[Any]:
        """The LangChain tools ``agent`` may use. Tools of servers that aren't connected are skipped
        (policy-kb tools are stubbed when ``use_stubs`` is on)."""
        out = []
        for name in AGENT_TOOLS[agent]:
            try:
                out.append(self.tool(name))
            except KeyError:
                continue
        return out

    def schema(self, model: str) -> dict:
        """A server input model as a standalone JSON schema, e.g. ``ClaimIn``, ``LetterIn``, ``PolicyIn``.

        Taken from the live tool listing, so the document reader always extracts
        into the shape the server currently accepts.
        """
        for t in self.tools.values():
            args = t.args_schema if isinstance(t.args_schema, dict) else {}
            defs = args.get("$defs", {})
            if model in defs:
                return {**defs[model], "$defs": defs}
        raise KeyError(f"no tool input uses a model called {model!r}")

    # ------------------------------------------------------------------ typed calls

    async def call(self, name: str, args: dict) -> dict:
        """Call a tool and return its structured result, or raise ``ClaimClearToolError``."""
        msg = await self.tool(name).ainvoke({"type": "tool_call", "id": f"call_{uuid.uuid4().hex[:12]}",
                                             "name": name, "args": args})
        err = tool_error(msg)
        if err is not None:
            raise ClaimClearToolError(err)
        result = structured(msg)
        if result is None:
            raise RuntimeError(f"{name} returned no structured content")
        return result

    # case-records
    async def list_case_documents(self, case_id: str) -> dict:
        return await self.call("list_case_documents", {"case_id": case_id})

    async def get_document_text(self, case_id: str, document_id: str, pages: Optional[list[int]] = None) -> dict:
        args: dict = {"case_id": case_id, "document_id": document_id}
        if pages:
            args["pages"] = pages
        return await self.call("get_document_text", args)

    async def get_policy(self, case_id: str) -> dict:
        return await self.call("get_policy", {"case_id": case_id})

    async def get_policy_wording(self, case_id: str) -> dict:
        """Which wording the case is checked against; ``wording_needed`` true means ask the user for theirs."""
        return await self.call("get_policy_wording", {"case_id": case_id})

    async def get_claim_history(self, case_id: str, scope: str = "current_period") -> list[dict]:
        return (await self.call("get_claim_history", {"case_id": case_id, "scope": scope}))["claims"]

    async def read_case(self, case_id: str) -> dict:
        """Everything case-records has for a case: ``{"documents": {document_id: text}, "policy", "wording", "history"}``."""
        docs = await self.list_case_documents(case_id)
        texts = {d["document_id"]: await self.get_document_text(case_id, d["document_id"]) for d in docs["documents"]}
        return {"documents": texts, "policy": await self.get_policy(case_id),
                "wording": await self.get_policy_wording(case_id), "history": await self.get_claim_history(case_id)}

    # settlement-engine
    async def expected_settlement(self, case: dict) -> dict:
        return await self.call("expected_settlement", {"case": case})

    async def reproduce_deduction(self, case: dict, letter: dict, row_id: str,
                                  hypothesis_ids: Optional[list[str]] = None) -> dict:
        args: dict = {"case": case, "letter": letter, "row_id": row_id}
        if hypothesis_ids is not None:
            args["hypothesis_ids"] = hypothesis_ids
        return await self.call("reproduce_deduction", args)

    async def audit_settlement_letter(self, case: dict, letter: dict,
                                      hypothesis_ids: Optional[list[str]] = None) -> dict:
        args: dict = {"case": case, "letter": letter}
        if hypothesis_ids is not None:
            args["hypothesis_ids"] = hypothesis_ids
        return await self.call("audit_settlement_letter", args)

    async def list_hypotheses(self, kind: Optional[str] = None) -> list[dict]:
        return (await self.call("list_hypotheses", {"kind": kind} if kind else {}))["hypotheses"]

    # policy-kb (pass the case's wording_uin from get_policy; with an uploaded wording also its case_id)
    @staticmethod
    def _wording(args: dict, wording_uin: Optional[str], case_id: Optional[str]) -> dict:
        if wording_uin:
            args["wording_uin"] = wording_uin
        if case_id:
            args["case_id"] = case_id
        return args

    async def list_policies(self, insurer: Optional[str] = None, query: Optional[str] = None,
                            case_id: Optional[str] = None) -> dict:
        """``{"default_wording_uin", "policies": [...]}``: the catalogue, plus the case's upload."""
        args = {k: v for k, v in {"insurer": insurer, "query": query, "case_id": case_id}.items() if v}
        return await self.call("list_policies", args)

    async def search_clauses(self, query: str, k: int = 5, wording_uin: Optional[str] = None,
                             case_id: Optional[str] = None) -> dict:
        """``{"query", "wording", "synthetic", "hits": [...]}``; each hit has ``clause_id``, ``text``, ``citation``."""
        return await self.call("search_clauses", self._wording({"query": query, "k": k}, wording_uin, case_id))

    async def get_clause(self, clause_id: str, wording_uin: Optional[str] = None,
                         case_id: Optional[str] = None) -> dict:
        """One clause; ``found`` is false when the wording has no such clause (not an error)."""
        return await self.call("get_clause", self._wording({"clause_id": clause_id}, wording_uin, case_id))

    async def clauses_for_rule(self, rule_ref: str, wording_uin: Optional[str] = None,
                               case_id: Optional[str] = None) -> dict:
        """The clauses behind a settlement-engine ``rule_ref``; cite ``clauses[0]``."""
        return await self.call("clauses_for_rule", self._wording({"rule_ref": rule_ref}, wording_uin, case_id))

    async def register_uploaded_wording(self, case_id: str, document_id: str, pages: list[dict]) -> dict:
        """APP ONLY (upload ingestion): index the visible text of the user's own policy for one case.
        ``pages`` are ``{"page", "text"}`` from ``get_document_text`` (``page.text`` only)."""
        return await self.call("register_uploaded_wording",
                               {"case_id": case_id, "document_id": document_id, "pages": pages})

    async def ingest_uploaded_policy(self, case_id: str, document_id: str) -> dict:
        """APP ONLY: read the uploaded policy through case-records (visible text only) and index it."""
        doc = await self.get_document_text(case_id, document_id)
        pages = [{"page": p["page"], "text": p["text"]} for p in doc["pages"] if p["text"].strip()]
        return await self.register_uploaded_wording(case_id, document_id, pages or [{"page": 1, "text": ""}])

    # insurer-portal (dry run until Member 4's mock portal is connected)
    async def file_grievance(self, case_id: str, claim_id: str, row_ids: list[str], text: str, text_sha256: str,
                             approval_token: str) -> dict:
        """WRITE, grievance agent only, after the approval gate."""
        return await self.call("file_grievance", {"case_id": case_id, "claim_id": claim_id, "row_ids": row_ids,
                                                  "text": text, "text_sha256": text_sha256,
                                                  "approval_token": approval_token})

    async def grievance_status(self, reference: str) -> dict:
        return await self.call("grievance_status", {"reference": reference})
