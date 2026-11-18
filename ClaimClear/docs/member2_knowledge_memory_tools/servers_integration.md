# Connecting Member 2's servers to Member 3's agents

This guide is for **Member 3** (agents and orchestration), from **Member 2** (knowledge, memory and tools). It explains how the LangGraph agents connect to the MCP servers, which agent may call which tool, what goes into `CaseState`, how each tool's result should steer the graph, and how we keep both sides in step.

| Server | Folder | Status | Tools |
|---|---|---|---|
| `case-records` | [`case_records/`](case_records.md) | ✅ built | `list_case_documents`, `get_document_text`, `get_policy`, `get_policy_wording`, `get_claim_history` |
| `settlement-engine` | [`settlement_engine/`](settlement_engine.md) | ✅ built | `expected_settlement`, `reproduce_deduction`, `audit_settlement_letter`, `list_hypotheses` |
| `policy-kb` | [`policy_kb/`](policy_kb.md) | ✅ built | `list_policies`, `search_clauses`, `get_clause`, `clauses_for_rule` (see [§9](#9-policy-kb-citing-the-wording)); `register_uploaded_wording` for the app only |
| `insurer-portal` | [`insurer_portal/`](../../servers/insurer_portal/insurer_portal/app.py) | ✅ interface + dry run · 🔜 mock portal (Member 4) | `grievance_status`, `file_grievance` (behind the approval gate) |
| `document-reader` | [`document_reader/`](document_reader.md) | ✅ built · **for the app, not agents** | `read_document`, `reader_status`. All OCR and document reading; case-records' `get_document_text` uses the same reader |



> **Fastest path: use [`agents/toolkit`](toolkit.md).** It packages everything in sections 3–9 below: `ClaimClearToolkit` (connection, sessions, per-agent tools, schemas, typed calls), `results` (result and error parsing), `signals` (tool result → graph route), `case` (case assembly, applying answers), `critic` (figure and wording checks). This guide explains what it does and why; the toolkit is the code to import.

---

## Contents

1. [The picture](#1-the-picture)
2. [Environments: keep the servers and the agents apart](#2-environments-keep-the-servers-and-the-agents-apart)
3. [Connecting from LangGraph](#3-connecting-from-langgraph)
4. [Which agent gets which tools](#4-which-agent-gets-which-tools)
5. [Reading tool results and errors](#5-reading-tool-results-and-errors)
6. [CaseState: the data contract](#6-casestate-the-data-contract)
7. [Node by node](#7-node-by-node)
8. [Tool signals that drive the graph](#8-tool-signals-that-drive-the-graph)
9. [policy-kb: citing the wording](#9-policy-kb-citing-the-wording)
10. [Baselines C0 and C1](#10-baselines-c0-and-c1)
11. [Keeping both sides in step](#11-keeping-both-sides-in-step)
12. [Verified end to end](#12-verified-end-to-end)
13. [Checklist for Member 3](#13-checklist-for-member-3)

---

## 1. The picture

```
                     ┌──────────────── LangGraph (Member 3) ────────────────┐
                     │ supervisor/planner ─► document reader ─► policy analyst│
                     │        ▲                                   │          │
                     │        └── critic ◄── settlement auditor ◄─┘          │
                     │                 └──► explainer ──► grievance agent    │
                     └──────┬──────────────────┬──────────────────┬──────────┘
                            │ MCP (stdio in dev, streamable HTTP in Docker)   │
             ┌──────────────▼───────┐ ┌────────▼──────────┐ ┌─────▼────────┐
             │ case-records    ✅   │ │ settlement-engine ✅│ │ policy-kb ✅ │
             │ documents, policy,   │ │ engine, hypotheses,│ │ clauses      │
             │ claim history        │ │ matcher            │ │              │
             └──────────────────────┘ └────────────────────┘ └──────────────┘
```

Two more servers sit beside these: **insurer-portal** (✅ interface and dry run; only the grievance agent calls it, behind the approval gate) and **document-reader** (✅ for the app's upload pipeline, never for agents).

**The division of work in one sentence:** the agents decide *what to read, which methods to try, what to ask and how to say it*; the servers decide *what the documents say, every rupee figure and every verdict*.

---

## 2. Environments: keep the servers and the agents apart

| Side | Environment | Key packages |
|---|---|---|
| Servers (Member 2) | `<repo>/.venv`, Python 3.15 | `mcp==2.3.0`, `pymupdf`, `pydantic` |
| Agents (Member 3) | **A separate venv**, Python **3.14** recommended | `langgraph`, `langchain-core`, `langchain-openai`, `langchain-mcp-adapters` |

**Why separate.** `langchain-mcp-adapters` (latest 0.3.2) requires `mcp<2.0`, so it installs the mcp **1.x** client, while our servers use mcp **2.3**. They can't share one environment, and they don't need to: each server runs as its own process (stdio) or container (HTTP). **We tested this:** an mcp 1.30 client (through the adapters, Python 3.14) called every tool on the mcp 2.3 servers over stdio and got the right results (see [§12](#12-verified-end-to-end)); the toolkit's live tests repeat this against every server.

**Why Python 3.14 for the agents.** `langchain-core` needs PyYAML, which has no ready-made wheel for 3.15 yet.

```bash
py -3.14 -m venv .venv-agents
```

```bash
.venv-agents/Scripts/python.exe -m pip install langgraph langchain-openai langchain-mcp-adapters
```

In Docker (Member 4) each server is its own container, so this split happens naturally.

---

## 3. Connecting from LangGraph

**With the toolkit** (recommended):

```python
from claimclear_tools import ClaimClearToolkit

async with ClaimClearToolkit() as tk:     # stdio by default; CLAIMCLEAR_MCP_MODE=http for running servers
    tools = tk.tools                     # every live tool, one persistent session per server
    graph = build_graph(tk)
```

### Why the toolkit, not the servers directly

The agents could call the MCP servers themselves, as the rest of this section shows. The toolkit does the plumbing every node would otherwise repeat, and keeps the rules in one tested place:

| Without the toolkit, every node would have to... | The toolkit gives |
|---|---|
| start or reach four servers and keep a session to each | `ClaimClearToolkit`: one session per server, about 100 times faster than a process per call |
| keep its own list of allowed tools | `tk.for_agent(...)`, from one table (`AGENT_TOOLS`, §4) that Member 4's permission hook reads too |
| dig the typed result out of each reply and parse errors | `structured(msg)`, `tool_error(msg)` (§5) |
| decide in prompts where the graph goes next | `signals` (§8): tested code, not prompt text |
| assemble the engine's input and apply the user's answers | `build_case(...)`, `apply_answer(...)` |
| check that every rupee in a draft came from a tool | `critic.unsupported_figures`, `critic.wording_for` |
| bridge two MCP versions | nothing: it runs in the agents' environment (mcp 1.x) and reaches the servers (mcp 2.3) over MCP (§2) |
| attach Member 4's hooks | `tool_interceptors=[...]`, and `may_use` for the permission hook (below) |

The servers still decide every figure and verdict; the toolkit only connects the agents to them correctly.

### Where the hooks attach

Member 4 writes the hooks; Member 2 built the two places they attach. Every tool call passes three checkpoints:

| | Hook 1: before the toolkit | Hook 2: inside the toolkit | After the toolkit |
|---|---|---|---|
| Where | LangGraph's `ToolNode(..., awrap_tool_call=hook)`, around each call an agent node makes | `ClaimClearToolkit(tool_interceptors=[...])`, around every MCP call (first is outermost) | the MCP server itself |
| Knows | **which agent** is calling, and the graph state | which **server** (`request.server_name`), the tool and its arguments | its own input schema |
| For | permission (`may_use(agent, tool)`), case access, budget | refusing or rewriting a call, logging, scrubbing personal data, timing | rejecting bad input with an error code; `file_grievance` refuses without the approval token |
| Refuse by | returning a `ToolMessage(status="error")` instead of calling `execute` | returning a `ToolMessage` instead of calling `handler` | a structured error (`{code, message, retryable}`) |
| Written by | Member 4 | Member 4 | Member 2 (built) |

**Wiring them in is Member 3's part:** open the toolkit once per graph run with Member 4's interceptors, and give each agent its own `ToolNode` with Member 4's wrapper.

```python
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode, create_react_agent
from claimclear_tools import ClaimClearToolkit
from claimclear_tools.agents import may_use

# Hook 1: around each call one agent node makes; it knows the agent
def permission_hook(agent):
    async def wrapper(request, execute):                 # request.tool_call = {"name", "args", "id"}
        name = request.tool_call["name"]
        if not may_use(agent, name):                     # Member 4: also case ownership and budget
            return ToolMessage(content=f'{{"code": "NOT_ALLOWED", "message": "{agent} may not call {name}"}}',
                               tool_call_id=request.tool_call["id"], status="error")
        return await execute(request)
    return wrapper

# Hook 2: around every MCP call; it knows the server and the arguments
async def audit_log(request, handler):
    result = await handler(request)                      # the real call to the server
    log(request.server_name, request.name)               # Member 4: scrubbed trace, latency, cost
    return result

async with ClaimClearToolkit(tool_interceptors=[audit_log]) as tk:
    auditor_tools = ToolNode(tk.for_agent("settlement_auditor"), awrap_tool_call=permission_hook("settlement_auditor"))
    auditor = create_react_agent(llm, auditor_tools)     # create_react_agent also takes a ToolNode
```

`log` stands for Member 4's logger. Both hooks are tested against the live servers in `agents/toolkit/tests/test_toolkit_live.py`. A refusal from either hook reaches the agent as an ordinary tool error, so `tool_error(msg)` and the graph's edges handle it like any other.

**Direct calls from code.** Typed calls such as `await tk.expected_settlement(case)` (in the critic or the baselines) don't go through an agent's `ToolNode`, so hook 1 doesn't see them; hook 2 still does, because the toolkit loads every tool with the interceptors.

The rest of this section is what the toolkit does under the hood, for reference.

### Development: stdio

```python
import os
from pathlib import Path
from langchain_mcp_adapters.client import MultiServerMCPClient

REPO = Path(__file__).resolve().parents[N]          # adjust to your file
SERVER_PY = str(REPO / ".venv" / "Scripts" / "python.exe")   # the servers' venv, not yours

client = MultiServerMCPClient({
    "case-records": {
        "transport": "stdio",
        "command": SERVER_PY,
        "args": ["-m", "case_records"],
        "cwd": str(REPO / "servers" / "case_records"),
        "env": {**os.environ,                        # keep SYSTEMROOT etc. on Windows
                "CLAIMCLEAR_CASE_STORE": str(REPO / "var" / "case_store")},
    },
    "settlement-engine": {
        "transport": "stdio",
        "command": SERVER_PY,
        "args": ["-m", "mcp_server"],
        "cwd": str(REPO / "servers" / "settlement_engine"),
        "env": dict(os.environ),
    },
    "policy-kb": {
        "transport": "stdio",
        "command": SERVER_PY,
        "args": ["-m", "policy_kb.mcp_server"],
        "cwd": str(REPO / "servers" / "policy_kb"),
        "env": dict(os.environ),                     # CLAIMCLEAR_POLICY_KB_INDEX if not var/policy_kb/index.json
    },
    "insurer-portal": {                              # the grievance agent's tools only
        "transport": "stdio",
        "command": SERVER_PY,
        "args": ["-m", "insurer_portal"],
        "cwd": str(REPO / "servers" / "insurer_portal"),
        "env": dict(os.environ),
    },
})
```

**Use a persistent session per server.** Without one, `client.get_tools()` tools start a **new server process for every call** (about 2 s each in our test). With a session, 5 calls took **0.08 s**.

```python
from langchain_mcp_adapters.tools import load_mcp_tools

async with client.session("case-records") as cr, client.session("settlement-engine") as se:
    tools = {t.name: t for t in (await load_mcp_tools(cr)) + (await load_mcp_tools(se))}
    graph = build_graph(tools)          # build the graph inside the sessions
    await graph.ainvoke(...)
```

### Docker: streamable HTTP

```python
client = MultiServerMCPClient({
    "case-records":      {"transport": "streamable_http", "url": "http://case-records:8102/mcp"},
    "settlement-engine": {"transport": "streamable_http", "url": "http://settlement-engine:8101/mcp"},
    "policy-kb":         {"transport": "streamable_http", "url": "http://policy-kb:8103/mcp"},
    "insurer-portal":    {"transport": "streamable_http", "url": "http://insurer-portal:8104/mcp"},
})
```

| Server | Start command (in its folder, servers' venv) | Default port |
|---|---|---|
| `settlement-engine` | `python -m mcp_server --transport streamable-http --host 0.0.0.0 --port 8101` | 8101 |
| `case-records` | `python -m case_records --transport streamable-http --host 0.0.0.0 --port 8102` | 8102 |
| `policy-kb` | `python -m policy_kb.mcp_server --transport streamable-http --host 0.0.0.0 --port 8103` | 8103 |
| `insurer-portal` | `python -m insurer_portal --transport streamable-http --host 0.0.0.0 --port 8104` | 8104 |
| `document-reader` (the app's, not the agents') | `python -m document_reader --transport streamable-http --host 0.0.0.0 --port 8105` | 8105 |

Load the dataset into the case store once for development:

```bash
cd servers/case_records && ../../.venv/Scripts/python.exe -m case_records.register_dataset
```

This writes `var/case_store/` and `var/dataset_map.json`. **The map is for the evaluation runner only. Never put it in a prompt, a tool or the agent's state.** It reveals which documents are attacks.

---

## 4. Which agent gets which tools

The plan requires that each agent has **only the tools it needs**. Give each agent node its own list:

| Agent | Tools | Server | Why |
|---|---|---|---|
| Document reader | `list_case_documents`, `get_document_text` | case-records | Reads the case's documents |
| Policy analyst | `get_policy`, `get_policy_wording`, `get_claim_history`, `list_policies`, `search_clauses`, `get_clause`, `clauses_for_rule` | case-records, policy-kb | Policy schedule, earlier claims, clauses |
| Settlement auditor | `expected_settlement`, `list_hypotheses`, `reproduce_deduction` | settlement-engine | The ReAct loop over letter rows |
| Critic | `audit_settlement_letter`, `expected_settlement`, `get_clause` | settlement-engine, policy-kb | Re-runs every figure; checks citations |
| Explainer | `get_clause`, `clauses_for_rule` (to quote wording) | policy-kb | Writes only from facts already in state |
| Grievance agent | `file_grievance`, `grievance_status` | insurer-portal (interface and dry run here; the mock portal is Member 4's) | **Only** agent with a write tool, behind the approval gate |
| Supervisor / planner | none | — | Routes; doesn't call tools |

With the toolkit, the table lives in `claimclear_tools.agents.AGENT_TOOLS`:

```python
auditor_tools = tk.for_agent("settlement_auditor")   # expected_settlement, list_hypotheses, reproduce_deduction
analyst_tools = tk.for_agent("policy_analyst")       # get_policy, get_policy_wording, get_claim_history, list_policies, search_clauses, get_clause, clauses_for_rule
from claimclear_tools.agents import may_use            # for Member 4's permission hook
```

Every agent tool on case-records, settlement-engine and policy-kb, and insurer-portal's `grievance_status`, is annotated read-only (`read_only_hint=true`) and tagged `_meta.access = "read"`, so Member 4's permission hook can allow them without the approval gate. The one write tool, `file_grievance`, is tagged `access: write` and needs an approval token. Tools only the app calls (`register_uploaded_wording`, the document-reader's tools) also carry `caller: app`.

---

## 5. Reading tool results and errors

The adapters return tools with `response_format="content_and_artifact"`.

* **Structured result:** when the tool is invoked as a tool call (as LangGraph's `ToolNode` does), the `ToolMessage` carries the typed result in **`artifact["structured_content"]`**. Put that in state, not the text.
* **The LLM sees** the same JSON as text in the message content.
* **Errors don't raise.** They come back as text:
  `Error executing tool get_document_text: {"code": "DOCUMENT_NOT_IN_CASE", "message": "...", "retryable": false}`.

With the toolkit: `from claimclear_tools import structured, tool_error`. `tool_error` returns a `ToolErrorInfo` with the suggested `action` from the table below, and the toolkit's typed calls raise `ClaimClearToolError`. The plain version, for reference:

```python
import json

def structured(msg):
    """Typed tool result from a ToolMessage (None if the tool failed)."""
    return (msg.artifact or {}).get("structured_content") if isinstance(msg.artifact, dict) else None

def tool_error(msg):
    """{"code", "message", "retryable"} if the tool returned one of our errors, else None."""
    text = msg.content if isinstance(msg.content, str) else "".join(b.get("text", "") for b in msg.content)
    if text.startswith("Error executing tool") and "{" in text:
        return json.loads(text[text.index("{"):])
    return None
```

Error codes, and what the graph should do:

| Code | Server | Graph action |
|---|---|---|
| `CASE_NOT_FOUND`, `DOCUMENT_NOT_IN_CASE` | case-records | Stop; it's a programming or isolation error. Never retry with another ID |
| `DOCUMENT_UNREADABLE`, `DOCUMENT_ENCRYPTED` | case-records | **Missing-document edge:** ask the user for a readable copy |
| `PAGE_OUT_OF_RANGE` | case-records | Fix the page list (from `page_count`) and retry once |
| `POLICY_NOT_FOUND` | case-records | Ask the user to confirm the policy number; don't audit |
| `POLICY_MISMATCH`, `HISTORY_POLICY_MISMATCH` | settlement-engine | Bug in assembling `case`; stop |
| `ROW_NOT_FOUND` | settlement-engine | The message lists valid row IDs; retry once with one of them |
| `UNKNOWN_HYPOTHESIS` | settlement-engine | Call `list_hypotheses`, pick again |
| `INDEX_UNAVAILABLE` | policy-kb | No index built yet: explain from the engine's rule summaries, marked as summaries |
| `UPSTREAM_UNAVAILABLE` | policy-kb | OpenRouter failed while embedding or rewriting the query; `retryable: true` for rate limits and outages: retry later |
| `NO_RULE_MAP`, `UNKNOWN_RULE` | policy-kb | No reviewed clause map for this rule or wording: use `search_clauses` instead |
| *(schema validation message)* | all | The extracted data is malformed; send it back to the document reader once |

Apart from `UPSTREAM_UNAVAILABLE`, our codes have `retryable: false`: retrying the same call won't help.

---

## 6. CaseState: the data contract

What each field holds, who fills it, and its exact shape. The shapes are the servers' own schemas, so data flows through without conversion.

| `CaseState` field | Filled by | Shape (server schema) | Read by |
|---|---|---|---|
| `case_id` | App (M4), at upload | `case_[0-9a-f]{16}` | Everyone |
| `documents` | Document reader ← `list_case_documents` | `CaseDocumentsOut.documents` | Document reader |
| `pages` | Document reader ← `get_document_text` | `DocumentTextOut` | Document reader, guardrails |
| `claim` | Document reader (LLM extraction) | **`ClaimIn`** (settlement-engine) | Auditor, critic |
| `letter` | Document reader (LLM extraction) | **`LetterIn`** (settlement-engine) | Auditor, critic, grievance agent |
| `sources` | Document reader | `{field path: span_id}`, e.g. `{"letter.rows[2].amount": "p1-s41"}` | UI highlighting, critic |
| `policy` | Policy analyst ← `get_policy` | `PolicyOut` = settlement-engine `PolicyIn` | Auditor, critic |
| `wording` | Policy analyst ← `get_policy_wording` | `WordingOut` | Supervisor (asks the user for their wording when `wording_needed`), explainer |
| `history` | Policy analyst ← `get_claim_history` | `[PastClaimOut]` = `[PastClaimIn]` | Auditor, critic |
| `clauses` | Policy analyst ← `search_clauses` / `clauses_for_rule` | `{clause_id: get_clause result}` | Explainer, critic |
| `settlement` | Auditor ← `expected_settlement` | `SettlementOut` (status, deductions, facts, questions) | Auditor, explainer, critic |
| `row_audits` | Auditor ← `reproduce_deduction` | `{row_id: RowAuditOut}` | Explainer, critic, grievance agent |
| `letter_audit` | Critic ← `audit_settlement_letter` | `LetterAuditOut` (disputable, unverifiable amounts) | Critic, explainer |
| `questions` | From `settlement.questions` and `row_audits[*].questions` | `[QuestionOut]` | Supervisor → `interrupt()` |
| `answers` | User, via `interrupt()` | sets `claim.condition_type` / `claim.room_priced_by_category` | Auditor (re-run) |
| `user_id` | App (M4), from the session | the app's opaque ID | Memory |
| `memory` | Supervisor ← `claimclear_memory` `store.session_memory(user_id).context(policy_no=...)` at session start (empty without consent) | `{policies, recent_claims, balances, open_grievances, figures, note}` ([memory/](memory.md)) | Everyone; critic takes `figures` |
| `security_flags` | Guardrails (M4) from `pages[*].hidden_text`, `metadata`, `annotations`, `form_fields`, `attachments` | M4 | Supervisor |

**Assembling the `case` argument** for every settlement-engine call:

```python
case = {"claim": state["claim"], "policy": state["policy"], "history": state["history"]}
```

`get_policy` and `get_claim_history` already return the exact shapes, so pass them unchanged. A test in `case_records` validates them against the settlement-engine schemas.

**Never put in state or prompts:** policy limits (the engine loads its own), file paths, `dataset_map.json`, the manifest or answer key, or held-out cases.

---

## 7. Node by node

### Document reader

1. `list_case_documents(case_id)`, then `get_document_text(case_id, document_id)` for each document.
2. **Use only `pages[*].text`** (visible text). `hidden_text`, metadata, annotations, form fields and attachments are **not** document content. They go to the guardrails, never into the extraction prompt as facts.
3. If a page has `ocr_status` of `"unavailable"` or `"failed"`, take the **missing-document edge**: ask for a clearer copy. Never guess figures.
4. Extract with structured output, using the **server's own schemas**, taken at runtime from the tool listing so they never drift:

   ```python
   claim_schema  = tk.schema("ClaimIn")      # toolkit; same as below
   letter_schema = tk.schema("LetterIn")
   # under the hood: defs = tools["reproduce_deduction"].args_schema["$defs"]; {**defs["ClaimIn"], "$defs": defs}
   claim  = llm.with_structured_output(claim_schema).invoke(prompt_for_bill(pages))
   letter = llm.with_structured_output(letter_schema).invoke(prompt_for_letter(pages))
   ```

   (Check that the chosen model supports JSON-schema structured output; the plan notes support varies by model.)
5. Ask the model for a `span_id` per extracted field and keep them in `sources`. **Don't add extra keys to `claim` or `letter`**: the servers reject unknown fields.
6. Copy **what the documents say**. Leave `category` and `non_payable` empty unless the bill states them, and **never set `condition_type`** from a guess: the engine works these out or asks.

### Policy analyst

* `get_policy(case_id)` → `policy`; `get_claim_history(case_id)` → `history` (default scope: current policy year, which sub-limits use).
* `search_clauses` with the user's words (the server rewrites them into policy language), one query per letter row topic (room rent, proportionate deduction, co-pay…). Store the clause IDs. For an engine deduction, `clauses_for_rule(rule_ref)` gives the reviewed clauses directly.

### Settlement auditor (ReAct)

1. `expected_settlement(case)`.
   * `status == "needs_information"` → **interrupt** with `settlement.questions`, write the answer into `claim`, call again.
   * `status == "computed"` → continue. `facts` are now the **only** numbers anyone may use.
2. For each letter row (plus `COPAY` and `REJECTION` when present):
   * read the row's wording; `list_hypotheses(kind)` once per kind and **pick** likely methods;
   * `reproduce_deduction(case, letter, row_id, hypothesis_ids=[...picks])`;
   * if `verdict == "not_verifiable"` and `exhaustive == false` → **replan**: call again without `hypothesis_ids`. Log this; it is the replan trace for the minimum bar;
   * if the row has `questions` (`Q-TIE-…`) → interrupt with that one question;
   * if `Q-BREAKDOWN-…` → keep it: the explainer tells the user to ask the insurer for a breakdown.
3. Store each `RowAuditOut` in `row_audits[row_id]`.

**The auditor must never compute or adjust a figure.** It chooses what to test; the tool decides.

### Critic

1. `audit_settlement_letter(case, letter)` (one call re-runs everything).
2. Every rupee figure in the explainer's draft must equal a figure in `letter_audit` / `settlement.facts` (match within ₹0.01). Any figure that matches nothing fails.
3. Verdict words must follow the row verdicts:

   | Verdict | Allowed wording |
   |---|---|
   | `matches_policy` | "matches your policy" |
   | `does_not_match_policy` with positive `difference` | "may be disputable" |
   | `does_not_match_policy` with negative `difference` | "the insurer deducted less than the policy allows" (no dispute) |
   | `method_matches` (co-pay) | "worked out correctly, on the insurer's figures" (not separately disputable) |
   | `not_verifiable` | "we can't check this without…" |

4. The disputable total quoted must equal `letter_audit.disputable_amount`.
5. `get_clause` for every cited clause; `found: false` fails the draft.
6. If anything fails, return the draft **once**; on a second failure, fall back to the plain verdict table.

### Explainer

Writes from an explanation plan where each sentence cites `fact_id`s (e.g. `F-D-PROPORTIONATE`, `F-PAYABLE`) or row IDs, and quotes wording only from `clauses_for_rule` / `get_clause` with its `citation`. Useful raw material: `RowAuditOut.explanation` (factual), the hypothesis `title` and `description` (plain English, from `list_hypotheses`), and `settlement.deductions[*].formula`.

### Grievance agent

Offer a grievance **only** for rows with `verdict == "does_not_match_policy"` and `difference > 0`, and only if `letter_audit.disputable_amount > 0`. Build the letter from those rows' facts; the exact text then goes through Member 4's approval gate.

---

## 8. Tool signals that drive the graph

| Signal in a tool result | Conditional edge |
|---|---|
| `get_document_text`: `ocr_status` is `unavailable` / `failed`, or `DOCUMENT_UNREADABLE` | → ask for a readable document (**missing document**) |
| `get_document_text`: `warnings` mention hidden text, annotations, form fields or attachments | → guardrails record `security_flags`; flow continues on visible text |
| `expected_settlement`: `status == "needs_information"` | → `interrupt()` with `questions`, then back to the auditor |
| `expected_settlement`: `status == "not_admissible"` | → explain the exclusion; compare with a rejection letter |
| `reproduce_deduction`: `not_verifiable` and `exhaustive == false` | → **replan** (same row, all hypotheses) |
| `reproduce_deduction`: `Q-TIE-…` question | → `interrupt()` with that question (**tie between hypotheses**) |
| `audit_settlement_letter`: `letter_arithmetic_gap != 0` | → mention the letter doesn't add up (it's in `warnings`) |
| `audit_settlement_letter`: `disputable_amount > 0` and the user wants to act | → grievance agent (**wants to dispute**) |
| `audit_settlement_letter`: `disputable_amount == 0` | → no grievance offered (protects against false disputes) |
| any `tool_error(...)` | → see the [error table](#5-reading-tool-results-and-errors) |

---

## 9. policy-kb: citing the wording

The `policy-kb` server ([servers/policy_kb](policy_kb.md#mcp-server-and-agent-tools)) serves the indexed policy wording (today Go Digit's Arogya Sanjeevani, 127 clauses):

| Tool | Use it for |
|---|---|
| `search_clauses(query, k=5)` | Policy analyst: one query per letter-row topic, in the user's words (the server rewrites them into policy terms). Store the returned `clause_id`s |
| `get_clause(clause_id)` | Critic: check every cited clause (`found: false` → the citation fails). Explainer: quote the exact `text` with its `citation` |
| `clauses_for_rule(rule_ref)` | Explainer and analyst: each engine deduction and fact carries a `rule_ref`; this returns the reviewed clauses behind it. Cite `clauses[0]`; if `differs_from_engine` is set, say the wording and the engine differ |

Rules:
* Quote only text a policy-kb tool returned, with its `citation`.
* `synthetic: true` means a test wording: never show it to a user as their policy.
* The server starts even before an index is built; then every call returns `INDEX_UNAVAILABLE`, and the explainer falls back to the engine's rule summaries (`servers/settlement_engine/engine/rules.py`, `RULE_REFS`), clearly marked as summaries, not policy wording.
* The toolkit still has stubs (`claimclear_tools.stubs`) with the same names and shapes, used only when the server isn't connected; every stub result has `stub: true`. `ClaimClearToolkit(servers={}, local_tools=policy_kb.tools.make_tools(kb))` runs the real tools in-process instead.

---

## 10. Baselines C0 and C1

The E1 experiment compares three designs with the **same model, tools and budget**:

| Config | How it uses the servers |
|---|---|
| **C0** fixed workflow | No agent choices: `list_case_documents` → `get_document_text` → one extraction call → `get_policy` / `get_claim_history` → **`audit_settlement_letter`** → one explanation call |
| **C1** single agent | One ReAct agent given **all eight tools** at once |
| **C2** team | The graph above, each agent with its own tool list |

Tool calls are cheap (about 15 ms each over a session), so E1 cost differences come from LLM calls, not the servers.

---

## 11. Keeping both sides in step

* **Schema snapshots.** `servers/*/tests/snapshots/*.json` pin every tool's name, annotations and input/output schema. Any change fails CI until the snapshot is regenerated, and **a schema change needs Member 3's review on the pull request.**

  ```bash
  cd servers/settlement_engine && ../../.venv/Scripts/python.exe -m mcp_server --dump-schemas > tests/snapshots/settlement_engine_tools.json
  ```

  ```bash
  cd servers/case_records && ../../.venv/Scripts/python.exe -m case_records --dump-schemas > tests/snapshots/case_records_tools.json
  ```

  ```bash
  cd servers/policy_kb && ../../.venv/Scripts/python.exe -m policy_kb.mcp_server --dump-schemas > tests/snapshots/policy_kb_tools.json
  ```

  The same for `insurer_portal` (`python -m insurer_portal --dump-schemas`) and `document_reader`. Then refresh the shared contracts: `cd contracts && ../.venv/Scripts/python.exe -m claimclear_contracts.export` (CI runs it with `--check`).

* **Taking schemas at runtime** (`args_schema["$defs"]`, §7) means the document reader always extracts into the current shape.
* **Fixed model IDs and prompts** live in Member 3's versioned config; **policy rules** live in the server's config (`CLAIMCLEAR_POLICY_RULES`). Neither side reaches into the other's.
* **Separation the guide requires:** Member 3 tunes on development cases only. `var/dataset_map.json` and the held-out folder stay with Member 1.
* **Weekly integration demo** on the shared branch: run SET-01 through the graph and check the ₹8,522.86.

---

## 12. Verified end to end

We ran an agent-side script in a **separate Python 3.14 environment** with `langchain-mcp-adapters 0.3.2` (mcp 1.30 client). It started both servers from `<repo>/.venv` (mcp 2.3) over stdio and played the document reader's part with SET-01's extracted claim and letter:

| Step | Tool | Result |
|---|---|---|
| 1 | `list_case_documents` | 3 documents in the case (bill, discharge summary, letter) |
| 2 | `get_document_text` (letter) | Visible text contains ₹30,371.43 |
| 3 | `get_policy`, `get_claim_history` | Policy and empty history, passed through unchanged |
| 4 | `expected_settlement` | `computed`, payable ₹95,617.50 |
| 5 | `reproduce_deduction` R3 with `["prop_incl_pharmacy"]` | `not_verifiable`, `exhaustive: false` → replan |
| 6 | `reproduce_deduction` R3, all hypotheses | `does_not_match_policy`, `prop_on_all_lines`, +₹8,971.43 |
| 7 | `audit_settlement_letter` | disputable ₹8,522.86, unverifiable ₹0 |
| 8 | `get_document_text` with a document ID that isn't in the case | error text with `DOCUMENT_NOT_IN_CASE` (no exception) |

The toolkit's live tests (`agents/toolkit/tests/test_toolkit_live.py`) now repeat this run against all five servers, and `eval/dev_cases/run.py` does it for every dev case.

We also confirmed:
- one session per server makes 5 calls in 0.08 s;
- `ToolMessage.artifact["structured_content"]` holds the typed result;
- `args_schema["$defs"]` exposes `ClaimIn`, `LetterIn`, `PolicyIn`, `PastClaimIn` and the rest.

---

## 13. Checklist for Member 3

- [ ] `requirements-agents.txt` installed in `.venv-agents` (brings `claimclear_tools`)
- [ ] `agents/toolkit/examples/verify_settlement_demo.py SET-01` runs and shows ₹8,522.86
- [ ] Graph built inside `async with ClaimClearToolkit(tool_interceptors=[...]) as tk` (Member 4's hook 2), agents given `tk.for_agent(...)`
- [ ] Each agent's tools in its own `ToolNode(..., awrap_tool_call=...)` with Member 4's wrapper (hook 1); `create_react_agent` takes that `ToolNode`
- [ ] Conditional edges use `claimclear_tools.signals`; critic uses `claimclear_tools.critic`
- [ ] Separate agent venv (Python 3.14) with `langgraph`, `langchain-openai`, `langchain-mcp-adapters`
- [ ] `MultiServerMCPClient` config pointing at the **servers'** venv; one **session** per server
- [ ] `register_dataset` run once; `case_id`s taken from the app or the dev store, **never** from `dataset_map.json` in prompts
- [ ] Per-agent tool lists exactly as in [§4](#4-which-agent-gets-which-tools)
- [ ] `structured()` / `tool_error()` helpers; state filled from `artifact["structured_content"]`
- [ ] `CaseState` fields and shapes as in [§6](#6-casestate-the-data-contract); `case = {claim, policy, history}`
- [ ] Document reader extracts into `ClaimIn` / `LetterIn` from `args_schema`, visible text only, with `sources`
- [ ] Conditional edges for every signal in [§8](#8-tool-signals-that-drive-the-graph), including interrupt on questions and the replan edge
- [ ] Critic compares every draft figure with tool facts; verdict wording table enforced
- [ ] Policy-kb index built (`python -m policy_kb build ...`); critic checks every citation with `get_clause`
- [ ] C0 and C1 baselines built on the same tools
- [ ] SET-01 end to end in the weekly demo: payable ₹95,617.50, R3 `prop_on_all_lines`, disputable ₹8,522.86
