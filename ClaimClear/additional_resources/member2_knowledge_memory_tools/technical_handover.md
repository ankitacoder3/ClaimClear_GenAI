# ClaimClear: Member 2 technical handover

Member 2 is the knowledge, memory and tools engineer. This document explains everything Member 2 built in this repository: the architecture, the five MCP servers and all 18 tools with real input and output examples, how Member 3's agents connect and call them, where hooks attach in a tool call, document processing and OCR, the memory architecture and storage, the end-to-end workflow, technologies and configuration, how to run and test everything, and a walkthrough of every module.

It is plain Markdown: edit any part. Diagrams are Mermaid (GitHub, GitLab and VS Code render them). Tool tables and examples were produced by calling the real tools on the synthetic dataset.

**Status labels** used throughout:

| Label | Meaning |
|---|---|
| **Implemented** | Built here, tested, usable now. |
| **Partial** | Built in part; what exists and what is missing is stated next to it. |
| **Planned / other member** | Not built here: a later Member 2 task, or Member 3's or Member 4's responsibility in the plan (named). |

## Contents

1. [Summary and status](#1-summary-and-status)
2. [System architecture](#2-system-architecture)
3. [How a tool call travels, and where hooks attach](#3-how-a-tool-call-travels-and-where-hooks-attach)
4. [MCP server implementation](#4-mcp-server-implementation)
5. [Connecting from Member 3's code](#5-connecting-from-member-3s-code)
6. [Tool reference](#6-tool-reference)
7. [Settlement engine and matcher](#7-settlement-engine-and-matcher)
8. [Document processing and OCR](#8-document-processing-and-ocr)
9. [Case and document store](#9-case-and-document-store)
10. [Policy knowledge base](#10-policy-knowledge-base)
11. [Memory architecture](#11-memory-architecture)
12. [Storage and databases](#12-storage-and-databases)
13. [End-to-end workflow](#13-end-to-end-workflow)
14. [Contracts and the agents' toolkit](#14-contracts-and-the-agents-toolkit)
15. [Technologies, dependencies and configuration](#15-technologies-dependencies-and-configuration)
16. [Run and test everything](#16-run-and-test-everything)
17. [Files and modules walkthrough](#17-files-and-modules-walkthrough)
18. [Error codes](#18-error-codes)
19. [Known limitations and next tasks](#19-known-limitations-and-next-tasks)
20. [Appendix: a complete case and letter (SET-01)](#20-appendix-a-complete-case-and-letter-set-01)

## 1. Summary and status

ClaimClear checks a health-insurance settlement letter against the policy: it works out how each deduction was calculated, says whether the wording allows it, explains it plainly and, after the policyholder approves the exact text, files a grievance. Member 2 builds the parts that **know things and compute things**, so the agents never do: policy-wording search, the settlement engine, document reading and OCR, long-term memory, and the MCP servers that expose them.

**The rule behind every part: the model proposes, code decides.** No LLM computes or checks a rupee figure (money is `Decimal`, rounded half up to the paisa, inside the engine). Document text is data, never instructions. Every agent-facing tool is reached through a `case_id`, never a file path. Every tool is marked read or write, and the only write tool agents get sits behind an approval gate.

| Area | Status | What exists / what is missing |
|---|---|---|
| MCP servers (3 core) | Implemented | settlement-engine (4 tools), case-records (5), policy-kb (5); schemas, structured errors, one test per tool, snapshots, stdio + HTTP |
| document-reader | Implemented | 2 tools + library; PyMuPDF extraction, hidden-text rules, Tesseract OCR, checks, cache |
| insurer-portal | Partial | interface, approval checks and dry-run store built; the mock portal (Member 4) not |
| Settlement engine | Implemented | 12 steps, 41 methods, matcher; the 5 cross-check gaps fixed; some rows still not verifiable |
| Policy retrieval | Partial | ingestion, BM25 + vectors + RRF, rewriting, rule maps built; reranker not measured; final Recall@5 needs Member 1's labels |
| Memory | Implemented | store with consent, retention, forget, context; SQLite and PostgreSQL |
| Memory on vs off | Partial | runner and first result; rerun with the graph pending |
| Production storage | Implemented | PostgreSQL index + MinIO files, PostgreSQL memory, pgvector vectors; text cache stays local |
| Contracts | Implemented | CaseState, hand-offs, tool schemas, errors, wording; Member 3 review pending |
| Agents' toolkit | Implemented | connection, per-agent tools, signals, critic checks, live tests |
| CI | Partial | workflow pushed; first run not checked here |
| Hooks | Planned / other member | Member 4; Member 2 provides access marks, may_use, error codes (section 12) |
| Approval gate | Planned / other member | Member 4; the portal already checks text hash and token |
| Agents / LangGraph graph | Planned / other member | Member 3 |
| App, UI, guardrails, deployment | Planned / other member | Member 4 |

**Latest full test run** (Tesseract installed, PostgreSQL + pgvector and MinIO running, so OCR and storage tests ran):

| Suite | Folder | Result |
|---|---|---|
| settlement-engine | `servers/settlement_engine` | 321 passed |
| document-reader | `servers/document_reader` | 80 passed |
| case-records | `servers/case_records` | 59 passed |
| policy-kb | `servers/policy_kb` | 114 passed, 1 skipped |
| insurer-portal | `servers/insurer_portal` | 13 passed |
| memory | `memory` | 91 passed |
| contracts | `contracts` | 20 passed |
| memory on vs off runner | `development/dev_eval/memory_on_off` | 3 passed |
| agents' toolkit | `agents/toolkit` | 45 passed |

All five servers answered over HTTP (`scripts/dev_servers.py --check`).

**Whole-application run over the 42 dev cases** (`development/dev_eval/dev_cases/run.py`, details in `additional_resources/member2_knowledge_memory_tools/evaluation_dev_cases.md`): all 42 ran to the end; 40/42 overall verdicts, 89/94 row verdicts, 28/31 payables and 37/40 disputable amounts right. Synthetic cases: 21/22 overall, 20/20 rows, 21/21 disputable amounts. gen-data cases, which use another insurer's wording and phrasing: 19/20 overall, 69/74 rows, 16/19 disputable amounts. Section 16.1 has the full result. The README lists what the gen-data cases showed, what was fixed in the engine, what still differs, and where the answer key may be wrong. Decided: the proportionate deduction keeps IRDAI's 2020 rule, so three gen-data answers that cut consumables and diagnostics are labelled as decided disagreements (`development/dev_eval/dev_cases/decisions.json`). The dataset itself is explained in `additional_resources/member2_knowledge_memory_tools/dataset_guide.md`.

## 2. System architecture

Green: Member 2, built here. Blue: Member 3 (agents). Orange: Member 4 (app, security, deployment), not built here. Yellow: partial. Dotted arrows: optional production backends.

```mermaid
flowchart TB
    user(["Policyholder"])

    subgraph M4["Member 4 (not built here)"]
        app["Chat UI + FastAPI<br/>sessions, input/output guardrails"]
        gate{{"Approval gate<br/>exact text + SHA-256"}}
        hooks["Hooks<br/>pre-tool: permission, budget<br/>post-tool: scrubbed log"]
    end

    subgraph M3["Member 3 (not built here)"]
        agents["Supervisor + planner<br/>document reader, policy analyst,<br/>settlement auditor, critic, explainer,<br/>grievance agent"]
    end

    subgraph LIB["Member 2: libraries"]
        toolkit["claimclear_tools<br/>connection, per-agent tools,<br/>signals, critic checks"]
        contracts["claimclear_contracts<br/>CaseState, hand-offs,<br/>tool schemas, errors"]
        memory["claimclear_memory<br/>consent, retention, context"]
    end

    subgraph MCP["Member 2: MCP servers"]
        se["settlement-engine :8101"]
        cr["case-records :8102"]
        pk["policy-kb :8103"]
        ip["insurer-portal :8104<br/>interface + dry run"]
        dr["document-reader :8105<br/>for the app"]
    end

    subgraph DATA["Member 2: storage"]
        store[("Case store<br/>index + files")]
        index[("Policy index<br/>clauses + vectors")]
        memdb[("Memory database")]
        tess["Tesseract OCR"]
        pg[("PostgreSQL + pgvector")]
        minio[("MinIO")]
    end

    user --> app
    app --> agents
    agents --> toolkit
    agents --> memory
    agents -.-> contracts
    toolkit -->|"MCP: stdio or HTTP"| se
    toolkit --> cr
    toolkit --> pk
    toolkit --> ip
    cr --> store
    cr -->|"reader library"| tess
    dr --> tess
    pk --> index
    memory --> memdb
    store -.-> pg
    store -.-> minio
    index -.-> pg
    memdb -.-> pg

    classDef m2 fill:#e3f4e8,stroke:#2f855a,color:#1a202c
    classDef m3 fill:#e6eefc,stroke:#3b6fd8,color:#1a202c
    classDef m4 fill:#fdf0e6,stroke:#c05621,color:#1a202c
    classDef partial fill:#fff4db,stroke:#b7791f,color:#1a202c
    class toolkit,contracts,memory,se,cr,pk,dr,store,index,memdb,tess,pg,minio m2
    class agents m3
    class app,gate,hooks m4
    class ip partial
```

Hooks sit between the agents and the toolkit on every tool call (section 3); the approval gate sits in front of `file_grievance`. The upload path does not go through the agents:

```mermaid
flowchart LR
    user(["Policyholder"]) -->|"upload"| app["App (M4)<br/>file checks"]
    app -->|"create_case, add_document"| store[("CaseStore<br/>neutral IDs")]
    app -.->|"optional: read_document<br/>for masking or routing"| dr["document-reader :8105"]
    app -.->|"user's own policy:<br/>register_uploaded_wording"| pk["policy-kb :8103"]
    cr["case-records :8102<br/>get_document_text"] -->|"reads stored bytes"| store
    cr -->|"reader library"| lib["DocumentReader<br/>PyMuPDF + Tesseract"]
    dr --> lib
    classDef m2 fill:#e3f4e8,stroke:#2f855a,color:#1a202c
    classDef m4 fill:#fdf0e6,stroke:#c05621,color:#1a202c
    class store,dr,pk,cr,lib m2
    class app m4
```

| Component | Folder | Port | Type | Used by |
|---|---|---|---|---|
| settlement-engine | `servers/settlement_engine` | 8101 | MCP server + engine library | settlement auditor, critic |
| case-records | `servers/case_records` | 8102 | MCP server + case store | document reader, policy analyst |
| policy-kb | `servers/policy_kb` | 8103 | MCP server + retrieval library | policy analyst, critic, explainer; app (uploads) |
| insurer-portal | `servers/insurer_portal` | 8104 | MCP interface, dry-run backend | grievance agent only (write, gated) |
| document-reader | `servers/document_reader` | 8105 | MCP server + reader library | case-records; the app (not agents) |
| claimclear_memory | `memory` | - | library | Member 3's graph, Member 4's app |
| claimclear_contracts | `contracts` | - | library | both sides |
| claimclear_tools | `agents/toolkit` | - | library (agents' environment) | Member 3 |
| storage services | `deploy/storage.compose.yml` | 5432, 9000 | Docker Compose | production backends, tests |

**Two Python environments.** `langchain-mcp-adapters` (the agents' MCP client) needs mcp 1.x; the servers use mcp 2.3. They never share an environment: each server runs as its own process (stdio) or service (HTTP), and the two versions talk over the protocol (tested by the toolkit's live tests).

| Environment | Holds | Install |
|---|---|---|
| `.venv` (servers) | servers, document reader, memory, contracts, server tests | `pip install -r requirements-servers.txt` |
| `.venv-agents` | toolkit, contracts, memory, policy-kb in-process tools, LangGraph, langchain-mcp-adapters | `pip install -r requirements-agents.txt` |

## 3. How a tool call travels, and where hooks attach

**Status: the hooks themselves are not built here (Member 4 in the plan).** What *is* built: the two places they attach (both tested against the live servers), and everything a hook needs to decide (access marks, the per-agent tool table, error codes, the approval check on the write tool).

**In short**, every tool call passes three checkpoints, two of them hooks:

| | Hook 1: before the toolkit | Hook 2: inside the toolkit | After the toolkit |
|---|---|---|---|
| Where | LangGraph's `ToolNode(..., awrap_tool_call=hook)`, around each call an agent node makes | `ClaimClearToolkit(tool_interceptors=[...])`, around every MCP call | the MCP server itself |
| Knows | **which agent** is calling, and the graph state | which **server** and the exact arguments | its own input schema |
| For | permission (`may_use(agent, tool)`), case access, budget | refusing or rewriting a call, logging, scrubbing personal data, timing | rejecting bad input with an error code; `file_grievance` refuses without the approval token |
| Written by | Member 4 | Member 4 | Member 2 (built) |

**Wiring them in is Member 3's part:** build the toolkit once per graph run with Member 4's interceptors, and give each agent node its own `ToolNode` with Member 4's wrapper (code in 3.3). A refusal from either hook comes back as an ordinary tool error (`ToolMessage` with `status="error"` and a JSON code), so `results.tool_error(msg)` and the graph's edges handle it like any other error.

```mermaid
sequenceDiagram
    autonumber
    participant A as Agent node (M3)
    participant TN as LangGraph ToolNode
    participant T as LangChain tool (toolkit)
    participant I as MCP interceptors
    participant S as MCP session (stdio/HTTP)
    participant M as MCP server (M2)
    participant C as Core (engine, store, kb)
    A->>TN: AIMessage with tool_calls
    Note over TN: HOOK POINT 1: awrap_tool_call<br/>knows the agent and graph state<br/>pre: permission, case access, budget
    TN->>T: ainvoke(tool_call)
    T->>I: MCPToolCallRequest(name, args, server_name)
    Note over I: HOOK POINT 2: tool_interceptors<br/>knows the server and arguments<br/>pre: refuse or rewrite, post: log, scrub, time
    I->>S: call_tool(name, args)
    S->>M: tools/call
    M->>M: validate input against the pydantic schema
    M->>C: run the tool
    C-->>M: result or domain error
    M-->>S: structured content, or error JSON {code, message, retryable}
    S-->>I: CallToolResult
    Note over I: post-tool part of HOOK POINT 2
    I-->>T: result
    T-->>TN: ToolMessage (artifact.structured_content)
    Note over TN: post-tool part of HOOK POINT 1
    TN-->>A: ToolMessage
```

### 3.1 The two hook points

|  | Hook point 1: `ToolNode(awrap_tool_call=...)` | Hook point 2: `ClaimClearToolkit(tool_interceptors=[...])` |
|---|---|---|
| Library | LangGraph `langgraph.prebuilt.ToolNode` | `langchain-mcp-adapters` interceptors, passed by the toolkit to `load_mcp_tools` |
| Runs | around each tool call one agent node makes | around every MCP call through the toolkit (first interceptor is outermost) |
| Knows | the tool call (name, args, id), the tool, the graph state, the runtime | tool name, args, `server_name`, headers, LangGraph runtime |
| Best for | permission per agent, case ownership from state, budget per case | audit log, scrubbing, timing and cost, server-level rules |
| Refuse a call | return a `ToolMessage(status="error")` instead of calling `execute` | return a `ToolMessage` instead of calling `handler` |
| Status | Implemented (LangGraph feature; tested here) | Implemented (toolkit parameter added and tested here) |

### 3.2 Intended order (plan; hooks are Member 4's)

| # | Stage | Where | Inputs Member 2 provides (implemented) |
|---|---|---|---|
| 1 | Permission: may this agent call this tool? | hook point 1 | `claimclear_tools.agents.may_use(agent, tool)`, `AGENT_TOOLS`, `WRITE_TOOLS`, `APP_ONLY_TOOLS`; `claimclear_contracts.tools.access(name)`, `app_only(name)` |
| 2 | Case access: does the session's user own `case_id`? | hook point 1 (state has `user_id`, `case_id`) | every agent tool takes a `case_id`; the store refuses another case's documents |
| 3 | Budget: tool calls and cost per case | hook point 1 | - |
| 4 | Tool runs: schema validation, scoping, structured errors | MCP server | implemented in every server |
| 5 | Scrub personal data from the trace | hook point 2 (post) | untrusted channels kept apart in `DocumentTextOut`; `signals.untrusted_channels()` |
| 6 | Audit log, latency, tokens | hook point 2 (post) | error codes and `server_name` |
| 7 | Write tool only: approval | approval gate before `file_grievance` | `file_grievance` checks the text's SHA-256 and the approval token (below) |

### 3.3 Code: both hook points (as tested in `agents/toolkit/tests/test_toolkit_live.py`)

```python
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from claimclear_tools import ClaimClearToolkit
from claimclear_tools.agents import may_use


# Hook point 2: around every MCP call (server-level)
async def audit_log(request, handler):                 # request: MCPToolCallRequest
    result = await handler(request)                     # the real call to the MCP server
    print("tool", request.server_name, request.name)   # Member 4: scrubbed trace, latency, cost
    return result


async def refuse_hook(request, handler):               # pre-tool: refuse without reaching the server
    if request.name == "list_hypotheses":               # Member 4: any server-level rule
        return ToolMessage(content='{"code": "NOT_ALLOWED", "message": "refused by hook", "retryable": false}',
                           tool_call_id="refused", status="error")
    return await handler(request)


# Hook point 1: around each call one agent node makes (agent-level)
def permission_hook(agent: str):
    async def wrapper(request, execute):                # request.tool_call = {"name", "args", "id"}
        name = request.tool_call["name"]
        if not may_use(agent, name):                    # Member 4: also case ownership and budget here
            return ToolMessage(content=f'{{"code": "NOT_ALLOWED", "message": "{agent} may not call {name}"}}',
                               tool_call_id=request.tool_call["id"], status="error")
        return await execute(request)
    return wrapper


async def main():
    async with ClaimClearToolkit(tool_interceptors=[audit_log, refuse_hook]) as tk:   # first is outermost
        node = ToolNode(tk.for_agent("explainer"), awrap_tool_call=permission_hook("explainer"))
        g = StateGraph(MessagesState)
        g.add_node("explainer_tools", node)
        g.add_edge(START, "explainer_tools")
        g.add_edge("explainer_tools", END)
        calls = [{"name": "get_clause", "args": {"clause_id": "C.1.1"}, "id": "a", "type": "tool_call"}]
        out = await g.compile().ainvoke({"messages": [AIMessage(content="", tool_calls=calls)]})
        print(out["messages"][-1].content)
```

`NOT_ALLOWED` is the hook's own code in this example; no server returns it.

### 3.4 The approval check that is implemented

`file_grievance` (insurer-portal) already enforces the server side of the gate: `sha256(text)` must equal `text_sha256` (an edit after approval fails with `TEXT_HASH_MISMATCH`); an `approval_token` is required; and when `CLAIMCLEAR_GATE_SECRET` is set the token must equal `HMAC-SHA256(secret, text_sha256)` (`APPROVAL_REQUIRED` otherwise). Issuing tokens through LangGraph `interrupt()` (approve, edit, reject) is Member 4's gate, not built here. Memory keeps only the approved text's hash.

## 4. MCP server implementation

All five servers use the official MCP Python SDK (`mcp==2.3.0`, class `MCPServer`) and the same four layers:

```mermaid
flowchart LR
    main["__main__.py<br/>transport, host, port,<br/>--dump-schemas"] --> app["app.py: create_server()<br/>@server.tool: validate,<br/>call core, structured error"]
    app --> schemas["schemas.py<br/>pydantic inputs and outputs<br/>(the contract)"]
    app --> core["core modules<br/>pure logic, no MCP"]
    tests["tests/<br/>unit tests, one test per tool,<br/>schema snapshot, stdio"] -.-> app
    classDef m2 fill:#e3f4e8,stroke:#2f855a,color:#1a202c
    class main,app,schemas,core,tests m2
```

| Server | Run from | stdio (development) | Streamable HTTP | Endpoint |
|---|---|---|---|---|
| settlement-engine | `servers/settlement_engine` | `python -m mcp_server` | `python -m mcp_server --transport streamable-http --port 8101` | `http://127.0.0.1:8101/mcp` |
| case-records | `servers/case_records` | `python -m case_records` | `... --transport streamable-http --port 8102` | `http://127.0.0.1:8102/mcp` |
| policy-kb | `servers/policy_kb` | `python -m policy_kb.mcp_server` | `... --transport streamable-http --port 8103` | `http://127.0.0.1:8103/mcp` |
| insurer-portal | `servers/insurer_portal` | `python -m insurer_portal` | `... --transport streamable-http --port 8104` | `http://127.0.0.1:8104/mcp` |
| document-reader | `servers/document_reader` | `python -m document_reader` | `... --transport streamable-http --port 8105` | `http://127.0.0.1:8105/mcp` |

Add `--host 0.0.0.0` inside Docker. `scripts/dev_servers.py` starts all five over HTTP (`--check` starts, confirms and stops). Logs go to stderr.

**Access marks.** Every tool has MCP annotations and a `_meta` dictionary a hook can read without knowing the tool:

| Kind | Annotations | `_meta` | Tools |
|---|---|---|---|
| Agent read tools | read_only, not destructive, idempotent, closed world | `{"access": "read"}` | 14: settlement-engine (4), case-records (5), policy-kb (4), grievance_status |
| App-only read tools | read-only | `{"access": "read", "caller": "app"}` | read_document, reader_status |
| App-only write tool | not read-only | `{"access": "write", "caller": "app"}` | register_uploaded_wording |
| Agent write tool | destructive | `{"access": "write", "requires": "approval_token"}` | file_grievance |

**Errors.** An expected failure is a tool error whose text is `Error executing tool <name>: {"code": ..., "message": ..., "retryable": ...}`. Real example (`get_policy` on an unknown case):

```text
Error executing tool get_policy: {"code": "CASE_NOT_FOUND", "message": "no case 'case_0000000000000000'", "retryable": false}
```

**Schema contract.** `tests/snapshots/<server>_tools.json` pins every tool's name, annotations, meta and JSON schemas; a test fails on any change. After a deliberate change: `python -m <module> --dump-schemas > tests/snapshots/<server>_tools.json`, then `python -m claimclear_contracts.export` in `contracts/`, then tell Member 3.

## 5. Connecting from Member 3's code

**Why the toolkit, not the servers directly.** The agents could call the MCP servers themselves. `claimclear_tools` does the plumbing every node would otherwise repeat, and keeps the rules in one tested place:

| Without the toolkit, every node would have to... | The toolkit gives |
|---|---|
| start or reach four servers and keep a session to each | `async with ClaimClearToolkit() as tk:`: one session per server, about 100 times faster than a process per call |
| keep its own list of allowed tools | `tk.for_agent("settlement_auditor")`, from one table (`AGENT_TOOLS`) that Member 4's permission hook reads too |
| dig the typed result out of each reply and parse errors | `results.structured(msg)`; `results.tool_error(msg)` gives the error code and the graph action |
| decide in prompts where the graph goes next | `signals`: ask the user, replan, missing document, offer a grievance, inconsistent bill (tested code, not prompt text) |
| assemble the engine's input and apply the user's answers | `case.build_case(...)`, `case.apply_answer(...)` |
| check that every rupee in a draft came from a tool | `critic.unsupported_figures`, `critic.wording_for` |
| bridge two MCP versions | nothing: the toolkit runs in the agents' environment (mcp 1.x) and reaches the servers (mcp 2.3) over MCP |
| attach Member 4's hooks | `tool_interceptors=[...]` (hook point 2) and `may_use` for hook point 1 (section 3) |

The servers still decide every figure and verdict; the toolkit only connects the agents to them correctly. Section 5.5 shows a call without the toolkit.

### 5.1 Steps

1. Create both environments (section 16) and build the local data (policy index, case store).
1. Choose a mode. **stdio** (default): the toolkit starts each server as a child process with the servers' Python (`<repo>/.venv`, or `CLAIMCLEAR_SERVER_PYTHON`). **http**: start the servers once with `python scripts/dev_servers.py` and set `CLAIMCLEAR_MCP_MODE=http` (URLs from `CLAIMCLEAR_*_URL`, default `http://127.0.0.1:810x/mcp`).
1. Open `ClaimClearToolkit` once per graph run (one persistent session per server; a session call is fast, a process per call is not).
1. Give each agent node only its tools: `tk.for_agent("settlement_auditor")` (table in section 14).
1. Wire Member 4's hooks: open the toolkit with `tool_interceptors=[...]` and give each agent its own `ToolNode(tk.for_agent(name), awrap_tool_call=...)` (section 3.3).
1. Read results from the `ToolMessage`: `results.structured(msg)` (the typed result) and `results.tool_error(msg)` (the error code). Put structured results in `CaseState` (section 14).
1. For deterministic code (critic, baselines), call tools directly: `await tk.expected_settlement(case)` returns a dict or raises `ClaimClearToolError`.

### 5.2 Connect and call tools (toolkit)

```python
import asyncio
from claimclear_tools import ClaimClearToolkit, ClaimClearToolError, results, signals

async def main(case_id: str):
    async with ClaimClearToolkit() as tk:                     # mode from CLAIMCLEAR_MCP_MODE (stdio default)
        print(sorted(tk.tools))                               # every live tool
        auditor_tools = tk.for_agent("settlement_auditor")    # LangChain tools for that node only

        # typed calls: structured result as a dict
        docs = await tk.list_case_documents(case_id)
        letter_id = next(d["document_id"] for d in docs["documents"] if d["role"] == "settlement_letter")
        text = await tk.get_document_text(case_id, letter_id)
        if signals.after_document_text(text) == signals.MISSING_DOCUMENT:
            ...                                               # ask for a readable copy
        policy = await tk.get_policy(case_id)
        history = await tk.get_claim_history(case_id)         # list of past claims
        hits = await tk.search_clauses("they cut my room rent", k=3, wording_uin=policy["wording_uin"])

        # the case argument for every settlement-engine tool
        claim = ...                                           # extracted by the document reader into tk.schema("ClaimIn")
        case = {"claim": claim, "policy": policy, "history": history}
        try:
            settlement = await tk.expected_settlement(case)
        except ClaimClearToolError as e:
            print(e.info.code, e.info.message)                # e.g. POLICY_MISMATCH

asyncio.run(main("case_0123456789abcdef"))
```

### 5.3 Call a tool the way an agent does (a tool call)

```python
msg = await tk.tool("reproduce_deduction").ainvoke({
    "type": "tool_call", "id": "call_1", "name": "reproduce_deduction",
    "args": {"case": case, "letter": letter, "row_id": "R3", "hypothesis_ids": ["prop_on_all_lines"]},
})
row = results.structured(msg)          # RowAuditOut as a dict (msg.artifact["structured_content"])
err = results.tool_error(msg)          # None, or ToolErrorInfo(tool, code, message, retryable, action)
route = signals.after_row_audit(row)   # "replan", "ask_user" or "done"
```

### 5.4 Tools inside a LangGraph agent

The tool part below is what the hook test runs. The model part is the standard LangChain pattern; it needs an OpenRouter key and was not run here.

```python
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

tools = tk.for_agent("policy_analyst")
llm = ChatOpenAI(model="openai/gpt-4.1-mini", base_url="https://openrouter.ai/api/v1",
                 api_key=os.environ["OPENROUTER_API_KEY"]).bind_tools(tools)

async def analyst(state: MessagesState):
    return {"messages": [await llm.ainvoke(state["messages"])]}

g = StateGraph(MessagesState)
g.add_node("analyst", analyst)
g.add_node("analyst_tools", ToolNode(tools))          # add awrap_tool_call=... for hooks (section 3)
g.add_edge(START, "analyst")
g.add_conditional_edges("analyst", tools_condition, {"tools": "analyst_tools", "__end__": END})
g.add_edge("analyst_tools", "analyst")
app = g.compile()
```

### 5.5 Without the toolkit

```python
# agents' environment, servers running over HTTP (scripts/dev_servers.py)
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

client = MultiServerMCPClient({
    "settlement-engine": {"transport": "streamable_http", "url": "http://127.0.0.1:8101/mcp"},
    "case-records":      {"transport": "streamable_http", "url": "http://127.0.0.1:8102/mcp"},
    "policy-kb":         {"transport": "streamable_http", "url": "http://127.0.0.1:8103/mcp"},
})
async with client.session("case-records") as session:     # keep the session open for the whole run
    tools = {t.name: t for t in await load_mcp_tools(session)}

# servers' environment, in process (tests, scripts)
from mcp import Client
from case_records.app import create_server
async with Client(create_server()) as c:
    r = await c.call_tool("get_policy", {"case_id": "case_0123456789abcdef"})
    print(r.structured_content if not r.is_error else r.content[0].text)
```

**Schemas for structured extraction:** `tk.schema("ClaimIn")` and `tk.schema("LetterIn")` from the live listing, or `claimclear_contracts.tools.schema("ClaimIn")` without a server. Do not add keys the schema does not have: the servers reject unknown fields. Leave `category`, `non_payable` and `condition_type` empty unless the bill or the user states them; the engine works them out or asks.

**Never** read `var/dataset_map.json` or held-out cases, and never put them in prompts.

## 6. Tool reference

Every tool below: what it does (the server's own description), how it works, who calls it, the toolkit call, every input field, and a **real example** input and output from calling it on the synthetic dataset. Examples are trimmed: long lists show their first items and long strings end in `…`. The full engine case used in the examples is in the appendix. Full JSON schemas: `contracts/claimclear_contracts/tool_schemas.json`.

### 6.1 settlement-engine

Signature challenge A: the policy-correct settlement and which calculation reproduces each figure on the insurer's letter. Code in `engine/` (no MCP) and `mcp_server/`.

#### `expected_settlement`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Expected settlement | read | settlement auditor, critic | `settlement = await tk.expected_settlement(case)` |

**What it does.** Work out what the policy wording says should be paid on a claim: every deduction with its formula and rule, the admissible amount, co-pay and payable amount, with a fact_id for every figure. Returns status 'needs_information' with questions instead of guessing.

**How it works.** Converts the `case` (ClaimIn, PolicyIn, PastClaimIn list) to engine objects, refuses a claim on another policy (canonical form, so look-alike characters match) or history on another policy, picks the rules for the case's wording (catalogue rules file, else the standard rules with a warning), then runs `compute_settlement` (the 12 steps in section 5).

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case | CaseIn | yes | Everything the engine needs for one claim. |

Nested input models:

| Model | Fields |
|---|---|
| BillLineIn | line_id, description, amount, qty, rate, gst_pct, non_payable, category, date |
| CaseIn | claim, policy, history |
| Category | one of: room, icu, nursing, professional_fees, operation_theatre, diagnostics, pharmacy, consumables, implants, blood_products, package, ambulance, unknown |
| ClaimIn | claim_id, policy_no, admission, discharge, lines, diagnosis, procedure, discount, printed_total, condition_type, room_priced_by_category |
| ConditionType | one of: accident, illness, listed_illness_short, listed_illness_long, pre_existing |
| PastClaimIn | claim_id, policy_no, admission, status, settled_amount, diagnosis, procedure |
| PolicyIn | policy_no, sum_insured, period_start, period_end, first_inception, holder, insurer, product, wording_uin, wording_source |

**Output** (`SettlementOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| claim_id | string | yes |  |
| status | Status | yes |  |
| claimed_amount | number | yes |  |
| deductions | list[DeductionOut] | yes |  |
| total_deductions | number | yes |  |
| admissible_amount | number \| null | yes |  |
| copay_amount | number \| null | yes |  |
| payable_amount | number \| null | yes |  |
| facts | list[FactOut] | yes |  |
| questions | list[QuestionOut] | yes |  |
| lines | list[LineViewOut] | yes |  |
| warnings | list[string] | yes |  |

**Example input** (real call)

```json
{
  "case": {
    "claim": {
      "claim_id": "AGI/HC/2526/004512",
      "policy_no": "AS-2025-100478",
      "admission": "2026-01-19",
      "discharge": "2026-01-22",
      "lines": [
        {
          "line_id": "L01",
          "description": "Private room",
          "amount": "21000.0",
          "qty": "3.0",
          "rate": "7000.0",
          "gst_pct": "5.0",
          "non_payable": null,
          "category": null,
          "date": null
        },
        {
          "line_id": "L02",
          "description": "Nursing and duty doctor charges",
          "amount": "4500.0",
          "qty": "3.0",
          "rate": "1500.0",
          "gst_pct": "0",
          "non_payable": null,
          "category": null,
          "date": null
        },
        {
          "line_id": "L03",
          "description": "Surgeon fee - laparoscopic cholecystectomy",
          "amount": "32000.0",
          "qty": "1.0",
          "rate": "32000.0",
          "gst_pct": "0",
          "non_payable": null,
          "category": null,
          "date": null
        }
      ],
      "diagnosis": "Cholelithiasis with cholecystitis",
      "procedure": "Laparoscopic cholecystectomy",
      "discount": "0",
      "printed_total": "128350.0",
      "condition_type": null,
      "room_priced_by_category": {}
    },
    "policy": {
      "policy_no": "AS-2025-100478",
      "sum_insured": "300000",
      "period_start": "2025-07-15",
      "period_end": "2026-07-14",
      "first_inception": "2022-07-15",
      "holder": "Rudransh Kelapure",
      "insurer": "Aarohan General Insurance Ltd.",
      "product": "Arogya Sanjeevani Policy",
      "wording_uin": "",
      "wording_source": ""
    },
    "history": []
  }
}
```

**Example output** (real result, trimmed)

```json
{
  "claim_id": "AGI/HC/2526/004512",
  "status": "computed",
  "claimed_amount": 128350.0,
  "deductions": [
    {
      "deduction_id": "D-ROOM-L01",
      "kind": "room_rent_excess",
      "amount": 6000.0,
      "description": "Room rent above the limit (₹2,000 a day for 3 days)",
      "formula": "3 x (7,000 - 5,000)",
      "rule_ref": "room_rent_cap",
      "line_ids": [
        "L01"
      ],
      "fact_id": "F-D-ROOM-L01"
    },
    {
      "deduction_id": "D-ROOMGST-L01",
      "kind": "room_gst_excess",
      "amount": 300.0,
      "description": "GST on room rent above the limit",
      "formula": "5.0% of 6,000",
      "rule_ref": "gst_follows_charge",
      "line_ids": [
        "L01"
      ],
      "fact_id": "F-D-ROOMGST-L01"
    }
  ],
  "total_deductions": 27700.0,
  "admissible_amount": 100650.0,
  "copay_amount": 5032.5,
  "payable_amount": 95617.5,
  "facts": [
    {
      "fact_id": "F-CLAIMED",
      "kind": "claimed_amount",
      "text": "Amount claimed: ₹1,28,350",
      "amount": 128350.0,
      "formula": "lines 1,27,300 + GST 1,050",
      "rule_ref": "",
      "line_ids": [],
      "inputs": {
        "line_sum": "127300.0",
        "gst": "1050.00",
        "discount": "0"
      }
    },
    {
      "fact_id": "F-WAITING",
      "kind": "waiting_period",
      "text": "42 full months of cover since first inception, longer than every waiting period (36 months at most), so none applies.",
      "amount": null,
      "formula": "",
      "rule_ref": "listed_illness_waiting_period",
      "line_ids": [],
      "inputs": {
        "first_inception": "2022-07-15",
        "admission": "2026-01-19",
        "days_since_inception": 1284,
        "months_since_inception": 42,
        "required": "36 months (longest)",
        "served": true,
        "condition_type": null,
        "condition_source": "keyword"
      }
    }
  ],
  "questions": [],
  "lines": [
    {
      "line_id": "L01",
      "description": "Private room",
      "amount": 21000.0,
      "gst": 1050.0,
      "category": "room",
      "category_source": "keyword",
      "non_payable": false,
      "non_payable_source": "default",
      "room_linked": false
    },
    {
      "line_id": "L02",
      "description": "Nursing and duty doctor charges",
      "amount": 4500.0,
      "gst": 0.0,
      "category": "nursing",
      "category_source": "keyword",
      "non_payable": false,
      "non_payable_source": "default",
      "room_linked": true
    }
  ],
  "warnings": []
}
```

#### `reproduce_deduction`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Reproduce one deduction | read | settlement auditor (ReAct loop) | `row = await tk.reproduce_deduction(case, letter, "R3", hypothesis_ids=["prop_on_all_lines"])` |

**What it does.** For one row of the insurer's settlement letter, find the calculation that produces the insurer's figure, compare it with what the policy requires, and give a verdict (matches_policy, does_not_match_policy, not_verifiable, method_matches) with the rupee difference. row_id is a letter row, or COPAY / REJECTION. Pass hypothesis_ids to test only the methods you picked; if nothing matches and exhaustive is false, call again without hypothesis_ids (replan).

**How it works.** Prepares the case and letter as above, classifies the row from its wording (or `kind`), runs the policy-correct method plus the chosen hypotheses (all applicable ones when `hypothesis_ids` is omitted) and gives a verdict; `exhaustive=false` with `not_verifiable` means: replan with every hypothesis.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case | CaseIn | yes | Everything the engine needs for one claim. |
| letter | LetterIn | yes | The insurer's decision, as extracted from the letter. |
| row_id | string | yes |  |
| hypothesis_ids | list[string] \| null | no | (default null) |

Nested input models:

| Model | Fields |
|---|---|
| BillLineIn | line_id, description, amount, qty, rate, gst_pct, non_payable, category, date |
| CaseIn | claim, policy, history |
| Category | one of: room, icu, nursing, professional_fees, operation_theatre, diagnostics, pharmacy, consumables, implants, blood_products, package, ambulance, unknown |
| ClaimIn | claim_id, policy_no, admission, discharge, lines, diagnosis, procedure, discount, printed_total, condition_type, room_priced_by_category |
| ConditionType | one of: accident, illness, listed_illness_short, listed_illness_long, pre_existing |
| LetterIn | letter_id, letter_type, claimed_amount, rows, paid_amount, copay_amount, rejection_reason |
| LetterRowIn | row_id, particulars, amount, reason, kind |
| PastClaimIn | claim_id, policy_no, admission, status, settled_amount, diagnosis, procedure |
| PolicyIn | policy_no, sum_insured, period_start, period_end, first_inception, holder, insurer, product, wording_uin, wording_source |
| RowKind | one of: room_rent, room_gst, icu, icu_gst, room_and_icu, proportionate, non_payable, cataract, copay, waiting_period, sum_insured, duplicate, cover_window, ambulance, policy_period, already_paid, unitemised, unspecified |

**Output** (`RowAuditOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| row_id | string | yes |  |
| particulars | string | yes |  |
| kind | RowKind | yes | What a row of the insurer's letter is about. Decides which hypotheses are tested. |
| kind_source | one of: input, keyword | yes |  |
| insurer_amount | number | yes |  |
| policy_amount | number \| null | yes |  |
| difference | number \| null | yes |  |
| verdict | Verdict | yes |  |
| method | string \| null | yes |  |
| explanation | string | yes |  |
| matches | list[HypothesisMatchOut] | yes |  |
| tested | list[string] | yes |  |
| exhaustive | boolean | yes |  |
| rule_ref | string | yes |  |
| policy_fact_ids | list[string] | yes |  |
| questions | list[QuestionOut] | yes |  |

**Example input** (real call)

```json
{
  "case": {
    "claim": {
      "claim_id": "AGI/HC/2526/004512",
      "policy_no": "AS-2025-100478",
      "admission": "2026-01-19",
      "discharge": "2026-01-22",
      "lines": [
        {
          "line_id": "L01",
          "description": "Private room",
          "amount": "21000.0",
          "qty": "3.0",
          "rate": "7000.0",
          "gst_pct": "5.0",
          "non_payable": null,
          "category": null,
          "date": null
        },
        {
          "line_id": "L02",
          "description": "Nursing and duty doctor charges",
          "amount": "4500.0",
          "qty": "3.0",
          "rate": "1500.0",
          "gst_pct": "0",
          "non_payable": null,
          "category": null,
          "date": null
        },
        {
          "line_id": "L03",
          "description": "Surgeon fee - laparoscopic cholecystectomy",
          "amount": "32000.0",
          "qty": "1.0",
          "rate": "32000.0",
          "gst_pct": "0",
          "non_payable": null,
          "category": null,
          "date": null
        }
      ],
      "diagnosis": "Cholelithiasis with cholecystitis",
      "procedure": "Laparoscopic cholecystectomy",
      "discount": "0",
      "printed_total": "128350.0",
      "condition_type": null,
      "room_priced_by_category": {}
    },
    "policy": {
      "policy_no": "AS-2025-100478",
      "sum_insured": "300000",
      "period_start": "2025-07-15",
      "period_end": "2026-07-14",
      "first_inception": "2022-07-15",
      "holder": "Rudransh Kelapure",
      "insurer": "Aarohan General Insurance Ltd.",
      "product": "Arogya Sanjeevani Policy",
      "wording_uin": "",
      "wording_source": ""
    },
    "history": []
  },
  "letter": {
    "letter_id": "AGI/HC/2526/004512",
    "letter_type": "settlement",
    "claimed_amount": "128350.0",
    "rows": [
      {
        "row_id": "R1",
        "particulars": "Room rent above eligible limit (₹2,000 a day for 3 days)",
        "amount": "6000.0",
        "reason": "Room rent is limited to 2% of sum insured, at most ₹5,000 a day",
        "kind": null
      },
      {
        "row_id": "R2",
        "particulars": "GST on room rent above eligible limit",
        "amount": "300.0",
        "reason": "Follows the room rent deduction",
        "kind": null
      },
      {
        "row_id": "R3",
        "particulars": "Proportionate deduction on associated medical expenses (₹5,000 / ₹7,000)",
        "amount": "30371.43",
        "reason": "Room category above eligibility, so associated expenses are reduced in the same proportion",
        "kind": null
      }
    ],
    "paid_amount": "87094.64",
    "copay_amount": "4583.93",
    "rejection_reason": ""
  },
  "row_id": "R3",
  "hypothesis_ids": [
    "prop_on_all_lines",
    "prop_incl_pharmacy"
  ]
}
```

**Example output** (real result, trimmed)

```json
{
  "row_id": "R3",
  "particulars": "Proportionate deduction on associated medical expenses (₹5,000 / ₹7,000)",
  "kind": "proportionate",
  "kind_source": "keyword",
  "insurer_amount": 30371.43,
  "policy_amount": 21400.0,
  "difference": 8971.43,
  "verdict": "does_not_match_policy",
  "method": "prop_on_all_lines",
  "explanation": "The policy requires ₹21,400. The insurer's ₹30,371.43 is reproduced by: Proportionate cut applied to every non-room line (every non-room line: 106,300 x (21,000 - 15,000)…",
  "matches": [
    {
      "hypothesis_id": "prop_on_all_lines",
      "correct": false,
      "title": "Proportionate cut applied to every non-room line",
      "amount": 30371.43,
      "detail": "every non-room line: 106,300 x (21,000 - 15,000) / 21,000",
      "line_ids": [
        "L02",
        "L03"
      ]
    }
  ],
  "tested": [
    "proportionate_policy",
    "prop_incl_pharmacy"
  ],
  "exhaustive": false,
  "rule_ref": "proportionate_deduction",
  "policy_fact_ids": [
    "F-D-PROPORTIONATE"
  ],
  "questions": []
}
```

#### `audit_settlement_letter`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Audit settlement letter | read | critic; C0/C1 baselines | `audit = await tk.audit_settlement_letter(case, letter)` |

**What it does.** Audit every row of the insurer's settlement or rejection letter (co-pay and rejection included) and summarise: payable under the policy, amount paid, rupees that may be disputable and rupees that can't be checked (both after co-pay), and whether the letter's own arithmetic adds up.

**How it works.** Runs `reproduce_deduction` logic on every row, adds the co-pay and rejection as rows, and computes the summary: policy-correct payable, paid, gap, disputable and unverifiable amounts (after co-pay), overpaid, the letter's own arithmetic, deductions the policy requires but the letter omits.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case | CaseIn | yes | Everything the engine needs for one claim. |
| letter | LetterIn | yes | The insurer's decision, as extracted from the letter. |
| hypothesis_ids | list[string] \| null | no | (default null) |

Nested input models:

| Model | Fields |
|---|---|
| BillLineIn | line_id, description, amount, qty, rate, gst_pct, non_payable, category, date |
| CaseIn | claim, policy, history |
| Category | one of: room, icu, nursing, professional_fees, operation_theatre, diagnostics, pharmacy, consumables, implants, blood_products, package, ambulance, unknown |
| ClaimIn | claim_id, policy_no, admission, discharge, lines, diagnosis, procedure, discount, printed_total, condition_type, room_priced_by_category |
| ConditionType | one of: accident, illness, listed_illness_short, listed_illness_long, pre_existing |
| LetterIn | letter_id, letter_type, claimed_amount, rows, paid_amount, copay_amount, rejection_reason |
| LetterRowIn | row_id, particulars, amount, reason, kind |
| PastClaimIn | claim_id, policy_no, admission, status, settled_amount, diagnosis, procedure |
| PolicyIn | policy_no, sum_insured, period_start, period_end, first_inception, holder, insurer, product, wording_uin, wording_source |
| RowKind | one of: room_rent, room_gst, icu, icu_gst, room_and_icu, proportionate, non_payable, cataract, copay, waiting_period, sum_insured, duplicate, cover_window, ambulance, policy_period, already_paid, unitemised, unspecified |

**Output** (`LetterAuditOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| letter_id | string | yes |  |
| rows | list[RowAuditOut] | yes |  |
| policy_payable | number \| null | yes |  |
| insurer_paid | number | yes |  |
| gap | number \| null | yes |  |
| unverified_amount | number \| null | yes |  |
| disputable_amount | number \| null | yes |  |
| overpaid_amount | number \| null | yes |  |
| letter_arithmetic_gap | number | yes |  |
| policy_deductions_not_on_letter | list[string] | yes |  |
| questions | list[QuestionOut] | yes |  |
| warnings | list[string] | yes |  |
| settlement | SettlementOut | yes | What the policy wording says should be paid. Cite figures by ``fact_id``. |

**Example input** (real call)

```json
{
  "case": {
    "claim": {
      "claim_id": "AGI/HC/2526/004512",
      "policy_no": "AS-2025-100478",
      "admission": "2026-01-19",
      "discharge": "2026-01-22",
      "lines": [
        {
          "line_id": "L01",
          "description": "Private room",
          "amount": "21000.0",
          "qty": "3.0",
          "rate": "7000.0",
          "gst_pct": "5.0",
          "non_payable": null,
          "category": null,
          "date": null
        },
        {
          "line_id": "L02",
          "description": "Nursing and duty doctor charges",
          "amount": "4500.0",
          "qty": "3.0",
          "rate": "1500.0",
          "gst_pct": "0",
          "non_payable": null,
          "category": null,
          "date": null
        },
        {
          "line_id": "L03",
          "description": "Surgeon fee - laparoscopic cholecystectomy",
          "amount": "32000.0",
          "qty": "1.0",
          "rate": "32000.0",
          "gst_pct": "0",
          "non_payable": null,
          "category": null,
          "date": null
        }
      ],
      "diagnosis": "Cholelithiasis with cholecystitis",
      "procedure": "Laparoscopic cholecystectomy",
      "discount": "0",
      "printed_total": "128350.0",
      "condition_type": null,
      "room_priced_by_category": {}
    },
    "policy": {
      "policy_no": "AS-2025-100478",
      "sum_insured": "300000",
      "period_start": "2025-07-15",
      "period_end": "2026-07-14",
      "first_inception": "2022-07-15",
      "holder": "Rudransh Kelapure",
      "insurer": "Aarohan General Insurance Ltd.",
      "product": "Arogya Sanjeevani Policy",
      "wording_uin": "",
      "wording_source": ""
    },
    "history": []
  },
  "letter": {
    "letter_id": "AGI/HC/2526/004512",
    "letter_type": "settlement",
    "claimed_amount": "128350.0",
    "rows": [
      {
        "row_id": "R1",
        "particulars": "Room rent above eligible limit (₹2,000 a day for 3 days)",
        "amount": "6000.0",
        "reason": "Room rent is limited to 2% of sum insured, at most ₹5,000 a day",
        "kind": null
      },
      {
        "row_id": "R2",
        "particulars": "GST on room rent above eligible limit",
        "amount": "300.0",
        "reason": "Follows the room rent deduction",
        "kind": null
      },
      {
        "row_id": "R3",
        "particulars": "Proportionate deduction on associated medical expenses (₹5,000 / ₹7,000)",
        "amount": "30371.43",
        "reason": "Room category above eligibility, so associated expenses are reduced in the same proportion",
        "kind": null
      }
    ],
    "paid_amount": "87094.64",
    "copay_amount": "4583.93",
    "rejection_reason": ""
  }
}
```

**Example output** (real result, trimmed)

```json
{
  "letter_id": "AGI/HC/2526/004512",
  "rows": [
    {
      "row_id": "R1",
      "particulars": "Room rent above eligible limit (₹2,000 a day for 3 days)",
      "kind": "room_rent",
      "kind_source": "keyword",
      "insurer_amount": 6000.0,
      "policy_amount": 6000.0,
      "difference": 0.0,
      "verdict": "matches_policy",
      "method": "room_rent_policy",
      "explanation": "₹6,000 is what the policy requires for this row (₹6,000).",
      "matches": [
        {
          "hypothesis_id": "room_rent_policy",
          "correct": true,
          "title": "Room rent above the policy limit",
          "amount": 6000.0,
          "detail": "Room rent above the limit (₹2,000 a day for 3 days): 3 x (7,000 - 5,000)",
          "line_ids": []
        },
        {
          "hypothesis_id": "room_cap_max_only",
          "correct": false,
          "title": "Room cap at ₹5,000, ignoring 2% of sum insured",
          "amount": 6000.0,
          "detail": "3 x (7,000 - 5,000)",
          "line_ids": [
            "L01"
          ]
        }
      ],
      "tested": [
        "room_rent_policy",
        "room_cap_max_only"
      ],
      "exhaustive": true,
      "rule_ref": "room_rent_cap",
      "policy_fact_ids": [
        "F-D-ROOM-L01"
      ],
      "questions": []
    },
    {
      "row_id": "R2",
      "particulars": "GST on room rent above eligible limit",
      "kind": "room_gst",
      "kind_source": "keyword",
      "insurer_amount": 300.0,
      "policy_amount": 300.0,
      "difference": 0.0,
      "verdict": "matches_policy",
      "method": "room_gst_policy",
      "explanation": "₹300 is what the policy requires for this row (₹300).",
      "matches": [
        {
          "hypothesis_id": "room_gst_policy",
          "correct": true,
          "title": "GST on the disallowed room rent",
          "amount": 300.0,
          "detail": "GST on room rent above the limit: 5.0% of 6,000",
          "line_ids": []
        }
      ],
      "tested": [
        "room_gst_policy",
        "room_gst_on_full_room"
      ],
      "exhaustive": true,
      "rule_ref": "gst_follows_charge",
      "policy_fact_ids": [
        "F-D-ROOMGST-L01"
      ],
      "questions": []
    }
  ],
  "policy_payable": 95617.5,
  "insurer_paid": 87094.64,
  "gap": 8522.86,
  "unverified_amount": 0.0,
  "disputable_amount": 8522.86,
  "overpaid_amount": 0.0,
  "letter_arithmetic_gap": 0.0,
  "policy_deductions_not_on_letter": [],
  "questions": [],
  "warnings": [],
  "settlement": {
    "claim_id": "AGI/HC/2526/004512",
    "status": "computed",
    "claimed_amount": 128350.0,
    "deductions": [
      {
        "deduction_id": "D-ROOM-L01",
        "kind": "room_rent_excess",
        "amount": 6000.0,
        "description": "Room rent above the limit (₹2,000 a day for 3 days)",
        "formula": "3 x (7,000 - 5,000)",
        "rule_ref": "room_rent_cap",
        "line_ids": [
          "L01"
        ],
        "fact_id": "F-D-ROOM-L01"
      },
      {
        "deduction_id": "D-ROOMGST-L01",
        "kind": "room_gst_excess",
        "amount": 300.0,
        "description": "GST on room rent above the limit",
        "formula": "5.0% of 6,000",
        "rule_ref": "gst_follows_charge",
        "line_ids": [
          "L01"
        ],
        "fact_id": "F-D-ROOMGST-L01"
      }
    ],
    "total_deductions": 27700.0,
    "admissible_amount": 100650.0,
    "copay_amount": 5032.5,
    "payable_amount": 95617.5,
    "facts": [
      {
        "fact_id": "F-CLAIMED",
        "kind": "claimed_amount",
        "text": "Amount claimed: ₹1,28,350",
        "amount": 128350.0,
        "formula": "lines 1,27,300 + GST 1,050",
        "rule_ref": "",
        "line_ids": [],
        "inputs": {
          "line_sum": "127300.0",
          "gst": "1050.00",
          "discount": "0"
        }
      },
      {
        "fact_id": "F-WAITING",
        "kind": "waiting_period",
        "text": "42 full months of cover since first inception, longer than every waiting period (36 months at most), so none applies.",
        "amount": null,
        "formula": "",
        "rule_ref": "listed_illness_waiting_period",
        "line_ids": [],
        "inputs": {
          "first_inception": "2022-07-15",
          "admission": "2026-01-19",
          "days_since_inception": 1284,
          "months_since_inception": 42,
          "required": "36 months (longest)",
          "served": true,
          "condition_type": null,
          "condition_source": "keyword"
        }
      }
    ],
    "questions": [],
    "lines": [
      {
        "line_id": "L01",
        "description": "Private room",
        "amount": 21000.0,
        "gst": 1050.0,
        "category": "room",
        "category_source": "keyword",
        "non_payable": false,
        "non_payable_source": "default",
        "room_linked": false
      },
      {
        "line_id": "L02",
        "description": "Nursing and duty doctor charges",
        "amount": 4500.0,
        "gst": 0.0,
        "category": "nursing",
        "category_source": "keyword",
        "non_payable": false,
        "non_payable_source": "default",
        "room_linked": true
      }
    ],
    "warnings": []
  }
}
```

#### `list_hypotheses`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| List hypotheses | read | settlement auditor | `methods = await tk.list_hypotheses("copay")        # list of hypotheses` |

**What it does.** List the calculations the matcher can test: one correct method per kind of letter row and documented wrong methods, each with a plain-English description. Filter by kind.

**How it works.** Returns the hypothesis registry (optionally one row kind): ID, kind, whether it is the policy-correct method, title and description. Read-only, no case needed.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| kind | RowKind \| null | no | (default null) |

Nested input models:

| Model | Fields |
|---|---|
| RowKind | one of: room_rent, room_gst, icu, icu_gst, room_and_icu, proportionate, non_payable, cataract, copay, waiting_period, sum_insured, duplicate, cover_window, ambulance, policy_period, already_paid, unitemised, unspecified |

**Output** (`HypothesisListOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| hypotheses | list[HypothesisOut] | yes |  |

**Example input** (real call)

```json
{
  "kind": "copay"
}
```

**Example output** (real result, trimmed)

```json
{
  "hypotheses": [
    {
      "hypothesis_id": "copay_policy",
      "kind": "copay",
      "correct": true,
      "method_only": false,
      "title": "Co-pay on the policy-correct admissible amount",
      "description": "5% of the amount admissible after every other deduction the policy allows."
    },
    {
      "hypothesis_id": "copay_double_rate",
      "kind": "copay",
      "correct": false,
      "method_only": false,
      "title": "Co-pay at double the rate",
      "description": "The co-pay is taken at twice the policy's rate."
    }
  ]
}
```


### 6.2 case-records

One claim's records: the uploaded documents (read through the document reader), the policy schedule and earlier claims, in the settlement engine's own shapes. The app writes the store; the server only reads.

#### `list_case_documents`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| List case documents | read | document reader | `docs = await tk.list_case_documents(case_id)` |

**What it does.** List the documents uploaded for a case: neutral document IDs, media type, size and SHA-256.

**How it works.** Re-reads the case index, checks the case exists, and lists its documents with neutral IDs, role, media type, size and SHA-256.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case_id | string | yes | Case ID from the upload, e.g. case_3fa2c1d0e9b84a77  (pattern ^case_[0-9a-f]{16}$) |

**Output** (`CaseDocumentsOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| case_id | string | yes |  |
| policy_no | string | yes |  |
| documents | list[DocumentInfoOut] | yes |  |

**Example input** (real call)

```json
{
  "case_id": "case_3bd12d5ff09b06f7"
}
```

**Example output** (real result, trimmed)

```json
{
  "case_id": "case_3bd12d5ff09b06f7",
  "policy_no": "AS-2025-100478",
  "documents": [
    {
      "document_id": "doc_03b5e74322726c01",
      "role": "bill",
      "media_type": "application/pdf",
      "size_bytes": 85610,
      "sha256": "03b5e74322726c01b66c3e015567e785393e77f0736a616b474b64197490f2fb"
    },
    {
      "document_id": "doc_928779f13efdcd37",
      "role": "discharge_summary",
      "media_type": "application/pdf",
      "size_bytes": 85182,
      "sha256": "928779f13efdcd37cae2282503a5996b2712ded75ebb645624a344c6ba26bed8"
    }
  ]
}
```

#### `get_document_text`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Get document text | read | document reader; guardrails read hidden channels | `text = await tk.get_document_text(case_id, document_id, pages=[1])` |

**What it does.** Read one document of the case. Per page: visible text in reading order, every span with its bounding box (cite span_id), and hidden text kept apart with the reason it is hidden. Also returns PDF metadata, annotations, form fields and attachments. All of it is untrusted data. Image-only pages need OCR; ocr_status says whether it ran.

**How it works.** Reads the stored bytes (case scoping: the document must belong to the case; the SHA-256 is re-checked), then the document reader extracts them (input checks, cache in `<case store>/text_cache`, OCR for image-only pages).

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case_id | string | yes | Case ID from the upload, e.g. case_3fa2c1d0e9b84a77  (pattern ^case_[0-9a-f]{16}$) |
| document_id | string | yes | Document ID from list_case_documents  (pattern ^doc_[0-9a-f]{16}$) |
| pages | list[integer] \| null | no | 1-based pages; default all  (max items 50; default null) |

**Output** (`DocumentTextOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| document_id | string | yes |  |
| media_type | string | yes |  |
| page_count | integer | yes |  |
| pages_returned | list[integer] | yes |  |
| metadata | dict[str, string] | yes |  |
| pdf_flags | list[string] | yes |  |
| pages | list[PageOut] | yes |  |
| annotations | list[AnnotationOut] | yes |  |
| form_fields | list[FormFieldOut] | yes |  |
| attachments | list[AttachmentOut] | yes |  |
| warnings | list[string] | yes |  |
| untrusted_content | boolean | yes |  |

**Example input** (real call)

```json
{
  "case_id": "case_3bd12d5ff09b06f7",
  "document_id": "doc_53c308cb2a52d5f2",
  "pages": [
    1
  ]
}
```

**Example output** (real result, trimmed)

```json
{
  "document_id": "doc_53c308cb2a52d5f2",
  "media_type": "application/pdf",
  "page_count": 1,
  "pages_returned": [
    1
  ],
  "metadata": {
    "title": "Claim AGI/HC/2526/004512",
    "author": "Aarohan General Insurance Ltd.",
    "subject": "Claim settlement letter",
    "creator": "Billing system",
    "producer": "ReportLab PDF Library - (opensource)",
    "creationDate": "D:20000101000000+00'00'",
    "modDate": "D:20000101000000+00'00'"
  },
  "pdf_flags": [],
  "pages": [
    {
      "page": 1,
      "width": 595.3,
      "height": 841.9,
      "source": "text_layer",
      "text": "Aarohan General Insurance Ltd.\nAarohan House, 21 Sagar Marg, Mumbai 000400\nclaims@aarohan.example | +91 00000 12000\nHealth Claims Department IRDAI Reg. No. FIC-000\nRef: A…",
      "hidden_text": "",
      "spans": [
        {
          "span_id": "p1-s1",
          "text": "Aarohan General Insurance Ltd.",
          "bbox": [
            48.5,
            60.3
          ],
          "font_size": 15.0,
          "color": "#ffffff",
          "hidden": false,
          "hidden_reasons": []
        },
        {
          "span_id": "p1-s2",
          "text": "Aarohan House, 21 Sagar Marg, Mumbai 000400",
          "bbox": [
            398.7,
            58.9
          ],
          "font_size": 7.5,
          "color": "#ffffff",
          "hidden": false,
          "hidden_reasons": []
        }
      ],
      "has_images": false,
      "ocr_status": "not_needed",
      "warnings": []
    }
  ],
  "annotations": [],
  "form_fields": [],
  "attachments": [],
  "warnings": [],
  "untrusted_content": true
}
```

#### `get_policy`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Get policy | read | policy analyst | `policy = await tk.get_policy(case_id)` |

**What it does.** The policy schedule for the case's policy, in the shape the settlement-engine tools take, with the wording_uin to pass to policy-kb. POLICY_NOT_FOUND means there is no pre-stored schedule (e.g. the user uploaded their own policy): extract the schedule from the policy document and confirm it with the user.

**How it works.** Looks up the case's policy number in the reference policies and adds the wording to cite (`wording_uin`, catalogue or uploaded). The output has exactly the engine's PolicyIn fields.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case_id | string | yes | Case ID from the upload, e.g. case_3fa2c1d0e9b84a77  (pattern ^case_[0-9a-f]{16}$) |

**Output** (`PolicyOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| policy_no | string | yes |  |
| sum_insured | number | yes |  |
| period_start | string | yes |  |
| period_end | string | yes |  |
| first_inception | string | yes |  |
| holder | string | yes |  |
| insurer | string | yes |  |
| product | string | yes |  |
| wording_uin | string | yes | The policy wording to cite: an IRDAI UIN from the catalogue, or upload:doc_<id> for a policy the user uploaded. Pass it to policy-kb. |
| wording_source | one of: catalogue, uploaded | yes |  |

**Example input** (real call)

```json
{
  "case_id": "case_3bd12d5ff09b06f7"
}
```

**Example output** (real result, trimmed)

```json
{
  "policy_no": "AS-2025-100478",
  "sum_insured": 300000.0,
  "period_start": "2025-07-15",
  "period_end": "2026-07-14",
  "first_inception": "2022-07-15",
  "holder": "Rudransh Kelapure",
  "insurer": "Aarohan General Insurance Ltd.",
  "product": "Arogya Sanjeevani Policy",
  "wording_uin": "GODHLIP24179V022324",
  "wording_source": "catalogue"
}
```

#### `get_policy_wording`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Get policy wording | read | policy analyst | `wording = await tk.get_policy_wording(case_id)` |

**What it does.** Which policy wording the case is checked against. It is read from the UIN printed on the policy schedule: a wording ClaimClear has reviewed is used without asking the user for anything. When `wording_needed` is true the schedule names a wording ClaimClear hasn't reviewed: tell the user the standard Arogya Sanjeevani wording was used and ask them to upload their policy wording (`note` says what to say).

**How it works.** `case_records/wording.py` reads the visible text of the case's `policy_schedule` document and finds the IRDAI UIN it prints. Order: a wording the app set on the case (`uploaded`, `selected`), then the schedule's UIN if it is in `development/dev_data/wordings/catalogue.json` (`from_schedule`), else the default wording with `wording_needed` (`not_reviewed`), or the default when no UIN is printed (`not_printed`). `get_policy` returns the same `wording_uin`. A UIN on a document can only pick a reviewed catalogue wording.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case_id | string | yes | Case ID from the upload (pattern ^case_[0-9a-f]{16}$) |

**Output** (`WordingOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| case_id | string | yes | |
| wording_uin | string | yes | The wording get_policy returns and policy-kb is called with |
| wording_source | one of: catalogue, uploaded | yes | |
| status | one of: selected, uploaded, from_schedule, not_reviewed, not_printed | yes | How the wording was chosen |
| schedule_wording_uin | string | yes | The UIN printed on the policy schedule; empty if none |
| wording_needed | boolean | yes | True: ask the user for their policy wording (or index wording_document_id) |
| wording_document_id | string | yes | A document of the case with the role policy_wording; empty if none |
| note | string | yes | What to tell or ask the user |

**Example output** (real result: a gen-data case whose schedule names an unreviewed wording)

```json
{
  "case_id": "case_b5de4be6c54055b5",
  "wording_uin": "GODHLIP24179V022324",
  "wording_source": "catalogue",
  "status": "not_reviewed",
  "schedule_wording_uin": "XNHHLIP20161V011920",
  "wording_needed": true,
  "wording_document_id": "doc_b30c9e5f26c04119",
  "note": "The policy schedule names wording XNHHLIP20161V011920, which ClaimClear has not reviewed. Until the user's wording is uploaded, the standard Arogya Sanjeevani wording (GODHLIP24179V022324) and its limits are used; say so in the answer. The case already has a policy wording document (doc_b30c9e5f26c04119): index it (the app's upload step) instead of asking."
}
```

A synthetic case (its schedule prints no UIN) returns `"status": "not_printed"`, `"wording_needed": false` and the default wording.

**How Member 3 uses it.** The policy analyst calls it once per case and puts the result in `state["wording"]`. If `wording_needed`, the supervisor tells the user the standard wording was used and asks for their policy wording (an `interrupt()`, like the other questions). When the user uploads it, the app indexes it (`ClaimClearToolkit.ingest_uploaded_policy`, app only) and sets `upload:doc_...` on the case; the next `get_policy` returns it.

#### `get_claim_history`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Get claim history | read | policy analyst | `history = await tk.get_claim_history(case_id, scope="current_period")   # list of claims` |

**What it does.** Earlier claims on the case's policy, in the shape the settlement-engine tools take. scope 'current_period' (default) keeps claims in the current policy year, which sub-limits depend on; 'all' returns every year.

**How it works.** Earlier claims on the case's policy from the reference claim history, current policy period by default (sub-limits depend on it), or all years.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case_id | string | yes | Case ID from the upload, e.g. case_3fa2c1d0e9b84a77  (pattern ^case_[0-9a-f]{16}$) |
| scope | one of: current_period, all | no | (default "current_period") |

**Output** (`ClaimHistoryOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| policy_no | string | yes |  |
| scope | one of: current_period, all | yes |  |
| claims | list[PastClaimOut] | yes |  |

**Example input** (real call)

```json
{
  "case_id": "case_3bd12d5ff09b06f7",
  "scope": "current_period"
}
```

**Example output** (real result, trimmed)

```json
{
  "policy_no": "AS-2025-100478",
  "scope": "current_period",
  "claims": []
}
```


### 6.3 policy-kb

The policy wording as citable clauses, with hybrid retrieval. Default wording: Go Digit Arogya Sanjeevani, UIN GODHLIP24179V022324.

#### `list_policies`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| List policies | read | policy analyst; app | `wordings = await tk.list_policies()` |

**What it does.** The policy wordings available: the reviewed catalogue, plus the case's own uploaded wording when case_id is given. Each has a wording_uin to pass to the other tools. Use it to show the policy picker or to confirm which wording a case uses.

**How it works.** Lists the catalogue wordings (development/dev_data/wordings/catalogue.json) and, with `case_id`, that case's uploaded wording, each with whether its index is built and whether it has a rule map.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| insurer | string \| null | no | (max length 100; default null) |
| query | string \| null | no | (max length 100; default null) |
| case_id | string \| null | no | Required with an uploaded wording (upload:doc_...)  (pattern ^case_[0-9a-f]{16}$; default null) |

**Output** (`ListPoliciesOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| default_wording_uin | string | yes |  |
| policies | list[PolicySummaryOut] | yes |  |

**Example input** (real call)

```json
{}
```

**Example output** (real result, trimmed)

```json
{
  "default_wording_uin": "GODHLIP24179V022324",
  "policies": [
    {
      "wording_uin": "GODHLIP24179V022324",
      "insurer": "Go Digit General Insurance Limited",
      "product": "Arogya Sanjeevani Policy",
      "version": "GODHLIP24179V022324",
      "source": "catalogue",
      "reviewed": true,
      "index_available": true,
      "clause_count": 127,
      "has_rule_map": true
    }
  ]
}
```

#### `search_clauses`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Search clauses | read | policy analyst | `hits = await tk.search_clauses("they cut my room rent", k=3, wording_uin=policy["wording_uin"])` |

**What it does.** Search the policy wording for the clauses most relevant to a question, in the policyholder's words or policy terms. Returns up to k clauses in 'hits', best first, each with clause_id, title, text, pages and a citation. Quote only returned text.

**How it works.** Resolves the wording (`wording_uin` or the case's upload, else the default), rewrites the query into policy language, ranks clauses with BM25 and vectors, fuses with RRF (k = 60) and optionally reranks; returns hits with clause ID, text, pages and a citation.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| query | string | yes | The policyholder's question or policy terms, e.g. 'why did they cut my medicine bill'  (min length 1; max length 500) |
| k | integer | no | How many clauses to return (1-10)  (min 1; max 10; default 5) |
| wording_uin | string \| null | no | The case's wording (case-records get_policy wording_uin). Omit for the default wording.  (pattern ^[A-Z]{7}\d{5}V\d{6}$\|^upload:doc_[0-9a-f]{16}$; default null) |
| case_id | string \| null | no | Required with an uploaded wording (upload:doc_...)  (pattern ^case_[0-9a-f]{16}$; default null) |

**Output** (`SearchClausesOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| query | string | yes |  |
| wording | WordingOut | yes | Which policy wording the clauses come from. |
| synthetic | boolean | yes |  |
| hits | list[ClauseHitOut] | yes |  |

**Example input** (real call)

```json
{
  "query": "they cut my room rent",
  "k": 3
}
```

**Example output** (real result, trimmed)

```json
{
  "query": "they cut my room rent",
  "wording": {
    "insurer": "Go Digit General Insurance Limited",
    "product": "Arogya Sanjeevani Policy",
    "uin": "GODHLIP24179V022324",
    "version": "GODHLIP24179V022324",
    "source_url": "https://www.godigit.com/content/dam/godigit/directportal/en/downloads/health/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf",
    "downloaded_on": "<download date>",
    "sha256": "70ec4e51cf03a49c06cd7b06fd2dae16ac4ab3a204591fb1e8568a50858ea75b",
    "synthetic": false,
    "source": "catalogue",
    "reviewed": true
  },
  "synthetic": false,
  "hits": [
    {
      "clause_id": "B.40",
      "title": "Room Rent",
      "section": "DEFINITIONS",
      "text": "Room Rent means the amount charged by a hospital towards Room and Boarding expenses and shall include the associated medical expenses.",
      "score": 0.032787,
      "page_start": 5,
      "page_end": 5,
      "ranks": {
        "bm25": 1,
        "vector": 1
      },
      "citation": "Go Digit General Insurance Limited Arogya Sanjeevani Policy (GODHLIP24179V022324), clause B.40"
    },
    {
      "clause_id": "C.1.1",
      "title": "Other expenses",
      "section": "BENEFITS COVERED UNDER THE POLICY",
      "text": "i. Expenses incurred on treatment of cataract subject to the sub limits\nii. Dental treatment, necessitated due to disease or injury\niii. Plastic surgery necessitated due …",
      "score": 0.032258,
      "page_start": 6,
      "page_end": 6,
      "ranks": {
        "bm25": 2,
        "vector": 2
      },
      "citation": "Go Digit General Insurance Limited Arogya Sanjeevani Policy (GODHLIP24179V022324), clause C.1.1"
    }
  ]
}
```

#### `get_clause`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Get clause | read | policy analyst, critic, explainer | `clause = await tk.get_clause("C.1.1")` |

**What it does.** Fetch one clause of the policy wording by its printed number, e.g. 'C.1.1' or 'Annexure A List I' (or 'Page 3' for an uploaded wording indexed by page). Returns found=false if the wording has no such clause. Use it to check a citation before quoting it.

**How it works.** Fetches one clause by its printed number (normalised: 'C.1.1', 'clause 5.2', 'Annexure A List I'); `found: false` instead of an error when the wording has no such clause.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| clause_id | string | yes | Printed clause number, e.g. 'C.1.1', '5.2', 'Annexure A List I'  (pattern ^[A-Za-z0-9 .\-–]+$; min length 1; max length 60) |
| wording_uin | string \| null | no | The case's wording (case-records get_policy wording_uin). Omit for the default wording.  (pattern ^[A-Z]{7}\d{5}V\d{6}$\|^upload:doc_[0-9a-f]{16}$; default null) |
| case_id | string \| null | no | Required with an uploaded wording (upload:doc_...)  (pattern ^case_[0-9a-f]{16}$; default null) |

**Output** (`ClauseOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| found | boolean | yes | False when the wording has no such clause; then do not cite it |
| clause_id | string | yes |  |
| title | string | yes |  |
| section | string | yes |  |
| parent_id | string \| null | yes |  |
| text | string | yes |  |
| page_start | integer \| null | yes |  |
| page_end | integer \| null | yes |  |
| codes | list[string] | yes | IRDAI exclusion codes printed in the clause, e.g. Excl01 |
| citation | string \| null | yes |  |
| wording | WordingOut | yes | Which policy wording the clauses come from. |
| synthetic | boolean | yes |  |

**Example input** (real call)

```json
{
  "clause_id": "C.1.1"
}
```

**Example output** (real result, trimmed)

```json
{
  "found": true,
  "clause_id": "C.1.1",
  "title": "Other expenses",
  "section": "BENEFITS COVERED UNDER THE POLICY",
  "parent_id": "C.1",
  "text": "i. Expenses incurred on treatment of cataract subject to the sub limits\nii. Dental treatment, necessitated due to disease or injury\niii. Plastic surgery necessitated due …",
  "page_start": 6,
  "page_end": 6,
  "codes": [],
  "citation": "Go Digit General Insurance Limited Arogya Sanjeevani Policy (GODHLIP24179V022324), clause C.1.1",
  "wording": {
    "insurer": "Go Digit General Insurance Limited",
    "product": "Arogya Sanjeevani Policy",
    "uin": "GODHLIP24179V022324",
    "version": "GODHLIP24179V022324",
    "source_url": "https://www.godigit.com/content/dam/godigit/directportal/en/downloads/health/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf",
    "downloaded_on": "<download date>",
    "sha256": "70ec4e51cf03a49c06cd7b06fd2dae16ac4ab3a204591fb1e8568a50858ea75b",
    "synthetic": false,
    "source": "catalogue",
    "reviewed": true
  },
  "synthetic": false
}
```

#### `clauses_for_rule`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Clauses for an engine rule | read | policy analyst, explainer | `clauses = await tk.clauses_for_rule("copay")` |

**What it does.** The policy clauses behind a settlement-engine rule_ref (from a deduction or fact), e.g. 'room_rent_cap', 'proportionate_deduction', 'copay', from a map reviewed against the wording. Cite the first clause. 'differs_from_engine', when set, says where the wording and the engine disagree. Uploaded wordings have no map: NO_RULE_MAP, use search_clauses.

**How it works.** Looks the engine `rule_ref` up in the wording's reviewed rule map (`policy_kb/rule_maps/<UIN>.json`) and returns those clauses; uploaded wordings have no map (`NO_RULE_MAP`).

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| rule_ref | string | yes | A settlement-engine rule_ref, e.g. 'room_rent_cap', 'copay'  (pattern ^[a-z][a-z0-9_]*$; min length 1; max length 60) |
| wording_uin | string \| null | no | The case's wording (case-records get_policy wording_uin). Omit for the default wording.  (pattern ^[A-Z]{7}\d{5}V\d{6}$\|^upload:doc_[0-9a-f]{16}$; default null) |
| case_id | string \| null | no | Required with an uploaded wording (upload:doc_...)  (pattern ^case_[0-9a-f]{16}$; default null) |

**Output** (`RuleClausesOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| rule_ref | string | yes |  |
| where | string | yes | Where in the clauses the rule is stated (reviewed note) |
| differs_from_engine | string \| null | yes | Set when the wording and the settlement engine disagree; a verdict-policy decision |
| clauses | list[ClauseOut] | yes | The first is the clause to cite; may be empty if the wording does not address the rule |
| wording | WordingOut | yes | Which policy wording the clauses come from. |
| synthetic | boolean | yes |  |

**Example input** (real call)

```json
{
  "rule_ref": "copay"
}
```

**Example output** (real result, trimmed)

```json
{
  "rule_ref": "copay",
  "where": "E.28.3: each claim subject to a co-payment of 5% of the admissible claim amount; amount payable is after the co-payment",
  "differs_from_engine": null,
  "clauses": [
    {
      "found": true,
      "clause_id": "E.28.3",
      "title": "Any delay in notification or submission may be",
      "section": "GENERAL TERMS & CLAUSES",
      "parent_id": "E.28",
      "text": "Any delay in notification or submission may be condoned on merit where delay is proved to be for reasons beyond the control of the Insured Person.\nc. Co-payment Each and …",
      "page_start": 18,
      "page_end": 19,
      "codes": [],
      "citation": "Go Digit General Insurance Limited Arogya Sanjeevani Policy (GODHLIP24179V022324), clause E.28.3",
      "wording": {
        "insurer": "Go Digit General Insurance Limited",
        "product": "Arogya Sanjeevani Policy",
        "uin": "GODHLIP24179V022324",
        "version": "GODHLIP24179V022324",
        "source_url": "https://www.godigit.com/content/dam/godigit/directportal/en/downloads/health/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf",
        "downloaded_on": "<download date>",
        "sha256": "70ec4e51cf03a49c06cd7b06fd2dae16ac4ab3a204591fb1e8568a50858ea75b",
        "synthetic": false,
        "source": "catalogue",
        "reviewed": true
      },
      "synthetic": false
    },
    {
      "found": true,
      "clause_id": "B.10",
      "title": "Co-payment",
      "section": "DEFINITIONS",
      "parent_id": "B",
      "text": "Co-payment means a cost sharing requirement under a health insurance policy that provides that the policyholder/insured will bear a specified percentage of the admissible…",
      "page_start": 2,
      "page_end": 3,
      "codes": [],
      "citation": "Go Digit General Insurance Limited Arogya Sanjeevani Policy (GODHLIP24179V022324), clause B.10",
      "wording": {
        "insurer": "Go Digit General Insurance Limited",
        "product": "Arogya Sanjeevani Policy",
        "uin": "GODHLIP24179V022324",
        "version": "GODHLIP24179V022324",
        "source_url": "https://www.godigit.com/content/dam/godigit/directportal/en/downloads/health/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf",
        "downloaded_on": "<download date>",
        "sha256": "70ec4e51cf03a49c06cd7b06fd2dae16ac4ab3a204591fb1e8568a50858ea75b",
        "synthetic": false,
        "source": "catalogue",
        "reviewed": true
      },
      "synthetic": false
    }
  ],
  "wording": {
    "insurer": "Go Digit General Insurance Limited",
    "product": "Arogya Sanjeevani Policy",
    "uin": "GODHLIP24179V022324",
    "version": "GODHLIP24179V022324",
    "source_url": "https://www.godigit.com/content/dam/godigit/directportal/en/downloads/health/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf",
    "downloaded_on": "<download date>",
    "sha256": "70ec4e51cf03a49c06cd7b06fd2dae16ac4ab3a204591fb1e8568a50858ea75b",
    "synthetic": false,
    "source": "catalogue",
    "reviewed": true
  },
  "synthetic": false
}
```

#### `register_uploaded_wording`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Register uploaded wording | write, caller app | app only (upload job) | `out = await tk.ingest_uploaded_policy(case_id, document_id)   # app only: reads the pages, then registers` |

**What it does.** APP ONLY, not for agents. Index the visible text of a policy wording the user uploaded (pages from case-records get_document_text, page.text only) for one case. Returns its wording_uin (upload:doc_...), how it was indexed, and whether it looks like an Arogya Sanjeevani policy.

**How it works.** App only. Ingests the visible page text of a policy the user uploaded, clause by clause (page by page when fewer than 20 clauses are found), indexes it for that case as `upload:doc_<id>`, and reports whether it looks like an Arogya Sanjeevani policy.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case_id | string | yes | The case the upload belongs to  (pattern ^case_[0-9a-f]{16}$) |
| document_id | string | yes | The uploaded policy's document_id  (pattern ^doc_[0-9a-f]{16}$) |
| pages | list[PageIn] | yes | (min items 1; max items 300) |

Nested input models:

| Model | Fields |
|---|---|
| PageIn | page, text |

**Output** (`RegisterUploadOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| wording_uin | string | yes | upload:doc_<id>; store it on the case (case-records set_wording) |
| case_id | string | yes |  |
| document_id | string | yes |  |
| clause_count | integer | yes |  |
| structure | one of: clauses, pages | yes | pages: numbered clauses weren't recognised, so each page is one searchable chunk |
| in_scope | boolean | yes | False when the text doesn't look like an Arogya Sanjeevani policy |
| detected_uin | string \| null | yes |  |
| catalogue_match | string \| null | yes | Set when the detected UIN is in the catalogue: the reviewed copy can be used instead |
| reviewed | boolean | yes |  |
| warnings | list[string] | yes |  |

**Example input** (real call)

```json
{
  "case_id": "case_3bd12d5ff09b06f7",
  "document_id": "doc_53c308cb2a52d5f2",
  "pages": [
    {
      "page": 1,
      "text": "SYNTHETIC TEST WORDING - NOT AN INSURER'S DOCUMENT\nWritten for ClaimClear's policy-kb tests. It imitates the numbered structure of a standard\nArogya Sanjeevani policy wording, in our own words. Do not cite it as policy wording.\n\nAarohan General Insurance Ltd. - Arogya Sanjeevani Policy (synthetic)\nUIN: SYNHLIP00000V000000\n\n1. PREAMBLE\nThis policy is a contract between the insured person and the co…"
    }
  ]
}
```

**Example output** (real result, trimmed)

```json
{
  "wording_uin": "upload:doc_53c308cb2a52d5f2",
  "case_id": "case_3bd12d5ff09b06f7",
  "document_id": "doc_53c308cb2a52d5f2",
  "clause_count": 33,
  "structure": "clauses",
  "in_scope": true,
  "detected_uin": "SYNHLIP00000V000000",
  "catalogue_match": null,
  "reviewed": false,
  "warnings": [
    "5 line(s) before the first clause were not indexed (title page, UIN, notes)"
  ]
}
```


### 6.4 insurer-portal

The interface of the only write action in ClaimClear. The backend is a dry run that records filings in `var/insurer_portal/dry_run.json` and sends nothing; Member 4's mock portal replaces it behind the same tools.

#### `file_grievance`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| File grievance | write, requires approval_token | grievance agent only, after the approval gate | `filed = await tk.file_grievance(case_id, claim_id, row_ids, text, text_sha256, approval_token)` |

**What it does.** WRITE. File the grievance text the policyholder approved at the approval gate. Pass the exact text, its SHA-256 and the gate's approval_token. Returns a reference to follow up with. In dry-run mode nothing is sent to the insurer (status 'dry_run').

**How it works.** Checks that `sha256(text)` equals `text_sha256` (an edit after approval fails), and when `CLAIMCLEAR_GATE_SECRET` is set that the token equals HMAC-SHA256(secret, text_sha256); files once per text and case in the dry-run store (nothing is sent).

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| case_id | string | yes | The case the grievance is about  (pattern ^case_[0-9a-f]{16}$) |
| claim_id | string | yes | (min length 1; max length 64) |
| row_ids | list[string] | yes | The disputable letter rows the grievance covers  (min items 1; max items 50) |
| text | string | yes | The exact approved grievance text  (min length 50; max length 20000) |
| text_sha256 | string | yes | (pattern ^[0-9a-f]{64}$) |
| approval_token | string | yes | (min length 16; max length 256) |

**Output** (`FileGrievanceOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| reference | string | yes | Keep it: grievance_status and claimclear_memory update_grievance use it |
| status | one of: dry_run, filed, acknowledged, resolved, rejected, escalated, closed | yes | dry_run while the mock portal isn't connected; nothing was sent |
| filed_at | string | yes | ISO time the portal accepted it |
| text_sha256 | string | yes | SHA-256 of the exact text that was filed |
| duplicate | boolean | yes | True when this exact text was already filed for the case; the earlier reference is returned and nothing is filed twice |
| dry_run | boolean | yes |  |

**Example input** (real call)

```json
{
  "case_id": "case_3bd12d5ff09b06f7",
  "claim_id": "AGI/HC/2526/004512",
  "row_ids": [
    "R3"
  ],
  "text": "Dear Grievance Officer, I dispute the proportionate deduction of Rs 30,371.43 on claim AGI/HC/2526/004512: the policy allows Rs 21,400.00 on associated medical expenses only.",
  "text_sha256": "e3f50e1f9a95dba0abe0ecef0e55d41ca9e4bd8c3784d632422b06f4127f5864",
  "approval_token": "tok_approved_by_the_gate_123"
}
```

**Example output** (real result, trimmed)

```json
{
  "reference": "DRYRUN-D8669A871502",
  "status": "dry_run",
  "filed_at": "<UTC timestamp>",
  "text_sha256": "e3f50e1f9a95dba0abe0ecef0e55d41ca9e4bd8c3784d632422b06f4127f5864",
  "duplicate": false,
  "dry_run": true
}
```

#### `grievance_status`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Grievance status | read | grievance agent | `status = await tk.grievance_status(reference)` |

**What it does.** The current status of a filed grievance, by the reference file_grievance returned.

**How it works.** Reads a filing from the dry-run store by its reference.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| reference | string | yes | The portal's reference from file_grievance  (pattern ^[A-Z]{2,8}-[0-9A-F]{8,16}$; max length 30) |

**Output** (`GrievanceStatusOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| reference | string | yes |  |
| case_id | string | yes |  |
| claim_id | string | yes |  |
| status | one of: dry_run, filed, acknowledged, resolved, rejected, escalated, closed | yes |  |
| last_update | string | yes |  |
| insurer_response | string \| null | yes |  |
| dry_run | boolean | yes |  |

**Example input** (real call)

```json
{
  "reference": "DRYRUN-D8669A871502"
}
```

**Example output** (real result, trimmed)

```json
{
  "reference": "DRYRUN-D8669A871502",
  "case_id": "case_3bd12d5ff09b06f7",
  "claim_id": "AGI/HC/2526/004512",
  "status": "dry_run",
  "last_update": "<UTC timestamp>",
  "insurer_response": null,
  "dry_run": true
}
```


### 6.5 document-reader

The single place documents are read, for the app's upload pipeline. Agents read documents through case-records, which uses the same reader library, so both give the same result (a test checks it).

#### `read_document`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Read document | read, caller app | app only (upload pipeline) | `# app only: MCP call to document-reader :8105 (not in the toolkit's agent tools)` |

**What it does.** Read a PDF, JPG or PNG sent as base64. Per page: visible text in reading order, every span with its bounding box (cite span_id), and hidden text kept apart with the reason it is hidden. Also returns PDF metadata, annotations, form fields and attachments. All of it is untrusted data. Image-only pages need OCR; ocr_status says whether it ran. document_id is doc_ plus the first 16 hex digits of the file's SHA-256.

**How it works.** Decodes base64, runs the reader's input checks (type, size, magic bytes), extracts (cache only if `CLAIMCLEAR_DOCUMENT_CACHE` is set) and returns the same shape as get_document_text; `document_id` is doc_ + the first 16 hex digits of the SHA-256.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| content_base64 | string | yes | The file's bytes, base64-encoded  (min length 4; max length 34952536) |
| media_type | one of: application/pdf, image/jpeg, image/png | yes | What the file is |
| pages | list[integer] \| null | no | 1-based pages; default all  (max items 50; default null) |

**Output** (`DocumentTextOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| document_id | string | yes |  |
| media_type | string | yes |  |
| page_count | integer | yes |  |
| pages_returned | list[integer] | yes |  |
| metadata | dict[str, string] | yes |  |
| pdf_flags | list[string] | yes |  |
| pages | list[PageOut] | yes |  |
| annotations | list[AnnotationOut] | yes |  |
| form_fields | list[FormFieldOut] | yes |  |
| attachments | list[AttachmentOut] | yes |  |
| warnings | list[string] | yes |  |
| untrusted_content | boolean | yes |  |

**Example input** (real call)

```json
{
  "content_base64": "JVBERi0xLjQKJZOMi54gUmVw…",
  "media_type": "application/pdf",
  "pages": [
    1
  ]
}
```

**Example output** (real result, trimmed)

```json
{
  "document_id": "doc_53c308cb2a52d5f2",
  "media_type": "application/pdf",
  "page_count": 1,
  "pages_returned": [
    1
  ],
  "metadata": {
    "title": "Claim AGI/HC/2526/004512",
    "author": "Aarohan General Insurance Ltd.",
    "subject": "Claim settlement letter",
    "creator": "Billing system",
    "producer": "ReportLab PDF Library - (opensource)",
    "creationDate": "D:20000101000000+00'00'",
    "modDate": "D:20000101000000+00'00'"
  },
  "pdf_flags": [],
  "pages": [
    {
      "page": 1,
      "width": 595.3,
      "height": 841.9,
      "source": "text_layer",
      "text": "Aarohan General Insurance Ltd.\nAarohan House, 21 Sagar Marg, Mumbai 000400\nclaims@aarohan.example | +91 00000 12000\nHealth Claims Department IRDAI Reg. No. FIC-000\nRef: A…",
      "hidden_text": "",
      "spans": [
        {
          "span_id": "p1-s1",
          "text": "Aarohan General Insurance Ltd.",
          "bbox": [
            48.5,
            60.3
          ],
          "font_size": 15.0,
          "color": "#ffffff",
          "hidden": false,
          "hidden_reasons": []
        },
        {
          "span_id": "p1-s2",
          "text": "Aarohan House, 21 Sagar Marg, Mumbai 000400",
          "bbox": [
            398.7,
            58.9
          ],
          "font_size": 7.5,
          "color": "#ffffff",
          "hidden": false,
          "hidden_reasons": []
        }
      ],
      "has_images": false,
      "ocr_status": "not_needed",
      "warnings": []
    }
  ],
  "annotations": [],
  "form_fields": [],
  "attachments": [],
  "warnings": [],
  "untrusted_content": true
}
```

#### `reader_status`

| Title | Access | Callers | Toolkit call |
|---|---|---|---|
| Reader status | read, caller app | app only | `# app only: MCP call to document-reader :8105` |

**What it does.** Whether OCR is installed and switched on, its languages and resolution, and the reader's limits.

**How it works.** Reports the reader version, accepted media types, limits, whether a cache is on, and OCR state (installed, enabled, language, dpi, installed and missing languages). No local paths.

**Input fields**

| Field | Type | Required | Description / constraints |
|---|---|---|---|
| (none) |  |  |  |

**Output** (`ReaderStatusOut`)

| Field | Type | Always present | Description |
|---|---|---|---|
| version | string | yes | Reader version; results cached under another version are not reused |
| media_types | list[one of: application/pdf, image/jpeg, image/png] | yes |  |
| max_bytes | integer | yes |  |
| max_pages | integer | yes |  |
| cache | boolean | yes | Results are cached by file content, so a file is OCR'd only once |
| ocr | OcrStatusOut | yes |  |

**Example input** (real call)

```json
{}
```

**Example output** (real result, trimmed)

```json
{
  "version": "1",
  "media_types": [
    "application/pdf",
    "image/jpeg"
  ],
  "max_bytes": 26214400,
  "max_pages": 50,
  "cache": false,
  "ocr": {
    "engine": "tesseract",
    "installed": true,
    "enabled": false,
    "language": "eng",
    "dpi": 300,
    "installed_languages": [
      "eng",
      "osd"
    ],
    "missing_languages": []
  }
}
```


## 7. Settlement engine and matcher

`servers/settlement_engine/engine/` computes, in plain tested Python, what an Arogya Sanjeevani policy says should be paid on a reimbursement claim; the matcher finds which documented method reproduces each figure on the insurer's letter. No LLM is involved.

```mermaid
flowchart TB
    s1["Step 1: Read every bill line: category, GST, non-payable flag (Annexure A)"]
    s2["Step 2: Claimed amount = line amounts + line GST - hospital discount"]
    s3["Step 3: Policy period; a hospitalisation already settled is not paid again"]
    s4["Step 4: Waiting periods, from first inception; the condition picks its list"]
    s5["Step 5: Non-payable items, charges billed twice, bills outside the 30/60-day window, ambulance above ₹2,000"]
    s6["Step 6: Room-rent cap per day, and the GST on the excess"]
    s7["Step 7: ICU cap per day, and the GST on the excess"]
    s8["Step 8: Proportionate deduction on associated expenses only (IRDAI 2020)"]
    s9["Step 9: Cataract sub-limit per eye…"]
    s10["Step 10: Admissible = claimed - deductions 5-9"]
    s11["Step 11: Co-pay on the admissible amount"]
    s12["Step 12: Payable = admissible - co-pay…"]
    s1 --> s2
    s2 --> s3
    s3 --> s4
    s4 --> s5
    s5 --> s6
    s6 --> s7
    s7 --> s8
    s8 --> s9
    s9 --> s10
    s10 --> s11
    s11 --> s12
    s12 --> m["Matcher, per letter row:<br/>policy method + chosen hypotheses<br/>within ₹1 → verdict"]
    h["Hypothesis library (49 methods)"] --> m
    classDef m2 fill:#e3f4e8,stroke:#2f855a,color:#1a202c
    class s1,s2,s3,s4,s5,s6,s7,s8,s9,s10,s11,s12,m,h m2
```

**Order of operations** (from `engine/engine.py`):

1. Read every bill line: category, GST, non-payable flag.
2. Claimed amount = line amounts + line GST - hospital discount. Check it against the printed total.
3. Policy period: the admission must fall inside the policy period on record. A bill with no admission date (a pharmacy or post-hospitalisation bill) asks for it and skips steps 3-4. A hospitalisation an earlier settled claim already paid is not paid again.
4. Waiting periods, counted from first inception. Not served -> whole claim not admissible.
5. Non-payable items (line amount + its GST), then lines billed twice for the same day, then bills dated outside the pre/post-hospitalisation days, then road ambulance above its limit.
6. Room-rent cap per day, and the GST on the excess.
7. ICU cap per day, and the GST on the excess.
8. Proportionate deduction on associated expenses only, if the room was above the cap.
9. Cataract sub-limit per eye, net of what was used earlier this policy period.
10. Admissible = claimed - deductions 5-9.
11. Co-pay on the admissible amount.
12. Payable = admissible - co-pay, capped at the sum insured left this policy period.

When it needs a fact it does not have (an unknown line the proportionate cut would touch, an unknown condition type inside a waiting period, an admission outside the policy period or missing, an unstated eye) it returns `needs_information` with questions and no payable figure. It never guesses.

**Bill lines.** A line the bill doesn't mark is checked against IRDAI's standard list of items not paid as separate lines, Annexure A of the wording (`categories.ANNEXURE_A`): List I items not covered (mineral water, crepe bandage, nebuliser kit), List II items subsumed into room charges (file opening, documentation, admission kit), List III items subsumed into procedure charges (gauze, cotton, eye kit and drape), List IV items subsumed into the cost of treatment (registration, urine bag). Items the list says are payable in some cases are left out, so nothing is disallowed on a keyword alone.

| Verdict | Meaning | Wording an explanation may use (contracts) |
|---|---|---|
| matches_policy | the insurer's figure is what the wording requires (within ₹1) | matches your policy |
| does_not_match_policy | a documented wrong method reproduces it; or, after every hypothesis is tested, the insurer took more than the policy figure (the insurer is asked for its working) | may be disputable (positive difference); the insurer deducted less than your policy allows (negative) |
| method_matches | co-pay only: right method on a base carrying another row's error | worked out correctly, but on the insurer's figures |
| not_verifiable | nothing tested reproduces it and it isn't more than the policy figure; the row names an item the engine doesn't recognise; it is part of a line that groups many items; it depends on earlier claims the engine wasn't given; or information is missing | we can't check this without more information |

**Rows about particular lines.** A non-payable, charged-twice or cover-window row that names bill lines ("Crepe bandage - List I (not payable)") is measured against the engine's deduction on those lines only.

**Rule references** (every deduction and fact carries one; `clauses_for_rule` resolves it to clauses):

| rule_ref | Summary |
|---|---|
| room_rent_cap | Room rent per day is limited to a % of sum insured, up to a rupee maximum. |
| icu_cap | ICU charges per day are limited to a % of sum insured, up to a rupee maximum. |
| gst_follows_charge | GST on a disallowed part of a charge is disallowed with it. |
| proportionate_deduction | If the room rent exceeds the limit, associated medical expenses are reduced in the same proportion. IRDAI/HLT/REG/CIR/151/06/2020 (11 Jun 2020) bars this for pharmacy, consumables, implants, medical devices, diagnostics, ICU charges, and any expense the hospital does not price differently by room category. |
| non_payable_items | Items on the policy's list of non-payable items are not paid. |
| cataract_limit | Cataract treatment is limited per eye per policy period to the lower of a % of sum insured and a rupee maximum. |
| initial_waiting_period | Illness treated within the first days of first inception is excluded (accidents are not). |
| listed_illness_waiting_period | Listed illnesses are covered only after a waiting period counted from first inception. |
| pre_existing_waiting_period | Pre-existing diseases are covered only after a waiting period counted from first inception. |
| copay | The policyholder bears a fixed % of every admissible claim, applied after all other deductions. |
| sum_insured | Payments in one policy period cannot exceed the sum insured. |
| pre_hospitalisation | Expenses before admission are paid only for a fixed number of days before the admission. |
| post_hospitalisation | Expenses after discharge are paid only for a fixed number of days from the discharge. |
| ambulance_limit | Road ambulance is paid up to a rupee limit per hospitalisation. |
| policy_period | A claim is covered when the admission falls inside the policy period. |
| expenses_actually_incurred | Only expenses actually incurred are paid: a charge billed twice for the same day is paid once. |

**Hypothesis library** (49 methods, from the registry):

| ID | Row kind | Correct | Title |
|---|---|---|---|
| already_paid_policy | already_paid | yes | The same hospitalisation already settled |
| ambulance_policy | ambulance | yes | Road ambulance above its limit |
| cataract_policy | cataract | yes | Cataract limit per eye |
| cataract_15pct_si | cataract | no | Cataract limit taken as 15% of sum insured |
| cataract_max_only | cataract | no | Cataract limit at ₹40,000, ignoring 25% of sum insured |
| cataract_mixes_policy_years | cataract | no | Cataract limit reduced by claims from earlier policy years |
| cataract_pct_only | cataract | no | Cataract limit at 25% of sum insured, ignoring ₹40,000 |
| cataract_shared_between_eyes | cataract | no | Cataract limit shared between the two eyes |
| copay_policy | copay | yes | Co-pay on the policy-correct admissible amount |
| copay_double_rate | copay | no | Co-pay at double the rate |
| copay_on_claimed | copay | no | Co-pay on the full bill |
| copay_on_insurer_base | copay | no | Co-pay at the right rate on the insurer's own admissible amount |
| copay_twice | copay | no | Co-pay applied twice |
| cover_window_policy | cover_window | yes | Bills outside the pre/post-hospitalisation days |
| duplicate_named_items | duplicate | yes | The repeated charges this row names |
| duplicate_policy | duplicate | yes | Charges billed twice for the same day |
| duplicate_daily_repeats | duplicate | no | A daily charge treated as a duplicate of the first day |
| icu_policy | icu | yes | ICU charges above the policy limit |
| icu_cap_max_only | icu | no | ICU cap at ₹10,000, ignoring 5% of sum insured |
| icu_cap_pct_only | icu | no | ICU cap at 5% of sum insured, ignoring the ₹10,000 maximum |
| icu_room_cap_used | icu | no | ICU charges capped at the room-rent limit |
| icu_gst_policy | icu_gst | yes | GST on the disallowed ICU charges |
| non_payable_named_items | non_payable | yes | The non-payable items this row names |
| non_payable_policy | non_payable | yes | Items on the non-payable list |
| nonpay_payable_item_listed | non_payable | no | A payable item counted as non-payable |
| policy_period_policy | policy_period | yes | Admission inside the policy period |
| proportionate_policy | proportionate | yes | Proportionate deduction on associated expenses only |
| prop_incl_diagnostics | proportionate | no | Proportionate cut also applied to diagnostics |
| prop_incl_implants | proportionate | no | Proportionate cut also applied to implants |
| prop_incl_non_payable | proportionate | no | Proportionate cut applied before removing non-payable items |
| prop_incl_pharmacy | proportionate | no | Proportionate cut also applied to pharmacy |
| prop_on_all_lines | proportionate | no | Proportionate cut applied to every non-room line |
| prop_on_all_lines_incl_icu | proportionate | no | Proportionate cut applied to every non-room line, ICU included |
| prop_on_whole_bill | proportionate | no | Proportionate cut applied to the whole bill |
| prop_round_each_line | proportionate | no | Proportionate cut rounded to the rupee on each line |
| room_and_icu_policy | room_and_icu | yes | Room rent and ICU above their limits |
| room_and_icu_room_cap_on_icu | room_and_icu | no | ICU days capped at the room-rent limit |
| room_gst_policy | room_gst | yes | GST on the disallowed room rent |
| room_gst_on_full_room | room_gst | no | GST disallowed on the whole room charge |
| room_rent_policy | room_rent | yes | Room rent above the policy limit |
| room_cap_max_only | room_rent | no | Room cap at ₹5,000, ignoring 2% of sum insured |
| room_cap_pct_only | room_rent | no | Room cap at 2% of sum insured, ignoring the ₹5,000 maximum |
| room_days_incl_discharge | room_rent | no | Room excess counted for one day too many |
| sum_insured_policy | sum_insured | yes | Sum insured left this policy period |
| si_mixes_policy_years | sum_insured | no | Sum insured reduced by claims from earlier policy years |
| unitemised_policy | unitemised | yes | Amount the itemised lines don't support |
| waiting_period_policy | waiting_period | yes | Waiting periods counted from first inception |
| waiting_from_renewal | waiting_period | no | Waiting period counted from the latest renewal |
| waiting_pre_existing_assumed | waiting_period | no | Condition treated as pre-existing without it being stated |

**Gaps fixed from the dataset cross-check:**

| Gap | Fix | Result on the answer key |
|---|---|---|
| Unmarked bill lines treated as payable | a bill can only mark a line non-payable; the policy list decides otherwise; correct method `non_payable_named_items` for rows naming some items | SET-16: ₹0 disputable |
| Charges billed twice | same service (synonyms merged), date and amount → `duplicate_line` deduction (rule `expenses_actually_incurred`, clause B.26) | SET-35 pays ₹82,650 |
| Daily charges cut as duplicates | wrong method `duplicate_daily_repeats` | SET-24: ₹8,977.50 disputable |
| Bills without an admission date crashed | optional dates; the engine asks `Q-ADMISSION` | SET-06, SET-22, SET-25 no longer crash |
| Look-alike policy numbers | `engine/identifiers.py`: canonical form for comparisons, with a warning | SET-21 pays ₹24,937.50 |
| Annexure A items missing (gen-data dev cases) | `categories.ANNEXURE_A`, Lists I–IV; rows citing a list are non-payable rows | 14 cases; three no longer blocked by a room-pricing question |
| Too hesitant to call out a mistake | after every hypothesis is tested, a larger deduction than the policy figure is `does_not_match_policy` | 6 cases, e.g. a proportionate cut with the room under its cap |
| Ambulance limit, cover window | ₹2,000 per hospitalisation; dated bills outside 30 days before / 60 days after | 6 cases |
| Rows measured against the wrong line | a row is measured against the lines it names | 2 cases |
| Whole-claim checks | policy-period rejections, the condition's waiting-period list, a hospitalisation already settled, a test billed twice, room-and-ICU rows, amounts no line supports | 9 cases |


**Partial:** rows still `not_verifiable`: OT unbundling and lab totals above the itemised rate (SET-16 rows 2 and 5), surgical consumables (SET-33 row 2), a letter on an invented policy (SET-08).


The dev-case results and the reasoning behind each fix are in `additional_resources/member2_knowledge_memory_tools/evaluation_dev_cases.md`. **Decided:** the proportionate deduction keeps IRDAI's 2020 rule; three gen-data answers that follow an older wording are labelled from `development/dev_eval/dev_cases/decisions.json`.

## 8. Document processing and OCR

`servers/document_reader` is the only code that opens a document: case-records imports it, the app calls its MCP server. PyMuPDF reads text with positions and drawing order; Tesseract (through PyMuPDF) reads scans and photos.

```mermaid
flowchart LR
    in["Bytes or stored file<br/>PDF, JPG, PNG"] --> chk{"Input checks<br/>type, ≤ 25 MB,<br/>magic bytes"}
    chk -->|"fail"| err["UNSUPPORTED_MEDIA_TYPE<br/>MEDIA_TYPE_MISMATCH<br/>DOCUMENT_TOO_LARGE"]
    chk --> cache{"Cache hit?<br/>sha256 of version, file,<br/>type, OCR, pages"}
    cache -->|"yes"| out
    cache -->|"no"| trace["PyMuPDF text trace<br/>spans, boxes, colours,<br/>drawing order"]
    trace --> hidden["Hidden-text rules<br/>kept out of text"]
    trace --> img{"Image-only page?"}
    img -->|"yes, OCR on"| ocr["Tesseract OCR<br/>spans source=ocr<br/>layer vs picture check"]
    img -->|"yes, OCR off"| un["ocr_status=unavailable<br/>no guessed text"]
    trace --> other["metadata, annotations,<br/>form fields, attachments,<br/>PDF edit flags"]
    hidden --> out["DocumentTextOut<br/>untrusted_content: true"]
    ocr --> out
    un --> out
    other --> out
    out --> save[("cache, unless OCR failed")]
    classDef m2 fill:#e3f4e8,stroke:#2f855a,color:#1a202c
    class in,chk,cache,trace,hidden,img,ocr,un,other,out,save,err m2
```

| Check / limit | Value | Error |
|---|---|---|
| Media types | application/pdf, image/jpeg, image/png | UNSUPPORTED_MEDIA_TYPE |
| Size | 1 byte to 26,214,400 bytes (25 MB) | DOCUMENT_UNREADABLE / DOCUMENT_TOO_LARGE |
| Content matches type | `%PDF-` in the first 1 KB, PNG signature, JPEG `FF D8 FF` | MEDIA_TYPE_MISMATCH |
| Pages per call | 50 | warning; first 50 returned |
| Spans per page / characters per field | 5000 / 1000 | - |
| Encrypted PDF | - | DOCUMENT_ENCRYPTED |

| Hidden reason | Rule |
|---|---|
| invisible_render | text drawn in invisible render mode (PDF Tr 3) |
| transparent | zero opacity |
| tiny_font | font size under 2 pt |
| white_on_white | white text with no coloured shape or image behind it (white on a coloured bar is visible) |
| covered | an opaque shape drawn after the text covers at least 80% of it |
| off_page | less than half of the text inside the page |

**OCR.** `CLAIMCLEAR_OCR` auto/on/off (auto = on when Tesseract is found), `CLAIMCLEAR_OCR_LANGUAGE` (eng), `CLAIMCLEAR_OCR_DPI` (300, range 150–600). Tesseract's data is found from `TESSDATA_PREFIX` (only if that folder exists), Tesseract on the PATH, then standard folders (Windows per-user and machine-wide, Fedora `/usr/share/tesseract/tessdata`, Debian, Homebrew). An image-only page (no visible text, at least half image) is OCR'd; any invisible text layer is compared with the OCR words, and a number in the layer but not in the picture gives a warning (forged layer). **Implemented** and tested with Tesseract 5.4 (English); Hindi needs its language pack and is not measured.

**Cache.** Key: SHA-256 of reader version (1), file SHA-256, media type, OCR settings and pages; stored as `<cache>/<2 hex>/<key>.json`, written atomically; failed OCR is not cached. case-records keeps it in `<case store>/text_cache` (deleted with the store); the document-reader service caches nothing unless `CLAIMCLEAR_DOCUMENT_CACHE` is set. **Partial** for production: the cache stays on the case-records host's disk.

## 9. Case and document store

`servers/case_records/case_records/store.py` (`CaseStore`): written by the upload path (the app, `case_records.register_dataset`, `scripts/register_case_folder.py`); the MCP server only reads.

| Concept | Detail |
|---|---|
| Document ID | `doc_` + first 16 hex digits of the file's SHA-256; the same file is stored once |
| Stored name | `<document_id>.pdf\|.jpg\|.png`; original file names are never stored or returned |
| Case | `case_` + 16 hex digits; policy number, document IDs, role per document, wording UIN |
| Roles | bill, settlement_letter, discharge_summary, policy_wording, policy_schedule, other |
| Case scoping | `read(case_id, document_id)` refuses another case's document (DOCUMENT_NOT_IN_CASE) |
| Integrity | every read re-hashes the bytes (DOCUMENT_INTEGRITY) |
| Index | re-read on every tool call, so new uploads appear at once |

| Piece | Default | Production backend (implemented) | Variable |
|---|---|---|---|
| Index | JsonIndex: `index.json` | PostgresIndex: tables `case_store_documents`, `case_store_cases` (`?table_prefix=`) | `CLAIMCLEAR_CASE_INDEX` |
| Files | LocalBlobs: `files/` | S3Blobs: MinIO or any S3 bucket (`prefix` in the URL) | `CLAIMCLEAR_BLOB_STORE`, `CLAIMCLEAR_S3_ACCESS_KEY`, `CLAIMCLEAR_S3_SECRET_KEY` |

```python
from case_records.store import CaseStore
store = CaseStore()                                   # backends from the environment
case = store.create_case("AS-2025-100478", wording_uin="GODHLIP24179V022324")
doc = store.add_document(case.case_id, "bill.pdf", role="bill")
record, data = store.read(case.case_id, doc.document_id)   # bytes after the SHA-256 check
```

## 10. Policy knowledge base

| Stage | Implementation | Status |
|---|---|---|
| Ingestion | `ingest.py`: one chunk per numbered clause (number, title, section, parent, pages); annexure lists as their own chunks; lettered layouts (A, B.1, C.1.1) qualified; under 20 clauses → page chunks for uploads | Implemented |
| Lexical | `bm25.py`: own BM25 (k1 1.5, b 0.75); `text.py` tokens and stemming | Implemented |
| Vectors | `embedders.py`: hashing-1024 (default, offline), OpenRouter `baai/bge-m3` (key needed), fastembed `BAAI/bge-small-en-v1.5` (optional) | Implemented |
| Vector store | `vectorstore.py`: in memory (default) or pgvector (`<#>` inner product, uploaded once per wording + embedder) | Implemented |
| Fusion | Reciprocal Rank Fusion, k = 60 (`kb.py`) | Implemented |
| Query rewriting | `rewrite.py`: glossary (default); OpenRouter LLM rewriter `openai/gpt-4.1-mini` (off by default: it hurt recall in the draft run) | Implemented |
| Reranker | `rerankers.py`: none by default; fastembed `Xenova/ms-marco-MiniLM-L-6-v2` (downloaded on first use); not measured | Partial |
| Rule maps | `rule_maps/GODHLIP24179V022324.json`: engine rule_ref → reviewed clauses; a test checks every clause exists | Implemented |
| Evaluation | `python -m policy_kb evaluate <queries.jsonl>`: Recall@k, Hit@k, MRR, before/after rewriting; draft Recall@5 0.933 on draft labels; Member 1's labels needed | Partial |
| Catalogue and uploads | `catalogue.py`: reviewed wordings from `development/dev_data/wordings/catalogue.json` plus per-case uploads (`upload:doc_<id>`, `reviewed: false`) | Implemented |

## 11. Memory architecture

The plan asks for trimmed short-term context plus one long-term store per user with consent, expiry and 'forget my data'. `memory/claimclear_memory/` implements the long-term store and the context the agents receive; trimming the chat messages themselves belongs to Member 3's graph.

```mermaid
flowchart TB
    caller["Member 3's graph / Member 4's app"] -->|"tool results only"| api["MemoryStore.for_user(user_id)<br/>session_memory(user_id)"]
    api --> ops["grant_consent, remember_policy, remember_claim,<br/>open_grievance, update_grievance,<br/>context, render, merge_history, export, forget"]
    ops --> rules{"Rules in code<br/>consent? final audit?<br/>amounts copied, not computed"}
    rules --> db["db.py: Database"]
    db -->|"default"| sqlite[("SQLite file<br/>var/memory/memory.db")]
    db -.->|"CLAIMCLEAR_MEMORY_DB=postgresql://"| pg[("PostgreSQL<br/>same tables")]
    ops --> ctx["context() → CaseState memory<br/>render() → bounded prompt block"]
    classDef m2 fill:#e3f4e8,stroke:#2f855a,color:#1a202c
    classDef m3 fill:#e6eefc,stroke:#3b6fd8,color:#1a202c
    class api,ops,rules,db,sqlite,pg,ctx m2
    class caller m3
```

| Stored per user_id | Source | Not stored |
|---|---|---|
| policy profile: sum insured, period, first inception, insurer, product, wording UIN | get_policy result | the policyholder's name |
| verified claims: claimed, paid, policy payable, disputable, unverified, verdict counts, disputable rows, diagnosis, procedure, dates | audit_settlement_letter result (final audits only) | audits still waiting for answers |
| sub-limit balances (sum insured left, cataract left) | the engine's own facts | anything memory would compute |
| grievance status and events | approval gate hash, portal reference | the grievance text (only its SHA-256) |
| consent version and events | the user's action in the app | - |

**Where and how.** One database: SQLite by default (`$CLAIMCLEAR_MEMORY_DB`, else `var/memory/memory.db`, git-ignored) or PostgreSQL when the variable is a `postgresql://` URL (`?schema=` for a separate schema). Schema version 2; consent policy `memory-policy-v1`. `db.py` opens either; the store writes portable SQL (`?` placeholders, `INSERT ... ON CONFLICT ... DO UPDATE` built from the schema).

| Table | Columns | Primary key |
|---|---|---|
| meta | key, value | key |
| policies | user_id, policy_no, insurer, product, sum_insured, period_start, period_end, first_inception, wording_uin, source, updated_at | user_id, policy_no |
| claims | user_id, claim_id, policy_no, admission, discharge, diagnosis, procedure, status, claimed_amount, insurer_paid, policy_payable, disputable_amount, unverified_amount, verdicts, disputable_rows, case_id, source, created_at, updated_at | user_id, claim_id |
| balances | user_id, policy_no, period_start, fact_id, rule_ref, amount, text, claim_id, claim_admission, recorded_at | user_id, policy_no, period_start, fact_id |
| grievances | user_id, grievance_id, claim_id, policy_no, status, row_ids, disputable_amount, text_sha256, reference_no, created_at, updated_at | user_id, grievance_id |
| grievance_events | user_id, grievance_id, seq, at, status, note | user_id, grievance_id, seq |
| users | user_id, consent_version, consent_at, consent_source, last_seen | user_id |
| consent_events | user_id, seq, at, action, policy_version, source | user_id, seq |

| Rule | Value |
|---|---|
| Consent | nothing is stored until the user consents to the current memory policy; a new policy version needs new consent; withdrawing deletes by default |
| Claims | kept 730 days from when last verified (waits while a grievance is open) |
| Closed grievances | kept 365 days after the last change |
| Inactive users | everything deleted after 365 days without use |
| Expiry | `purge_expired()` runs before every `context()`; `MemoryStore.purge_expired()` is the daily job (scheduling it is the app's: planned) |
| Forget / export | `forget()` deletes every row of the user; `export()` returns them |
| Isolation | the only way in is `for_user(user_id)`; no query spans users |

Grievance lifecycle (only these transitions are allowed):

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> approved
    draft --> withdrawn
    approved --> filed
    approved --> withdrawn
    filed --> acknowledged
    filed --> rejected
    filed --> resolved
    filed --> withdrawn
    acknowledged --> rejected
    acknowledged --> resolved
    acknowledged --> withdrawn
    resolved --> closed
    resolved --> escalated
    rejected --> closed
    rejected --> escalated
    escalated --> closed
    escalated --> rejected
    escalated --> resolved
    closed --> [*]
    withdrawn --> [*]
```

```python
from claimclear_memory import MemoryStore, merge_history, render

store = MemoryStore()                                    # SQLite or PostgreSQL from CLAIMCLEAR_MEMORY_DB
store.for_user("u_7f3a").grant_consent("app:settings")   # only from the user's own action in the app
mem = store.session_memory("u_7f3a")                     # UserMemory with consent, else NoMemory (stores nothing)
mem.remember_policy(policy)                              # after get_policy
mem.remember_claim(case, letter_audit, case_id=case_id, letter=letter)   # after the critic passes
ctx = mem.context(policy_no=policy["policy_no"])         # -> CaseState["memory"]
prompt_block = render(ctx, max_chars=1500)
case["history"] = merge_history(history, mem.claim_history(policy["policy_no"]))
```

**Memory on vs off: Partial.** `development/dev_eval/memory_on_off/run.py` runs the development cases per policyholder with and without memory and scores them. No difference on the current development set (it has no two paid claims on one policy); rerun with Member 3's graph (`--pipeline module:function`) and Member 1's same-policy cases.

## 12. Storage and databases

```mermaid
flowchart LR
    cs["CaseStore"] --> ji[("index.json")]
    cs --> lf[("files/")]
    cs -.->|"CLAIMCLEAR_CASE_INDEX"| pgi[("PostgreSQL<br/>case_store_*")]
    cs -.->|"CLAIMCLEAR_BLOB_STORE"| s3[("MinIO bucket")]
    ms["MemoryStore"] --> sq[("SQLite")]
    ms -.->|"CLAIMCLEAR_MEMORY_DB"| pgm[("PostgreSQL")]
    kb["PolicyKB"] --> vf[("vectors in index.json")]
    kb -.->|"CLAIMCLEAR_POLICY_KB_VECTORS"| pv[("pgvector<br/>policy_kb_vectors")]
    classDef m2 fill:#e3f4e8,stroke:#2f855a,color:#1a202c
    class cs,ms,kb,ji,lf,pgi,s3,sq,pgm,vf,pv m2
```

| Data | Default (development) | Production backend | Status |
|---|---|---|---|
| Uploaded documents | `var/case_store/files/` | MinIO / S3 (`CLAIMCLEAR_BLOB_STORE`) | Implemented |
| Case index | `var/case_store/index.json` | PostgreSQL (`CLAIMCLEAR_CASE_INDEX`) | Implemented |
| Extracted-text cache | `<case store>/text_cache` | local disk of the case-records host | Partial |
| Policy clauses | `var/policy_kb/index.json` | stays a file, built per wording | Implemented |
| Clause vectors | in the index file | PostgreSQL + pgvector (`CLAIMCLEAR_POLICY_KB_VECTORS`) | Implemented |
| Memory | `var/memory/memory.db` (SQLite) | PostgreSQL (`CLAIMCLEAR_MEMORY_DB`) | Implemented |
| Grievance filings | `var/insurer_portal/dry_run.json` | Member 4's mock portal database | Planned / other member |
| Dataset map (evaluation only) | `var/dataset_map.json` | never given to agents | Implemented |

`deploy/storage.compose.yml` starts PostgreSQL 16 with pgvector (`pgvector/pgvector:pg16`, port 5432) and MinIO (Chainguard's build of MinIO pinned by digest, ports 9000/9001; MinIO no longer publishes community images on Docker Hub). The credentials in it are for development only. Drivers: `pg8000` and `minio`, imported only when a production URL is set.

## 13. End-to-end workflow

A policyholder uploads a settlement letter, the bill and the policy schedule, and asks why they were paid less.

```mermaid
sequenceDiagram
    autonumber
    actor U as Policyholder
    participant APP as App + guardrails (M4)
    participant CS as CaseStore (M2)
    participant G as LangGraph agents (M3)
    participant H as Hooks (M4)
    participant CR as case-records (M2)
    participant PK as policy-kb (M2)
    participant SE as settlement-engine (M2)
    participant MEM as memory (M2)
    participant IP as insurer-portal (M2)
    U->>APP: upload letter, bill, schedule
    APP->>CS: create_case, add_document (neutral IDs)
    U->>APP: "Why did they cut so much?"
    APP->>G: start (case_id, user_id)
    G->>MEM: context(policy_no)
    Note over G,H: every tool call below passes the hooks (section 3)
    G->>CR: list_case_documents, get_document_text
    G->>G: document reader extracts claim + letter (span IDs)
    G->>CR: get_policy, get_claim_history
    G->>PK: search_clauses, clauses_for_rule
    G->>SE: expected_settlement
    alt needs information
        SE-->>G: questions
        G->>U: interrupt: ask, then rerun with the answer
    end
    G->>SE: list_hypotheses, reproduce_deduction per row
    G->>SE: audit_settlement_letter (critic re-checks every figure)
    G->>G: explainer writes from fact IDs
    G->>APP: draft → output guardrails
    APP->>U: answer and verdict table
    G->>MEM: remember_claim (with consent)
    opt user disputes
        G->>APP: grievance draft → approval gate (exact text + SHA-256)
        APP-->>G: approval token for that hash
        G->>IP: file_grievance (grievance agent only)
    end
```

| # | Step | Who | Status |
|---|---|---|---|
| 1 | Upload; file checks; store under neutral IDs (`CaseStore`) | App (M4) → store (M2) | Partial: store built, app not |
| 2 | Optional: read the upload once (`read_document`) for masking or routing | App → document-reader | Partial |
| 3 | Question; input guardrails mark document text as data | App (M4) | Planned / other member |
| 4 | Supervisor loads memory context | Graph (M3) → memory (M2) | Partial: memory built |
| 5 | Hooks check permission and budget on each call | Hooks (M4) | Planned (attach points built) |
| 6 | Read documents; extract claim and letter with span IDs | Graph → case-records | Partial: tools built |
| 7 | Policy, history, clauses | Graph → case-records, policy-kb | Partial: tools built |
| 8 | Settlement, hypotheses per row, questions, replan | Graph → settlement-engine | Partial: tools built |
| 9 | Critic: `audit_settlement_letter`; figures only from the engine | Graph → engine; toolkit `critic` | Partial: tools and checks built |
| 10 | Explainer from fact IDs, wording from the contracts | Graph (M3) | Planned / other member |
| 11 | Output guardrails; reply | App (M4) | Planned / other member |
| 12 | Remember the claim (consent) | Graph → memory | Partial: memory built |
| 13 | Dispute: approval gate, then `file_grievance` (grievance agent only) | M3 + M4 → insurer-portal | Partial: tool and checks built, gate not |

**Worked example (verified by tests).** On SET-01, `audit_settlement_letter` gives a policy-correct payable of ₹95,617.50, the insurer paid ₹87,094.64, and ₹8,522.86 may be disputable; the proportionate deduction is reproduced by the wrong method `prop_on_all_lines` (₹30,371.43 where the policy allows ₹21,400). That matches the plan's hand-worked answer.

## 14. Contracts and the agents' toolkit

### 14.1 `claimclear_contracts` (both sides import it)

| Module | Content |
|---|---|
| `state.py` | `CaseState` and `FIELD_SHAPES` (below); `engine_case(state)` builds the engine's `case` |
| `handoffs.py` | `Plan`/`PlanStep` (a replan must state `replan_reason`), `ReaderHandoff`, `AnalystHandoff`, `AuditorHandoff`, `CriticReport`, `ExplainerDraft`, `GrievanceDraft` (text and SHA-256 must agree); all refuse unknown keys |
| `tools.py` | all tool schemas (exported from the servers' snapshots); `schema(model)`, `validate(model, data)`, `access(name)`, `app_only(name)` |
| `errors.py` | `ToolErrorPayload`, `parse_tool_error`, `ERROR_CODES` (section 18) |
| `verdicts.py` | verdict labels, `VERDICT_WORDING`, `FORBIDDEN_PHRASES`, `wording_for`, `may_offer_grievance` |
| `export.py` | `python -m claimclear_contracts.export [--check]` |

| CaseState field | Schema | Filled by | Read by |
|---|---|---|---|
| case_id | - | app (Member 4), at upload | everyone |
| user_id | - | app (Member 4), from the session | memory |
| plan | Plan | supervisor | everyone; shown to the user |
| documents | DocumentInfoOut | document reader <- list_case_documents | document reader |
| pages | DocumentTextOut | document reader <- get_document_text | document reader, guardrails |
| claim | ClaimIn | document reader (structured extraction) | auditor, critic |
| letter | LetterIn | document reader (structured extraction) | auditor, critic, grievance agent |
| sources | - | document reader | UI highlighting, critic |
| policy | PolicyOut | policy analyst <- get_policy | auditor, critic |
| history | PastClaimOut | policy analyst <- get_claim_history | auditor, critic |
| clauses | ClauseOut | policy analyst <- get_clause / clauses_for_rule | explainer, critic |
| settlement | SettlementOut | auditor <- expected_settlement | auditor, explainer, critic |
| row_audits | RowAuditOut | auditor <- reproduce_deduction | explainer, critic, grievance agent |
| letter_audit | LetterAuditOut | critic <- audit_settlement_letter | critic, explainer |
| questions | QuestionOut | from settlement and row_audits | supervisor -> interrupt() |
| answers | - | user, via interrupt() | auditor (re-run) |
| memory | - | supervisor <- claimclear_memory context() | everyone; critic takes figures |
| security_flags | - | guardrails (Member 4) | supervisor |
| critic | CriticReport | critic | supervisor |
| draft | ExplainerDraft | explainer | critic, output guardrails |
| grievance | GrievanceDraft | grievance agent | approval gate (Member 4) |

**Status:** implemented and tested; Member 3 has not reviewed it yet (the plan makes contracts a joint decision).

### 14.2 `claimclear_tools` (agents' environment)

| Module | Content |
|---|---|
| `toolkit.py` | `ClaimClearToolkit(mode, servers, use_stubs, local_tools, tool_interceptors)`: sessions, LangChain tools, `for_agent`, `schema`, `call`, a typed method per tool, `read_case`, `ingest_uploaded_policy`. `tool_interceptors` is hook point 2 |
| `agents.py` | `AGENT_TOOLS`, `TOOL_SERVER`, `WRITE_TOOLS`, `APP_ONLY_TOOLS`, `tools_for`, and `may_use(agent, tool)` for the permission check at hook point 1 |
| `config.py` | stdio / http endpoints from environment variables |
| `results.py` | `structured(msg)`, `tool_error(msg)`, `message_text(msg)` |
| `signals.py` | routes: ok, missing_document, ask_user, audit_rows, not_admissible, replan, done, offer_grievance, no_grievance (`after_document_text`, `after_settlement`, `after_row_audit`, `after_letter_audit`); `questions_to_ask` (questions for the user, without those meant for the insurer), `breakdown_requests` (ask the insurer for its working or item list), `bill_inconsistencies` (a repeated charge paid twice); `visible_text`, `security_flags`, `untrusted_channels` |
| `case.py` | `build_case`, `apply_answer` (Q-ROOM-PRICING, Q-CONDITION-TYPE, Q-EYE, Q-ADMISSION) |
| `critic.py` | `allowed_figures`, `unsupported_figures`, `wording_for` |
| `stubs.py` | stand-ins when policy-kb is not connected |

| Agent | Tools it gets (`tk.for_agent`) |
|---|---|
| document_reader | list_case_documents, get_document_text |
| policy_analyst | get_policy, get_policy_wording, get_claim_history, list_policies, search_clauses, get_clause, clauses_for_rule |
| settlement_auditor | expected_settlement, list_hypotheses, reproduce_deduction |
| critic | audit_settlement_letter, expected_settlement, get_clause |
| explainer | get_clause, clauses_for_rule |
| grievance_agent | grievance_status, file_grievance |
| supervisor | (none) |
| single_agent | list_case_documents, get_document_text, get_policy, get_policy_wording, get_claim_history, expected_settlement, list_hypotheses, reproduce_deduction, audit_settlement_letter, list_policies, search_clauses, get_clause, clauses_for_rule |

## 15. Technologies, dependencies and configuration

| Technology | Version installed here | Used for |
|---|---|---|
| Python | Python 3.15.0 (servers), Python 3.14.7 (agents) | everything |
| MCP Python SDK `mcp` | 2.3.0 (servers), 1.30.0 (agents) | servers, clients, in-process tests |
| pydantic | 2.14.3 | tool schemas, contracts |
| PyMuPDF `pymupdf` | 1.28.2 | text with positions, OCR driver, PDF ingestion |
| Tesseract OCR | 5.4 (Windows build) / distribution package | scans and photos |
| uvicorn / starlette | 0.54.0 / 1.10.0 | HTTP transport (from the SDK) |
| pg8000 | 1.31.6 | PostgreSQL driver (pure Python) |
| minio | 7.2.20 | S3 client |
| PostgreSQL + pgvector | 16 + 0.8.x (`pgvector/pgvector:pg16`) | case index, memory, clause vectors |
| MinIO | Chainguard build, pinned digest | uploaded documents |
| SQLite | standard library | default memory database |
| jsonschema | 4.26.0 | contract validation |
| pytest | 9.2.0 | tests |
| LangGraph | 1.2.20 | Member 3's graph; ToolNode hook point |
| langchain-core | 1.7.6 | tools for agents |
| langchain-mcp-adapters | 0.3.2 | MCP tools in LangChain; interceptor hook point |
| langchain-openai | 1.7.4 | OpenRouter chat models (Member 3) |
| fastembed (optional) | not installed in .venv | local embeddings and reranker |
| OpenRouter API | HTTPS | embeddings `baai/bge-m3`, LLM rewriting `openai/gpt-4.1-mini` (optional) |
| Docker Compose | - | storage services |
| GitHub Actions | - | CI `.github/workflows/member2.yml` (Member 2's suites) and `ci.yml` (smoke tests), at the repository root |

| Package | Dependencies | Optional extras |
|---|---|---|
| claimclear-settlement-engine | (none) | server: mcp==2.3.0; dev: pytest>=8, mcp==2.3.0 |
| claimclear-case-records | pymupdf>=1.24 | server: mcp==2.3.0; postgres: pg8000>=1.31; s3: minio>=7.2; dev: pytest>=8, mcp==2.3.0 |
| claimclear-policy-kb | (none) | pdf: pymupdf>=1.24; embeddings: fastembed>=0.4; pgvector: pg8000>=1.31; tools: langchain-core>=1.3,<2; mcp: mcp==2.3.0; dev: pytest>=8 |
| claimclear-insurer-portal | mcp==2.3.0 | dev: pytest>=8 |
| claimclear-document-reader | pymupdf>=1.24, pydantic>=2 | server: mcp==2.3.0; dev: pytest>=8, mcp==2.3.0 |
| claimclear-memory | (none) | postgres: pg8000>=1.31; dev: pytest>=8 |
| claimclear-contracts | pydantic>=2 | validate: jsonschema>=4; dev: pytest>=8, jsonschema>=4 |
| claimclear-tools | claimclear-contracts, langchain-mcp-adapters>=0.3,<0.4, langchain-core>=1.3,<2 | dev: pytest>=8 |

| Variable | Default | Meaning |
|---|---|---|
| CLAIMCLEAR_CASE_STORE | var/case_store | case store root (local index and files) |
| CLAIMCLEAR_REFERENCE_DIR | development/dev_data/dataset/dev/reference | policies and claim history |
| CLAIMCLEAR_CASE_INDEX | unset (index.json) | postgresql:// case index |
| CLAIMCLEAR_BLOB_STORE | unset (files/) | s3://bucket?endpoint=… document store |
| CLAIMCLEAR_S3_ACCESS_KEY / _SECRET_KEY | - | MinIO credentials (keep in .env) |
| CLAIMCLEAR_DOCUMENT_CACHE | <case store>/text_cache | extracted-text cache; off to disable |
| CLAIMCLEAR_OCR / _OCR_LANGUAGE / _OCR_DPI | auto / eng / 300 | OCR switch, languages, resolution |
| CLAIMCLEAR_DEFAULT_WORDING_UIN | GODHLIP24179V022324 | wording when a case names none |
| CLAIMCLEAR_POLICY_KB_INDEX | var/policy_kb/index.json | policy index file |
| CLAIMCLEAR_POLICY_CATALOGUE | development/dev_data/wordings/catalogue.json | reviewed wordings |
| CLAIMCLEAR_POLICY_KB_VECTORS | unset (in memory) | postgresql:// pgvector store |
| CLAIMCLEAR_POLICY_KB_REWRITER / _RERANKER | glossary / none | query rewriting, reranking |
| CLAIMCLEAR_EMBEDDING_MODEL / _REWRITE_MODEL | baai/bge-m3 / openai/gpt-4.1-mini | OpenRouter models |
| CLAIMCLEAR_UPLOAD_EMBEDDER | hashing | embedder for uploaded wordings |
| CLAIMCLEAR_POLICY_RULES / CLAIMCLEAR_RULES_DIR | dataset rules / development/dev_data/wordings/rules | engine limits per wording |
| CLAIMCLEAR_DATASET_DIR | development/dev_data/dataset | dataset for the engine CLI and tests |
| CLAIMCLEAR_MEMORY_DB | var/memory/memory.db | SQLite path or postgresql:// URL |
| CLAIMCLEAR_PORTAL_STORE | var/insurer_portal/dry_run.json | dry-run filings |
| CLAIMCLEAR_GATE_SECRET | unset | turns on the approval-token HMAC check |
| CLAIMCLEAR_MCP_MODE | stdio | toolkit: stdio or http |
| CLAIMCLEAR_*_URL (5) | http://127.0.0.1:810x/mcp | server URLs in http mode |
| CLAIMCLEAR_SERVER_PYTHON | <repo>/.venv | Python that starts the servers |
| CLAIMCLEAR_REPO | found automatically | repository root for the toolkit |
| OPENROUTER_API_KEY | unset | OpenRouter key, only in .env |

Every `CLAIMCLEAR_*` variable the code reads: `CLAIMCLEAR_BLOB_STORE`, `CLAIMCLEAR_CASE_INDEX`, `CLAIMCLEAR_CASE_RECORDS_URL`, `CLAIMCLEAR_CASE_STORE`, `CLAIMCLEAR_DATASET_DIR`, `CLAIMCLEAR_DEFAULT_WORDING_UIN`, `CLAIMCLEAR_DOCUMENT_CACHE`, `CLAIMCLEAR_EMBEDDING_MODEL`, `CLAIMCLEAR_GATE_SECRET`, `CLAIMCLEAR_INSURER_PORTAL_URL`, `CLAIMCLEAR_MCP_MODE`, `CLAIMCLEAR_MEMORY_DB`, `CLAIMCLEAR_OCR`, `CLAIMCLEAR_OCR_DPI`, `CLAIMCLEAR_OCR_LANGUAGE`, `CLAIMCLEAR_POLICY_CATALOGUE`, `CLAIMCLEAR_POLICY_KB_INDEX`, `CLAIMCLEAR_POLICY_KB_RERANKER`, `CLAIMCLEAR_POLICY_KB_REWRITER`, `CLAIMCLEAR_POLICY_KB_URL`, `CLAIMCLEAR_POLICY_KB_VECTORS`, `CLAIMCLEAR_POLICY_RULES`, `CLAIMCLEAR_PORTAL_STORE`, `CLAIMCLEAR_REFERENCE_DIR`, `CLAIMCLEAR_REPO`, `CLAIMCLEAR_REWRITE_MODEL`, `CLAIMCLEAR_RULES_DIR`, `CLAIMCLEAR_S3_ACCESS_KEY`, `CLAIMCLEAR_S3_SECRET_KEY`, `CLAIMCLEAR_SERVER_PYTHON`, `CLAIMCLEAR_SETTLEMENT_URL`, `CLAIMCLEAR_UPLOAD_EMBEDDER`.

## 16. Run and test everything

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-servers.txt          # Linux/macOS: .venv/bin/python
py -3.14 -m venv .venv-agents
.venv-agents/Scripts/python.exe -m pip install -r requirements-agents.txt
# Tesseract: winget install --id UB-Mannheim.TesseractOCR -e   (Fedora: see additional_resources/setup_fedora.md)
cp .env.example .env                                                          # optional: OPENROUTER_API_KEY
```

| Step | Command (from the repository root unless noted) | Result |
|---|---|---|
| Build the policy index | `cd servers/policy_kb && python -m policy_kb build --wording ../../development/dev_data/wordings/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf` | `var/policy_kb/index.json` |
| Load the development cases | `cd servers/case_records && python -m case_records.register_dataset --split dev` | `var/case_store/` |
| Try one case | `python scripts/try_case_records.py development/dev_data/dataset/dev/cases/syn-dev-001 --ocr` | every case-records tool, both safety checks |
| Run every dev case through the whole app | `.venv-agents/Scripts/python.exe development/dev_eval/dev_cases/run.py` | `development/dev_eval/dev_cases/results/dev_cases.md`: route, verdicts and amounts per case, scored against `answers/` |
| Audit the worked example | `cd servers/settlement_engine && python -m engine.cli SET-01 --audit` | ₹8,522.86 may be disputable |
| Search the wording | `cd servers/policy_kb && python -m policy_kb search "they cut my medicine bill"` | clause IDs and scores |
| Start all servers | `python scripts/dev_servers.py` (`--check` to verify) | HTTP on 8101–8105 |
| Agents' demo | `.venv-agents/Scripts/python.exe agents/toolkit/examples/verify_settlement_demo.py` | the chain through the toolkit |
| Storage services | `docker compose -f deploy/storage.compose.yml up -d` | PostgreSQL 5432, MinIO 9000 |

Tests: from each folder, `python -m pytest -o addopts=""` (servers' environment; the toolkit uses `.venv-agents`). The storage tests need:

```bash
export CLAIMCLEAR_TEST_POSTGRES=postgresql://claimclear:claimclear@127.0.0.1:5432/claimclear
export CLAIMCLEAR_TEST_S3="s3://claimclear-test?endpoint=127.0.0.1:9000&secure=0"
export CLAIMCLEAR_S3_ACCESS_KEY=claimclear CLAIMCLEAR_S3_SECRET_KEY=claimclear-secret
```

| What the tests check | Where |
|---|---|
| Engine arithmetic from the plan's worked example, every hypothesis, matcher verdicts, letters against the answer key | `servers/settlement_engine/tests` |
| One test per tool, every error code, case scoping, malformed input, schema snapshot, stdio | each server's `tests/test_mcp_server.py` |
| Hidden text on attack documents, OCR, cache, input checks | `servers/document_reader/tests` |
| PostgreSQL, MinIO and pgvector backends | `servers/case_records/tests/test_backends.py`, `memory/tests/test_postgres.py`, `servers/policy_kb/tests/test_vectorstore.py` |
| Consent, retention, forget, grievances, context bounds | `memory/tests` |
| Contract drift, error codes, access marks, agent tool lists | `contracts/tests` |
| Live: agents' environment against every server; both hook points | `agents/toolkit/tests/test_toolkit_live.py` |
| Every dev case end to end, scored against its answer (section 16.1); the extraction stand-in reads and reconciles every case | `development/dev_eval/dev_cases/run.py`, `development/dev_eval/dev_cases/test_extract.py` |

**CI** (`.github/workflows/member2.yml` at the repository root; moved there on 23 November, because GitHub only runs workflows from the root): a servers job (Tesseract, PostgreSQL + pgvector, MinIO, every server suite, memory, contracts, the memory runner, all servers over HTTP) and a toolkit job (both environments, live tests). No API keys or paid services. The root `ci.yml` (Member 4) runs the app's smoke tests separately.

### 16.1 Whole-application run on the dev cases

`development/dev_eval/dev_cases/run.py` sends each of the 42 dev cases through the toolkit and all five servers, the way Member 3's graph will call them, and scores it against `answers/` (read only after the run). There is no LLM yet, so the claim and letter come from a development stand-in (`development/dev_eval/dev_cases/extract.py`): printed fields for synthetic cases, parsed PDFs for gen-data cases, where every bill adds up to its printed total and every letter reconciles exactly.

| Step | Who in the graph | Tools |
|---|---|---|
| Upload | the app | `case_records.register_dataset --split dev` |
| Read every document | document reader | `list_case_documents`, `get_document_text`; guardrail signals |
| Policy | policy analyst | `get_policy`, `get_policy_wording`, `get_claim_history` |
| Audit | settlement auditor | `expected_settlement`, `reproduce_deduction` for every row (plus co-pay or rejection) |
| Explain and check | explainer, critic | `clauses_for_rule`, `audit_settlement_letter`, the critic's figure check |
| Score | evaluation | overall verdict, row verdicts, payable and disputable amount |

**Latest run:**

| | Synthetic | gen-data | All |
|---|---|---|---|
| cases | 22 | 20 | 42 |
| ran to the end | 21 | 20 | 41 |
| overall verdict right | 16 / 22 | 18 / 20 | 34 / 42 |
| row verdicts right | 19 / 20 | 69 / 74 | 88 / 94 |
| policy-correct payable right (within ₹1) | 12 / 13 | 14 / 17 | 26 / 30 |
| disputable amount right (within ₹1) | 19 / 19 | 15 / 19 | 34 / 38 |

Every case read its documents (163 documents, 1,157 pages) and its wording status. policy-kb returned a clause for 110 of the 111 rules the rows cited; the other is "GST follows the charge", which has no clause in the wording by design. The critic found no unsupported figure in any draft. Four cases raised guardrail flags: hidden text in three (one of them also an edited PDF) and a look-alike policy number on the bill in one.

| Route | Synthetic | gen-data |
|---|---|---|
| `offer_grievance`: some rupees may be disputable | 5 | 16 |
| `no_grievance`: nothing disputable | 14 | 2 |
| `ask_user`: the engine needs an answer first | 2 | 2 |
| `invalid_extraction`: the claim is impossible | 1 | 0 |

**What still differs from the answer key** (the 8 overall misses):

| Case | What differs | Why |
|---|---|---|
| gen-dev-50b4e6 (and the amounts of 6a82b1, a0a2f1) | the proportionate deduction | the answer key cuts consumables and diagnostics; ClaimClear keeps IRDAI's 2020 rule (decided, labelled from `development/dev_eval/dev_cases/decisions.json`) |
| gen-dev-b4331d | ₹215.50 disputable, the answer says none | the letter takes co-pay before its own ₹4,300 cut, so ₹215.50 is owed either way; the answer's own note agrees |
| syn-dev-004, 006, 012, 015 | rejections (impossible dates, fraud, an invented hospital, an altered date) are confirmed: `matches_policy`, payable ₹0 | the integrity checks find the evidence in the documents (discharge before admission, room days beyond the stay, dated lines outside the stay, a malformed GSTIN) |
| syn-dev-017 | the insurer paid a meniscus repair, so the condition it accepted is taken from the letter | no waiting-period row on a paid claim means the letter accepted the condition (fact `F-CONDITION-FROM-LETTER`) |
| syn-dev-021 | asks for the admission date | a pharmacy bill with no admission date, by design |

Results per case: `development/dev_eval/dev_cases/results/dev_cases.md` (and `.json` with every step's output). The fixes these cases led to, and the reasoning on the answer key, are in `additional_resources/member2_knowledge_memory_tools/evaluation_dev_cases.md`.

## 17. Files and modules walkthrough

Every module, its line count and the first line of its own docstring. Tests are summarised per package.

### settlement-engine (`servers/settlement_engine/`)

| File | Lines | What it is |
|---|---|---|
| `engine/__init__.py` | 76 | ClaimClear settlement engine. |
| `engine/calculators.py` | 338 | One pure function per policy rule. |
| `engine/categories.py` | 195 | Bill-line categorisation and non-payable detection. |
| `engine/cli.py` | 104 | Command line for the engine and the matcher. |
| `engine/dataset.py` | 192 | Load cases from the standard dataset (`development/dev_data/dataset/`) into engine inputs. |
| `engine/engine.py` | 468 | `compute_settlement`: what the policy wording says should be paid. |
| `engine/hypotheses.py` | 727 | Hypothesis library: the ways an insurer might have calculated a deduction. |
| `engine/identifiers.py` | 39 | Policy numbers as printed versus as filed. |
| `engine/matcher.py` | 433 | Matcher: work out how the insurer got each figure, and whether the wording allows it. |
| `engine/models.py` | 511 | Typed inputs and outputs of the settlement engine. |
| `engine/money.py` | 70 | Money and date helpers. |
| `engine/rules.py` | 137 | Policy limits and rule references. |
| `mcp_server/__init__.py` | 5 | MCP server exposing the ClaimClear settlement engine (FastMCP-style, mcp 2.x `MCPServer`). |
| `mcp_server/__main__.py` | 89 | Run the settlement-engine MCP server. |
| `mcp_server/app.py` | 240 | The settlement-engine MCP server. |
| `mcp_server/convert.py` | 191 | Conversion between the MCP schemas (pydantic) and the engine's dataclasses. |
| `mcp_server/schemas.py` | 287 | Typed inputs and outputs of the settlement-engine MCP tools (pydantic). |
| 18 test files | 1766 | conftest.py, factories.py, test_caps.py, test_cataract.py, test_categories.py, test_copay_sum_insured.py, test_engine_flow.py, test_hypotheses.py, test_letter_audits.py, test_letter_gaps.py, test_matcher.py, test_mcp_server.py, test_money.py, test_non_payable.py, test_proportionate.py, test_settlement_letters.py, test_waiting_period.py, test_wording_rules.py |

### case-records (`servers/case_records/`)

| File | Lines | What it is |
|---|---|---|
| `case_records/__init__.py` | 9 | ClaimClear case-records: document store, policy and claim history; documents are read by the document reader. |
| `case_records/__main__.py` | 60 | Run the case-records MCP server. |
| `case_records/app.py` | 207 | The case-records MCP server. |
| `case_records/backends.py` | 209 | Where the case store keeps its index and its files. |
| `case_records/reference.py` | 83 | Policy schedules and claim history (read-only reference data). |
| `case_records/register_dataset.py` | 81 | Register the synthetic dataset into a case store (development and evaluation only). |
| `case_records/schemas.py` | 95 | Typed outputs of the case-records MCP tools (pydantic). |
| `case_records/store.py` | 189 | Case and document store. |
| 5 test files | 579 | conftest.py, test_backends.py, test_mcp_server.py, test_reference.py, test_store.py |

### document-reader (`servers/document_reader/`)

| File | Lines | What it is |
|---|---|---|
| `document_reader/__init__.py` | 8 | ClaimClear document reader: PDF, JPG and PNG to text with source spans, hidden content kept apart, OCR for scans. |
| `document_reader/__main__.py` | 78 | Run the document-reader MCP server. |
| `document_reader/app.py` | 113 | The document-reader MCP server. |
| `document_reader/extract.py` | 399 | Text extraction with source spans, and a clear line between what a reader sees and what is hidden. |
| `document_reader/ocr.py` | 116 | OCR settings and engine status. |
| `document_reader/reader.py` | 140 | The document reader: checks a file, extracts it once, and serves later reads from a cache. |
| `document_reader/schemas.py` | 102 | Typed outputs of the document reader (pydantic). |
| 5 test files | 536 | conftest.py, test_extract.py, test_mcp_server.py, test_ocr.py, test_reader.py |

### policy-kb (`servers/policy_kb/`)

| File | Lines | What it is |
|---|---|---|
| `policy_kb/__init__.py` | 40 | policy_kb: ClaimClear's policy-wording knowledge base (ingestion, hybrid retrieval, query rewriting). |
| `policy_kb/__main__.py` | 157 | Command line for the policy knowledge base. |
| `policy_kb/bm25.py` | 40 | Okapi BM25, the keyword half of hybrid search. |
| `policy_kb/catalogue.py` | 263 | The policy catalogue: every wording policy-kb can serve, and the per-case uploaded wordings. |
| `policy_kb/embedders.py` | 129 | Embedders: turn text into vectors for the semantic half of hybrid search. |
| `policy_kb/evaluate.py` | 105 | Recall@k for the retrieval report. |
| `policy_kb/fetch.py` | 68 | Download a policy wording and record where it came from. |
| `policy_kb/ingest.py` | 366 | Split a policy wording into clauses: one chunk per numbered clause, with metadata. |
| `policy_kb/kb.py` | 184 | `PolicyKB`: the policy knowledge base. Build it once from a wording, then search it. |
| `policy_kb/mcp_server/__init__.py` | 7 | The policy-kb MCP server: `search_clauses`, `get_clause`, `clauses_for_rule`. |
| `policy_kb/mcp_server/__main__.py` | 63 | Run the policy-kb MCP server. |
| `policy_kb/mcp_server/app.py` | 202 | The policy-kb MCP server. |
| `policy_kb/mcp_server/schemas.py` | 119 | Typed outputs of the policy-kb MCP tools (pydantic). |
| `policy_kb/models.py` | 76 | Data shapes of the policy knowledge base. |
| `policy_kb/openrouter.py` | 165 | A small OpenRouter client for policy-kb: embeddings and chat completions. |
| `policy_kb/rerankers.py` | 44 | Rerankers: re-score the top candidates by reading the query and each clause together. |
| `policy_kb/rewrite.py` | 143 | Query rewriting: from the policyholder's words to the wording's words. |
| `policy_kb/text.py` | 56 | Tokenising for BM25 and the hashing embedder: lower-case, split, drop stop words, light stemming. |
| `policy_kb/tools.py` | 164 | Tool results over a `PolicyKB`, and the same tools as in-process LangChain tools. |
| `policy_kb/vectorstore.py` | 122 | Where clause vectors live, and how the vector half of hybrid search is ranked. |
| 9 test files | 1142 | conftest.py, test_catalogue.py, test_evaluate_and_tools.py, test_ingest.py, test_lettered_layout.py, test_mcp_server.py, test_openrouter.py, test_retrieval.py, test_vectorstore.py |

### insurer-portal (`servers/insurer_portal/`)

| File | Lines | What it is |
|---|---|---|
| `insurer_portal/__init__.py` | 5 | insurer_portal: the insurer-portal MCP server interface, with a dry-run backend (Member 4 adds the mock portal). |
| `insurer_portal/__main__.py` | 61 | Run the insurer-portal MCP server (interface + dry-run backend). |
| `insurer_portal/app.py` | 169 | The insurer-portal MCP server: the interface, with a dry-run backend. |
| `insurer_portal/schemas.py` | 42 | Typed inputs and outputs of the insurer-portal MCP tools (the interface). |
| 1 test files | 115 | test_mcp_server.py |

### memory (`memory/`)

| File | Lines | What it is |
|---|---|---|
| `claimclear_memory/__init__.py` | 37 | claimclear_memory: ClaimClear's long-term memory, with consent, expiry and trimming. |
| `claimclear_memory/context.py` | 131 | What memory hands to the agents at the start of a session, kept small. |
| `claimclear_memory/db.py` | 140 | The database under the memory store: SQLite (one file, the default) or PostgreSQL (production). |
| `claimclear_memory/models.py` | 170 | What the memory store keeps for each user. |
| `claimclear_memory/store.py` | 695 | The memory store: SQLite (one file) or PostgreSQL, every row keyed by the app's `user_id`. |
| 2 test files | 663 | test_memory.py, test_postgres.py |

### contracts (`contracts/`)

| File | Lines | What it is |
|---|---|---|
| `claimclear_contracts/__init__.py` | 54 | ClaimClear contracts: what Member 2's tools and Member 3's agents both import. |
| `claimclear_contracts/errors.py` | 103 | The standard tool error and every error code a ClaimClear server or library can return. |
| `claimclear_contracts/export.py` | 64 | Build `tool_schemas.json` from the servers' pinned snapshots, and pin the contracts' own schemas. |
| `claimclear_contracts/handoffs.py` | 152 | Typed hand-off messages between the agents, and the plan object shown to the user. |
| `claimclear_contracts/state.py` | 78 | `CaseState`: the LangGraph state for one case. |
| `claimclear_contracts/tools.py` | 78 | Every MCP tool's input and output schema, in one exported file. |
| `claimclear_contracts/verdicts.py` | 40 | Verdict labels and the only wording an explanation may use for each. |
| 1 test files | 190 | test_contracts.py |

### agents' toolkit (`agents/toolkit/`)

| File | Lines | What it is |
|---|---|---|
| `claimclear_tools/__init__.py` | 42 | claimclear_tools: the agents' side of the ClaimClear MCP servers (for Member 3). |
| `claimclear_tools/agents.py` | 67 | Which agent may use which tool. |
| `claimclear_tools/case.py` | 101 | Assembling tool arguments, and applying the policyholder's answers. |
| `claimclear_tools/config.py` | 142 | Where the MCP servers are, and how to reach them. |
| `claimclear_tools/critic.py` | 100 | Checks the critic runs on a draft reply. |
| `claimclear_tools/results.py` | 132 | Reading tool results and errors. |
| `claimclear_tools/signals.py` | 165 | Turning tool results into graph decisions. |
| `claimclear_tools/stubs.py` | 44 | Stand-ins for the policy-kb tools, used only when the policy-kb server is not connected. |
| `claimclear_tools/toolkit.py` | 225 | `ClaimClearToolkit`: one object that connects the agents to every ClaimClear MCP server. |
| `examples/show_agent_tools.py` | 34 | Print the tools each agent gets, straight from the live servers. |
| `examples/verify_settlement_demo.py` | 92 | Reference flow: verify one settlement through the MCP servers, no LLM (the C0 fixed-workflow shape). |
| 2 test files | 556 | test_helpers.py, test_toolkit_live.py |

### scripts and evaluation

| File | Lines | What it is |
|---|---|---|
| `development/dev_eval/memory_on_off/run.py` | 285 | Memory on vs off: run the development cases with and without ClaimClear's long-term memory. |
| `scripts/dev_servers.py` | 142 | Start every built MCP server over streamable HTTP, for local agent development. |
| `scripts/register_case_folder.py` | 77 | Register one case folder (bill, settlement letter, policy schedule, discharge summary) and print its case ID. |
| `scripts/try_case_records.py` | 113 | Upload one case folder and call every case-records tool on it, as an agent would. |
| 1 test files | 40 | test_memory_on_off.py |

Other files:

| Path | What |
|---|---|
| `development/dev_data/dataset/` | every case in one standard format: `dev/` (42) and `heldout/` (53), each with `cases.json`, `cases/<case_id>/` (documents only), `reference/` and `answers/`; explained in `additional_resources/member2_knowledge_memory_tools/dataset_guide.md` |
| `development/dev_eval/dev_cases/` | the whole-application run over the dev cases (`run.py`), the extraction stand-in for the LLM document reader (`extract.py`), results and findings |
| `development/dev_data/wordings/` | Go Digit Arogya Sanjeevani wording, its source record, the catalogue, checked limits |
| `servers/*/tests/snapshots/*.json` | pinned tool schemas |
| `contracts/claimclear_contracts/tool_schemas.json`, `contracts/snapshots/contracts.json` | exported tool schemas; contract model schemas |
| `deploy/storage.compose.yml` | PostgreSQL + pgvector and MinIO |
| `.github/workflows/member2.yml` (repository root) | CI: Member 2's suites |
| `development/dev_eval/retrieval/`, `development/dev_eval/memory_on_off/results/` | draft retrieval queries and results; memory comparison results |
| `docs/` | this document, memory policy, Member 2 overview, technology choices, Fedora setup, tech-stack guide, diagrams |
| `.claude/skills/claimclear-member2/` | Member 2 playbook for Claude and teammates |
| `README.md` | repository guide |

## 18. Error codes

From `contracts/claimclear_contracts/errors.py` (a test checks every code the code raises is listed). Only `UPSTREAM_UNAVAILABLE` is retryable.

| Server | Code | Meaning and next step |
|---|---|---|
| settlement-engine | `POLICY_MISMATCH` | claim.policy_no and policy.policy_no differ: load the case's own policy (get_policy) |
| settlement-engine | `HISTORY_POLICY_MISMATCH` | the history holds claims on another policy: pass get_claim_history unchanged |
| settlement-engine | `ROW_NOT_FOUND` | no such row on the letter: the message lists the valid row IDs |
| settlement-engine | `UNKNOWN_HYPOTHESIS` | a hypothesis ID that doesn't exist: call list_hypotheses |
| case-records | `CASE_NOT_FOUND` | no such case: the app gave a wrong case_id |
| case-records | `DOCUMENT_NOT_IN_CASE` | the document belongs to another case (or doesn't exist) |
| case-records | `DOCUMENT_INTEGRITY` | the stored copy is missing or changed: ask the user to upload it again |
| case-records | `POLICY_NOT_FOUND` | no pre-stored schedule for the policy: extract it from the uploaded policy and confirm |
| case-records | `INVALID_SCOPE` | claim-history scope not recognised |
| case-records | `INVALID_ROLE` | upload path: a document role that doesn't exist |
| case-records | `INVALID_POLICY` | upload path: setting a case's policy number to an empty value (`set_policy`) |
| case-records | `INVALID_WORDING` | upload path: a wording UIN in the wrong format |
| case-records | `UNSUPPORTED_MEDIA_TYPE` | upload path: only PDF, JPG and PNG are accepted |
| case-records | `FILE_TOO_LARGE` | upload path: the file is over 25 MB |
| document-reader | `INVALID_CONTENT` | content_base64 is not valid base64 |
| document-reader | `UNSUPPORTED_MEDIA_TYPE` | only PDF, JPG and PNG are read |
| document-reader | `MEDIA_TYPE_MISMATCH` | the bytes are not the declared type (a renamed file) |
| document-reader | `DOCUMENT_TOO_LARGE` | the file is over 25 MB |
| document-reader | `DOCUMENT_UNREADABLE` | empty, missing or can't be opened: ask for another copy |
| document-reader | `DOCUMENT_ENCRYPTED` | the PDF is password-protected: ask for an unprotected copy |
| document-reader | `PAGE_OUT_OF_RANGE` | a requested page doesn't exist |
| policy-kb | `EMPTY_QUERY` | the search query is empty after cleaning |
| policy-kb | `INDEX_UNAVAILABLE` | the wording's index isn't built: run python -m policy_kb build |
| policy-kb | `NO_RULE_MAP` | the wording has no rule map (uploaded wordings): use search_clauses |
| policy-kb | `UNKNOWN_RULE` | a rule_ref the rule map doesn't have |
| policy-kb | `UNKNOWN_WORDING` | a wording UIN that isn't in the catalogue or the case |
| policy-kb | `UPLOAD_REJECTED` | the uploaded policy could not be indexed (out of scope or unreadable) |
| policy-kb | `UPSTREAM_UNAVAILABLE` | the embedding or rewriting service is down: retryable |
| insurer-portal | `APPROVAL_REQUIRED` | no valid approval token for this exact letter: go back to the approval gate |
| insurer-portal | `TEXT_HASH_MISMATCH` | the letter changed after approval: get a fresh approval |
| insurer-portal | `GRIEVANCE_NOT_FOUND` | no grievance with that reference |
| memory | `NO_CONSENT` | the user has not agreed to the memory policy: nothing is stored |
| memory | `POLICY_VERSION` | consent was given to an older memory policy: ask again |
| memory | `INVALID_USER` | user_id is not the app's opaque ID |
| memory | `NOT_FINAL` | the audit still needs the user's answers: only final audits are stored |
| memory | `MISSING_FIELD` | the case or audit lacks a field memory needs |
| memory | `CLAIM_MISMATCH` | the audit belongs to another claim |
| memory | `CLAIM_NOT_FOUND` | no remembered claim with that ID |
| memory | `NOTHING_TO_DISPUTE` | the audit found nothing disputable: no grievance |
| memory | `ROW_NOT_DISPUTABLE` | a grievance on a row the audit did not find disputable |
| memory | `BAD_TRANSITION` | a grievance status change the lifecycle doesn't allow |
| memory | `GRIEVANCE_NOT_FOUND` | no grievance with that ID for this user |
| memory | `INVALID_HASH` | the approved text's hash is not a SHA-256 |
| memory | `SCHEMA_VERSION` | the memory database is from a newer version |

## 19. Known limitations and next tasks

| Item | Status | Notes |
|---|---|---|
| Hooks, approval gate, guardrails, app, UI | Planned / other member | Member 4; hook attach points and inputs are built (section 3) |
| LangGraph graph and agents | Planned / other member | Member 3; toolkit and contracts are ready |
| Mock insurer portal | Planned / other member | Member 4; interface and dry run exist |
| Retrieval report on Member 1's labels; reranker measurement | Partial | draft Recall@5 0.933 on draft labels |
| Memory on vs off with the graph and same-policy cases | Partial | runner built |
| Engine rows still not verifiable | Partial | OT unbundling, itemised-rate totals, invented policy; fraud is judged by the document checks, not the engine |
| Insurer-specific notes on Annexure A items | Partial | the plain IRDAI list is applied (e.g. Go Digit's "urine bag where medically necessary" is not) |
| Shared extracted-text cache for production | Partial | the cache is local to the case-records host |
| Daily purge job scheduling | Planned / other member | the function exists; the app schedules it |
| Prometheus metrics and Grafana | Planned / other member | Member 4 (Member 2 as backup) |
| Docker images and Compose for the servers | Planned / other member | Member 4; the storage Compose exists |
| Hindi OCR and embeddings | Planned | stretch goal |
| CI first run | Partial | check the Actions tab |

## 20. Appendix: a complete case and letter (SET-01)

The exact `case` and `letter` used in the settlement-engine examples (produced by `python -m mcp_server --case-payload SET-01` in `servers/settlement_engine`). Copy them to try the tools.

**case**

```json
{
  "claim": {
    "claim_id": "AGI/HC/2526/004512",
    "policy_no": "AS-2025-100478",
    "admission": "2026-01-19",
    "discharge": "2026-01-22",
    "lines": [
      {
        "line_id": "L01",
        "description": "Private room",
        "amount": "21000.0",
        "qty": "3.0",
        "rate": "7000.0",
        "gst_pct": "5.0",
        "non_payable": null,
        "category": null,
        "date": null
      },
      {
        "line_id": "L02",
        "description": "Nursing and duty doctor charges",
        "amount": "4500.0",
        "qty": "3.0",
        "rate": "1500.0",
        "gst_pct": "0",
        "non_payable": null,
        "category": null,
        "date": null
      },
      {
        "line_id": "L03",
        "description": "Surgeon fee - laparoscopic cholecystectomy",
        "amount": "32000.0",
        "qty": "1.0",
        "rate": "32000.0",
        "gst_pct": "0",
        "non_payable": null,
        "category": null,
        "date": null
      },
      {
        "line_id": "L04",
        "description": "Anaesthetist fee",
        "amount": "11000.0",
        "qty": "1.0",
        "rate": "11000.0",
        "gst_pct": "0",
        "non_payable": null,
        "category": null,
        "date": null
      },
      {
        "line_id": "L05",
        "description": "Operation theatre charges",
        "amount": "22000.0",
        "qty": "1.0",
        "rate": "22000.0",
        "gst_pct": "0",
        "non_payable": null,
        "category": null,
        "date": null
      },
      {
        "line_id": "L06",
        "description": "Consultant visits",
        "amount": "5400.0",
        "qty": "3.0",
        "rate": "1800.0",
        "gst_pct": "0",
        "non_payable": null,
        "category": null,
        "date": null
      },
      {
        "line_id": "L07",
        "description": "Laboratory investigations",
        "amount": "7200.0",
        "qty": "1.0",
        "rate": "7200.0",
        "gst_pct": "0",
        "non_payable": null,
        "category": null,
        "date": null
      },
      {
        "line_id": "L08",
        "description": "MRCP",
        "amount": "6500.0",
        "qty": "1.0",
        "rate": "6500.0",
        "gst_pct": "0",
        "non_payable": null,
        "category": null,
        "date": null
      },
      {
        "line_id": "L09",
        "description": "Pharmacy - inpatient medicines",
        "amount": "12900.0",
        "qty": "1.0",
        "rate": "12900.0",
        "gst_pct": "0",
        "non_payable": null,
        "category": null,
        "date": null
      },
      {
        "line_id": "L10",
        "description": "Laparoscopic clips and retrieval bag",
        "amount": "4800.0",
        "qty": "1.0",
        "rate": "4800.0",
        "gst_pct": "0",
        "non_payable": null,
        "category": null,
        "date": null
      }
    ],
    "diagnosis": "Cholelithiasis with cholecystitis",
    "procedure": "Laparoscopic cholecystectomy",
    "discount": "0",
    "printed_total": "128350.0",
    "condition_type": null,
    "room_priced_by_category": {}
  },
  "policy": {
    "policy_no": "AS-2025-100478",
    "sum_insured": "300000",
    "period_start": "2025-07-15",
    "period_end": "2026-07-14",
    "first_inception": "2022-07-15",
    "holder": "Rudransh Kelapure",
    "insurer": "Aarohan General Insurance Ltd.",
    "product": "Arogya Sanjeevani Policy",
    "wording_uin": "",
    "wording_source": ""
  },
  "history": []
}
```

**letter**

```json
{
  "letter_id": "AGI/HC/2526/004512",
  "letter_type": "settlement",
  "claimed_amount": "128350.0",
  "rows": [
    {
      "row_id": "R1",
      "particulars": "Room rent above eligible limit (₹2,000 a day for 3 days)",
      "amount": "6000.0",
      "reason": "Room rent is limited to 2% of sum insured, at most ₹5,000 a day",
      "kind": null
    },
    {
      "row_id": "R2",
      "particulars": "GST on room rent above eligible limit",
      "amount": "300.0",
      "reason": "Follows the room rent deduction",
      "kind": null
    },
    {
      "row_id": "R3",
      "particulars": "Proportionate deduction on associated medical expenses (₹5,000 / ₹7,000)",
      "amount": "30371.43",
      "reason": "Room category above eligibility, so associated expenses are reduced in the same proportion",
      "kind": null
    }
  ],
  "paid_amount": "87094.64",
  "copay_amount": "4583.93",
  "rejection_reason": ""
}
```

